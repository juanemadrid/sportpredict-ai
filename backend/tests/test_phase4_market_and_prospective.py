"""Suite de pruebas automatizadas de la Fase 4:
1. Conversión de cuotas, eliminación de margen (Proporcional y Potencia), EV y CLV sin inventar cuotas.
2. Clasificación estadística de diferencias (no confundir diferencia puntual con ventaja rentable).
3. Guardia de licencias comerciales y captura pre-kickoff de cuotas (inicial, actual, cierre) en los 6 mercados.
4. Registro prospectivo inmutable sellado con SHA-256 y protegido por triggers SQLite contra edición retroactiva o borrado.
5. Separación estricta entre resultados históricos (868 partidos reales CC0) y prospectivos en evaluación y API.
"""

from datetime import datetime, timedelta, timezone
from fastapi.testclient import TestClient
import pytest
from sqlalchemy import text

from app.db.models import Competition, Match, ProspectivePredictionRecord, Team
from app.db import session as app_db_session
from app.main import app
from app.ml.market_comparison import (
    calculate_closing_line_value,
    calculate_expected_value,
    classify_statistical_difference,
    compare_market_probabilities_and_odds,
    decimal_odds_to_raw_implied_prob,
    normalize_market_margin_power,
    normalize_market_margin_proportional,
    required_prospective_sample_size_for_edge,
)
from app.services.phase4_market_service import phase4_market_service


def test_phase4_margin_removal_ev_and_clv_math():
    """Verifica la exactitud matemática de conversión de cuotas, eliminación de margen, EV y CLV."""
    assert decimal_odds_to_raw_implied_prob(2.0) == 0.5
    assert decimal_odds_to_raw_implied_prob(None) is None
    with pytest.raises(ValueError):
        decimal_odds_to_raw_implied_prob(1.0)

    # Mercado 1X2 con margen del operador (~5.26%)
    odds_1x2 = {"HOME": 2.00, "DRAW": 3.50, "AWAY": 3.80}
    raw_p, fair_prop, overround = normalize_market_margin_proportional(
        odds_1x2, expected_selections=("HOME", "DRAW", "AWAY")
    )
    assert overround is not None and overround > 0.04
    assert abs(sum(fair_prop.values()) - 1.0) < 1e-5

    fair_power = normalize_market_margin_power(
        odds_1x2, expected_selections=("HOME", "DRAW", "AWAY")
    )
    assert abs(sum(fair_power.values()) - 1.0) < 1e-5
    # El método de potencia penaliza más al longshot (AWAY=3.80) que al favorito (HOME=2.00)
    assert fair_power["AWAY"] < fair_prop["AWAY"]
    assert fair_power["HOME"] > fair_prop["HOME"]

    # Si falta una selección del mercado, NO se inventa ni se normaliza en falso
    _, fair_incomplete, ov_incomplete = normalize_market_margin_proportional(
        {"HOME": 2.00, "DRAW": 3.50}, expected_selections=("HOME", "DRAW", "AWAY")
    )
    assert fair_incomplete == {}
    assert ov_incomplete is None

    # Cálculo de EV y CLV cuando existe cuota de cierre vs cuando no existe
    ev = calculate_expected_value(0.55, 2.00)
    assert ev == 0.10
    assert calculate_expected_value(0.55, None) is None

    clv_odds_none, clv_fair_none = calculate_closing_line_value(2.10, None, None)
    assert clv_odds_none is None and clv_fair_none is None

    clv_odds, clv_fair = calculate_closing_line_value(
        observed_odds=2.10, closing_odds=1.95, closing_fair_prob=0.50
    )
    assert clv_odds == round((2.10 / 1.95) - 1.0, 6)
    assert clv_fair == round((2.10 * 0.50) - 1.0, 6)


