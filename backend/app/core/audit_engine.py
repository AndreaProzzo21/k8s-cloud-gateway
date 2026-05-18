"""
audit_engine.py
===============

Compliance engine for evaluating audit rules against the fleet.

Architecture
------------
Rules are ``AuditRule`` objects registered in the ``RULE_REGISTRY`` dictionary.
Each rule declares:

- ``id``          — unique key, used as ``rule_id`` in the DB.
- ``name``        — human-readable name shown in the UI.
- ``description`` — explanation of what the rule checks.
- ``severity``    — impact if the rule fails: ``critical``, ``warning``, ``info``.
- ``needs``       — set of data keys required from the cluster snapshot.
                    Used by the scanner to know what to collect.
- ``evaluate``    — function ``(cluster_data: dict) -> AuditFinding`` that
                    performs the evaluation and returns the result.

Default-on logic
----------------
If no ``AuditRuleConfig`` record exists in the DB for a given
(cluster_id, rule_id) pair, the rule is considered **enabled**.
This ensures a freshly registered cluster is immediately subject to
the full audit suite without any manual configuration.

Adding a new rule
-----------------
1. Define an ``evaluate(cluster: dict) -> AuditFinding`` function.
2. Create an ``AuditRule`` instance with the required fields.
3. Register it in ``RULE_REGISTRY``.
No DB migration required.

Available data from the scanner
--------------------------------
The cluster snapshot provided to ``run_audit`` has this structure::

    {
        "cluster_id":   str,
        "cluster_name": str,
        "host":         str,
        "status":       "online" | "offline" | "degraded",
        "server_version": str,          # e.g. "1.30"
        "error":        str | None,
        "nodes": [
            {
                "name":             str,
                "status":           str,   # "Ready" | other
                "role":             str,   # "Control Plane" | "Worker"
                "version":          str,   # e.g. "v1.30.14"
                "os":               str,
                "cpu":              str,   # number as string
                "memory":           str,   # Ki as string
                "cpu_allocatable":  str,
                "mem_allocatable":  str,
            }
        ],
        "namespaces": {
            "can_list": bool,
            "items": [
                {"name": str, "status": str}
            ]
        },
        "stats": {
            "cpu_total":    int,
            "pods_total":   int,
            "pods_running": int,
            "pods_failed":  int,
            "pods_pending": int,
            "namespaces_total": int,
            "services_lb":  int,
            "deployments_single_replica": int,
            "deprecated_apis": bool,
        }
    }
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from app.infrastructure.database import AuditRuleConfig, SessionLocal


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class AuditFinding:
    """
    Result of evaluating a single rule against a single cluster.

    ``passed`` is True if the cluster satisfies the rule's requirement.
    ``detail`` contains a human-readable description of the result, including
    specific details (e.g. names of non-ready nodes, detected version).
    ``evidence`` is an optional dictionary with structured data for UI drill-down
    (e.g. list of namespaces without quota, list of nodes with outdated version).
    """
    passed:   bool
    detail:   str
    evidence: dict = field(default_factory=dict)


@dataclass
class AuditRule:
    """
    Definition of a compliance rule.

    Attributes
    ----------
    id          : Unique rule key. Corresponds to ``rule_id`` in the DB.
    name        : Short name shown in the UI.
    description : Detailed explanation of what is checked and why.
    severity    : Impact of failure: ``"critical"``, ``"warning"``, ``"info"``.
    needs       : Set of cluster snapshot keys required for evaluation.
                  Used by the scanner to collect only what the active rules
                  for a given cluster actually need, avoiding unnecessary K8s calls.
    evaluate    : Evaluation function. Receives the full cluster snapshot dict
                  and returns an ``AuditFinding``.
                  Must never raise exceptions: missing data cases should be
                  handled internally with an appropriate finding.
    """
    id:          str
    name:        str
    description: str
    severity:    str
    needs:       set[str]
    evaluate:    Callable[[dict], AuditFinding]


# ---------------------------------------------------------------------------
# System namespaces — excluded from user namespace rules
# ---------------------------------------------------------------------------

_SYSTEM_NAMESPACES = frozenset({
    "kube-system",
    "kube-public",
    "kube-node-lease",
    "kube-flannel",        # common CNI in bare-metal clusters
    "kube-proxy",
    "cert-manager",        # typically considered infrastructure
})

# Minimum supported K8s version — used by k8s-version-policy rule
_MIN_K8S_MINOR = 28   # K8s 1.28 — EOL October 2024, below this threshold is critical


# ---------------------------------------------------------------------------
# Rule evaluation functions
# ---------------------------------------------------------------------------

def _eval_cluster_reachable(cluster: dict) -> AuditFinding:
    """
    The cluster must be reachable and responding to API calls.
    An offline cluster cannot be audited on any other dimension.
    """
    if cluster.get("status") == "online":
        return AuditFinding(passed=True, detail="Cluster reachable and API server responsive.")

    error = cluster.get("error") or "No details available."
    return AuditFinding(
        passed=False,
        detail=f"Cluster unreachable: {error}",
        evidence={"error": error, "host": cluster.get("host")},
    )


def _eval_all_nodes_ready(cluster: dict) -> AuditFinding:
    """
    All cluster nodes must be in Ready state.
    A non-Ready node indicates resource, network, or kubelet issues.
    """
    nodes = cluster.get("nodes") or []
    if not nodes:
        return AuditFinding(
            passed=False,
            detail="No nodes detected — unable to verify node state.",
        )

    not_ready = [n["name"] for n in nodes if n.get("status") != "Ready"]
    if not not_ready:
        return AuditFinding(
            passed=True,
            detail=f"All {len(nodes)} nodes are in Ready state.",
            evidence={"total_nodes": len(nodes)},
        )

    return AuditFinding(
        passed=False,
        detail=f"{len(not_ready)} node(s) not Ready: {', '.join(not_ready)}",
        evidence={"not_ready_nodes": not_ready, "total_nodes": len(nodes)},
    )


def _eval_k8s_version_policy(cluster: dict) -> AuditFinding:
    """
    All nodes must run a K8s version above the minimum supported threshold.
    EOL versions do not receive security patches and may be incompatible
    with updated components (CNI, CSI, admission controllers).
    """
    nodes = cluster.get("nodes") or []
    if not nodes:
        return AuditFinding(passed=False, detail="No nodes available for version check.")

    outdated = []
    for node in nodes:
        version_str = node.get("version", "")
        # Expected format: "v1.30.14" → minor = 30
        try:
            parts = version_str.lstrip("v").split(".")
            minor = int(parts[1]) if len(parts) >= 2 else 0
            if minor < _MIN_K8S_MINOR:
                outdated.append({"node": node["name"], "version": version_str})
        except (ValueError, IndexError):
            # Unparseable version — flag as non-compliant
            outdated.append({"node": node["name"], "version": version_str or "unknown"})

    if not outdated:
        sample_version = nodes[0].get("version", "N/A")
        return AuditFinding(
            passed=True,
            detail=f"All nodes run K8s >= 1.{_MIN_K8S_MINOR} (detected: {sample_version}).",
            evidence={"min_required": f"1.{_MIN_K8S_MINOR}"},
        )

    return AuditFinding(
        passed=False,
        detail=f"{len(outdated)} node(s) running K8s below 1.{_MIN_K8S_MINOR}.",
        evidence={"outdated_nodes": outdated, "min_required": f"1.{_MIN_K8S_MINOR}"},
    )


def _eval_no_failed_pods(cluster: dict) -> AuditFinding:
    """
    No pod should be in Failed state.
    Failed pods indicate unhandled application errors or scheduling issues.
    """
    stats = cluster.get("stats") or {}
    failed = stats.get("pods_failed", 0)
    total  = stats.get("pods_total", 0)

    if failed == 0:
        return AuditFinding(
            passed=True,
            detail=f"No pods in Failed state out of {total} total pods.",
            evidence={"pods_total": total, "pods_failed": 0},
        )

    return AuditFinding(
        passed=False,
        detail=f"{failed} pod(s) in Failed state out of {total} total.",
        evidence={"pods_total": total, "pods_failed": failed},
    )


def _eval_pod_health_ratio(cluster: dict) -> AuditFinding:
    """
    At least 80% of pods must be in Running state.
    A low ratio indicates cluster instability or application issues.
    """
    stats   = cluster.get("stats") or {}
    total   = stats.get("pods_total", 0)
    running = stats.get("pods_running", 0)

    if total == 0:
        return AuditFinding(passed=True, detail="No pods present in the cluster.")

    ratio = (running / total) * 100
    threshold = 80.0

    if ratio >= threshold:
        return AuditFinding(
            passed=True,
            detail=f"{running}/{total} pods Running ({ratio:.0f}%) — above the {threshold:.0f}% threshold.",
            evidence={"pods_running": running, "pods_total": total, "ratio_pct": round(ratio, 1)},
        )

    return AuditFinding(
        passed=False,
        detail=f"Only {running}/{total} pods Running ({ratio:.0f}%) — below the {threshold:.0f}% threshold.",
        evidence={"pods_running": running, "pods_total": total, "ratio_pct": round(ratio, 1)},
    )


def _eval_user_namespaces_present(cluster: dict) -> AuditFinding:
    """
    The cluster must have at least one user namespace (non-system).
    A cluster with no user namespaces has no application workloads deployed.
    """
    ns_data = cluster.get("namespaces") or {}

    if not ns_data.get("can_list", True):
        return AuditFinding(
            passed=True,
            detail="Insufficient permissions to list namespaces — rule skipped.",
        )

    items   = ns_data.get("items") or []
    user_ns = [ns["name"] for ns in items if ns.get("name") not in _SYSTEM_NAMESPACES]

    if user_ns:
        return AuditFinding(
            passed=True,
            detail=f"{len(user_ns)} user namespace(s) found: {', '.join(user_ns)}.",
            evidence={"user_namespaces": user_ns},
        )

    return AuditFinding(
        passed=False,
        detail="No user namespaces found — only system namespaces present.",
        evidence={"system_namespaces": [ns["name"] for ns in items]},
    )


def _eval_namespace_count_reasonable(cluster: dict) -> AuditFinding:
    """
    The number of user namespaces must not exceed a reasonable threshold.
    An excessive count may indicate a lack of governance or an inactive cleanup process.
    The threshold is set to 50 user namespaces — configurable in the future.
    """
    _MAX_USER_NAMESPACES = 50

    ns_data  = cluster.get("namespaces") or {}
    items    = ns_data.get("items") or []
    user_ns  = [ns["name"] for ns in items if ns.get("name") not in _SYSTEM_NAMESPACES]
    count    = len(user_ns)

    if count <= _MAX_USER_NAMESPACES:
        return AuditFinding(
            passed=True,
            detail=f"{count} user namespace(s) — within the {_MAX_USER_NAMESPACES} threshold.",
            evidence={"count": count, "threshold": _MAX_USER_NAMESPACES},
        )

    return AuditFinding(
        passed=False,
        detail=f"{count} user namespaces exceed the {_MAX_USER_NAMESPACES} threshold.",
        evidence={"count": count, "threshold": _MAX_USER_NAMESPACES, "namespaces": user_ns},
    )


def _eval_control_plane_present(cluster: dict) -> AuditFinding:
    """
    At least one Control Plane node must be present in the cluster.
    Absence indicates a gateway configuration issue or missing node labels.
    """
    nodes    = cluster.get("nodes") or []
    cp_nodes = [n["name"] for n in nodes if n.get("role") == "Control Plane"]

    if cp_nodes:
        return AuditFinding(
            passed=True,
            detail=f"Control Plane identified: {', '.join(cp_nodes)}.",
            evidence={"control_plane_nodes": cp_nodes},
        )

    return AuditFinding(
        passed=False,
        detail="No Control Plane node detected.",
        evidence={"total_nodes": len(nodes)},
    )


def _eval_worker_nodes_present(cluster: dict) -> AuditFinding:
    """
    At least one Worker node must be present.
    A cluster with only a Control Plane cannot host application workloads.
    """
    nodes        = cluster.get("nodes") or []
    worker_nodes = [n["name"] for n in nodes if n.get("role") == "Worker"]

    if worker_nodes:
        return AuditFinding(
            passed=True,
            detail=f"{len(worker_nodes)} worker node(s) found: {', '.join(worker_nodes)}.",
            evidence={"worker_nodes": worker_nodes},
        )

    return AuditFinding(
        passed=False,
        detail="No worker nodes detected — cluster cannot schedule application workloads.",
        evidence={"total_nodes": len(nodes)},
    )


def _eval_os_homogeneity(cluster: dict) -> AuditFinding:
    """
    All nodes must run the same operating system.
    Heterogeneous environments increase operational complexity and the risk
    of inconsistent behavior across nodes (syscalls, cgroup versions, kernel features).
    """
    nodes = cluster.get("nodes") or []
    if not nodes:
        return AuditFinding(passed=False, detail="No nodes available for OS check.")

    os_set = set(n.get("os", "unknown") for n in nodes)

    if len(os_set) == 1:
        return AuditFinding(
            passed=True,
            detail=f"All nodes run the same OS: {next(iter(os_set))}.",
            evidence={"os": next(iter(os_set))},
        )

    node_os_map = {n["name"]: n.get("os", "unknown") for n in nodes}
    return AuditFinding(
        passed=False,
        detail=f"Heterogeneous OS detected: {', '.join(sorted(os_set))}.",
        evidence={"os_distribution": node_os_map},
    )


def _eval_node_cpu_pressure(cluster: dict) -> AuditFinding:
    """
    No node should be saturating more than 85% of its CPU capacity.
    High CPU pressure causes scheduling delays, throttling, and degraded
    application performance across the entire node.
    """
    nodes    = cluster.get("nodes") or []
    stressed = []
    for n in nodes:
        try:
            total = int(n.get("cpu", "0"))
            alloc = int(n.get("cpu_allocatable", "0"))
            if total > 0:
                usage = ((total - alloc) / total) * 100
                if usage > 85:
                    stressed.append(f"{n['name']} ({usage:.0f}%)")
        except Exception:
            continue

    if not stressed:
        return AuditFinding(
            passed=True,
            detail="CPU pressure within acceptable limits on all nodes.",
            evidence={"stressed_nodes": []},
        )

    return AuditFinding(
        passed=False,
        detail=f"Node(s) under high CPU pressure (>85%): {', '.join(stressed)}",
        evidence={"stressed_nodes": stressed},
    )


def _eval_namespace_quota_presence(cluster: dict) -> AuditFinding:
    """
    Every user namespace should be protected by a ResourceQuota.
    Namespaces without resource limits are a 'Noisy Neighbor' risk — a single
    misbehaving workload can exhaust cluster-wide resources and starve other tenants.
    Requires the scanner to populate 'has_quota' on each namespace item.
    """
    ns_data = cluster.get("namespaces", {})
    if not ns_data.get("can_list", True):
        return AuditFinding(
            passed=True,
            detail="Insufficient permissions to check ResourceQuotas — rule skipped.",
            evidence={"skipped": True, "reason": "namespaces list not allowed"},
        )

    items   = ns_data.get("items", [])
    user_ns = [ns["name"] for ns in items if ns["name"] not in _SYSTEM_NAMESPACES]
    missing = [
        ns for ns in user_ns
        if not any(n["name"] == ns and n.get("has_quota") for n in items)
    ]

    if not missing:
        return AuditFinding(
            passed=True,
            detail="All user namespaces have ResourceQuotas defined.",
            evidence={"checked_namespaces": user_ns},
        )

    return AuditFinding(
        passed=False,
        detail=f"Namespace(s) without ResourceQuota (risk of resource exhaustion): {', '.join(missing)}",
        evidence={"missing_quotas": missing},
    )


def _eval_loadbalancer_usage(cluster: dict) -> AuditFinding:
    """
    The number of LoadBalancer-type Services should not exceed a safe threshold.
    Each LoadBalancer typically provisions an external IP from a cloud provider
    or a MetalLB pool — excessive use can exhaust IP allocations and incur unexpected costs.
    Threshold: 10 LoadBalancer services.
    """
    stats    = cluster.get("stats", {})
    lb_count = stats.get("services_lb", 0)
    limit    = 10

    if lb_count <= limit:
        return AuditFinding(
            passed=True,
            detail=f"LoadBalancer usage within safe limits ({lb_count}/{limit}).",
            evidence={"lb_count": lb_count, "limit": limit},
        )

    return AuditFinding(
        passed=False,
        detail=f"Excessive LoadBalancer usage ({lb_count}) — risk of IP pool exhaustion or unexpected costs.",
        evidence={"lb_count": lb_count, "limit": limit},
    )


def _eval_pending_pods_check(cluster: dict) -> AuditFinding:
    """
    No pod should be stuck in Pending state.
    Pending pods indicate insufficient cluster resources, unsatisfied node affinity
    rules, missing PersistentVolumes, or unavailable node selectors.
    """
    stats   = cluster.get("stats", {})
    pending = stats.get("pods_pending", 0)

    if pending == 0:
        return AuditFinding(
            passed=True,
            detail="No pods waiting for scheduling.",
            evidence={"pods_pending": 0},
        )

    return AuditFinding(
        passed=False,
        detail=f"{pending} pod(s) in Pending state — possible resource shortage or affinity misconfiguration.",
        evidence={"pods_pending": pending},
    )


def _eval_single_replica_deployments(cluster: dict) -> AuditFinding:
    """
    All Deployments should have more than one replica to ensure high availability.
    Single-replica workloads experience downtime during rolling updates, node
    evictions, or pod crashes, with no healthy replica to serve traffic in the meantime.
    Requires the scanner to populate 'deployments_single_replica' in stats.
    """
    single_replicas = cluster.get("stats", {}).get("deployments_single_replica", 0)

    if single_replicas == 0:
        return AuditFinding(
            passed=True,
            detail="All workloads have multiple replicas (HA).",
            evidence={"single_replica_count": 0},
        )

    return AuditFinding(
        passed=False,
        detail=f"{single_replicas} deployment(s) with a single replica — risk of downtime during updates or pod restarts.",
        evidence={"single_replica_count": single_replicas},
    )


def _eval_deprecated_api_usage(cluster: dict) -> AuditFinding:
    """
    No deprecated or removed Kubernetes API versions should be in use.
    APIs removed in recent versions (e.g. networking.k8s.io/v1beta1 Ingress removed
    in 1.22, autoscaling/v2beta2 removed in 1.26) will cause apply failures after
    a cluster upgrade. Requires the scanner to populate 'deprecated_apis' in stats.
    """
    ver     = cluster.get("server_version", "0.0")
    has_old = cluster.get("stats", {}).get("deprecated_apis", False)

    try:
        version_float = float(ver)
    except (ValueError, TypeError):
        version_float = 0.0

    passed = not (version_float >= 1.29 and has_old)

    if passed:
        return AuditFinding(
            passed=True,
            detail="No deprecated API usage detected.",
            evidence={"server_version": ver},
        )

    return AuditFinding(
        passed=False,
        detail=f"Deprecated API usage detected on K8s {ver} — these APIs may be removed in future upgrades.",
        evidence={"server_version": ver, "deprecated_apis_present": True},
    )


def _eval_node_memory_pressure(cluster: dict) -> AuditFinding:
    """
    No node should be consuming more than 90% of its allocatable memory.
    High memory pressure triggers the OOM killer, evicting pods unpredictably
    and causing cascading failures across co-located workloads.
    Threshold: 90% memory utilization per node.
    """
    nodes    = cluster.get("nodes") or []
    stressed = []

    for n in nodes:
        try:
            # memory and mem_allocatable are expressed in Ki
            total = int(n.get("memory", "0"))
            alloc = int(n.get("mem_allocatable", "0"))
            if total > 0:
                usage = ((total - alloc) / total) * 100
                if usage > 90:
                    stressed.append(f"{n['name']} ({usage:.0f}%)")
        except Exception:
            continue

    if not stressed:
        return AuditFinding(
            passed=True,
            detail="Memory pressure within acceptable limits on all nodes.",
            evidence={"stressed_nodes": []},
        )

    return AuditFinding(
        passed=False,
        detail=f"Node(s) under high memory pressure (>90%): {', '.join(stressed)}",
        evidence={"stressed_nodes": stressed},
    )


def _eval_multi_node_cluster(cluster: dict) -> AuditFinding:
    """
    A production cluster should have more than one node.
    Single-node clusters have no fault tolerance: a node failure takes down
    both the Control Plane and all workloads simultaneously.
    This rule is informational — single-node setups are valid for development.
    """
    nodes      = cluster.get("nodes") or []
    node_count = len(nodes)

    if node_count > 1:
        return AuditFinding(
            passed=True,
            detail=f"Cluster has {node_count} nodes — fault tolerance available.",
            evidence={"node_count": node_count},
        )

    return AuditFinding(
        passed=False,
        detail=f"Single-node cluster detected ({node_count} node) — no fault tolerance. Acceptable for dev/lab, not for production.",
        evidence={"node_count": node_count},
    )


def _eval_default_namespace_usage(cluster: dict) -> AuditFinding:
    """
    Workloads should not be deployed in the 'default' namespace.
    Using 'default' for application workloads bypasses namespace-level RBAC,
    ResourceQuotas, and NetworkPolicies, making it impossible to scope
    permissions and resource limits properly.
    Requires the scanner to populate 'pods_in_default_ns' in stats.
    """
    stats           = cluster.get("stats", {})
    pods_in_default = stats.get("pods_in_default_ns", 0)

    if pods_in_default == 0:
        return AuditFinding(
            passed=True,
            detail="No application pods detected in the 'default' namespace.",
            evidence={"pods_in_default_ns": 0},
        )

    return AuditFinding(
        passed=False,
        detail=f"{pods_in_default} pod(s) running in the 'default' namespace — workloads should use dedicated namespaces.",
        evidence={"pods_in_default_ns": pods_in_default},
    )


# ---------------------------------------------------------------------------
# Rule registry
# ---------------------------------------------------------------------------
# Rules are ordered by severity (critical → warning → info) then by logical
# category. Order determines the display order in the UI.

RULE_REGISTRY: dict[str, AuditRule] = {r.id: r for r in [

    # ── Availability (Critical) ──────────────────────────────────────────

    AuditRule(
        id="cluster-reachable",
        name="Cluster Reachable",
        description=(
            "Verifies that the cluster is reachable and the API server is responding. "
            "An offline cluster cannot be audited on any other dimension. "
            "Common causes: network unavailable, VPN disconnected, cluster powered off."
        ),
        severity="critical",
        needs={"status", "error"},
        evaluate=_eval_cluster_reachable,
    ),

    AuditRule(
        id="all-nodes-ready",
        name="All Nodes Ready",
        description=(
            "All cluster nodes must be in Ready state. "
            "A NotReady node indicates kubelet, network, or resource issues "
            "(memory pressure, disk pressure, CPU pressure)."
        ),
        severity="critical",
        needs={"nodes"},
        evaluate=_eval_all_nodes_ready,
    ),

    AuditRule(
        id="control-plane-present",
        name="Control Plane Node Present",
        description=(
            "At least one Control Plane node must be identifiable. "
            "Absence indicates a node labeling issue or a misconfigured "
            "admin profile used by the scanner."
        ),
        severity="critical",
        needs={"nodes"},
        evaluate=_eval_control_plane_present,
    ),

    AuditRule(
        id="pending-pods-check",
        name="No Pending Pods",
        description=(
            "No pod should be stuck in Pending state. "
            "Pending pods indicate insufficient cluster resources, unsatisfied "
            "node affinity rules, missing PersistentVolumes, or unavailable node selectors."
        ),
        severity="critical",
        needs={"stats"},
        evaluate=_eval_pending_pods_check,
    ),

    # ── Workloads (Warning) ──────────────────────────────────────────────

    AuditRule(
        id="no-failed-pods",
        name="No Failed Pods",
        description=(
            "No pod should be in Failed state. "
            "Failed pods indicate unhandled application errors, scheduling failures, "
            "or insufficient resources."
        ),
        severity="warning",
        needs={"stats"},
        evaluate=_eval_no_failed_pods,
    ),

    AuditRule(
        id="pod-health-ratio",
        name="Pod Health Ratio ≥ 80%",
        description=(
            "At least 80% of pods must be in Running state. "
            "A lower ratio indicates application instability or cluster resource issues."
        ),
        severity="warning",
        needs={"stats"},
        evaluate=_eval_pod_health_ratio,
    ),

    AuditRule(
        id="worker-nodes-present",
        name="Worker Nodes Present",
        description=(
            "The cluster must have at least one Worker node. "
            "A cluster with only a Control Plane cannot host application workloads "
            "in standard configurations."
        ),
        severity="warning",
        needs={"nodes"},
        evaluate=_eval_worker_nodes_present,
    ),

    AuditRule(
        id="ha-workload-policy",
        name="High Availability Deployments",
        description=(
            "All Deployments should have more than one replica to ensure high availability. "
            "Single-replica workloads experience downtime during rolling updates, "
            "node evictions, or pod crashes."
        ),
        severity="warning",
        needs={"stats"},
        evaluate=_eval_single_replica_deployments,
    ),

    AuditRule(
        id="node-cpu-pressure",
        name="Node CPU Pressure < 85%",
        description=(
            "No node should be saturating more than 85% of its CPU capacity. "
            "High CPU pressure causes scheduling delays, throttling, and degraded "
            "application performance across the entire node."
        ),
        severity="warning",
        needs={"nodes"},
        evaluate=_eval_node_cpu_pressure,
    ),

    AuditRule(
        id="node-memory-pressure",
        name="Node Memory Pressure < 90%",
        description=(
            "No node should be consuming more than 90% of its allocatable memory. "
            "High memory pressure triggers the OOM killer, evicting pods unpredictably "
            "and causing cascading failures across co-located workloads."
        ),
        severity="warning",
        needs={"nodes"},
        evaluate=_eval_node_memory_pressure,
    ),

    AuditRule(
        id="namespace-quota-presence",
        name="Namespace Resource Quotas",
        description=(
            "Every user namespace should be protected by a ResourceQuota. "
            "Namespaces without resource limits are a 'Noisy Neighbor' risk — "
            "a single misbehaving workload can exhaust cluster-wide resources."
        ),
        severity="warning",
        needs={"namespaces"},
        evaluate=_eval_namespace_quota_presence,
    ),

    AuditRule(
        id="deprecated-api-check",
        name="Modern API Compliance",
        description=(
            "No deprecated or removed Kubernetes API versions should be in use. "
            "APIs removed in recent versions will cause apply failures after a cluster upgrade."
        ),
        severity="warning",
        needs={"server_version", "stats"},
        evaluate=_eval_deprecated_api_usage,
    ),

    # ── Versioning (Warning) ─────────────────────────────────────────────

    AuditRule(
        id="k8s-version-policy",
        name=f"K8s Version ≥ 1.{_MIN_K8S_MINOR}",
        description=(
            f"All nodes must run Kubernetes >= 1.{_MIN_K8S_MINOR}. "
            "EOL versions do not receive security patches and may be incompatible "
            "with updated components (CNI, CSI, admission controllers)."
        ),
        severity="warning",
        needs={"nodes"},
        evaluate=_eval_k8s_version_policy,
    ),

    AuditRule(
        id="os-homogeneity",
        name="Homogeneous Node OS",
        description=(
            "All nodes must run the same operating system. "
            "Heterogeneous environments increase operational complexity and the risk "
            "of inconsistent behavior (syscalls, cgroup versions, kernel features)."
        ),
        severity="warning",
        needs={"nodes"},
        evaluate=_eval_os_homogeneity,
    ),

    # ── Governance (Info) ────────────────────────────────────────────────

    AuditRule(
        id="user-namespaces-present",
        name="User Namespaces Present",
        description=(
            "The cluster must have at least one non-system namespace. "
            "A cluster without user namespaces has no application workloads deployed "
            "and may indicate an unconfigured cluster."
        ),
        severity="info",
        needs={"namespaces"},
        evaluate=_eval_user_namespaces_present,
    ),

    AuditRule(
        id="namespace-count-reasonable",
        name="Namespace Count ≤ 50",
        description=(
            "The number of user namespaces must not exceed 50. "
            "An excessive count may indicate a lack of governance or "
            "an inactive cleanup process."
        ),
        severity="info",
        needs={"namespaces"},
        evaluate=_eval_namespace_count_reasonable,
    ),

    AuditRule(
        id="loadbalancer-limit",
        name="LoadBalancer Usage Control",
        description=(
            "The number of LoadBalancer-type Services should not exceed 10. "
            "Each LoadBalancer typically provisions an external IP — excessive use "
            "can exhaust IP pool allocations and incur unexpected infrastructure costs."
        ),
        severity="info",
        needs={"stats"},
        evaluate=_eval_loadbalancer_usage,
    ),

    AuditRule(
        id="multi-node-cluster",
        name="Multi-Node Cluster",
        description=(
            "A production cluster should have more than one node. "
            "Single-node clusters have no fault tolerance: a node failure takes down "
            "both the Control Plane and all workloads simultaneously. "
            "Acceptable for development and lab environments."
        ),
        severity="info",
        needs={"nodes"},
        evaluate=_eval_multi_node_cluster,
    ),

    AuditRule(
        id="default-namespace-usage",
        name="No Workloads in Default Namespace",
        description=(
            "Application workloads should not be deployed in the 'default' namespace. "
            "Using 'default' bypasses namespace-level RBAC, ResourceQuotas, and "
            "NetworkPolicies, making it impossible to scope permissions and resource limits properly."
        ),
        severity="info",
        needs={"stats"},
        evaluate=_eval_default_namespace_usage,
    ),

]}


# ---------------------------------------------------------------------------
# Public functions
# ---------------------------------------------------------------------------

def get_all_rules() -> list[dict]:
    """
    Returns the list of all rules available in the registry.
    Used by admin endpoints to display configurable rules in the UI.

    Returns
    -------
    list[dict]
        List of dicts with id, name, description, severity, needs.
        Does not include the evaluate function (not JSON-serializable).
    """
    return [
        {
            "id":          rule.id,
            "name":        rule.name,
            "description": rule.description,
            "severity":    rule.severity,
            "needs":       list(rule.needs),
        }
        for rule in RULE_REGISTRY.values()
    ]


def get_active_rules_for_cluster(cluster_id: str) -> list[AuditRule]:
    """
    Returns the active rules for a cluster, respecting the DB configuration
    (default-on logic).

    Algorithm:
    1. Read all ``AuditRuleConfig`` records for this cluster.
    2. For each rule in the registry:
       - If a record with ``enabled=False`` exists → rule is disabled.
       - Otherwise (record absent or ``enabled=True``) → rule is active.

    Parameters
    ----------
    cluster_id : str
        Cluster ID (e.g. "PROD-1").

    Returns
    -------
    list[AuditRule]
        List of rules to execute against this cluster.
    """
    db = SessionLocal()
    try:
        configs = db.query(AuditRuleConfig).filter(
            AuditRuleConfig.cluster_id == cluster_id
        ).all()
        config_map: dict[str, bool] = {c.rule_id: c.enabled for c in configs}
    finally:
        db.close()

    return [
        rule for rule in RULE_REGISTRY.values()
        if config_map.get(rule.id, True)  # default-on: enabled if no config present
    ]


def get_rule_config_for_cluster(cluster_id: str) -> list[dict]:
    """
    Returns the full configuration of all rules for a cluster,
    including both explicitly configured rules and default-on rules.

    Used by ``GET /admin/audit/rules/{cluster_id}`` to render the
    enable/disable toggles in the Admin Console.

    Returns
    -------
    list[dict]
        List of dicts with id, name, description, severity, enabled, note.
        ``enabled`` reflects the DB config or the default (True) if absent.
        ``note`` is None if no admin note has been set.
    """
    db = SessionLocal()
    try:
        configs = db.query(AuditRuleConfig).filter(
            AuditRuleConfig.cluster_id == cluster_id
        ).all()
        config_map: dict[str, AuditRuleConfig] = {c.rule_id: c for c in configs}
    finally:
        db.close()

    result = []
    for rule in RULE_REGISTRY.values():
        db_config = config_map.get(rule.id)
        result.append({
            "id":          rule.id,
            "name":        rule.name,
            "description": rule.description,
            "severity":    rule.severity,
            "enabled":     db_config.enabled if db_config else True,  # default-on
            "note":        db_config.note    if db_config else None,
        })
    return result


def set_rule_config(cluster_id: str, rule_id: str, enabled: bool, note: str | None = None) -> dict:
    """
    Enables or disables a rule for a specific cluster (upsert).

    Updates the existing record if one exists for (cluster_id, rule_id),
    otherwise creates it.

    Parameters
    ----------
    cluster_id : str
        Target cluster ID.
    rule_id : str
        Rule ID to configure. Must exist in ``RULE_REGISTRY``.
    enabled : bool
        True to enable, False to disable.
    note : str | None
        Optional admin note (e.g. "development cluster — HA not required").

    Returns
    -------
    dict
        Updated configuration with cluster_id, rule_id, enabled, note.

    Raises
    ------
    ValueError
        If ``rule_id`` does not exist in the registry.
    """
    if rule_id not in RULE_REGISTRY:
        raise ValueError(
            f"Rule '{rule_id}' not found in registry. "
            f"Available rules: {', '.join(RULE_REGISTRY.keys())}"
        )

    db = SessionLocal()
    try:
        config = db.query(AuditRuleConfig).filter(
            AuditRuleConfig.cluster_id == cluster_id,
            AuditRuleConfig.rule_id    == rule_id,
        ).first()

        if config:
            config.enabled = enabled
            config.note    = note
        else:
            config = AuditRuleConfig(
                cluster_id=cluster_id,
                rule_id=rule_id,
                enabled=enabled,
                note=note,
            )
            db.add(config)

        db.commit()
        db.refresh(config)

        return {
            "cluster_id": config.cluster_id,
            "rule_id":    config.rule_id,
            "enabled":    config.enabled,
            "note":       config.note,
        }
    finally:
        db.close()


def run_audit(fleet_data: list[dict], respect_config: bool = True) -> list[dict]:
    """
    Runs all audit rules against every cluster in the fleet.

    For each cluster, retrieves the active rules (respecting DB configuration
    if ``respect_config=True``) and evaluates each rule, collecting findings.
    Offline clusters receive only the ``cluster-reachable`` rule to avoid
    false negatives on rules that require data not available when a cluster is down.

    Parameters
    ----------
    fleet_data : list[dict]
        List of cluster snapshots produced by ``scan_all_clusters()``.
    respect_config : bool
        If True (default), uses ``get_active_rules_for_cluster()`` to filter
        rules based on the DB configuration.
        If False, runs all rules against all clusters (useful for testing).

    Returns
    -------
    list[dict]
        List of per-cluster results::

            [
                {
                    "cluster_id":   str,
                    "cluster_name": str,
                    "status":       str,
                    "score":        int,   # rules passed
                    "total":        int,   # rules evaluated
                    "score_pct":    float, # compliance percentage
                    "findings": [
                        {
                            "rule_id":   str,
                            "rule_name": str,
                            "severity":  str,
                            "passed":    bool,
                            "detail":    str,
                            "evidence":  dict,
                        }
                    ]
                }
            ]
    """
    results = []

    for cluster in fleet_data:
        cluster_id = cluster["cluster_id"]
        is_offline = cluster.get("status") == "offline"

        if respect_config:
            active_rules = get_active_rules_for_cluster(cluster_id)
        else:
            active_rules = list(RULE_REGISTRY.values())

        # Offline cluster: run only the reachability rule to avoid false negatives
        # (e.g. "no nodes found" when the cluster is simply powered off)
        if is_offline:
            reachable_rule = RULE_REGISTRY.get("cluster-reachable")
            active_rules   = [reachable_rule] if reachable_rule else []

        findings = []
        for rule in active_rules:
            try:
                finding = rule.evaluate(cluster)
            except Exception as exc:
                # evaluate() should never raise, but handle defensively
                finding = AuditFinding(
                    passed=False,
                    detail=f"Internal error during rule evaluation: {exc}",
                )

            findings.append({
                "rule_id":   rule.id,
                "rule_name": rule.name,
                "severity":  rule.severity,
                "passed":    finding.passed,
                "detail":    finding.detail,
                "evidence":  finding.evidence,
            })

        passed = sum(1 for f in findings if f["passed"])
        total  = len(findings)

        results.append({
            "cluster_id":   cluster_id,
            "cluster_name": cluster.get("cluster_name", cluster_id),
            "status":       cluster.get("status", "unknown"),
            "score":        passed,
            "total":        total,
            "score_pct":    round((passed / total * 100) if total else 0, 1),
            "findings":     findings,
        })

    return results