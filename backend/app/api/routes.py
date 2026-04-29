from fastapi import APIRouter, Depends, File, UploadFile, HTTPException, status, Query
from fastapi.responses import PlainTextResponse
from typing import List, Dict
from app.core.core_manager import CoreManager
from app.api.deps import get_current_core_manager

router = APIRouter()

@router.post("/namespaces/{name}")
async def create_new_namespace(
    name: str,
    manager: CoreManager = Depends(get_current_core_manager)
):
    """Crea un nuovo namespace (richiede permessi di Cluster Admin)."""
    manager.create_namespace(name)
    return {"message": f"Namespace '{name}' creato correttamente"}

# --- POD ROUTES ---

@router.get("/namespaces/{namespace}/pods", response_model=List[Dict])
async def list_pods(
    namespace: str, 
    manager: CoreManager = Depends(get_current_core_manager)
):
    return manager.get_pods_in_namespace(namespace)

@router.get("/namespaces/{namespace}/pods/{name}", response_model=Dict)
async def get_pod(
    namespace: str, 
    name: str, 
    manager: CoreManager = Depends(get_current_core_manager)
):
    return manager.get_pod_by_name(name, namespace)

@router.get("/namespaces/{namespace}/pods/{name}/logs", response_class=PlainTextResponse)
async def get_pod_logs(
    namespace: str,
    name: str,
    tail: int = Query(None, description="Numero di ultime righe da recuperare"),
    manager: CoreManager = Depends(get_current_core_manager)
):
    """Restituisce i log del pod come testo piano."""
    return manager.get_pod_logs(name, namespace, tail_lines=tail)

# --- DEPLOYMENT ROUTES ---

@router.get("/namespaces/{namespace}/deployments", response_model=List[Dict])
async def list_deployments(
    namespace: str, 
    manager: CoreManager = Depends(get_current_core_manager)
):
    return manager.list_deployments_in_namespace(namespace)

@router.get("/namespaces/{namespace}/deployments/{name}", response_model=Dict)
async def get_deployment(
    namespace: str, 
    name: str, 
    manager: CoreManager = Depends(get_current_core_manager)
):
    return manager.get_deployment_by_name(name, namespace)

# --- DEPLOYMENT OPERATIONS ---

@router.delete("/namespaces/{namespace}/deployments/{name}")
async def delete_deployment(
    namespace: str,
    name: str,
    manager: CoreManager = Depends(get_current_core_manager)
):
    """Elimina definitivamente un deployment."""
    manager.delete_deployment(name, namespace)
    return {"message": f"Deployment {name} eliminato con successo"}

@router.patch("/namespaces/{namespace}/deployments/{name}/scale")
async def scale_deployment(
    namespace: str,
    name: str,
    replicas: int = Query(..., ge=0, le=10), # Limite di sicurezza 0-10
    manager: CoreManager = Depends(get_current_core_manager)
):
    """Cambia il numero di repliche di un deployment."""
    manager.scale_deployment(name, namespace, replicas)
    return {"message": f"Deployment {name} scalato a {replicas} repliche"}

@router.post("/namespaces/{namespace}/deployments/{name}/restart")
async def restart_deployment(
    namespace: str,
    name: str,
    manager: CoreManager = Depends(get_current_core_manager)
):
    """Esegue il rollout restart del deployment."""
    manager.restart_deployment(name, namespace)
    return {"message": f"Rollout restart avviato per {name}"}

# --- SERVICE ROUTES ---

@router.get("/namespaces/{namespace}/services", response_model=List[Dict])
async def list_services(
    namespace: str, 
    manager: CoreManager = Depends(get_current_core_manager)
):
    return manager.list_services_in_namespace(namespace)

@router.get("/namespaces/{namespace}/services/{name}", response_model=Dict)
async def get_service(
    namespace: str, 
    name: str, 
    manager: CoreManager = Depends(get_current_core_manager)
):
    return manager.get_service_by_name(name, namespace)

# --- WRITE OPERATIONS ---

@router.post("/namespaces/{namespace}/deployments/upload", status_code=status.HTTP_201_CREATED)
async def deploy_via_file(
    namespace: str,
    file: UploadFile = File(...),
    manager: CoreManager = Depends(get_current_core_manager)
):
    if not file.filename.endswith(('.yaml', '.yml')):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, 
            detail="Il file deve essere uno YAML"
        )

    content = await file.read()
    yaml_str = content.decode("utf-8")
    
    return manager.create_deployment(namespace, yaml_str)