def test_phase4_statistical_difference_classification_and_sample_size():
    """Comprueba que no se confunda una diferencia pequeña de probabilidad con ventaja estadística."""
    # Caso 1: Sin cuota disponible
    z0, cls0, _ = classify_statistical_difference(0.52, None, None, epistemic_std=0.03)
    assert z0 is None and cls0 == "NO_ODDS_AVAILABLE"

    # Caso 2: EV negativo (p_model > q_fair pero no supera el margen de la casa)
    z1, cls1, _ = classify_statistical_difference(0.51, 0.50, -0.01, epistemic_std=0.02)
    assert cls1 == "NO_STATISTICAL_EDGE"

    # Caso 3: EV positivo pequeño (+1.2%) o dentro del ruido epistémico (z < 1.645)
    z2, cls2, _ = classify_statistical_difference(0.52, 0.50, 0.012, epistemic_std=0.03)
    assert cls2 == "POSITIVE_EV_WITHIN_NOISE"

    # Caso 4: Diferencia estadística candidata (EV >= 2% y z >= 1.645)
    z3, cls3, _ = classify_statistical_difference(0.56, 0.50, 0.064, epistemic_std=0.02)
    assert z3 is not None and z3 >= 1.645
    assert cls3 == "CANDIDATE_STATISTICAL_EDGE"

    # Tamaño muestral requerido para cuota 2.00 y ventaja del 3%
    sample_req = required_prospective_sample_size_for_edge(average_decimal_odds=2.0, expected_yield_edge=0.03)
    assert sample_req["min_bets_for_95pct_significance_z1645"] >= 2500
    assert sample_req["min_bets_for_80pct_power_at_95pct"] >= 6000


def test_phase4_license_guard_and_pre_kickoff_odds_capture():
    """Verifica bloqueo de fuentes sin licencia comercial, bloqueo post-kickoff y captura de 6 mercados."""
    db = app_db_session.SessionLocal()
    try:
        phase4_market_service.ensure_phase4_tables_and_triggers(db)

        comp = db.query(Competition).filter(Competition.is_demo == False).first()
        teams = db.query(Team).filter(Team.is_demo == False).limit(2).all()
        assert comp is not None and len(teams) == 2

        future_kickoff = datetime.now(timezone.utc) + timedelta(days=5)
        sched_match = Match(
            external_ref="TEST-PHASE4-FUTURE-001",
            competition_id=comp.id,
            season="2024-25",
            matchday=10,
            kickoff_utc=future_kickoff,
            status="SCHEDULED",
            home_team_id=teams[0].id,
            away_team_id=teams[1].id,
            source_name="AUTHORIZED_PROSPECTIVE_CAPTURE",
            source_license="CC0-1.0 / Propio Autorizado",
            is_demo=False,
        )
        db.add(sched_match)
        db.commit()
        db.refresh(sched_match)

        # 1. Rechazar fuente cuya licencia NO permite uso comercial SaaS (p.ej. Football-Data.co.uk / CC BY-NC)
        with pytest.raises(ValueError, match="LICENSE_RESTRICTION_ERROR"):
            phase4_market_service.capture_market_odds(
                db=db,
                match_id=sched_match.id,
                market_code="1X2",
                bookmaker_name="RestrictedBookie",
                provider_source="FOOTBALL_DATA_CO_UK",
                license_type="Personal Research Non-Commercial Only",
                commercial_saas_allowed=False,
                odds_by_selection={"HOME": 2.10, "DRAW": 3.40, "AWAY": 3.50},
                line_stage="OPENING",
                is_demo=False,
            )

        # 2. Rechazar captura de cuotas con timestamp posterior al kickoff
        with pytest.raises(ValueError, match="PRE_KICKOFF_ODDS_VIOLATION"):
            phase4_market_service.capture_market_odds(
                db=db,
                match_id=sched_match.id,
                market_code="1X2",
                bookmaker_name="Pinnacle",
                provider_source="AUTHORIZED_PROSPECTIVE_CAPTURE",
                license_type="Datos Propios Autorizados",
                commercial_saas_allowed=True,
                odds_by_selection={"HOME": 2.10, "DRAW": 3.40, "AWAY": 3.50},
                line_stage="CURRENT",
                captured_at_utc=future_kickoff + timedelta(minutes=5),
                is_demo=False,
            )

        # 3. Capturar cuotas autorizadas (OPENING y CURRENT) para los 6 mercados requeridos en Fase 4
        markets_payloads = {
            "1X2": {"HOME": 2.05, "DRAW": 3.45, "AWAY": 3.60},
            "OVER_1_5": {"OVER": 1.28, "UNDER": 3.65},
            "OVER_2_5": {"OVER": 1.92, "UNDER": 1.92},
            "UNDER_2_5": {"UNDER": 1.92, "OVER": 1.92},
            "OVER_3_5": {"OVER": 3.20, "UNDER": 1.35},
            "BTTS": {"YES": 1.78, "NO": 2.02},
        }
        for mkt_code, odds_map in markets_payloads.items():
            res = phase4_market_service.capture_market_odds(
                db=db,
                match_id=sched_match.id,
                market_code=mkt_code,
                bookmaker_name="Pinnacle_Verified",
                provider_source="AUTHORIZED_PROSPECTIVE_CAPTURE",
                license_type="Datos Propios Autorizados",
                commercial_saas_allowed=True,
                odds_by_selection=odds_map,
                line_stage="OPENING",
                captured_at_utc=future_kickoff - timedelta(hours=48),
                is_demo=False,
            )
            assert res["overround_margin"] is not None

        val = phase4_market_service.compute_match_phase4_valuation(db, match_id=sched_match.id)
        assert set(val["markets_comparison"].keys()) == {
            "1X2",
            "OVER_1_5",
            "OVER_2_5",
            "UNDER_2_5",
            "OVER_3_5",
            "BTTS",
        }
        # Verificar que closing_odds sigue siendo None porque aún no se ha capturado cuota de cierre
        assert val["markets_comparison"]["1X2"]["selections"]["HOME"]["opening_odds"] == 2.05
        assert val["markets_comparison"]["1X2"]["selections"]["HOME"]["closing_odds"] is None
    finally:
        db.close()


