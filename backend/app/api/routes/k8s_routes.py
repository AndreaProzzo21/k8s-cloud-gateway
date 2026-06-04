import asyncio

from functools import partial
from typing import List, Dict, Optional
from concurrent.futures import ThreadPoolExecutor

from fastapi import APIRouter, Depends, File, UploadFile, HTTPException, status, Query
from fastapi.responses import PlainTextResponse

from app.core.core_manager import CoreManager
from app.api.dependencies.get_core_manager import get_current_core_manager


router = APIRouter()

@router.get("/auth/me")
async def get_user_profile(
    manager: CoreManager = Depends(get_current_core_manager)
):
    """
    Analizza i permessi RBAC del token in tempo reale sul cluster.
    Determina se la dashboard deve mostrare la vista 'Nodi' (Admin)
    o la vista 'Pod' con inserimento manuale del namespace (Restricted).
    """
    return await _run(manager.get_permissions_summary)


# --- CONFIGURAZIONE WORKERS ---
# Creiamo un pool dedicato per le chiamate Kubernetes.
# 100 worker permettono di gestire molti cluster offline contemporaneamente
# senza mai bloccare il login o le altre rotte di sistema.
k8s_executor = ThreadPoolExecutor(
    max_workers=20, 
    thread_name_prefix="k8s_worker"
)

async def _run(fn, *args, **kwargs):
    """
    Esegue una funzione sincrona (bloccante) in un ThreadPool dedicato.
    
    Usa 'k8s_executor' per isolare le chiamate Kubernetes dal resto dell'app,
    e 'asyncio.wait_for' per garantire che il controllo torni al frontend
    anche se il thread sottostante rimane temporaneamente appeso.
    """
    loop = asyncio.get_running_loop()
    
    # Timeout "hard" di sicurezza
    HARD_TIMEOUT = 10.0 

    try:
        # Usiamo k8s_executor invece di None per avere i 100 workers dedicati
        return await asyncio.wait_for(
            loop.run_in_executor(k8s_executor, partial(fn, *args, **kwargs)),
            timeout=HARD_TIMEOUT
        )
    except asyncio.TimeoutError:
        # Se scatta il timeout, il thread nel pool rimarrà occupato fino al 
        # timeout TCP, ma l'event loop viene liberato IMMEDIATAMENTE.
        print(f"[TIMEOUT] Hard limit raggiunto per {fn.__name__}. Thread isolato nel pool.")
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail="The remote server failed to respond within the time limit. The host might be powered off or unreachable."
        )

@router.get("/cluster/health")
async def cluster_health(manager: CoreManager = Depends(get_current_core_manager)):
    """
    Verifica la connettività al cluster via /version (nessun permesso RBAC richiesto).
    Usato dal frontend post-login prima di mostrare la dashboard.
    """
    return await _run(manager.check_connectivity)


# ---------------------------------------------------------------------------
# NAMESPACES
# ---------------------------------------------------------------------------

@router.post("/namespaces/{name}", status_code=status.HTTP_201_CREATED)
async def create_new_namespace(
    name: str,
    manager: CoreManager = Depends(get_current_core_manager)
):
    """Crea un nuovo namespace nel cluster."""
    return await _run(manager.create_namespace, name)


@router.get("/namespaces")
async def get_all_namespaces(
    manager: CoreManager = Depends(get_current_core_manager)
):
    """
    Elenca i namespace del cluster.
    Restituisce always HTTP 200: il campo 'can_list' indica se il profilo
    ha i permessi per listare (False = accesso negato, lista vuota).
    """
    return await _run(manager.list_namespaces)

@router.delete("/namespaces/{name}")
async def delete_cluster_namespace(
    name: str,
    manager: CoreManager = Depends(get_current_core_manager)
):
    """
    Rimuove un namespace dal cluster.
    Attenzione: l'operazione è distruttiva per tutte le risorse nel namespace.
    """
    return await _run(manager.delete_namespace, name)


# ---------------------------------------------------------------------------
# CONFIGMAPS, SECRETS, EVENTS
# ---------------------------------------------------------------------------

@router.get("/namespaces/{namespace}/configmaps")
async def get_configmaps(
    namespace: str,
    label_selector: str = None,
    manager: CoreManager = Depends(get_current_core_manager)
):
    return await _run(manager.list_configmaps, namespace, label_selector)

@router.get("/namespaces/{namespace}/secrets")
async def get_secrets(
    namespace: str,
    label_selector: str = None,
    manager: CoreManager = Depends(get_current_core_manager)
):
    return await _run(manager.list_secrets, namespace, label_selector)



