# app/api/routes/helm_routes.py
"""
Helm Routes
===========

Tutte le route sono prefissate /helm/* in main.py:
    app.include_router(helm_router, prefix="/api/v1/helm", tags=["helm"])

Convenzioni
-----------
- Namespace-scoped : /namespaces/{namespace}/releases/...
- Cluster-scoped   : /repos/..., /charts/...

Gestione errori
---------------
``_require_success`` è applicato a TUTTE le route (lettura e scrittura).
- Se Helm restituisce rc != 0 con "forbidden"/"unauthorized" → HTTP 403
  → il frontend (apiCall) lo converte in throw Error("RESTRICTED")
  → renderRestrictedAccess() si comporta come nella K8s dashboard
- Qualsiasi altro errore Helm → HTTP 400 con il messaggio stderr
- Nessuna route restituisce mai HTTP 200 con success=false nascosto
"""

import json
from typing import Any, Optional
import os
from fastapi import APIRouter, Body, Depends, File, HTTPException, Query, UploadFile, status, Form
from app.api.dependencies.get_helm_manager import get_helm_manager
from app.core.helm_manager import HelmManager
from app.core.helm_package_utils import safe_extension
import shutil
import tempfile
from pathlib import Path

router = APIRouter()


# ---------------------------------------------------------------------------
# Helper centrale — applicato a TUTTE le route
# ---------------------------------------------------------------------------

def _require_success(result: dict, operation: str) -> dict:
    """
    Valida il risultato di un comando Helm.

    Logica:
    - success=True  → restituisce result invariato
    - success=False + "forbidden"/"unauthorized" in stderr → HTTP 403
      (il frontend apiCall.js lo intercetta e lancia Error("RESTRICTED"))
    - success=False + altro → HTTP 400 con stderr come detail

    Non solleva mai su success=True, anche se stdout è vuoto
    (es. helm list su namespace senza release → success=True, data=[]).
    """
    if result.get("success"):
        return result

    stderr = (result.get("stderr") or result.get("stdout") or "").strip()

    if "forbidden" in stderr.lower() or "unauthorized" in stderr.lower():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Access denied: {stderr[:400]}",
        )

    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail=f"{operation} failed: {stderr[:500]}",
    )


# ---------------------------------------------------------------------------
# RELEASES — lettura
# ---------------------------------------------------------------------------

@router.get("/namespaces/{namespace}/releases")
async def list_helm_releases(
    namespace: str,
    manager: HelmManager = Depends(get_helm_manager),
):
    """
    Elenca le release Helm nel namespace specificato.

    Risposta in caso di successo:
        { "success": true, "data": [ ...releases... ] }
    Lista vuota se il namespace esiste ma non ha release:
        { "success": true, "data": [] }
    HTTP 403 se il SA non ha permessi sui Secret del namespace.
    """
    result = await manager.list_releases(namespace)
    return _require_success(result, f"helm list -n {namespace}")


@router.get("/namespaces/{namespace}/releases/{release_name}/status")
async def get_release_status(
    namespace: str,
    release_name: str,
    manager: HelmManager = Depends(get_helm_manager),
):
    """
    Restituisce stato dettagliato, manifest e note di una release.
    HTTP 400 se la release non esiste.
    """
    result = await manager.get_release_status(release_name, namespace)
    return _require_success(result, f"helm status {release_name}")


@router.get("/namespaces/{namespace}/releases/{release_name}/history")
async def get_release_history(
    namespace: str,
    release_name: str,
    max: int = Query(10, ge=1, le=100, description="Numero massimo di revisioni da restituire"),
    manager: HelmManager = Depends(get_helm_manager),
):
    """
    Restituisce la cronologia delle revisioni di una release.
    HTTP 400 se la release non esiste.
    """
    result = await manager.get_release_history(release_name, namespace, max)
    return _require_success(result, f"helm history {release_name}")


@router.get("/namespaces/{namespace}/releases/{release_name}/values")
async def get_release_values(
    namespace: str,
    release_name: str,
    all: bool = Query(False, description="Se true, include anche i valori di default del chart"),
    manager: HelmManager = Depends(get_helm_manager),
):
    """
    Restituisce i valori applicati alla release.
    Con all=false: solo i valori di override (quelli passati con -f o --set).
    Con all=true: tutti i valori, compresi i default del chart.
    """
    result = await manager.get_release_values(release_name, namespace, all)
    return _require_success(result, f"helm get values {release_name}")


