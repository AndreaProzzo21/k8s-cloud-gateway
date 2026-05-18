from fastapi import APIRouter, HTTPException, Body, status, Response
from app.api.auth.auth_handler import create_access_token
from app.core.config import settings

auth_router = APIRouter()

@auth_router.post("/login")
async def login(
    response: Response,
    cluster_id: str = Body(..., example="TESI"),
    profile: str = Body(..., example="messaging-mgr"),
    password: str = Body(...)
):
    """
    Verifica le credenziali e imposta un JWT come httpOnly cookie.
    Il token non viene mai esposto nel body della response.
    """
    token = create_access_token(cluster_id, profile, password)

    response.set_cookie(
        key="k8s_jwt",
        value=token,
        httponly=True,          # non accessibile da JS
        samesite="strict",      # inviato solo su stessa origine
        secure=False,           # → True in produzione con HTTPS
        max_age=settings.JWT_EXPIRE_HOURS * 3600,
        path="/",
    )
    # Restituiamo solo i metadati, mai il token
    return {"token_type": "bearer", "expires_in": settings.JWT_EXPIRE_HOURS}


@auth_router.post("/logout")
async def logout(response: Response):
    """
    Invalida la sessione cancellando il cookie lato client.
    """
    response.delete_cookie(key="k8s_jwt", path="/", samesite="strict")
    return {"status": "logged out"}