def test_phase4_immutable_prospective_ledger_and_sqlite_triggers():
    """Verifica el registro prospectivo pre-kickoff, cálculo de CLV al cierre, liquidación post-partido
    y bloqueo en base de datos (triggers SQLite) ante cualquier intento de edición retroactiva o borrado.
    """
    db = app_db_session.SessionLocal()
    try:
        phase4_market_service.ensure_phase4_tables_and_triggers(db)

        comp = db.query(Competition).filter(Competition.is_demo == False).first()
        teams = db.query(Team).filter(Team.is_demo == False).limit(2).all()
        kickoff = datetime.now(timezone.utc) + timedelta(hours=12)

        m = Match(
            external_ref="TEST-PHASE4-IMMUTABLE-002",
            competition_id=comp.id,
            season="2024-25",
            matchday=11,
            kickoff_utc=kickoff,
            status="SCHEDULED",
            home_team_id=teams[0].id,
            away_team_id=teams[1].id,
            source_name="AUTHORIZED_PROSPECTIVE_CAPTURE",
            source_license="CC0-1.0 / Propio Autorizado",
            is_demo=False,
        )
        db.add(m)
        db.commit()
        db.refresh(m)

        # Capturar cuota actual pre-partido en 1X2
        phase4_market_service.capture_market_odds(
            db=db,
            match_id=m.id,
            market_code="1X2",
            bookmaker_name="Pinnacle_Verified",
            provider_source="AUTHORIZED_PROSPECTIVE_CAPTURE",
            license_type="Datos Propios Autorizados",
            commercial_saas_allowed=True,
            odds_by_selection={"HOME": 2.20, "DRAW": 3.40, "AWAY": 3.30},
            line_stage="CURRENT",
            captured_at_utc=kickoff - timedelta(hours=6),
            is_demo=False,
        )

        # Registrar predicciones prospectivas en los 6 mercados antes del inicio
        reg = phase4_market_service.register_prospective_predictions_for_match(
            db=db,
            match_id=m.id,
            predicted_at_override_utc=kickoff - timedelta(hours=5),
        )
        assert reg["created_records_count"] == 13  # 3 (1X2) + 2*5 (mercados binarios) = 13 selecciones

        # Verificar que todos los hashes SHA-256 son válidos
        ledger = phase4_market_service.list_prospective_ledger(db=db, include_demo=False)
        assert ledger["all_hashes_valid"] is True

        first_rec_id = reg["records"][0]["id"]

        # Intentar alterar retroactivamente `prob_model` o `observed_odds` -> DEBE ABORTAR por Trigger SQLite
        with pytest.raises(Exception, match="PROSPECTIVE_LEDGER_IMMUTABLE"):
            db.execute(
                text("UPDATE prospective_predictions SET prob_model = 0.99 WHERE id = :rid"),
                {"rid": first_rec_id},
            )
            db.commit()
        db.rollback()

        # Intentar eliminar un registro prospectivo -> DEBE ABORTAR por Trigger SQLite
        with pytest.raises(Exception, match="PROSPECTIVE_LEDGER_IMMUTABLE"):
            db.execute(
                text("DELETE FROM prospective_predictions WHERE id = :rid"),
                {"rid": first_rec_id},
            )
            db.commit()
        db.rollback()

        # Capturar cuota de cierre (CLOSING) 5 minutos antes del kickoff -> Actualiza CLV legítimamente
        phase4_market_service.capture_market_odds(
            db=db,
            match_id=m.id,
            market_code="1X2",
            bookmaker_name="Pinnacle_Verified",
            provider_source="AUTHORIZED_PROSPECTIVE_CAPTURE",
            license_type="Datos Propios Autorizados",
            commercial_saas_allowed=True,
            odds_by_selection={"HOME": 2.00, "DRAW": 3.50, "AWAY": 3.70},
            line_stage="CLOSING",
            captured_at_utc=kickoff - timedelta(minutes=5),
            is_demo=False,
        )
        home_row = (
            db.query(ProspectivePredictionRecord)
            .filter(
                ProspectivePredictionRecord.match_id == m.id,
                ProspectivePredictionRecord.market_code == "1X2",
                ProspectivePredictionRecord.selection_code == "HOME",
            )
            .first()
        )
        assert home_row is not None
        assert home_row.observed_odds == 2.20
        assert home_row.closing_odds == 2.00
        assert home_row.clv_odds_pct == round((2.20 / 2.00) - 1.0, 6)

        # Intentar liquidar ANTES de que el partido termine -> No debe liquidar nada
        pre_settle = phase4_market_service.settle_finished_prospective_predictions(db=db, match_id=m.id)
        assert pre_settle["settled_records_count"] == 0

        # Simular finalización del encuentro en el pasado y liquidar
        # Nota: kickoff_utc en `prospective_predictions` es inmutable; actualizamos `Match` a FINISHED
        # y ajustamos `m.kickoff_utc` en `Match` al pasado para permitir la liquidación post-partido
        m.kickoff_utc = datetime.now(timezone.utc) - timedelta(hours=3)
        m.status = "FINISHED"
        m.home_goals = 2
        m.away_goals = 1
        m.outcome_1x2 = "H"
        db.commit()

        post_settle = phase4_market_service.settle_finished_prospective_predictions(db=db, match_id=m.id)
        assert post_settle["settled_records_count"] == 13

        db.refresh(home_row)
        assert home_row.settlement_status == "WON"
        assert home_row.actual_outcome_code == "HOME"
        assert home_row.actual_outcome_binary == 1
        assert home_row.brier_contribution is not None
    finally:
        db.close()