@router.get("/namespaces/{namespace}/events")
async def get_events(
    namespace: str,
    manager: CoreManager = Depends(get_current_core_manager)
):
    """Elenca gli eventi Kubernetes nel namespace, ordinati per timestamp decrescente."""
    return await _run(manager.list_events, namespace)


# ---------------------------------------------------------------------------
# PODS
# ---------------------------------------------------------------------------

@router.get("/namespaces/{namespace}/pods")
async def get_pods(
    namespace: str,
    label_selector: str = None,
    manager: CoreManager = Depends(get_current_core_manager)
):
    """
    Elenca i Pod nel namespace.
    Supporta il filtro opzionale per label tramite query string
    (es. ?label_selector=app=nginx).
    """
    return await _run(manager.list_pods, namespace, label_selector)


@router.get("/namespaces/{namespace}/pods/{name}")
async def get_pod_details(
    namespace: str,
    name: str,
    manager: CoreManager = Depends(get_current_core_manager)
):
    """Restituisce i dettagli di un singolo Pod."""
    return await _run(manager.get_pod_by_name, name, namespace)


@router.get("/namespaces/{namespace}/pods/{name}/logs", response_class=PlainTextResponse)
async def get_pod_logs(
    namespace: str,
    name: str,
    tail: int = Query(100, ge=1, le=5000, description="Numero di righe di log da restituire (1-5000)"),
    manager: CoreManager = Depends(get_current_core_manager)
):
    """
    Restituisce gli ultimi N log di un Pod come testo plain.
    Il parametro `tail` controlla quante righe vengono restituite (default 100, max 5000).
    """
    return await _run(manager.get_pod_logs, name, namespace, tail)


# ---------------------------------------------------------------------------
# DEPLOYMENTS
# ---------------------------------------------------------------------------

@router.get("/namespaces/{namespace}/deployments")
async def get_deployments(
    namespace: str,
    label_selector: str = None,
    manager: CoreManager = Depends(get_current_core_manager)
):
    """
    Elenca i Deployment nel namespace.
    Supporta il filtro opzionale per label tramite query string.
    """
    return await _run(manager.list_deployments, namespace, label_selector)


@router.get("/namespaces/{namespace}/deployments/{name}")
async def get_deployment_details(
    namespace: str,
    name: str,
    manager: CoreManager = Depends(get_current_core_manager)
):
    """Restituisce i dettagli di un singolo Deployment, incluse repliche e immagine."""
    return await _run(manager.get_deployment_by_name, name, namespace)


@router.patch("/namespaces/{namespace}/deployments/{name}/scale")
async def scale_deployment(
    namespace: str,
    name: str,
    replicas: int = Query(..., ge=0, description="Numero di repliche desiderate (>= 0)"),
    manager: CoreManager = Depends(get_current_core_manager)
):
    """
    Scala un Deployment al numero di repliche specificato.
    Passare replicas=0 sospende il deployment senza eliminarlo.
    """
    return await _run(manager.scale_deployment, name, namespace, replicas)


@router.post("/namespaces/{namespace}/deployments/{name}/restart")
async def restart_deploy(
    namespace: str,
    name: str,
    manager: CoreManager = Depends(get_current_core_manager)
):
    """
    Esegue un rollout restart del Deployment iniettando un'annotazione con il timestamp.
    Equivalente a `kubectl rollout restart deployment/<name>`.
    """
    return await _run(manager.restart_deployment, namespace, name)


@router.delete("/namespaces/{namespace}/deployments/{name}")
async def delete_deployment(
    namespace: str,
    name: str,
    manager: CoreManager = Depends(get_current_core_manager)
):
    """Elimina un Deployment dal namespace."""
    return await _run(manager.delete_deployment, name, namespace)


# ---------------------------------------------------------------------------
# SERVICES
# ---------------------------------------------------------------------------

@router.get("/namespaces/{namespace}/services")
async def get_services(
    namespace: str,
    label_selector: str = None,
    manager: CoreManager = Depends(get_current_core_manager)
):
    return await _run(manager.list_services_in_namespace, namespace, label_selector)


@router.get("/namespaces/{namespace}/services/{name}")
async def get_service_details(
    namespace: str,
    name: str,
    manager: CoreManager = Depends(get_current_core_manager)
):
    """Restituisce i dettagli di un Service, incluse porte e selettori."""
    return await _run(manager.get_service_by_name, name, namespace)


