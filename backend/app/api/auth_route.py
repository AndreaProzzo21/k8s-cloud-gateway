from fastapi import APIRouter, HTTPException, Body, status
from app.api.auth_handler import create_access_token

auth_router = APIRouter()

@auth_router.post("/login")
async def login(
    cluster_id: str = Body(..., example="TESI"),
    profile: str = Body(..., example="messaging-mgr"),
    password: str = Body(...)
):
    """
    Riceve l'ID del cluster e il profilo richiesto.
    Se la password è corretta, restituisce un JWT che impacchetta 
    le credenziali K8s di quel profilo specifico.
    """
    # Chiamiamo la funzione aggiornata che accetta 'profile'
    token = create_access_token(cluster_id, profile, password)
    
    return {
        "access_token": token, 
        "token_type": "bearer",
        "expires_in": "8h"
    }