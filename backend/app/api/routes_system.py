from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import PLAN_CATALOG, RequestContext, get_request_context
from app.db.models import Competition, DataSource, MarketCatalog, Match, MLModel, Prediction, Team
from app.db.session import get_db

router = APIRouter(prefix="/api/v1/system", tags=["System & Governance"])
public_router = APIRouter(prefix="/api/v1/public", tags=["Public & Compliance"])


@public_router.get("/compliance")
def get_public_compliance():
    """Información pública de cumplimiento normativo (+18 / Coljuegos) y catálogo de planes."""
    return {
        "project": settings.PROJECT_NAME,
        "version": settings.VERSION,
        "plans": [vars(p) for p in PLAN_CATALOG.values()],
        "compliance_notice": {
            "age_restriction": "+18 Exclusivamente para mayores de edad",
            "service_nature": "Servicio puramente informativo y estadístico. No capta apuestas ni gestiona saldos.",
            "jurisdiction_note": "Cumplimiento informativo Colombia (Coljuegos: prohibida afiliación sin autorización legal).",
        },
    }


@router.get("/diagnostic")
def get_system_diagnostic(
    db: Session = Depends(get_db),
    ctx: RequestContext = Depends(get_request_context),
):
    """Diagnóstico integral del sistema, fuentes de datos, mercados progresivos y planes SaaS."""
    sources = db.query(DataSource).all()
    markets = db.query(MarketCatalog).order_by(MarketCatalog.tier_level.asc()).all()
    models_count = db.query(MLModel).count()
    matches_total = db.query(Match).count()
    demo_matches = db.query(Match).filter(Match.is_demo.is_(True)).count()
    real_matches = matches_total - demo_matches
    predictions_total = db.query(Prediction).count()

    return {
        "project": settings.PROJECT_NAME,
        "version": settings.VERSION,
        "database_mode": "SUPABASE_POSTGRESQL" if settings.is_supabase_configured else "SQLITE_LOCAL_ISOLATED",
        "api_football_configured": settings.is_api_football_configured,
        "active_user_context": {
            "role": ctx.role,
            "plan_code": ctx.plan_code,
            "capabilities": vars(ctx.capabilities),
        },
        "counts": {
            "competitions": db.query(Competition).count(),
            "teams": db.query(Team).count(),
            "matches_total": matches_total,
            "matches_demo": demo_matches,
            "matches_real_authorized": real_matches,
            "registered_models": models_count,
            "immutable_predictions_logged": predictions_total,
        },
        "data_providers": [
            {
                "provider_code": s.provider_code,
                "display_name": s.display_name,
                "license_type": s.license_type,
                "daily_quota_limit": s.daily_quota_limit,
                "requests_used_today": s.requests_used_today,
                "status": s.status,
                "last_sync_at": s.last_sync_at.isoformat() if s.last_sync_at else None,
                "is_demo": s.is_demo,
            }
            for s in sources
        ],
        "market_governance": [
            {
                "market_code": m.market_code,
                "display_name": m.display_name,
                "tier_level": m.tier_level,
                "min_samples_required": m.min_samples_required,
                "is_enabled": m.is_enabled,
                "status_reason": m.status_reason,
            }
            for m in markets
        ],
        "saas_plans": [vars(p) for p in PLAN_CATALOG.values()],
        "compliance_notice": {
            "age_restriction": "+18 Exclusivamente para mayores de edad",
            "service_nature": "Servicio puramente informativo y estadístico. No capta apuestas ni gestiona saldos.",
            "jurisdiction_note": "Cumplimiento informativo Colombia (Coljuegos: prohibida afiliación sin autorización legal).",
        },
    }
