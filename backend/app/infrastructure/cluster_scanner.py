"""
cluster_scanner.py
==================

Parallel fleet scanner. Collects a snapshot of every registered cluster
using the best available admin profile, then returns structured data consumed
by the AuditEngine and ObserverEngine.

Snapshot schema
---------------
Each call to ``scan_all_clusters()`` returns a list of dicts with this shape::

    {
        "cluster_id":     str,
        "cluster_name":   str,
        "host":           str,
        "profile_used":   str | None,
        "status":         "online" | "degraded" | "offline",
        "server_version": str,          # e.g. "1.30"
        "error":          str | None,
        "nodes": [
            {
                "name":            str,
                "status":          str,   # "Ready" | other
                "role":            str,   # "Control Plane" | "Worker"
                "version":         str,
                "os":              str,
                "cpu":             str,   # total millicores as string
                "memory":          str,   # total Ki as string
                "cpu_allocatable": str,
                "mem_allocatable": str,
            }
        ],
        "namespaces": {
            "can_list": bool,
            "items": [
                {"name": str, "status": str, "has_quota": bool}
            ]
        },
        "stats": {
            "cpu_total":                  int,
            "pods_total":                 int,
            "pods_running":               int,
            "pods_failed":                int,
            "pods_pending":               int,
            "pods_in_default_ns":         int,
            "services_lb":                int,
            "deployments_single_replica": int,
            "namespaces_total":           int,
            "deprecated_apis":            bool,
        }
    }

Status logic
------------
- ``online``   — all nodes Ready, no scan errors.
- ``degraded`` — cluster reachable but one or more nodes not Ready,
                 or partial scan failures (some calls returned exceptions).
- ``offline``  — no token available, connection timed out, or both nodes
                 and namespaces returned empty / error.
"""

import asyncio
from functools import partial
from concurrent.futures import ThreadPoolExecutor

from app.infrastructure.database import SessionLocal, ClusterModel, ProfileModel
from app.infrastructure.k8s_factory import K8sClientFactory
from app.core.core_manager import CoreManager


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Profile names tried in order when looking for a wide-scope token.
# The first match wins; if none found, falls back to any profile on the cluster.
ADMIN_PROFILE_NAMES = ["admin", "gateway-admin", "cluster-admin"]

# Per-operation timeout in seconds. Keeps the scanner from blocking the
# event loop when a cluster is slow to respond.
SCAN_TIMEOUT = 5

# Dedicated thread pool for blocking K8s SDK calls.
# 50 workers: allows scanning many clusters in parallel without starving
# the main executor used by the gateway's request handlers.
executor = ThreadPoolExecutor(max_workers=50)

# Kubernetes API groups that have been deprecated or removed in recent versions.
# Used to populate the ``deprecated_apis`` flag in stats.
# Keys are the apiVersion string; values are the K8s minor version of removal.
_DEPRECATED_API_VERSIONS: dict[str, int] = {
    "networking.k8s.io/v1beta1":    22,   # Ingress removed in 1.22
    "extensions/v1beta1":           16,   # most resources removed in 1.16
    "autoscaling/v2beta1":          23,   # HPA removed in 1.23
    "autoscaling/v2beta2":          26,   # HPA removed in 1.26
    "policy/v1beta1":               25,   # PodDisruptionBudget removed in 1.25
    "batch/v1beta1":                21,   # CronJob removed in 1.21
}


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

async def scan_all_clusters() -> list[dict]:
    """
    Scans all registered clusters in parallel and returns their snapshots.

    Queries the database for all ``ClusterModel`` records, resolves the best
    available admin profile for each, then fans out to ``_scan_single_cluster``
    concurrently via ``asyncio.gather``.

    Returns
    -------
    list[dict]
        One snapshot dict per cluster (see module docstring for schema).
        Never raises — individual cluster failures are captured in the
        snapshot's ``error`` field with ``status="offline"``.
    """
    db = SessionLocal()
    try:
        clusters = db.query(ClusterModel).all()
        cluster_configs = []
        for cluster in clusters:
            profile = _find_best_profile(db, cluster.id)
            cluster_configs.append({
                "cluster_id":   cluster.id,
                "cluster_name": cluster.name,
                "host":         cluster.host,
                "ca_cert":      cluster.ca_cert,
                "k8s_token":    profile.k8s_token if profile else None,
                "profile_name": profile.name if profile else None,
            })
    finally:
        db.close()

    if not cluster_configs:
        return []

    tasks = [_scan_single_cluster(cfg) for cfg in cluster_configs]
    return await asyncio.gather(*tasks)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _find_best_profile(db, cluster_id: str):
    """
    Returns the best available profile for fleet scanning.

    Tries each name in ADMIN_PROFILE_NAMES in order. Falls back to the
    first available profile if none of the preferred names exist.
    Returns None if the cluster has no profiles at all.
    """
    for name in ADMIN_PROFILE_NAMES:
        profile = db.query(ProfileModel).filter(
            ProfileModel.cluster_id == cluster_id.upper(),
            ProfileModel.name == name,
        ).first()
        if profile:
            return profile
    # Fallback: any profile on this cluster
    return db.query(ProfileModel).filter(
        ProfileModel.cluster_id == cluster_id.upper()
    ).first()