# ---------------------------------------------------------------------------
# UNIVERSAL APPLY
# ---------------------------------------------------------------------------

@router.post("/apply")  # Rimosso /namespaces/{namespace}
async def apply_resource(
    file: UploadFile = File(...),
    manager: CoreManager = Depends(get_current_core_manager)
):
    """
    Applica un manifesto YAML multi-risorsa in modo indipendente.
    Il namespace viene letto direttamente dal file YAML. 
    Se assente, K8s userà il default o restituirà errore in base ai permessi.
    """
    if not file.filename.lower().endswith((".yaml", ".yml")):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Il file deve avere estensione .yaml o .yml"
        )

    content = await file.read()
    # Passiamo solo il contenuto, senza forzare un namespace
    return await _run(manager.apply_universal_yaml, content.decode("utf-8"))


# ---------------------------------------------------------------------------
# DELETE — PODS, SERVICES, CONFIGMAPS, SECRETS
# ---------------------------------------------------------------------------

@router.delete("/namespaces/{namespace}/pods/{name}")
async def delete_pod(
    namespace: str,
    name: str,
    manager: CoreManager = Depends(get_current_core_manager)
):
    """Elimina un Pod. Kubernetes ricrea automaticamente il Pod se gestito da un controller."""
    return await _run(manager.delete_pod, name, namespace)


@router.delete("/namespaces/{namespace}/services/{name}")
async def delete_service(
    namespace: str,
    name: str,
    manager: CoreManager = Depends(get_current_core_manager)
):
    """Elimina un Service dal namespace."""
    return await _run(manager.delete_service, name, namespace)


@router.delete("/namespaces/{namespace}/configmaps/{name}")
async def delete_configmap(
    namespace: str,
    name: str,
    manager: CoreManager = Depends(get_current_core_manager)
):
    """Elimina una ConfigMap dal namespace."""
    return await _run(manager.delete_configmap, name, namespace)


@router.delete("/namespaces/{namespace}/secrets/{name}")
async def delete_secret(
    namespace: str,
    name: str,
    manager: CoreManager = Depends(get_current_core_manager)
):
    """Elimina un Secret dal namespace."""
    return await _run(manager.delete_secret, name, namespace)


# ---------------------------------------------------------------------------
# NODES (cluster-wide)
# ---------------------------------------------------------------------------

@router.get("/cluster/nodes", response_model=List[Dict])
async def get_cluster_nodes(
    manager: CoreManager = Depends(get_current_core_manager)
):
    """
    Restituisce i dettagli tecnici dei nodi del cluster: CPU, memoria,
    versione kubelet, OS e ruolo (Control Plane / Worker).
    Richiede permessi di Cluster Admin sul Service Account.
    """
    return await _run(manager.list_nodes)


# ---------------------------------------------------------------------------
# RBAC
# ---------------------------------------------------------------------------

@router.get("/namespaces/{namespace}/serviceaccounts")
async def get_sas(
    namespace: str,
    manager: CoreManager = Depends(get_current_core_manager)
):
    """Elenca i ServiceAccount nel namespace."""
    return await _run(manager.list_service_accounts, namespace)


@router.delete("/namespaces/{namespace}/serviceaccounts/{name}")
async def del_sa(
    namespace: str,
    name: str,
    manager: CoreManager = Depends(get_current_core_manager)
):
    """Elimina un ServiceAccount dal namespace."""
    return await _run(manager.delete_service_account, namespace, name)


@router.get("/namespaces/{namespace}/roles")
async def get_roles(
    namespace: str,
    manager: CoreManager = Depends(get_current_core_manager)
):
    """Elenca i Role nel namespace con il numero di regole associate."""
    return await _run(manager.list_roles, namespace)


@router.delete("/namespaces/{namespace}/roles/{name}")
async def del_role(
    namespace: str,
    name: str,
    manager: CoreManager = Depends(get_current_core_manager)
):
    """Elimina un Role dal namespace."""
    return await _run(manager.delete_role, namespace, name)


@router.get("/namespaces/{namespace}/rolebindings")
async def get_bindings(
    namespace: str,
    manager: CoreManager = Depends(get_current_core_manager)
):
    """Elenca i RoleBinding nel namespace con role e subject associati."""
    return await _run(manager.list_role_bindings, namespace)


