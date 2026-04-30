from fastapi import APIRouter, Depends, File, UploadFile, HTTPException, status, Query
from fastapi.responses import PlainTextResponse
from typing import List, Dict
from app.core.core_manager import CoreManager
from app.api.deps import get_current_core_manager

router = APIRouter()


# --- NAMESPACES ---
@router.post("/namespaces/{name}")
async def create_new_namespace(name: str, manager: CoreManager = Depends(get_current_core_manager)):
    return manager.create_namespace(name)

@router.get("/namespaces")
async def get_all_namespaces(manager: CoreManager = Depends(get_current_core_manager)):
    return manager.list_namespaces()

# --- CONFIG/EVENTS ---
@router.get("/namespaces/{namespace}/configmaps")
async def get_configmaps(namespace: str, manager: CoreManager = Depends(get_current_core_manager)):
    return manager.list_configmaps(namespace)

@router.get("/namespaces/{namespace}/secrets")
async def get_secrets(namespace: str, manager: CoreManager = Depends(get_current_core_manager)):
    return manager.list_secrets(namespace)

@router.get("/namespaces/{namespace}/events")
async def get_events(namespace: str, manager: CoreManager = Depends(get_current_core_manager)):
    return manager.list_events(namespace)

# --- PODS ---
@router.get("/namespaces/{namespace}/pods")
async def get_pods(
    namespace: str, 
    label_selector: str = None, # FastAPI lo legge automaticamente dalla query string
    manager: CoreManager = Depends(get_current_core_manager)
):
    return manager.list_pods(namespace, label_selector)

@router.get("/namespaces/{namespace}/pods/{name}")
async def get_pod_details(namespace: str, name: str, manager: CoreManager = Depends(get_current_core_manager)):
    return manager.get_pod_by_name(name, namespace)

@router.get("/namespaces/{namespace}/pods/{name}/logs", response_class=PlainTextResponse)
async def get_pod_logs(namespace: str, name: str, tail: int = Query(100), manager: CoreManager = Depends(get_current_core_manager)):
    return manager.get_pod_logs(name, namespace, tail_lines=tail)

# --- DEPLOYMENTS ---

@router.get("/namespaces/{namespace}/deployments")
async def get_deployments(
    namespace: str, 
    label_selector: str = None,
    manager: CoreManager = Depends(get_current_core_manager)
):
    return manager.list_deployments(namespace, label_selector)

@router.get("/namespaces/{namespace}/deployments/{name}")
async def get_deployment_details(namespace: str, name: str, manager: CoreManager = Depends(get_current_core_manager)):
    return manager.get_deployment_by_name(name, namespace)

@router.patch("/namespaces/{namespace}/deployments/{name}/scale")
async def scale_deployment(namespace: str, name: str, replicas: int, manager: CoreManager = Depends(get_current_core_manager)):
    # Ora manager.scale_deployment restituisce un dict pulito, non un oggetto complesso
    return manager.scale_deployment(name, namespace, replicas)

@router.post("/namespaces/{namespace}/deployments/{name}/restart")
async def restart_deploy(namespace: str, name: str, manager: CoreManager = Depends(get_current_core_manager)):
    # Se manager.restart_deployment restituisce l'oggetto K8s, qui avrai il crash
    result = manager.restart_deployment(namespace, name)
    return result  # Ora result è un dizionario semplice {"status": "success", ...}

@router.delete("/namespaces/{namespace}/deployments/{name}")
async def delete_deployment(namespace: str, name: str, manager: CoreManager = Depends(get_current_core_manager)):
    return manager.delete_deployment(name, namespace)

# --- SERVICES ---
@router.get("/namespaces/{namespace}/services")
async def list_services(namespace: str, manager: CoreManager = Depends(get_current_core_manager)):
    return manager.list_services_in_namespace(namespace)

@router.get("/namespaces/{namespace}/services/{name}")
async def get_service_details(namespace: str, name: str, manager: CoreManager = Depends(get_current_core_manager)):
    return manager.get_service_by_name(name, namespace)

# --- WRITE OPERATIONS (UNIVERSAL APPLY) ---
@router.post("/namespaces/{namespace}/apply")
async def apply_resource(namespace: str, file: UploadFile = File(...), manager: CoreManager = Depends(get_current_core_manager)):
    if not file.filename.lower().endswith(('.yaml', '.yml')):
        raise HTTPException(status_code=400, detail="Il file deve essere uno YAML")
    
    content = await file.read()
    return manager.apply_universal_yaml(content.decode('utf-8'), namespace)

# --- DELETE ROUTES ---

@router.delete("/namespaces/{namespace}/pods/{name}")
async def delete_pod(namespace: str, name: str, manager: CoreManager = Depends(get_current_core_manager)):
    return manager.delete_pod(name, namespace)

@router.delete("/namespaces/{namespace}/services/{name}")
async def delete_service(namespace: str, name: str, manager: CoreManager = Depends(get_current_core_manager)):
    return manager.delete_service(name, namespace)

@router.delete("/namespaces/{namespace}/configmaps/{name}")
async def delete_configmap(namespace: str, name: str, manager: CoreManager = Depends(get_current_core_manager)):
    return manager.delete_configmap(name, namespace)

@router.delete("/namespaces/{namespace}/secrets/{name}")
async def delete_secret(namespace: str, name: str, manager: CoreManager = Depends(get_current_core_manager)):
    return manager.delete_secret(name, namespace)

@router.get("/cluster/nodes", response_model=List[Dict])
async def get_cluster_nodes(
    manager: CoreManager = Depends(get_current_core_manager)
):
    """Restituisce i dettagli tecnici dei nodi del cluster."""
    return manager.list_nodes()

# --- RBAC ENDPOINTS ---

@router.get("/namespaces/{namespace}/serviceaccounts")
async def get_sas(namespace: str, manager: CoreManager = Depends(get_current_core_manager)):
    return manager.list_service_accounts(namespace)

@router.delete("/namespaces/{namespace}/serviceaccounts/{name}")
async def del_sa(namespace: str, name: str, manager: CoreManager = Depends(get_current_core_manager)):
    return manager.delete_service_account(namespace, name)

@router.get("/namespaces/{namespace}/roles")
async def get_roles(namespace: str, manager: CoreManager = Depends(get_current_core_manager)):
    return manager.list_roles(namespace)

@router.delete("/namespaces/{namespace}/roles/{name}")
async def del_role(namespace: str, name: str, manager: CoreManager = Depends(get_current_core_manager)):
    return manager.delete_role(namespace, name)

@router.get("/namespaces/{namespace}/rolebindings")
async def get_bindings(namespace: str, manager: CoreManager = Depends(get_current_core_manager)):
    return manager.list_role_bindings(namespace)

@router.delete("/namespaces/{namespace}/rolebindings/{name}")
async def del_binding(namespace: str, name: str, manager: CoreManager = Depends(get_current_core_manager)):
    return manager.delete_role_binding(namespace, name)