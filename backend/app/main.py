from contextlib import asynccontextmanager
import logging

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.api.routes_ingestion import router as ingestion_router
from app.api.routes_matches import router as matches_router
from app.api.routes_models import router as models_router
from app.api.routes_phase4_market import router as phase4_market_router
from app.api.routes_system import public_router as system_public_router
from app.api.routes_system import router as system_router
from app.api.routes_users import router as users_router
from app.core.config import settings
from app.core.observability import configure_logging, install_observability
from app.core.security import current_user
import app.db.session as db_session
from app.db.init_db import init_database
from app.services.phase4_market_service import phase4_market_service


configure_logging()
logger = logging.getLogger("sportpredict.main")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    config_errors = settings.validate_for_production()
    if config_errors:
        for err in config_errors:
            logger.critical("Configuración inválida para producción: %s", err)
        raise RuntimeError("Configuración de producción inválida: " + " | ".join(config_errors))

    try:
        db = db_session.SessionLocal()
        try:
            init_database(db)
            phase4_market_service.ensure_phase4_tables_and_triggers(db)
        finally:
            db.close()
    except Exception as exc:
        logger.warning("Inicialización en lifespan completada previamente o advertencia menor: %s", exc)
    logger.info(
        "SPORTPREDICT AI %s iniciado (env=%s, db=%s, auth=%s)",
        settings.VERSION,
        settings.ENVIRONMENT,
        "postgresql" if settings.is_postgres else "sqlite",
        "supabase" if settings.is_auth_configured else ("dev-headers" if settings.dev_headers_enabled else "none"),
    )
    yield


docs_enabled = settings.ENABLE_API_DOCS and not settings.is_production

app = FastAPI(
    title=settings.PROJECT_NAME,
    version=settings.VERSION,
    description=(
        "Plataforma SaaS de análisis y predicción deportiva mediante modelos estadísticos "
        "(Poisson/Dixon-Coles, Elo Dinámico) y Machine Learning calibrado (Random Forest, XGBoost, Ensamble)."
    ),
    lifespan=lifespan,
    docs_url="/docs" if docs_enabled else None,
    redoc_url="/redoc" if docs_enabled else None,
    openapi_url="/openapi.json" if docs_enabled else None,
)

install_observability(app)
app.add_middleware(GZipMiddleware, minimum_size=1024)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
    max_age=86400,
)

# Rutas públicas (sin autenticación)
app.include_router(system_public_router)

# Rutas protegidas: todo /api/v1 exige usuario autenticado; las operaciones sensibles
# exigen además rol ADMIN dentro de cada endpoint.
protected = [Depends(current_user)]
app.include_router(system_router, dependencies=protected)
app.include_router(users_router, dependencies=protected)
app.include_router(matches_router, dependencies=protected)
app.include_router(models_router, dependencies=protected)
app.include_router(ingestion_router, dependencies=protected)
app.include_router(phase4_market_router, dependencies=protected)


@app.get("/")
@app.head("/")
def root_check():
    """Endpoint raíz para sondas de Render y orquestadores."""
    return {
        "status": "ok",
        "service": settings.PROJECT_NAME,
        "version": settings.VERSION,
    }


@app.get("/health")
@app.head("/health")
def health_check():
    """Liveness: el proceso responde."""
    return {
        "status": "ok",
        "service": settings.PROJECT_NAME,
        "version": settings.VERSION,
    }


@app.get("/ready")
def readiness_check():
    """Readiness: la base de datos responde."""
    try:
        with db_session.engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return {"status": "ready"}
    except Exception as exc:  # pragma: no cover - depende de infraestructura
        logger.error("Readiness falló: %s", exc)
        return JSONResponse(status_code=503, content={"status": "unavailable"})