@router.delete("/namespaces/{namespace}/rolebindings/{name}")
async def del_binding(
    namespace: str,
    name: str,
    manager: CoreManager = Depends(get_current_core_manager)
):
    """Elimina un RoleBinding dal namespace."""
    return await _run(manager.delete_role_binding, namespace, name)


# ---------------------------------------------------------------------------
# INGRESS
# ---------------------------------------------------------------------------

@router.get("/namespaces/{namespace}/ingress")
async def get_ingress(
    namespace: str,
    label_selector: str = None,
    manager: CoreManager = Depends(get_current_core_manager)
):
    return await _run(manager.list_ingress, namespace, label_selector)


@router.delete("/namespaces/{namespace}/ingress/{name}")
async def delete_ingress_resource(
    namespace: str,
    name: str,
    manager: CoreManager = Depends(get_current_core_manager)
):
    """Elimina una risorsa Ingress dal namespace."""
    return await _run(manager.delete_ingress, name, namespace)

@router.get("/cluster/volumes")
async def get_persistent_volumes(
    manager: CoreManager = Depends(get_current_core_manager)
):
    """Risorsa a livello di Cluster: PV."""
    return await _run(manager.list_persistent_volumes)

@router.get("/namespaces/{namespace}/pvc")
async def get_namespaced_pvc(
    namespace: str,
    manager: CoreManager = Depends(get_current_core_manager)
):
    """Risorsa a livello di Namespace: PVC."""
    return await _run(manager.list_namespaced_pvc, namespace)

@router.delete("/namespaces/{namespace}/pvc/{name}")
async def delete_pvc(
    namespace: str,
    name: str,
    manager: CoreManager = Depends(get_current_core_manager)
):
    """Elimina un PVC specifico."""
    return await _run(manager.delete_namespaced_pvc, name, namespace)

@router.get("/cluster/storage-classes")
async def get_storage_classes(manager: CoreManager = Depends(get_current_core_manager)):
    return await _run(manager.list_storage_classes)



@router.get("/namespaces/{namespace}/statefulsets")
async def get_stateful_sets(
    namespace: str, 
    label_selector: Optional[str] = None,  # Aggiungi questa riga
    manager: CoreManager = Depends(get_current_core_manager)
):
    """Recupera gli StatefulSet, opzionalmente filtrati per label."""
    return await _run(manager.list_namespaced_stateful_sets, namespace, label_selector)

@router.delete("/namespaces/{namespace}/statefulsets/{name}")
async def delete_stateful_set(
    namespace: str,
    name: str,
    manager: CoreManager = Depends(get_current_core_manager)
):
    """Elimina uno StatefulSet specifico."""
    return await _run(manager.delete_namespaced_stateful_set, name, namespace)

@router.delete("/cluster/storage-classes/{name}")
async def delete_cluster_storage_class(
    name: str,
    manager: CoreManager = Depends(get_current_core_manager)
):
    """Elimina una StorageClass specifica a livello di cluster."""
    return await _run(manager.delete_storage_class, name)

# ---------------------------------------------------------------------------
# DAEMONSETS
# ---------------------------------------------------------------------------

@router.get("/namespaces/{namespace}/daemonsets")
async def get_daemonsets(
    namespace: str,
    label_selector: str = None,
    manager: CoreManager = Depends(get_current_core_manager)
):
    """Elenca i DaemonSet nel namespace con stato di scheduling sui nodi."""
    return await _run(manager.list_daemonsets, namespace, label_selector)

@router.delete("/namespaces/{namespace}/daemonsets/{name}")
async def delete_daemonset(
    namespace: str,
    name: str,
    manager: CoreManager = Depends(get_current_core_manager)
):
    """Elimina un DaemonSet dal namespace."""
    return await _run(manager.delete_daemonset, name, namespace)


# ---------------------------------------------------------------------------
# CRONJOBS
# ---------------------------------------------------------------------------

@router.get("/namespaces/{namespace}/cronjobs")
async def get_cronjobs(
    namespace: str,
    label_selector: str = None,
    manager: CoreManager = Depends(get_current_core_manager)
):
    """Elenca i CronJob nel namespace con schedule e stato ultima esecuzione."""
    return await _run(manager.list_cronjobs, namespace, label_selector)

@router.delete("/namespaces/{namespace}/cronjobs/{name}")
async def delete_cronjob(
    namespace: str,
    name: str,
    manager: CoreManager = Depends(get_current_core_manager)
):
    """Elimina un CronJob dal namespace."""
    return await _run(manager.delete_cronjob, name, namespace)