# ---------------------------------------------------------------------------
# RELEASES — scrittura
# ---------------------------------------------------------------------------

@router.post("/namespaces/{namespace}/releases/{release_name}", status_code=status.HTTP_200_OK)
async def install_or_upgrade_chart(
    namespace: str,
    release_name: str,
    chart_ref: str = Query(
        ...,
        description="Riferimento al chart: 'repo/chart' (es. bitnami/nginx), path locale, OCI URL",
    ),
    version: Optional[str] = Query(
        None,
        description="Versione specifica del chart. Se omesso usa la latest.",
    ),
    create_namespace: bool = Query(
        False,
        description="Il namespace viene recuperato. Se non esiste va creato da SA che ha il permesso e non indipendentemente.",
    ),
    atomic: bool = Query(
        False,
        description="Rollback automatico se il deploy fallisce (--atomic)",
    ),
    wait: bool = Query(
        False,
        description="Attende che tutte le risorse siano Ready prima di rispondere (--wait)",
    ),
    timeout_seconds: int = Query(
        300, ge=10, le=600,
        description="Timeout per --wait/--atomic in secondi",
    ),
    dry_run: bool = Query(
        False,
        description="Simula l'installazione e restituisce i manifest generati senza applicare modifiche sul cluster (--dry-run)",
    ),
    # Body JSON opzionale: valori di override.
    # FastAPI lo deserializza quando Content-Type: application/json.
    # Endpoint separato (from-zip) gestisce multipart/form-data.
    values: dict[str, Any] = Body(
        default={},
        description="Valori di override (equivalente a -f values.yaml)",
    ),
    manager: HelmManager = Depends(get_helm_manager),
):
    """
    Installa o aggiorna una release Helm (``helm upgrade --install``).
    Se la release non esiste viene creata; se esiste viene aggiornata.
    Se dry_run=True, il cluster non viene modificato.
    """
    result = await manager.install_or_upgrade(
        release_name=release_name,
        chart_ref=chart_ref,
        namespace=namespace,
        values=values or None,
        version=version,
        create_namespace=create_namespace,
        atomic=atomic,
        wait=wait,
        timeout_seconds=timeout_seconds,
        dry_run=dry_run,
    )
    
    op_desc = f"helm upgrade --install {release_name}" + (" (dry-run)" if dry_run else "")
    return _require_success(result, op_desc)


@router.post(
    "/namespaces/{namespace}/releases/{release_name}/rollback",
    status_code=status.HTTP_200_OK,
)
async def rollback_release(
    namespace: str,
    release_name: str,
    revision: int = Query(
        0, ge=0,
        description="Revisione target. 0 = revisione precedente (comportamento nativo Helm)",
    ),
    wait: bool = Query(False),
    manager: HelmManager = Depends(get_helm_manager),
):
    """
    Rollback di una release a una revisione specifica.
    ``revision=0`` equivale a tornare alla revisione precedente.
    """
    result = await manager.rollback(release_name, revision, namespace, wait)
    return _require_success(result, f"helm rollback {release_name} {revision}")


@router.delete(
    "/namespaces/{namespace}/releases/{release_name}",
    status_code=status.HTTP_200_OK,
)
async def uninstall_release(
    namespace: str,
    release_name: str,
    keep_history: bool = Query(
        False,
        description="Se true, preserva la storia della release per rollback futuri",
    ),
    manager: HelmManager = Depends(get_helm_manager),
):
    """
    Rimuove una release Helm e tutte le risorse K8s gestite da essa.
    Con keep_history=true la storia rimane per permettere rollback.
    """
    result = await manager.uninstall(release_name, namespace, keep_history)
    return _require_success(result, f"helm uninstall {release_name}")


# ---------------------------------------------------------------------------
# REPOSITORIES
# ---------------------------------------------------------------------------

@router.get("/repos")
async def list_repos(
    manager: HelmManager = Depends(get_helm_manager),
):
    """
    Elenca i repository Helm configurati.
    Restituisce { "success": true, "data": [] } se nessun repo è configurato
    (helm repo list restituisce rc=1 in quel caso: normalizzato nel manager).
    """
    result = await manager.repo_list()
    # repo_list normalizza già rc=1 "no repositories" → success=True, data=[]
    # Per qualsiasi altro errore (es. filesystem) propaghiamo comunque.
    return _require_success(result, "helm repo list")