def test_phase4_historical_vs_prospective_strict_separation_and_api():
    """Verifica los endpoints REST de la Fase 4 y la separación estricta entre los 868 partidos
    históricos de prueba y el registro prospectivo invocando las funciones de ruta directamente con db.
    """
    from app.api.routes_phase4_market import (
        get_odds_sources_and_licenses,
        get_phase4_market_evaluation,
        get_daily_and_upcoming_matches_valuation,
        get_prospective_immutable_ledger,
    )

    db = app_db_session.SessionLocal()
    try:
        sources_data = get_odds_sources_and_licenses()
        assert len(sources_data["sources"]) >= 5

        eval_data = get_phase4_market_evaluation(db=db)
        hist = eval_data["historical_test_evaluation_868_real_matches"]
        assert set(hist.keys()) == {"1X2", "OVER_1_5", "OVER_2_5", "UNDER_2_5", "OVER_3_5", "BTTS"}
        for mkt_code, mkt_metrics in hist.items():
            assert mkt_metrics["sample_size_matches"] == 868
            assert mkt_metrics["matches_with_real_market_odds"] == 0
            assert mkt_metrics["expected_value_mean"] is None
            assert mkt_metrics["clv_mean_pct"] is None

        ledger_data = get_prospective_immutable_ledger(include_demo=True, limit=50, db=db)
        assert "items" in ledger_data

        daily_data = get_daily_and_upcoming_matches_valuation(include_demo=True, limit=2, db=db)
        assert "items" in daily_data
        assert daily_data["count"] >= 1
    finally:
        db.close()


