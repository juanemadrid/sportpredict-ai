"""Endpoints REST de la Fase 4: Fuentes de Cuotas y Licencias, Captura de Cuotas Reales,
Comparación Matemática contra el Mercado, Registro Prospectivo Inmutable y Evaluación por Mercado.
"""

from datetime import datetime
from typing import Dict, List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.security import RequestContext, get_request_context, require_admin_role
from app.db.models import Match
from app.db.session import get_db
from app.services.scheduler import daily_automation
from app.services.phase4_market_service import phase4_market_service

router = APIRouter(prefix="/api/v1/phase4", tags=["Phase 4: Market Odds, CLV & Prospective Ledger"])


class CaptureOddsPayload(BaseModel):
    match_id: int
    market_code: str = Field(..., description="1X2, OVER_1_5, OVER_2_5, UNDER_2_5, OVER_3_5 o BTTS")
    bookmaker_name: str = Field(..., description="Nombre del operador o proveedor")
    provider_source: str = Field(default="AUTHORIZED_PROSPECTIVE_CAPTURE")
    license_type: str = Field(default="Datos Propios Capturados Prospectivamente / Licencia Comercial Verificada")
    commercial_saas_allowed: bool = Field(default=True)
    line_stage: str = Field(default="CURRENT", description="OPENING, CURRENT o CLOSING")
    odds_by_selection: Dict[str, float]
    captured_at_utc: Optional[datetime] = None
    is_demo: bool = False


class RegisterProspectivePayload(BaseModel):
    markets: Optional[List[str]] = None


@router.get("/odds-sources")
def get_odds_sources_and_licenses():
    """Devuelve la auditoría de fuentes de cuotas, licencias, mercados cubiertos y costos potenciales."""
    return phase4_market_service.get_odds_sources_and_licensing_catalog()


@router.post("/odds/capture")
def capture_market_odds_endpoint(
    payload: CaptureOddsPayload,
    db: Session = Depends(get_db),
    ctx: RequestContext = Depends(get_request_context),
):
    """Captura cuotas reales (inicial, actual o cierre) verificando licencia compatible y hora anterior al inicio."""
    require_admin_role(ctx)
    try:
        return phase4_market_service.capture_market_odds(
            db=db,
            match_id=payload.match_id,
            market_code=payload.market_code,
            bookmaker_name=payload.bookmaker_name,
            provider_source=payload.provider_source,
            license_type=payload.license_type,
            commercial_saas_allowed=payload.commercial_saas_allowed,
            odds_by_selection=payload.odds_by_selection,
            line_stage=payload.line_stage,
            captured_at_utc=payload.captured_at_utc,
            is_demo=payload.is_demo,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/daily-matches")
def get_daily_and_upcoming_matches_valuation(
    include_demo: bool = Query(default=True, description="Incluir partidos DEMO claramente etiquetados"),
    limit: int = Query(default=10, ge=1, le=50),
    db: Session = Depends(get_db),
):
    """Devuelve los partidos programados (SCHEDULED) con probabilidades v3.1.0, cuotas disponibles,
    diferencias frente al mercado e identificación explícita de mercados sin ventaja estadística (Sección 6).
    """
    q = db.query(Match).filter(Match.status == "SCHEDULED")
    if not include_demo:
        q = q.filter(Match.is_demo == False)

    matches = q.order_by(Match.kickoff_utc.asc()).limit(limit).all()
    items = []
    for m in matches:
        val = phase4_market_service.compute_match_phase4_valuation(db, match_id=m.id)
        items.append(val)

    return {
        "count": len(items),
        "include_demo": include_demo,
        "items": items,
    }


@router.get("/matches/{match_id}/market-comparison")
def get_match_phase4_market_comparison(
    match_id: int,
    db: Session = Depends(get_db),
):
    """Comparación matemática completa (1X2, OVER_1_5, OVER_2_5, UNDER_2_5, OVER_3_5, BTTS) de un partido."""
    try:
        return phase4_market_service.compute_match_phase4_valuation(db, match_id=match_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/prospective/register/{match_id}")
def register_prospective_predictions(
    match_id: int,
    payload: Optional[RegisterProspectivePayload] = None,
    db: Session = Depends(get_db),
    ctx: RequestContext = Depends(get_request_context),
):
    """Registra de forma inmutable las predicciones pre-partido antes del kickoff con sello SHA-256."""
    require_admin_role(ctx)
    try:
        mkts = payload.markets if payload else None
        return phase4_market_service.register_prospective_predictions_for_match(
            db=db,
            match_id=match_id,
            markets_to_register=mkts,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/prospective/settle")
def settle_finished_prospective_predictions_endpoint(
    match_id: Optional[int] = Query(default=None),
    db: Session = Depends(get_db),
    ctx: RequestContext = Depends(get_request_context),
):
    """Liquida predicciones prospectivas pendientes únicamente después de que el partido ha finalizado."""
    require_admin_role(ctx)
    return phase4_market_service.settle_finished_prospective_predictions(db=db, match_id=match_id)


@router.get("/prospective/ledger")
def get_prospective_immutable_ledger(
    include_demo: bool = Query(default=False, description="Por defecto solo muestra predicciones reales (is_demo=False)"),
    market_code: Optional[str] = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
):
    """Devuelve el registro prospectivo inmutable verificando el hash SHA-256 de cada fila."""
    return phase4_market_service.list_prospective_ledger(
        db=db,
        include_demo=include_demo,
        market_code=market_code,
        limit=limit,
    )


@router.get("/evaluation")
def get_phase4_market_evaluation(db: Session = Depends(get_db)):
    """Devuelve la evaluación verificable por mercado separando estrictamente los resultados históricos
    (868 partidos reales CC0) de los prospectivos reales y del sandbox demostrativo.
    """
    return phase4_market_service.evaluate_all_markets_historical_and_prospective(db=db)


@router.post("/automation/run-daily-cycle")
def run_phase5_daily_cycle(
    date_iso: Optional[str] = Query(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
    db: Session = Depends(get_db),
    ctx: RequestContext = Depends(get_request_context),
):
    """Ejecuta el ciclo diario de automatización (Fase 5): sincronización gratuita, sellado pre-kickoff y liquidación."""
    require_admin_role(ctx)
    return daily_automation.run_daily_cycle(db=db, date_iso=date_iso)

