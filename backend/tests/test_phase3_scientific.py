from datetime import datetime, timedelta, timezone
import numpy as np
import pytest

from app.ml.evaluation.statistical_audit import (
    compute_per_match_multiclass_brier,
    evaluate_binary_market,
    paired_moving_block_bootstrap_test,
)
from app.ml.features import HistoricalMatchRecord, PointInTimeFeatureBuilder
from app.ml.models.elo_model import DynamicEloModel
from app.ml.models.goals_market_models import (
    GOAL_MARKET_CODES,
    CalibratedGoalMarketRF,
    GoalMarketSimplexEnsemble,
    build_goal_market_feature_dict,
    extract_goal_market_target,
    generate_temporal_oof_poisson_predictions,
)
from app.ml.models.poisson_model import PoissonDixonColesModel


def test_poisson_time_decay_and_competition_hfa():
    """Verifica el decaimiento temporal exponencial w(t)=exp(-xi*dt), la ventaja de localía por liga
    y la auditoría de calibración de goles esperados del Modelo A mejorado.
    """
    t0 = datetime(2023, 1, 1, 15, 0, tzinfo=timezone.utc)
    matches = []
    # Competición 1 (alta media goleadora local) vs Competición 2 (baja media goleadora local)
    for i in range(30):
        dt = t0 + timedelta(days=i * 7)
        # Equipo 1 anotaba poco hace meses, pero anota mucho recientemente
        hg_1 = 1 if i < 15 else 3
        matches.append(
            HistoricalMatchRecord(
                match_id=i + 1,
                competition_id=1,
                season="2023-24",
                kickoff_utc=dt,
                home_team_id=1,
                away_team_id=2,
                home_goals=hg_1,
                away_goals=1,
                status="FINISHED",
                is_demo=False,
            )
        )
        matches.append(
            HistoricalMatchRecord(
                match_id=100 + i + 1,
                competition_id=2,
                season="2023-24",
                kickoff_utc=dt,
                home_team_id=3,
                away_team_id=4,
                home_goals=1,
                away_goals=1,
                status="FINISHED",
                is_demo=False,
            )
        )

    p_no_decay = PoissonDixonColesModel(xi=0.0, use_competition_hfa=True, n_iterations=5).fit(matches)
    p_with_decay = PoissonDixonColesModel(xi=0.008, use_competition_hfa=True, n_iterations=5).fit(matches)

    # Con decaimiento temporal (xi > 0), la racha reciente de 3 goles del equipo 1 pesa más que con xi=0
    lam_h_static, _ = p_no_decay.estimate_expected_goals(1, 2, None, competition_id=1)
    lam_h_decay, _ = p_with_decay.estimate_expected_goals(1, 2, None, competition_id=1)
    assert lam_h_decay > lam_h_static

    # La ventaja goleadora local en la Competición 1 debe superar a la Competición 2
    assert p_with_decay.comp_home_avg[1] > p_with_decay.comp_home_avg[2]

    cal = p_with_decay.evaluate_expected_goals_calibration(matches)
    assert cal["matches_evaluated"] == 60
    assert cal["total_goals_rmse"] >= 0.0


def test_elo_competition_hfa_and_season_regression():
    """Verifica la ventaja de localía por competición y la regresión a la media entre temporadas en Elo."""
    t0 = datetime(2022, 8, 15, 15, 0, tzinfo=timezone.utc)
    matches = []
    for i in range(25):
        matches.append(
            HistoricalMatchRecord(
                match_id=i + 1,
                competition_id=10,
                season="2022-23",
                kickoff_utc=t0 + timedelta(days=i * 5),
                home_team_id=10,
                away_team_id=20,
                home_goals=2,
                away_goals=0,
                status="FINISHED",
                is_demo=False,
            )
        )

    elo = DynamicEloModel(k_factor=24.0, season_regression_theta=0.25, use_competition_hfa=True)
    elo.calibrate_competition_parameters(matches)
    assert 10 in elo.comp_home_advantage

    for m in matches:
        elo.update_after_match(
            m.home_team_id, m.away_team_id, int(m.home_goals), int(m.away_goals), m.kickoff_utc, m.match_id, m.competition_id, m.season
        )

    r_end_s1 = elo.get_rating(10, season="2022-23")
    assert r_end_s1 > 1600.0

    # Al consultar en una nueva temporada ("2023-24"), el rating regresa un 25% hacia 1500
    r_start_s2 = elo.get_rating(10, season="2023-24")
    expected_reg = round(0.75 * r_end_s1 + 0.25 * 1500.0, 2)
    assert r_start_s2 == pytest.approx(expected_reg, abs=0.05)


