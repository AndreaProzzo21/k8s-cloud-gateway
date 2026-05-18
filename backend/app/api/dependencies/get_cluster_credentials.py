from dataclasses import dataclass

from fastapi import Request, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from app.api.auth.auth_handler import decode_access_token
from app.infrastructure.database import ClusterModel, ProfileModel, SessionLocal


@dataclass(frozen=True)
class ClusterCredentials:
    cluster_id: str
    cluster_host: str
    profile: str
    k8s_token: str
    ca_cert: str


def _extract_token(request: Request) -> str:
    """
    Estrae il JWT dalla request con priorità:
      1. Cookie httpOnly  k8s_jwt  (browser normale)
      2. Header          Authorization: Bearer ...  (API calls dirette / testing)

    Raises HTTP 401 se nessuna delle due sorgenti contiene un token.
    """
    token = request.cookies.get("k8s_jwt")
    if token:
        return token

    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        return auth_header.removeprefix("Bearer ")

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Autenticazione richiesta: cookie di sessione o header Bearer mancante.",
        headers={"WWW-Authenticate": "Bearer"},
    )


async def get_cluster_credentials(request: Request) -> ClusterCredentials:
    """
    Dependency FastAPI condivisa: estrae il JWT, lo decodifica,
    recupera le credenziali cluster dal DB.
    """
    token = _extract_token(request)

    try:
        payload = decode_access_token(token)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Token not valid or expired: {exc}",
            headers={"WWW-Authenticate": "Bearer"},
        )

    cluster_id: str | None = payload.get("cluster_id")
    cluster_host: str | None = payload.get("cluster_host")
    profile: str | None = payload.get("profile")

    if not all([cluster_id, cluster_host, profile]):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incomplete JWT: Missing cluster_id, cluster_host or profile.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    db = SessionLocal()
    try:
        cluster = db.query(ClusterModel).filter(
            ClusterModel.id == cluster_id
        ).first()

        if cluster is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Cluster '{cluster_id}' not found in the registry.",
            )

        ca_cert: str | None = cluster.ca_cert

        profile_record = db.query(ProfileModel).filter(
            ProfileModel.cluster_id == cluster_id.upper(),
            ProfileModel.name == profile,
        ).first()

        if profile_record is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Record '{profile}' not found in cluster '{cluster_id}'.",
            )

        k8s_token: str | None = profile_record.k8s_token

    finally:
        db.close()

    if not ca_cert:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Missing CA Certificate for cluster '{cluster_id}'.",
        )

    if not k8s_token:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Missing k8s_token for profile '{profile}' of cluster '{cluster_id}'.",
        )

    return ClusterCredentials(
        cluster_id=cluster_id,
        cluster_host=cluster_host,
        profile=profile,
        k8s_token=k8s_token,
        ca_cert=ca_cert,
    )