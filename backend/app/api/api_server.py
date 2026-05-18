import time
import logging
import asyncio
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

# Import della configurazione centralizzata
from app.core.config import settings

from app.api.rate_limiter import RateLimitMiddleware
from app.core.exceptions import K8sBaseException
from app.api.routes.k8s_routes import router as k8s_router
from app.api.routes.helm_routes import router as helm_router
from app.api.auth.auth_route import auth_router
from app.api.routes.admin_routes import admin_router
from app.api.routes.audit_routes import audit_router
from app.infrastructure.database import init_db
from app.core.fleet_manager import FleetManager

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("k8s_gateway")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifecycle manager per startup e shutdown del gateway."""
    logger.info("🚀 Avvio K8S Cloud Gateway...")
    init_db()
    # L'osservatore viene avviato come task in background
    asyncio.create_task(FleetManager.start_observer(interval_seconds=30))
    yield
    logger.info("🛑 Spegnimento Gateway...")


def create_app() -> FastAPI:
    app = FastAPI(
        title="K8S Cloud Gateway",
        description="Integrated Framework for Multi-Cluster Kubernetes Governance",
        version="1.0.0",
        lifespan=lifespan,
        # Swagger disabilitato: documentazione su GitHub Pages
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )

    # ── MIDDLEWARE CHAIN ────────────────────────────────────────────────
    # L'ordine conta: ogni middleware wrappa quello successivo.
    # RateLimit → CORS → route handler.

    # 1. Rate limiting IP-based
    app.add_middleware(RateLimitMiddleware, calls_per_minute=40)

    # 2. CORS
    # Con reverse proxy nginx sulla stessa origine il CORS non viene mai
    # attivato dal browser per le chiamate normali dell'app. È configurato
    # correttamente comunque perché:
    #   a) allow_origins="*" + allow_credentials=True è rifiutato dai browser
    #   b) garantisce comportamento corretto se il backend venisse esposto
    #      direttamente in futuro (es. sviluppo, testing con client esterni)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.get_allowed_origins(), # Ora usa settings
        allow_credentials=True,     # necessario per i cookie httpOnly
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # 3. Performance logging — decommentare per debug/profiling
    # @app.middleware("http")
    # async def add_process_time_header(request: Request, call_next):
    #     start_time = time.perf_counter()
    #     response = await call_next(request)
    #     process_time = time.perf_counter() - start_time
    #     response.headers["X-Process-Time"] = f"{process_time:.4f}s"
    #     logger.info(
    #         f"REQ: {request.method} {request.url.path} | "
    #         f"RES: {response.status_code} | TIME: {process_time:.4f}s"
    #     )
    #     return response

    # ── EXCEPTION HANDLERS ─────────────────────────────────────────────

    @app.exception_handler(K8sBaseException)
    async def k8s_exception_handler(request: Request, exc: K8sBaseException):
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "error": "K8S_GATEWAY_ERROR",
                "message": exc.message,
                "status_code": exc.status_code,
            },
        )

    # ── SYSTEM ENDPOINTS ───────────────────────────────────────────────

    @app.get("/health", tags=["System"])
    async def health_check():
        """
        Liveness/Readiness probe per Kubernetes.
        Non richiede autenticazione. Non passa per nginx.
        """
        return {
            "status": "healthy",
            "timestamp": time.time(),
            "version": "1.0.0",
        }

    # ── ROUTING ────────────────────────────────────────────────────────

    app.include_router(auth_router,   prefix="/api/v1/auth",          tags=["Authentication"])
    app.include_router(k8s_router,    prefix="/api/v1",               tags=["Kubernetes Operations"])
    app.include_router(helm_router,   prefix="/api/v1/helm",          tags=["Helm Management"])
    app.include_router(admin_router,  prefix="/api/v1/admin",         tags=["Admin Operations"])
    app.include_router(audit_router,  prefix="/api/v1/admin/audit",   tags=["Audit Operations"])

    return app


# Inizializzazione dell'app basata sulla factory function
app = create_app()