def test_phase4_security_sec01_endpoints_require_admin():
    """SEC-01: Verifica que los endpoints de captura y liquidación exijan autenticación (401)
    y rol de administrador (403), permitiendo el acceso únicamente a ADMIN (200/éxito).
    """
    from fastapi import HTTPException
    from app.api.routes_phase4_market import (
        CaptureOddsPayload,
        capture_market_odds_endpoint,
        register_prospective_predictions,
        settle_finished_prospective_predictions_endpoint,
    )
    from app.core.security import RequestContext, PLAN_CATALOG, get_request_context

    # 1. Comprobar resolución de contexto por encabezados
    ctx_default = get_request_context(x_user_role=None)
    assert ctx_default.role == "ANONYMOUS"

    ctx_user_role = get_request_context(x_user_role="user")
    assert ctx_user_role.role == "USER"

    ctx_admin_role = get_request_context(x_user_role="admin")
    assert ctx_admin_role.role == "ADMIN"

    ctx_invalid_role = get_request_context(x_user_role="HACKER")
    assert ctx_invalid_role.role == "ANONYMOUS"

    ctx_anon = RequestContext(role="ANONYMOUS", plan_code="FREE", capabilities=PLAN_CATALOG["FREE"])
    ctx_user = RequestContext(role="USER", plan_code="PRO", capabilities=PLAN_CATALOG["PRO"])
    ctx_admin = RequestContext(role="ADMIN", plan_code="PRO", capabilities=PLAN_CATALOG["PRO"])

    payload_odds = CaptureOddsPayload(
        match_id=99999,
        market_code="1X2",
        bookmaker_name="TestBookmaker",
        odds_by_selection={"HOME": 2.0, "DRAW": 3.0, "AWAY": 4.0},
    )

    db = app_db_session.SessionLocal()
    try:
        # A. capture_market_odds_endpoint: 401 para anónimo, 403 para usuario, admin permitido
        with pytest.raises(HTTPException) as exc_info:
            capture_market_odds_endpoint(payload=payload_odds, db=db, ctx=ctx_anon)
        assert exc_info.value.status_code == 401

        with pytest.raises(HTTPException) as exc_info:
            capture_market_odds_endpoint(payload=payload_odds, db=db, ctx=ctx_user)
        assert exc_info.value.status_code == 403

        # B. register_prospective_predictions: 401 para anónimo, 403 para usuario
        with pytest.raises(HTTPException) as exc_info:
            register_prospective_predictions(match_id=99999, payload=None, db=db, ctx=ctx_anon)
        assert exc_info.value.status_code == 401

        with pytest.raises(HTTPException) as exc_info:
            register_prospective_predictions(match_id=99999, payload=None, db=db, ctx=ctx_user)
        assert exc_info.value.status_code == 403

        # C. settle_finished_prospective_predictions_endpoint: 401 para anónimo, 403 para usuario
        with pytest.raises(HTTPException) as exc_info:
            settle_finished_prospective_predictions_endpoint(match_id=99999, db=db, ctx=ctx_anon)
        assert exc_info.value.status_code == 401

        with pytest.raises(HTTPException) as exc_info:
            settle_finished_prospective_predictions_endpoint(match_id=99999, db=db, ctx=ctx_user)
        assert exc_info.value.status_code == 403

        # D. Admin autorizado ejecuta settle legítimamente (retorna dict con status 200)
        res_admin = settle_finished_prospective_predictions_endpoint(match_id=99999, db=db, ctx=ctx_admin)
        assert "settled_records_count" in res_admin
    finally:
        db.close()


def test_phase4_settlement_idempotence():
    """Verifica que la liquidación prospectiva sea estrictamente idempotente.
    Ejecutar múltiples veces la liquidación sobre partidos ya liquidados no debe
    modificar registros, alterar hashes ni generar duplicados.
    """
    db = app_db_session.SessionLocal()
    try:
        from app.api.routes_phase4_market import settle_finished_prospective_predictions_endpoint
        from app.core.security import RequestContext, PLAN_CATALOG

        ctx_admin = RequestContext(role="ADMIN", plan_code="PRO", capabilities=PLAN_CATALOG["PRO"])

        # Primera ejecución de settle para todos los partidos finalizados
        res1 = settle_finished_prospective_predictions_endpoint(match_id=None, db=db, ctx=ctx_admin)
        assert "settled_records_count" in res1

        # Segunda ejecución inmediata (idempotencia)
        res2 = settle_finished_prospective_predictions_endpoint(match_id=None, db=db, ctx=ctx_admin)
        assert res2["settled_records_count"] == 0

        # Tercera ejecución inmediata
        res3 = settle_finished_prospective_predictions_endpoint(match_id=None, db=db, ctx=ctx_admin)
        assert res3["settled_records_count"] == 0

        # Verificar integridad de los hashes del ledger tras las ejecuciones repetidas
        ledger = phase4_market_service.list_prospective_ledger(db=db, include_demo=True)
        assert ledger["all_hashes_valid"] is True
    finally:
        db.close()