def test_strict_disjoint_temporal_boundaries_and_pre_match_standings():
    """Verifica que split_chronologically_no_overlap garantice fronteras temporalmente disjuntas
    incluso cuando hay múltiples partidos simultáneos en el corte.
    """
    t0 = datetime(2023, 5, 1, 15, 0, tzinfo=timezone.utc)
    records = []
    for i in range(50):
        # 5 partidos por cada fecha/hora simultánea
        dt = t0 + timedelta(days=(i // 5) * 7)
        records.append(
            HistoricalMatchRecord(
                match_id=i + 1,
                competition_id=1,
                season="2023-24",
                kickoff_utc=dt,
                home_team_id=(i % 4) + 1,
                away_team_id=((i + 1) % 4) + 1,
                home_goals=(i % 3),
                away_goals=((i + 1) % 2),
                status="FINISHED",
                is_demo=False,
            )
        )

    tr, va, te = PointInTimeFeatureBuilder.split_chronologically_no_overlap(records, 0.60, 0.20)
    elo = DynamicEloModel()
    feats, _ = PointInTimeFeatureBuilder.build_all_chronological_features_and_elo(records, elo)
    audit = PointInTimeFeatureBuilder.audit_temporal_and_standings_integrity(records, tr, va, te, feats)

    assert audit["train_val_strictly_disjoint"] is True
    assert audit["val_test_strictly_disjoint"] is True
    assert audit["standings_integrity_verified"] is True


def test_moving_block_bootstrap_significance_audit():
    """Verifica que la prueba de significancia por bloques móviles detecte diferencias reales
    y no declare significancia artificial ante ruido aleatorio.
    """
    rng = np.random.default_rng(123)
    n = 300
    y_true = rng.integers(0, 3, size=n).tolist()

    # Modelo A claramente superior a Modelo B
    one_hot = np.zeros((n, 3))
    for i, y in enumerate(y_true):
        one_hot[i, y] = 1.0
    mat_good = np.clip(0.65 * one_hot + 0.35 * (1.0 / 3.0), 0.01, 0.99)
    mat_good /= mat_good.sum(axis=1, keepdims=True)
    mat_uniform = np.full((n, 3), 1.0 / 3.0)

    losses_good = compute_per_match_multiclass_brier(y_true, mat_good)
    losses_unif = compute_per_match_multiclass_brier(y_true, mat_uniform)

    res_sig = paired_moving_block_bootstrap_test(losses_good, losses_unif, "GOOD", "UNIFORM", block_size=15, n_boot=500)
    assert res_sig["mean_diff_brier"] < -0.10
    assert res_sig["statistically_significant_95"] is True

    # Dos modelos prácticamente idénticos (diferencia de ruido minúsculo no significativa)
    noise = rng.normal(0.0, 0.002, size=losses_good.shape)
    res_null = paired_moving_block_bootstrap_test(
        losses_good, losses_good + noise - np.mean(noise), "M1", "M2", block_size=15, n_boot=500
    )
    assert res_null["statistically_significant_95"] is False


def test_goal_markets_models_and_evaluation():
    """Verifica la extracción de etiquetas y evaluación binaria para Over 1.5, Over 2.5, Under 2.5, Over 3.5 y BTTS."""
    assert extract_goal_market_target(2, 1, "OVER_1_5") == 1
    assert extract_goal_market_target(2, 1, "OVER_2_5") == 1
    assert extract_goal_market_target(2, 1, "UNDER_2_5") == 0
    assert extract_goal_market_target(2, 1, "OVER_3_5") == 0
    assert extract_goal_market_target(2, 1, "BTTS") == 1
    assert set(GOAL_MARKET_CODES) == {"OVER_1_5", "OVER_2_5", "UNDER_2_5", "OVER_3_5", "BTTS"}

    y_bin = [1, 0, 1, 1, 0, 0, 1, 0, 1, 0] * 8
    probs = np.array([0.7, 0.3, 0.65, 0.6, 0.35, 0.4, 0.75, 0.25, 0.68, 0.32] * 8)
    report = evaluate_binary_market(y_bin, probs, baseline_rate=0.50, model_name="TEST_MKT", market_code="OVER_2_5")
    assert report["brier_score"] < report["baseline_brier_score"]
    assert 0.0 <= report["ece_calibration"] <= 1.0


def test_temporal_oof_poisson_zero_leakage():
    """Verifica que `generate_temporal_oof_poisson_predictions` genere las 4 variables `poisson_*`
    con ventana expansiva estrictamente anterior (`r.kickoff_utc < target.kickoff_utc`) sin fuga in-sample.
    """
    t0 = datetime(2023, 1, 1, 15, 0, tzinfo=timezone.utc)
    records = []
    for i in range(90):
        dt = t0 + timedelta(days=(i // 3) * 7)
        records.append(
            HistoricalMatchRecord(
                match_id=i + 1,
                competition_id=1,
                season="2023-24",
                kickoff_utc=dt,
                home_team_id=(i % 6) + 1,
                away_team_id=((i + 2) % 6) + 1,
                home_goals=(i % 3),
                away_goals=((i + 1) % 2),
                status="FINISHED",
                is_demo=False,
            )
        )
    elo = DynamicEloModel()
    feats, _ = PointInTimeFeatureBuilder.build_all_chronological_features_and_elo(records, elo)
    oof_preds, oof_audit = generate_temporal_oof_poisson_predictions(
        train_records=records,
        features_by_match_id=feats,
        min_fit_matches=15,
        expanding_step_size=25,
    )
    assert len(oof_preds) == 90
    assert oof_audit["temporal_violations_count"] == 0
    assert oof_audit["self_inclusion_violations_count"] == 0
    assert oof_audit["strictly_past_only_guaranteed"] is True


def test_version_tracking_preserves_previous_models():
    """Verifica que las versiones anteriores (v1.0.0-mvp, v1.1.0, v2.0.0-real-cc0, v3.0.0-phase3-scientific)
    sigan intactas y que exista una única versión activa sin ambigüedad.
    """
    from app.api.routes_models import get_models_scientific_comparison
    from app.db.models import MLModel
    from app.db.session import SessionLocal

    db = SessionLocal()
    try:
        versions = {v[0] for v in db.query(MLModel.version).all()}
        assert {"v1.0.0-mvp", "v1.1.0", "v2.0.0-real-cc0", "v3.0.0-phase3-scientific"}.issubset(versions)

        active_versions = {v[0] for v in db.query(MLModel.version).filter(MLModel.is_active == True).all()}
        assert len(active_versions) == 1

        comp = get_models_scientific_comparison(db=db)
        assert comp["active_version"] in active_versions
    finally:
        db.close()
