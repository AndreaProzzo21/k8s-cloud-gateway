"""
helm_package_utils.py
=====================

Pure utility functions for Helm chart archive handling.
No FastAPI, no HelmManager, no K8s dependencies — only stdlib.

Imported by:
  - app/core/helm_manager.py      (install_from_package, lint methods)
  - app/api/routes/helm_routes.py (route handlers for temp file creation)

Functions
---------
_safe_extension(filename)      → str
    Returns a temp-file-safe extension that preserves format detection.

_detect_and_unpack(src, dest)  → None
    Detects archive format and extracts it safely (no path traversal).

_find_chart_root(search_dir)   → str | None
    Locates the root Chart.yaml, skipping subchart directories.
"""

import os
import tarfile
import zipfile
from pathlib import Path
from typing import Optional


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def safe_extension(filename: str) -> str:
    """
    Returns a safe file extension for a temp file that preserves format
    detection by tarfile / zipfile.

    Handles compound extensions correctly:
      "chart.tar.gz"  → ".tar.gz"   (not ".gz" as Path.suffix would return)
      "chart.tgz"     → ".tgz"
      "chart.zip"     → ".zip"
      "upload"        → ".bin"      (fallback — magic-byte detection will handle it)
    """
    name = (filename or "").lower()
    for compound in (".tar.gz", ".tar.bz2", ".tar.xz"):
        if name.endswith(compound):
            return compound
    return Path(name).suffix or ".bin"


def detect_and_unpack(archive_path: str, dest_dir: str) -> None:
    """
    Detects the archive format and extracts it into ``dest_dir``.

    Detection order:
    1. Compound extension match  (.tar.gz, .tgz, .tar.bz2, .tar.xz)
    2. Simple extension match    (.zip)
    3. Magic-byte fallback       (ZIP: PK\\x03\\x04 / tar: tarfile.is_tarfile)

    Security: rejects entries with absolute paths or ``..`` components
    to prevent path traversal attacks in both tar and zip archives.

    Raises
    ------
    ValueError
        If the format cannot be detected or the archive is corrupt.
    """
    name = Path(archive_path).name.lower()

    # Compound extension — must be checked before Path.suffix
    if name.endswith(".tar.gz") or name.endswith(".tgz"):
        _unpack_tar(archive_path, dest_dir, mode="r:gz")
        return
    if name.endswith(".tar.bz2"):
        _unpack_tar(archive_path, dest_dir, mode="r:bz2")
        return
    if name.endswith(".tar.xz"):
        _unpack_tar(archive_path, dest_dir, mode="r:xz")
        return
    if name.endswith(".zip"):
        _unpack_zip(archive_path, dest_dir)
        return

    # Magic-byte fallback — browser may send no useful extension
    if _is_zip(archive_path):
        _unpack_zip(archive_path, dest_dir)
        return
    if tarfile.is_tarfile(archive_path):
        _unpack_tar(archive_path, dest_dir, mode="r:*")
        return

    raise ValueError(
        f"Unsupported or unrecognised archive format: '{Path(archive_path).name}'. "
        "Supported: .zip, .tgz, .tar.gz, .tar.bz2, .tar.xz"
    )


def find_chart_root(search_dir: str) -> Optional[str]:
    """
    Locates the root directory of a Helm chart within ``search_dir``.

    Searches recursively for ``Chart.yaml``, skipping any file located
    inside a ``charts/`` subdirectory (which contains dependency subcharts,
    not the root chart).

    Returns the parent directory of the first matching ``Chart.yaml``,
    or ``None`` if no valid chart root is found.
    """
    for chart_yaml in sorted(Path(search_dir).rglob("Chart.yaml")):
        # Skip subcharts: any ancestor directory named "charts"
        if "charts" in chart_yaml.parts[:-1]:
            continue
        return str(chart_yaml.parent)
    return None


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _unpack_tar(archive_path: str, dest_dir: str, mode: str) -> None:
    """Extracts a tar archive, rejecting path traversal entries."""
    try:
        with tarfile.open(archive_path, mode) as tar:
            safe_members = [
                m for m in tar.getmembers()
                if not os.path.isabs(m.name) and ".." not in Path(m.name).parts
            ]
            tar.extractall(path=dest_dir, members=safe_members)
    except tarfile.TarError as exc:
        raise ValueError(f"Failed to extract tar archive: {exc}") from exc


def _unpack_zip(archive_path: str, dest_dir: str) -> None:
    """Extracts a ZIP archive, rejecting path traversal entries."""
    try:
        with zipfile.ZipFile(archive_path, "r") as zf:
            for member in zf.infolist():
                member_path = Path(member.filename)
                if member_path.is_absolute() or ".." in member_path.parts:
                    continue
                zf.extract(member, dest_dir)
    except zipfile.BadZipFile as exc:
        raise ValueError(f"Failed to extract ZIP archive: {exc}") from exc


def _is_zip(path: str) -> bool:
    """Returns True if the file starts with ZIP magic bytes (PK\\x03\\x04)."""
    try:
        with open(path, "rb") as f:
            return f.read(4) == b"PK\x03\x04"
    except OSError:
        return False