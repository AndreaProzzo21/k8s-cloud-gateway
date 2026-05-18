import os
from fastapi import HTTPException, Security, status
from fastapi.security import APIKeyHeader

ADMIN_API_KEY = os.getenv("ADMIN_MASTER_KEY", "")

if not ADMIN_API_KEY:
    raise RuntimeError(
        "ADMIN_API_KEY non configurato. "
        "Generare: python -c \"import secrets; print(secrets.token_hex(32))\""
    )

_header_scheme = APIKeyHeader(name="X-Admin-Key", auto_error=False)

async def require_admin_key(key: str = Security(_header_scheme)) -> str:
    """
    Valida la chiave admin nell'header X-Admin-Key.
    Usata come dependency su tutti gli endpoint /admin/*.
    """
    if not key or key != ADMIN_API_KEY:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin key mancante o non valida."
        )
    return key