@router.post("/repos", status_code=status.HTTP_200_OK)
async def add_repo(
    name: str = Query(..., description="Nome locale del repository"),
    url: str = Query(..., description="URL del repository Helm"),
    username: str = Query(None, description="Username opzionale (es. 'gitlab-token')"),
    password: str = Query(None, description="Token/Password opzionale"),
    manager: HelmManager = Depends(get_helm_manager),
):
    """
    Aggiunge un repository Helm. 
    Supporta l'autenticazione per repository privati (GitLab, GitHub, etc).
    """
    result = await manager.repo_add(name, url, username, password)
    return _require_success(result, f"helm repo add {name}")

@router.post("/repos/update", status_code=status.HTTP_200_OK)
async def update_repos(
    name: str = Query(None, description="Nome opzionale del repository specifico da aggiornare"),
    manager: HelmManager = Depends(get_helm_manager),
):
    """
    Aggiorna l'indice locale dei repository. 
    Se viene fornito un nome, aggiorna solo quel repository, altrimenti li aggiorna tutti.
    """
    result = await manager.repo_update(name)
    
    msg = f"helm repo update {name}" if name else "helm repo update (all)"
    return _require_success(result, msg)

@router.delete("/repos/{name}", status_code=status.HTTP_200_OK)
async def remove_repo(
    name: str,
    manager: HelmManager = Depends(get_helm_manager),
):
    """
    Rimuove un repository Helm per nome (``helm repo remove``).
 
    Non esposto nel frontend — utilizzabile via /docs.
    HTTP 404 se il repository non esiste.
    """
    result = await manager.repo_remove(name)
 
    if not result.get("success"):
        stderr = (result.get("stderr") or "").strip()
        # Helm dice "no repo named X found" quando il nome non esiste
        if "no repo" in stderr.lower() or "not found" in stderr.lower():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Repository '{name}' not found.",
            )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"helm repo remove {name} failed: {stderr[:400]}",
        )
 
    return result


# ---------------------------------------------------------------------------
# CHARTS
# ---------------------------------------------------------------------------

@router.get("/charts/search")
async def search_charts(
    q: str = Query(..., description="Termine di ricerca (es. 'nginx', 'bitnami/redis')"),
    versions: bool = Query(False, description="Mostra tutte le versioni disponibili del chart"),
    manager: HelmManager = Depends(get_helm_manager),
):
    """
    Cerca chart nei repository configurati (helm search repo).
    HTTP 400 se nessun repository è configurato (helm restituisce errore).
    Lista vuota se nessun chart corrisponde alla query.
    """
    result = await manager.search_repo(q, versions)
    _require_success(result, f"helm search repo {q}")
    # Normalizza data null → [] (helm search restituisce null su zero risultati)
    if result["data"] is None:
        result["data"] = []
    return result


@router.get("/charts/values")
async def get_chart_default_values(
    chart_ref: str = Query(
        ...,
        description="Riferimento chart (es. 'bitnami/nginx', 'oci://registry/chart')",
    ),
    version: Optional[str] = Query(
        None,
        description="Versione specifica. Se omesso usa la latest.",
    ),
    manager: HelmManager = Depends(get_helm_manager),
):
    """
    Mostra i valori di default di un chart (helm show values).
    Restituisce YAML grezzo in ``stdout`` — non JSON.
    Usato dal frontend per mostrare i parametri configurabili prima del deploy.
    """
    result = await manager.show_chart_values(chart_ref, version)
    return _require_success(result, f"helm show values {chart_ref}")


# Allowed upload extensions — keep in sync with frontend _ALLOWED_CHART_EXTENSIONS
_ALLOWED_EXTENSIONS = (".zip", ".tgz", ".tar.gz", ".tar.bz2", ".tar.xz")
 
 
# ---------------------------------------------------------------------------
# POST /charts/lint
# ---------------------------------------------------------------------------
 