def _build_empty_snapshot(cfg: dict) -> dict:
    """Returns a fully-typed offline snapshot to use as base or on failure."""
    return {
        "cluster_id":   cfg["cluster_id"],
        "cluster_name": cfg["cluster_name"],
        "host":         cfg["host"],
        "profile_used": cfg["profile_name"],
        "status":       "offline",
        "server_version": "N/A",
        "error":        None,
        "nodes":        [],
        "namespaces":   {"can_list": False, "items": []},
        "stats": {
            "cpu_total":                  0,
            "pods_total":                 0,
            "pods_running":               0,
            "pods_failed":                0,
            "pods_pending":               0,
            "pods_in_default_ns":         0,
            "services_lb":                0,
            "deployments_single_replica": 0,
            "namespaces_total":           0,
            "deprecated_apis":            False,
        },
    }


def _detect_deprecated_apis(server_version: str, resources: list[dict]) -> bool:
    """
    Returns True if any resource in ``resources`` uses a deprecated or removed
    API version relative to ``server_version``.

    Parameters
    ----------
    server_version : str
        Server minor version string, e.g. "1.30".
    resources : list[dict]
        List of resource dicts that each contain an ``api_version`` key.
        Populated by CoreManager methods that support fleet-wide listing.
    """
    try:
        minor = int(str(server_version).split(".")[-1])
    except (ValueError, IndexError):
        return False

    for resource in resources:
        api_ver = resource.get("api_version", "")
        removed_in = _DEPRECATED_API_VERSIONS.get(api_ver)
        if removed_in is not None and minor >= removed_in:
            return True
    return False


def _determine_status(nodes: list[dict], partial_failure: bool) -> str:
    """
    Derives the cluster status string from node states and scan completeness.

    - ``online``   — all nodes Ready and no partial scan failures.
    - ``degraded`` — reachable but at least one node not Ready, or partial failure.
    - ``offline``  — no nodes returned at all (connection failure).
    """
    if not nodes:
        return "offline"
    all_ready = all(n.get("status") == "Ready" for n in nodes)
    if all_ready and not partial_failure:
        return "online"
    return "degraded"


# ---------------------------------------------------------------------------
# Single-cluster scan
# ---------------------------------------------------------------------------

