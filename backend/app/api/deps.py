from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from app.api.auth_handler import decode_access_token # <--- Deve corrispondere!
from app.infrastructure.k8s_factory import K8sClientFactory
from app.core.core_manager import CoreManager

security = HTTPBearer()

async def get_current_core_manager(res: HTTPAuthorizationCredentials = Depends(security)):
    # Estraiamo la stringa del token dal pacchetto Authorization: Bearer <token>
    token = res.credentials
    
    # Decodifichiamo per ottenere i dati del cluster
    payload = decode_access_token(token)
    
    # Creiamo i client K8s dinamici
    k8s_apis = K8sClientFactory.get_apis(
        cluster_host=payload.get("cluster_host"),
        k8s_token=payload.get("k8s_token")
    )
    
    # Restituiamo il manager pronto all'uso
    return CoreManager(k8s_apis)