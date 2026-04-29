import jwt
import datetime
import os
from fastapi import HTTPException, status
from app.core.registry import ClusterRegistry

JWT_SECRET = os.getenv("JWT_SECRET_KEY", "change-me-in-production")
ALGORITHM = "HS256"

def create_access_token(cluster_id: str, profile: str, password: str):
    cluster_data = ClusterRegistry.get_cluster_data(cluster_id, profile)
    
    if not cluster_data:
        raise HTTPException(
            status_code=404, 
            detail=f"Profilo '{profile}' non trovato per il cluster '{cluster_id}'"
        )
    
    if password != cluster_data["gateway_password"]:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, 
            detail="Password non valida"
        )
    
    payload = {
        "cluster_host": cluster_data["host"],
        "k8s_token": cluster_data["token"],
        "profile": profile,
        "cluster_id": cluster_id,
        "exp": datetime.datetime.utcnow() + datetime.timedelta(hours=8)
    }
    
    return jwt.encode(payload, JWT_SECRET, algorithm=ALGORITHM)

def decode_access_token(token: str):
    """Valida il JWT e restituisce il contenuto."""
    try:
        return jwt.decode(token, JWT_SECRET, algorithms=[ALGORITHM])
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token scaduto")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Token non valido")