async def _scan_single_cluster(cfg: dict) -> dict:
    """
    Scans a single cluster and returns its snapshot.

    All K8s SDK calls run in the dedicated ``executor`` thread pool.
    ``asyncio.wait_for`` enforces a hard timeout per-call and for the
    overall gather, so a slow or unresponsive cluster never blocks the
    event loop beyond ``SCAN_TIMEOUT + 2`` seconds.
    """
    base = _build_empty_snapshot(cfg)

    if not cfg["k8s_token"]:
        base["error"] = "No admin token available for this cluster."
        return base

    loop = asyncio.get_running_loop()

    try:
        # ── Step 1: build the K8s client ────────────────────────────────
        k8s_apis = await asyncio.wait_for(
            loop.run_in_executor(executor, partial(
                K8sClientFactory.get_apis,
                cluster_host=cfg["host"],
                k8s_token=cfg["k8s_token"],
                ca_cert=cfg["ca_cert"],
                cluster_id=cfg["cluster_id"],
            )),
            timeout=SCAN_TIMEOUT,
        )
        manager = CoreManager(k8s_apis)

        # ── Step 2: fan-out all data collection calls in parallel ────────
        # return_exceptions=True ensures one failing call does not cancel others.
        # Each result is individually checked below.
        results = await asyncio.wait_for(
            asyncio.gather(
                loop.run_in_executor(executor, partial(manager.list_nodes,                _request_timeout=SCAN_TIMEOUT)),
                loop.run_in_executor(executor, partial(manager.list_namespaces,           _request_timeout=SCAN_TIMEOUT)),
                loop.run_in_executor(executor, partial(manager.list_pods,       namespace=None, _request_timeout=SCAN_TIMEOUT)),
                loop.run_in_executor(executor, partial(manager.check_connectivity)),
                loop.run_in_executor(executor, partial(manager.list_resource_quotas,      namespace=None, _request_timeout=SCAN_TIMEOUT)),
                loop.run_in_executor(executor, partial(manager.list_services,             namespace=None, _request_timeout=SCAN_TIMEOUT)),
                loop.run_in_executor(executor, partial(manager.list_deployments_fleet,    namespace=None, _request_timeout=SCAN_TIMEOUT)),
                loop.run_in_executor(executor, partial(manager.list_ingresses_fleet,      namespace=None, _request_timeout=SCAN_TIMEOUT)),
                return_exceptions=True,
            ),
            timeout=SCAN_TIMEOUT + 2,
        )

    except asyncio.TimeoutError:
        base["error"] = "Cluster connection timed out."
        return base
    except Exception as exc:
        base["error"] = f"Scanner internal error: {exc}"
        return base

    # ── Step 3: unpack results, treating exceptions as empty fallbacks ───
    (
        res_nodes, res_ns, res_pods, res_ver,
        res_quotas, res_svcs, res_depl, res_ingresses,
    ) = results

    # Track whether any call partially failed (affects status: degraded vs online)
    partial_failure = any(isinstance(r, Exception) for r in results)

    nodes       = res_nodes     if isinstance(res_nodes, list)  else []
    namespaces  = res_ns        if isinstance(res_ns, dict)     else {"can_list": False, "items": []}
    pods        = res_pods      if isinstance(res_pods, list)   else []
    version     = res_ver       if isinstance(res_ver, dict)    else {}
    quotas      = res_quotas    if isinstance(res_quotas, list) else []
    services    = res_svcs      if isinstance(res_svcs, list)   else []
    deployments = res_depl      if isinstance(res_depl, list)   else []
    ingresses   = res_ingresses if isinstance(res_ingresses, list) else []

    # If both nodes and namespaces are empty we consider the cluster unreachable
    if not nodes and not namespaces.get("items"):
        base["error"] = "Unreachable or returned empty results."
        return base

    # ── Step 4: enrich and aggregate ────────────────────────────────────

    # Namespaces: mark which ones have a ResourceQuota
    ns_with_quota = {q.get("namespace") for q in quotas if isinstance(q, dict)}
    ns_items      = namespaces.get("items", [])
    for ns in ns_items:
        ns["has_quota"] = ns.get("name") in ns_with_quota

    # Pod stats
    pod_running        = sum(1 for p in pods if p.get("status") == "Running")
    pod_failed         = sum(1 for p in pods if p.get("status") == "Failed")
    pod_pending        = sum(1 for p in pods if p.get("status") == "Pending")
    pods_in_default_ns = sum(1 for p in pods if p.get("namespace") == "default")

    # Service and deployment stats
    services_lb     = sum(1 for s in services    if s.get("type") == "LoadBalancer")
    single_replicas = sum(1 for d in deployments if d.get("replicas_desired", 0) == 1)

    # CPU total (sum of all node CPU counts)
    total_cpu = 0
    for n in nodes:
        try:
            total_cpu += int(n.get("cpu", 0))
        except (ValueError, TypeError):
            pass

    # Deprecated API detection: check ingresses and deployments api_version fields
    server_version  = version.get("server_version", "N/A")
    deprecated_apis = _detect_deprecated_apis(server_version, ingresses + deployments)

    return {
        **base,
        "status":         _determine_status(nodes, partial_failure),
        "server_version": server_version,
        "error":          None,
        "nodes":          nodes,
        "namespaces": {
            "can_list": namespaces.get("can_list", True),
            "items":    ns_items,
        },
        "stats": {
            "cpu_total":                  total_cpu,
            "pods_total":                 len(pods),
            "pods_running":               pod_running,
            "pods_failed":                pod_failed,
            "pods_pending":               pod_pending,
            "pods_in_default_ns":         pods_in_default_ns,
            "services_lb":                services_lb,
            "deployments_single_replica": single_replicas,
            "namespaces_total":           len(ns_items),
            "deprecated_apis":            deprecated_apis,
        },
    }