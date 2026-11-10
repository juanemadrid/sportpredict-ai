from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.security import RequestContext, enforce_daily_analysis_quota, get_request_context
from app.db.models import Competition, Match, MLModel, Prediction, Team
from app.db.session import get_db
from app.services.prediction_service import prediction_service

router = APIRouter(prefix="/api/v1", tags=["Matches, Analysis & Predictions"])


@router.get("/matches")
def list_matches(
    status: Optional[str] = Query(default=None, description="SCHEDULED o FINISHED"),
    limit: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    """Lista encuentros (de hoy, próximos o históricos) con sus probabilidades y valor esperado (EV)."""
    q = db.query(Match)
    if status:
        q = q.filter(Match.status == status.upper())

    if status and status.upper() == "SCHEDULED":
        matches = q.order_by(Match.kickoff_utc.asc()).limit(limit).all()
    else:
        matches = q.order_by(Match.kickoff_utc.desc()).limit(limit).all()

    results = []
    for m in matches:
        analysis = prediction_service.analyze_match(db, m.id, persist_prediction=False)
        mkt_1x2 = analysis["markets"]["1X2"]["selections"]
        mkt_ou25 = analysis["markets"]["OVER_UNDER_2_5"]["selections"]

        # Detectar oportunidad de mejor Valor Esperado (EV) en el encuentro
        best_ev_sel = None
        best_ev_val = None
        for mkt_key, mkt_obj in analysis["markets"].items():
            for sel_k, sel_v in mkt_obj["selections"].items():
                ev_v = sel_v.get("expected_value")
                if ev_v is not None and (best_ev_val is None or ev_v > best_ev_val):
                    best_ev_val = ev_v
                    best_ev_sel = f"{mkt_key}:{sel_k}"

        results.append(
            {
                "match": analysis["match"],
                "model_version": analysis["model_version"],
                "expected_goals": {
                    "home": analysis["poisson_goal_model"]["expected_goals_home"],
                    "away": analysis["poisson_goal_model"]["expected_goals_away"],
                },
                "market_1x2": mkt_1x2,
                "market_ou_2_5": mkt_ou25,
                "best_value_opportunity": {
                    "selection": best_ev_sel,
                    "expected_value": best_ev_val,
                },
            }
        )
    return {"count": len(results), "items": results}


@router.get("/matches/{match_id}/analysis")
def get_match_detailed_analysis(
    match_id: int,
    db: Session = Depends(get_db),
    ctx: RequestContext = Depends(get_request_context),
):
    """Devuelve el análisis profundo de un partido (Sección 11).
    Consume una unidad del límite diario del plan SaaS del usuario (429 al excederlo)."""
    if not db.query(Match.id).filter(Match.id == match_id).first():
        raise HTTPException(status_code=404, detail=f"Partido con ID {match_id} no encontrado.")
    quota = enforce_daily_analysis_quota(ctx)
    try:
        data = prediction_service.analyze_match(db, match_id=match_id, persist_prediction=True)
        # Filtrar mercados según el nivel permitido por el plan SaaS del usuario
        max_tier = ctx.capabilities.allowed_market_tiers
        filtered_markets = {
            k: v for k, v in data["markets"].items() if v.get("tier_level", 1) <= max_tier
        }
        data["markets"] = filtered_markets
        data["user_plan_applied"] = ctx.plan_code
        data["usage_today"] = quota
        return data
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/teams")
def list_teams_statistics(db: Session = Depends(get_db)):
    """Estadísticas acumuladas y calificación dinámica Elo de los equipos registrados (Módulo 7)."""
    teams = db.query(Team).order_by(Team.current_elo.desc()).all()
    matches = db.query(Match).filter(Match.status == "FINISHED").all()

    items = []
    for t in teams:
        t_matches = [m for m in matches if m.home_team_id == t.id or m.away_team_id == t.id]
        gf = sum((m.home_goals if m.home_team_id == t.id else m.away_goals) or 0 for m in t_matches)
        ga = sum((m.away_goals if m.home_team_id == t.id else m.home_goals) or 0 for m in t_matches)
        wins = sum(
            1
            for m in t_matches
            if ((m.home_team_id == t.id and (m.home_goals or 0) > (m.away_goals or 0)) or (m.away_team_id == t.id and (m.away_goals or 0) > (m.home_goals or 0)))
        )
        draws = sum(1 for m in t_matches if m.home_goals == m.away_goals)
        losses = len(t_matches) - wins - draws
        n_m = max(1, len(t_matches))

        items.append(
            {
                "id": t.id,
                "canonical_name": t.canonical_name,
                "short_code": t.short_code,
                "country": t.country,
                "current_elo": round(t.current_elo, 2),
                "matches_played": len(t_matches),
                "wins": wins,
                "draws": draws,
                "losses": losses,
                "goals_for_avg": round(gf / n_m, 2),
                "goals_against_avg": round(ga / n_m, 2),
                "source_name": t.source_name,
                "is_demo": t.is_demo,
            }
        )
    return {"count": len(items), "items": items}


@router.get("/predictions/ledger")
def get_immutable_predictions_ledger(
    limit: int = Query(default=60, ge=1, le=200),
    db: Session = Depends(get_db),
):
    """Registro inmutable de predicciones guardadas antes del inicio de cada encuentro (Sección 10)."""
    preds = db.query(Prediction).order_by(Prediction.predicted_before_kickoff_at.desc()).limit(limit).all()
    matches_map = {m.id: m for m in db.query(Match).all()}
    teams_map = {t.id: t.canonical_name for t in db.query(Team).all()}
    comps_map = {c.id: c.name for c in db.query(Competition).all()}
    models_map = {md.id: f"{md.model_code} ({md.version})" for md in db.query(MLModel).all()}

    settled = [p for p in preds if p.settlement_status in ("WON", "LOST")]
    brier_vals = [p.brier_contribution for p in settled if p.brier_contribution is not None]

    # Para desempeño real de pronóstico principal por partido (selección de mayor probabilidad):
    by_match = {}
    for p in settled:
        by_match.setdefault(p.match_id, []).append(p)
    top_pick_hits = 0
    for m_id, p_list in by_match.items():
        top_p = max(p_list, key=lambda x: x.prob_estimated)
        if top_p.settlement_status == "WON":
            top_pick_hits += 1

    rows = []
    for p in preds:
        m = matches_map.get(p.match_id)
        if not m:
            continue
        rows.append(
            {
                "id": p.id,
                "match_id": m.id,
                "fixture": f"{teams_map.get(m.home_team_id, 'Local')} vs {teams_map.get(m.away_team_id, 'Visitante')}",
                "competition": comps_map.get(m.competition_id, "Liga"),
                "kickoff_utc": m.kickoff_utc.isoformat(),
                "model": models_map.get(p.model_id, "ENSEMBLE"),
                "market_code": p.market_code,
                "selection_code": p.selection_code,
                "prob_estimated": p.prob_estimated,
                "fair_decimal_odds": p.fair_decimal_odds,
                "available_decimal_odds": p.available_decimal_odds,
                "bookmaker_margin": p.bookmaker_margin,
                "expected_value": p.expected_value,
                "uncertainty_label": p.uncertainty_label,
                "predicted_before_kickoff_at": p.predicted_before_kickoff_at.isoformat(),
                "settlement_status": p.settlement_status,
                "actual_result_code": p.actual_result_code,
                "real_score": f"{m.home_goals}-{m.away_goals}" if m.home_goals is not None else None,
                "brier_contribution": p.brier_contribution,
                "is_demo": p.is_demo,
            }
        )

    return {
        "summary": {
            "total_records_returned": len(rows),
            "settled_matches_evaluated": len(by_match),
            "top_pick_hit_rate": round(top_pick_hits / len(by_match), 4) if by_match else None,
            "mean_brier_contribution": round(sum(brier_vals) / len(brier_vals), 5) if brier_vals else None,
            "immutability_policy": "Los pronósticos registrados antes del kickoff_utc nunca se alteran tras conocerse el marcador real.",
        },
        "items": rows,
    }
