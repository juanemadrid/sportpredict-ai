from datetime import datetime, timedelta, timezone
import pytest

from app.api.routes_ingestion import CSVImportPayload, import_authorized_csv
from app.api.routes_matches import (
    get_immutable_predictions_ledger,
    get_match_detailed_analysis,
    list_matches,
)
from app.api.routes_models import get_models_scientific_comparison
from app.api.routes_system import get_system_diagnostic
from app.core.security import get_request_context
from app.db.init_db import init_database
from app.db.session import SessionLocal
from app.ml.features import HistoricalMatchRecord, PointInTimeFeatureBuilder
from app.ml.odds_math import calculate_fair_odds, compute_expected_value, remove_bookmaker_margin


def test_odds_math_and_ev_formula():
    """Verifica la fórmula EV = (probabilidad * cuota decimal) - 1 y remoción de margen."""
    fair = calculate_fair_odds(0.50)
    assert fair == 2.0

    ev = compute_expected_value(0.55, 2.00)
    assert ev == pytest.approx(0.10, abs=1e-4)

    fair_probs, margin = remove_bookmaker_margin({"HOME": 2.00, "DRAW": 3.50, "AWAY": 4.00})
    assert margin > 0.03
    assert sum(fair_probs.values()) == pytest.approx(1.0, abs=1e-4)


def test_zero_future_data_leakage_in_feature_builder():
    """Garantiza que ningún partido posterior a la fecha del encuentro objetivo se filtre en las variables."""
    t0 = datetime(2026, 1, 1, 18, 0, tzinfo=timezone.utc)
    past_match = HistoricalMatchRecord(
        match_id=1,
        competition_id=1,
        season="2025/2026",
        kickoff_utc=t0 - timedelta(days=7),
        home_team_id=10,
        away_team_id=20,
        home_goals=2,
        away_goals=0,
        status="FINISHED",
    )
    target_match = HistoricalMatchRecord(
        match_id=2,
        competition_id=1,
        season="2025/2026",
        kickoff_utc=t0,
        home_team_id=10,
        away_team_id=20,
        home_goals=None,
        away_goals=None,
        status="SCHEDULED",
    )
    future_match = HistoricalMatchRecord(
        match_id=3,
        competition_id=1,
        season="2025/2026",
        kickoff_utc=t0 + timedelta(days=7),
        home_team_id=10,
        away_team_id=20,
        home_goals=9,
        away_goals=9,
        status="FINISHED",
    )

    feat_without_future = PointInTimeFeatureBuilder.build_features_for_match(
        target_match=target_match,
        all_prior_matches=[past_match],
        home_elo=1520.0,
        away_elo=1480.0,
    )
    feat_with_future_passed = PointInTimeFeatureBuilder.build_features_for_match(
        target_match=target_match,
        all_prior_matches=[past_match, future_match],
        home_elo=1520.0,
        away_elo=1480.0,
    )

    assert feat_without_future["home_gf_last5"] == feat_with_future_passed["home_gf_last5"] == 2.0
    assert feat_without_future["home_matches_played"] == feat_with_future_passed["home_matches_played"] == 1


def test_end_to_end_api_and_ml_pipeline():
    """Prueba integral del backend: inicialización, entrenamiento de los 5 modelos (A-E),
    métricas científicas en partición temporal, análisis de partidos, importador CSV y registro pre-partido.
    """
    db = SessionLocal()
    try:
        init_database(db)
        ctx = get_request_context("ADMIN", "PRO")

        # 1. Diagnóstico del sistema
        diag = get_system_diagnostic(db=db, ctx=ctx)
        assert diag["counts"]["matches_total"] >= 150
        assert diag["counts"]["matches_demo"] >= 150
        assert isinstance(diag["api_football_configured"], bool)

        # 2. Comparación científica de los 5 modelos (Poisson, Elo, RF, XGBoost, Ensamble)
        mod_data = get_models_scientific_comparison(db=db)
        codes = {m["model_code"] for m in mod_data["models"]}
        assert {"POISSON", "ELO", "RANDOM_FOREST", "XGBOOST", "ENSEMBLE"}.issubset(codes)

        for m in mod_data["models"]:
            bt = m["backtest"]
            assert bt is not None
            assert 0.0 <= bt["brier_score"] <= 1.5
            assert bt["log_loss"] > 0.0

        # 3. Análisis detallado de un partido y suma exacta de probabilidades
        scheduled_res = list_matches(status="SCHEDULED", limit=5, db=db)
        scheduled_items = scheduled_res["items"]
        assert len(scheduled_items) >= 1

        first_match_id = scheduled_items[0]["match"]["id"]
        analysis = get_match_detailed_analysis(match_id=first_match_id, db=db, ctx=ctx)
        assert analysis["match"]["is_demo"] in (True, False)

        for model_name, probs in analysis["models_comparison_1x2"].items():
            assert sum(probs.values()) == pytest.approx(1.0, abs=1e-3), f"Fallo en suma 1X2 de {model_name}"

        # 4. Registro inmutable de predicciones
        ledger = get_immutable_predictions_ledger(limit=30, db=db)
        assert ledger["summary"]["total_records_returned"] >= 6

        # 5. Importador CSV autorizado vs rechazo de fuente no autorizada
        valid_csv_text = (
            "external_ref,competition_code,competition_name,country,season,matchday,kickoff_utc,home_team,away_team,status,home_goals,away_goals,home_xg,away_xg,odds_home,odds_draw,odds_away\n"
            "AUTH-REAL-0001,ESP_LALIGA,LaLiga EA Sports,España,2026/2027,17,2026-11-15T20:00:00Z,Real Madrid,Real Sociedad,SCHEDULED,,,,,1.55,4.10,6.20\n"
        )
        csv_out = import_authorized_csv(
            payload=CSVImportPayload(
                csv_content=valid_csv_text,
                source_name="Dataset_Propio_Autorizado",
                source_license="Licencia Comercial Propia Verificada",
                is_demo=False,
            ),
            db=db,
            ctx=ctx,
        )
        assert (csv_out["records_inserted"] + csv_out["duplicates_detected"]) == 1
        assert csv_out["is_demo"] is False
    finally:
        db.close()
