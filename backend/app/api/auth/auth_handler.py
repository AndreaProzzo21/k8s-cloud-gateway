import jwt
import datetime
import os
import secrets
from fastapi import HTTPException, status
from app.core.registry import ClusterRegistry
from app.core.config import settings

def create_access_token(cluster_id: str, profile: str, password: str) -> str:
    """
    Verifica le credenziali e restituisce un JWT che identifica la sessione.

    Il JWT NON contiene il k8s_token — contiene solo cluster_id e profile,
    che vengono usati server-side per recuperare il token K8s dal DB ad ogni
    request. Questo limita l'impatto di una compromissione del JWT: l'attaccante
    ottiene solo un identificatore, non le credenziali K8s reali.
    """
    cluster_data = ClusterRegistry.get_cluster_data(cluster_id, profile)

    if not cluster_data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Profile '{profile}' not found in cluster '{cluster_id}'"
        )

    # Confronto costante nel tempo per prevenire timing attacks sulla password.
    if not secrets.compare_digest(password, cluster_data["gateway_password"]):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials"
        )

    payload = {
        "cluster_id": cluster_id,
        "cluster_host": cluster_data["host"],  # host è pubblico, ok nel JWT
        "profile": profile,
        # jti = JWT ID: identificatore univoco per questa sessione.
        # Utile in futuro per una blocklist di revoca.
        "jti": secrets.token_hex(16),
        "iat": datetime.datetime.utcnow(),
        "exp": datetime.datetime.utcnow() + datetime.timedelta(hours=settings.JWT_EXPIRE_HOURS),
    }

    return jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_SECRET_ALGORITHM)


def decode_access_token(token: str) -> dict:
    """Valida il JWT e restituisce il payload."""
    try:
        return jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_SECRET_ALGORITHM])
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token scaduto")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Token non valido")