@router.post("/charts/lint")
async def unified_lint(
    file:      Optional[UploadFile] = File(None),
    chart_ref: Optional[str]        = Form(None),
    version:   Optional[str]        = Form(None),
    strict:    bool                 = Form(False),
    manager:   HelmManager          = Depends(get_helm_manager),
):
    """
    Lints a Helm chart from a local archive upload or a remote repository reference.
 
    Exactly one of ``file`` or ``chart_ref`` must be provided.
 
    - **file**: ZIP, TGZ, TAR.GZ, TAR.BZ2, or TAR.XZ archive.
    - **chart_ref**: remote chart reference (e.g. ``bitnami/nginx``).
    - **version**: chart version (only used with chart_ref).
    - **strict**: treat warnings as errors (``--strict``).
 
    Returns HTTP 200 on success (no errors, possibly warnings).
    Returns HTTP 422 when lint finds errors — body contains stdout/stderr.
    """
    if not file and not chart_ref:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Provide either a chart file upload or a chart_ref string.",
        )
 
    tmp_archive_path: Optional[str] = None
 
    try:
        if file:
            # Stream upload to disk — never read the whole file into RAM
            ext = safe_extension(file.filename or "")
            fd, tmp_archive_path = tempfile.mkstemp(
                suffix=ext, prefix="helm_lint_upload_"
            )
            with os.fdopen(fd, "wb") as f_out:
                shutil.copyfileobj(file.file, f_out)
 
            result = await manager.lint(archive_path=tmp_archive_path, strict=strict)
        else:
            result = await manager.lint(
                chart_ref=chart_ref, version=version, strict=strict
            )
 
    finally:
        if tmp_archive_path and os.path.exists(tmp_archive_path):
            try:
                os.remove(tmp_archive_path)
            except OSError:
                pass
 
    # Return 422 with structured body when lint finds errors,
    # so the frontend can extract stdout/stderr and render them properly.
    if result.get("has_errors"):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "message":      "Chart has lint errors.",
                "stdout":       result.get("stdout", ""),
                "stderr":       result.get("stderr", ""),
                "has_errors":   True,
                "has_warnings": result.get("has_warnings", False),
            },
        )
 
    return {
        "success":      True,
        "stdout":       result.get("stdout", ""),
        "stderr":       result.get("stderr", ""),
        "has_errors":   False,
        "has_warnings": result.get("has_warnings", False),
    }
 
 
# ---------------------------------------------------------------------------
# POST /namespaces/{namespace}/releases/{release_name}/package
# ---------------------------------------------------------------------------
 
@router.post(
    "/namespaces/{namespace}/releases/{release_name}/package",
    status_code=status.HTTP_200_OK,
)
async def install_from_package_route(
    namespace:        str,
    release_name:     str,
    file:             UploadFile    = File(..., description="ZIP, TGZ, or TAR.GZ archive containing a Helm chart"),
    values_json:      Optional[str] = Query(None, description="Override values as a JSON string"),
    atomic:           bool          = Query(False),
    wait:             bool          = Query(False),
    create_namespace: bool          = Query(False),
    dry_run:          bool          = Query(False, description="Simula l'installazione senza alterare il cluster (--dry-run)"),
    manager:          HelmManager   = Depends(get_helm_manager),
):
    """
    Installs or upgrades a Helm release from an uploaded chart archive.
 
    The archive must contain a valid Helm chart (with ``Chart.yaml``).
    Supported: ``.zip``, ``.tgz``, ``.tar.gz``, ``.tar.bz2``, ``.tar.xz``.
 
    The upload is streamed to disk in chunks — memory usage is O(1)
    regardless of archive size.
    """
    # Validate extension before any I/O
    filename = (file.filename or "").lower()
    if not any(filename.endswith(ext) for ext in _ALLOWED_EXTENSIONS):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Unsupported file format. "
                f"Allowed: {', '.join(_ALLOWED_EXTENSIONS)}"
            ),
        )
 
    # Parse optional values override
    values: dict | None = None
    if values_json:
        try:
            values = json.loads(values_json)
        except json.JSONDecodeError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"values_json is not valid JSON: {exc}",
            )
 
    # Stream upload to disk
    ext = safe_extension(file.filename or "")
    fd, tmp_archive_path = tempfile.mkstemp(
        suffix=ext, prefix="helm_pkg_upload_"
    )
 
    try:
        with os.fdopen(fd, "wb") as f_out:
            shutil.copyfileobj(file.file, f_out)
 
        result = await manager.install_from_package(
            archive_path=tmp_archive_path,
            release_name=release_name,
            namespace=namespace,
            values=values,
            atomic=atomic,
            wait=wait,
            create_namespace=create_namespace,
            dry_run=dry_run,
        )
 
    finally:
        if os.path.exists(tmp_archive_path):
            try:
                os.remove(tmp_archive_path)
            except OSError:
                pass
 
    op_desc = f"helm install from package → {release_name}" + (" (dry-run)" if dry_run else "")
    return _require_success(result, op_desc)