# ---------------------------------------------------------------------------
# JOBS
# ---------------------------------------------------------------------------

@router.get("/namespaces/{namespace}/jobs")
async def get_jobs(
    namespace: str,
    label_selector: str = None,
    manager: CoreManager = Depends(get_current_core_manager)
):
    """Elenca i Job nel namespace con contatori succeeded/failed/active."""
    return await _run(manager.list_jobs, namespace, label_selector)

@router.delete("/namespaces/{namespace}/jobs/{name}")
async def delete_job(
    namespace: str,
    name: str,
    manager: CoreManager = Depends(get_current_core_manager)
):
    """Elimina un Job e i Pod figli (propagation Foreground)."""
    return await _run(manager.delete_job, name, namespace)


# ---------------------------------------------------------------------------
# HORIZONTAL POD AUTOSCALERS
# ---------------------------------------------------------------------------

@router.get("/namespaces/{namespace}/hpa")
async def get_hpas(
    namespace: str,
    label_selector: str = None,
    manager: CoreManager = Depends(get_current_core_manager)
):
    """Elenca gli HPA nel namespace con target, min/max replicas e stato corrente."""
    return await _run(manager.list_hpas, namespace, label_selector)

@router.delete("/namespaces/{namespace}/hpa/{name}")
async def delete_hpa(
    namespace: str,
    name: str,
    manager: CoreManager = Depends(get_current_core_manager)
):
    """Elimina un HorizontalPodAutoscaler dal namespace."""
    return await _run(manager.delete_hpa, name, namespace)


# ---------------------------------------------------------------------------
# NETWORK POLICIES
# ---------------------------------------------------------------------------

@router.get("/namespaces/{namespace}/networkpolicies")
async def get_network_policies(
    namespace: str,
    label_selector: str = None,
    manager: CoreManager = Depends(get_current_core_manager)
):
    """Elenca le NetworkPolicy nel namespace con pod selector e tipo di regole."""
    return await _run(manager.list_network_policies, namespace, label_selector)

@router.delete("/namespaces/{namespace}/networkpolicies/{name}")
async def delete_network_policy(
    namespace: str,
    name: str,
    manager: CoreManager = Depends(get_current_core_manager)
):
    """Elimina una NetworkPolicy dal namespace."""
    return await _run(manager.delete_network_policy, name, namespace)


# ---------------------------------------------------------------------------
# CLUSTER ROLES (cluster-wide)
# ---------------------------------------------------------------------------

@router.get("/cluster/clusterroles")
async def get_cluster_roles(
    manager: CoreManager = Depends(get_current_core_manager)
):
    """Elenca i ClusterRole a livello cluster."""
    return await _run(manager.list_cluster_roles)

@router.delete("/cluster/clusterroles/{name}")
async def delete_cluster_role(
    name: str,
    manager: CoreManager = Depends(get_current_core_manager)
):
    """Elimina un ClusterRole. Attenzione: operazione distruttiva per i binding associati."""
    return await _run(manager.delete_cluster_role, name)


# ---------------------------------------------------------------------------
# CLUSTER ROLE BINDINGS (cluster-wide)
# ---------------------------------------------------------------------------

@router.get("/cluster/clusterrolebindings")
async def get_cluster_role_bindings(
    manager: CoreManager = Depends(get_current_core_manager)
):
    """Elenca i ClusterRoleBinding a livello cluster con subject e role associati."""
    return await _run(manager.list_cluster_role_bindings)

@router.delete("/cluster/clusterrolebindings/{name}")
async def delete_cluster_role_binding(
    name: str,
    manager: CoreManager = Depends(get_current_core_manager)
):
    """Elimina un ClusterRoleBinding."""
    return await _run(manager.delete_cluster_role_binding, name)

@router.get("/namespaces/{namespace}/daemonsets/{name}")
async def get_daemonset_details(
    namespace: str, name: str,
    manager: CoreManager = Depends(get_current_core_manager)
):
    return await _run(manager.get_daemonset_by_name, name, namespace)

@router.get("/namespaces/{namespace}/jobs/{name}")
async def get_job_details(
    namespace: str, name: str,
    manager: CoreManager = Depends(get_current_core_manager)
):
    return await _run(manager.get_job_by_name, name, namespace)

@router.get("/namespaces/{namespace}/cronjobs/{name}")
async def get_cronjob_details(
    namespace: str, name: str,
    manager: CoreManager = Depends(get_current_core_manager)
):
    return await _run(manager.get_cronjob_by_name, name, namespace)