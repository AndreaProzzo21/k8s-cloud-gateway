from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from app.api.auth.auth_handler import decode_access_token
from app.infrastructure.k8s_factory import K8sClientFactory
from app.core.core_manager import CoreManager

security = HTTPBearer()

async def get_current_core_manager(res: HTTPAuthorizationCredentials = Depends(security)):
    # 1. Estraiamo la stringa del token
    token = res.credentials
    
    # 2. Decodifichiamo il JWT per ottenere i dati del payload
    payload = decode_access_token(token)
    
    # 3. Recuperiamo l'ID del cluster (es. "LAB", "PROD") salvato nel JWT durante il login
    cluster_id = payload.get("cluster_id")
    cluster_host = payload.get("cluster_host")
    k8s_token = payload.get("k8s_token")

    # 4. Inizializziamo i client passando anche il cluster_id
    k8s_apis = K8sClientFactory.get_apis(
        cluster_host=cluster_host,
        k8s_token=k8s_token,
        cluster_id=cluster_id  
    )
    
    # 5. Restituiamo il manager configurato
    return CoreManager(k8s_apis)