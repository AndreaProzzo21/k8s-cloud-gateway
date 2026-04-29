# app/api/api_server.py
from fastapi.middleware.cors import CORSMiddleware
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from app.core.exceptions import K8sBaseException
from app.api.routes import router as k8s_router
from app.api.auth_route import auth_router  # Importiamo le nuove rotte di login

def create_app() -> FastAPI:
    app = FastAPI(
        title="K8S Digital Twin Gateway",
        description="API Proxy Stateless per la gestione multi-cluster via JWT",
        version="2.0.0"
    )

    # Configurazione CORS per permettere al Frontend di comunicare con il Gateway
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Global Exception Handler per catturare i nostri errori personalizzati
    @app.exception_handler(K8sBaseException)
    async def k8s_exception_handler(request: Request, exc: K8sBaseException):
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "error": "K8S_GATEWAY_ERROR", 
                "message": exc.message,
                "status_code": exc.status_code
            },
        )

    # --- REGISTRAZIONE ROTTE ---
    
    # Rotte per l'autenticazione (Pubbliche: /auth/login)
    app.include_router(auth_router, prefix="/auth", tags=["Authentication"])
    
    # Rotte operative Kubernetes (Protette via JWT: /api/v1/...)
    app.include_router(k8s_router, prefix="/api/v1", tags=["Kubernetes Operations"])

    return app