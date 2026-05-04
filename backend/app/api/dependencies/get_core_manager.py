from fastapi import Depends, HTTPException
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from app.api.auth.auth_handler import decode_access_token
from app.infrastructure.k8s_factory import K8sClientFactory
from app.core.core_manager import CoreManager
from app.infrastructure.database import SessionLocal, ClusterModel

security = HTTPBearer()

async def get_current_core_manager(res: HTTPAuthorizationCredentials = Depends(security)):
    # 1. Estraiamo la stringa del token
    token = res.credentials
    
    # 2. Decodifichiamo il JWT
    payload = decode_access_token(token)
    
    cluster_id = payload.get("cluster_id")
    cluster_host = payload.get("cluster_host")
    k8s_token = payload.get("k8s_token")

    # 3. Recuperiamo il certificato CA dal Database
    # Usiamo il cluster_id presente nel payload per trovare il cluster corretto
    ca_cert = None
    db = SessionLocal()
    try:
        cluster = db.query(ClusterModel).filter(ClusterModel.id == cluster_id).first()
        if cluster:
            ca_cert = cluster.ca_cert
    finally:
        db.close()

    # 4. Inizializziamo i client passando il ca_cert recuperato dal DB
    k8s_apis = K8sClientFactory.get_apis(
        cluster_host=cluster_host,
        k8s_token=k8s_token,
        ca_cert=ca_cert,
        cluster_id=cluster_id  
    )
    
    # 5. Restituiamo il manager configurato
    return CoreManager(k8s_apis)