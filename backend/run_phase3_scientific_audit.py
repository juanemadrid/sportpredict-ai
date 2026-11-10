from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any, Dict, List
import joblib
import numpy as np

from app.core.config import ARTIFACTS_DIR
from app.db.models import BacktestRun, Competition, MLModel, OddsSnapshot
from app.db.session import SessionLocal
from app.ml.evaluation.backtester import (
    OUTCOME_TO_INDEX,
    evaluate_predictions_scientifically,
    multiclass_brier_score,
)
from app.ml.evaluation.statistical_audit import (
    compute_per_match_multiclass_brier,
    evaluate_binary_market,
    paired_moving_block_bootstrap_test,
)
from app.ml.features import FEATURE_COLUMNS, HistoricalMatchRecord, PointInTimeFeatureBuilder
from app.ml.models.elo_model import DynamicEloModel
from app.ml.models.ensemble_model import TemporalWeightedEnsembleModel
from app.ml.models.goals_market_models import (
    GOAL_MARKET_CODES,
    GOAL_MARKET_FEATURE_COLUMNS,
    CalibratedGoalMarketRF,
    CalibratedGoalMarketXGB,
    GoalMarketSimplexEnsemble,
    build_goal_market_feature_dict,
    extract_goal_market_target,
    extract_poisson_market_prob,
)
from app.ml.models.poisson_model import PoissonDixonColesModel
from app.ml.models.rf_model import CalibratedRandomForestModel
from app.ml.models.xgb_model import CalibratedXGBoostModel
from app.services.prediction_service import prediction_service


def outcome_idx(r: HistoricalMatchRecord) -> int:
    if r.home_goals > r.away_goals:
        return OUTCOME_TO_INDEX["H"]
    if r.away_goals > r.home_goals:
        return OUTCOME_TO_INDEX["A"]
    return OUTCOME_TO_INDEX["D"]


def outcome_str(r: HistoricalMatchRecord) -> str:
    if r.home_goals > r.away_goals:
        return "H"
    if r.away_goals > r.home_goals:
        return "A"
    return "D"


def probs_dict_to_matrix(dicts: List[Dict[str, float]]) -> np.ndarray:
    mat = np.array([[d["HOME"], d["DRAW"], d["AWAY"]] for d in dicts], dtype=np.float64)
    mat = np.clip(mat, 1e-5, 0.9999)
    return mat / mat.sum(axis=1, keepdims=True)


def matrix_to_eval_records(
    subset: List[HistoricalMatchRecord],
    prob_mat: np.ndarray,
    comp_map: Dict[int, str],
    odds_by_match: Dict[int, Dict[str, float]],
) -> List[Dict[str, Any]]:
    out = []
    for idx, r in enumerate(subset):
        out.append(
            {
                "match_id": r.match_id,
                "competition_name": comp_map.get(r.competition_id, "Liga"),
                "outcome_1x2": outcome_str(r),
                "probs": {
                    "HOME": float(prob_mat[idx, 0]),
                    "DRAW": float(prob_mat[idx, 1]),
                    "AWAY": float(prob_mat[idx, 2]),
                },
                "odds": odds_by_match.get(r.match_id),
            }
        )
    return out


def run_phase3_audit() -> Dict[str, Any]:
    db = SessionLocal()
    try:
        print("[FASE 3] 1. Cargando partidos historicos reales (is_demo=False) y verificando versiones previas...")
        prev_models = db.query(MLModel).order_by(MLModel.id.asc()).all()
        prev_versions_summary = [
            {
                "id": m.id,
                "model_code": m.model_code,
                "version": m.version,
                "is_active": m.is_active,
                "trained_at": m.trained_at.isoformat() if m.trained_at else None,
            }
            for m in prev_models
        ]

        all_records = prediction_service._load_historical_records(db, force_reload=True)
        real_finished = [
            r
            for r in all_records
            if (not r.is_demo)
            and r.status == "FINISHED"
            and r.home_goals is not None
            and r.away_goals is not None
        ]
        real_finished.sort(key=lambda r: (r.kickoff_utc, r.match_id))

        comp_map = {c.id: c.name for c in db.query(Competition).all()}
        odds_rows = db.query(OddsSnapshot).filter(OddsSnapshot.market_code == "1X2").all()
        odds_by_match: Dict[int, Dict[str, float]] = {}
        for o in odds_rows:
            odds_by_match.setdefault(o.match_id, {})[o.selection_code] = o.decimal_odds

        # Partición estricta sin solapamiento de fecha/hora en las fronteras (60% Train, 20% Val, 20% Test)
        train_records, val_records, test_records = PointInTimeFeatureBuilder.split_chronologically_no_overlap(
            real_finished, train_frac=0.60, val_frac=0.20
        )
        y_train = [outcome_idx(r) for r in train_records]
        y_val = [outcome_idx(r) for r in val_records]
        y_test = [outcome_idx(r) for r in test_records]

        # Naive baseline empírico en Train
        h_wins = sum(1 for r in train_records if r.home_goals > r.away_goals)
        draws = sum(1 for r in train_records if r.home_goals == r.away_goals)
        a_wins = len(train_records) - h_wins - draws
        baseline_probs = {
            "HOME": round(h_wins / len(train_records), 5),
            "DRAW": round(draws / len(train_records), 5),
            "AWAY": round(a_wins / len(train_records), 5),
        }
        base_val_mat = np.tile(
            np.array([baseline_probs["HOME"], baseline_probs["DRAW"], baseline_probs["AWAY"]], dtype=np.float64),
            (len(val_records), 1),
        )
        base_test_mat = np.tile(
            np.array([baseline_probs["HOME"], baseline_probs["DRAW"], baseline_probs["AWAY"]], dtype=np.float64),
            (len(test_records), 1),
        )
        base_val_brier = multiclass_brier_score(y_val, base_val_mat)
        base_test_brier = multiclass_brier_score(y_test, base_test_mat)

        print(
            f"[FASE 3] Split sin solapamiento: Train={len(train_records)}, Val={len(val_records)}, Test={len(test_records)}"
        )

        # =========================================================================
        # 2. EXPERIMENTO ELO (K, Regresión entre temporadas theta, HFA por liga)
        # =========================================================================
        print("[FASE 3] 2. Ejecutando busqueda en rejilla para variantes del Sistema Elo en T_val...")
        elo_grid_results: List[Dict[str, Any]] = []
        best_elo_cfg: Dict[str, Any] = {}
        best_elo_val_brier = 999.0

        # Evaluar variante Base de Fase 2 (K=24, theta=0.0, HFA global=65) + rejilla Fase 3
        for use_comp_hfa in (False, True):
            for k_val in (16.0, 20.0, 24.0, 28.0, 32.0):
                for theta_val in (0.0, 0.15, 0.25, 0.33):
                    elo_cand = DynamicEloModel(
                        k_factor=k_val,
                        season_regression_theta=theta_val,
                        use_competition_hfa=use_comp_hfa,
                    )
                    if use_comp_hfa:
                        elo_cand.calibrate_competition_parameters(train_records)

                    # Simulación cronológica rápida solo de probabilidades Elo
                    by_ts: Dict[datetime, List[HistoricalMatchRecord]] = {}
                    for r in real_finished:
                        by_ts.setdefault(r.kickoff_utc, []).append(r)

                    elo_probs_map: Dict[int, Dict[str, float]] = {}
                    for ts in sorted(by_ts.keys()):
                        batch = by_ts[ts]
                        for r in batch:
                            elo_probs_map[r.match_id] = elo_cand.predict_1x2(
                                r.home_team_id, r.away_team_id, r.competition_id, r.season
                            )
                        for r in batch:
                            elo_cand.update_after_match(
                                r.home_team_id,
                                r.away_team_id,
                                int(r.home_goals),
                                int(r.away_goals),
                                r.kickoff_utc,
                                r.match_id,
                                r.competition_id,
                                r.season,
                            )

                    val_mat = probs_dict_to_matrix([elo_probs_map[r.match_id] for r in val_records])
                    test_mat = probs_dict_to_matrix([elo_probs_map[r.match_id] for r in test_records])
                    v_brier = multiclass_brier_score(y_val, val_mat)
                    t_brier = multiclass_brier_score(y_test, test_mat)

                    row_info = {
                        "k_factor": k_val,
                        "season_regression_theta": theta_val,
                        "use_competition_hfa": use_comp_hfa,
                        "val_brier": v_brier,
                        "test_brier": t_brier,
                    }
                    elo_grid_results.append(row_info)
                    if v_brier < best_elo_val_brier:
                        best_elo_val_brier = v_brier
                        best_elo_cfg = row_info

        print(f"[FASE 3] Mejor Elo en T_val: {best_elo_cfg}")

        # Construir variables point-in-time con el mejor Elo (y conservar también Elo Fase 2 para comparación justa)
        elo_phase2 = DynamicEloModel(k_factor=24.0, season_regression_theta=0.0, use_competition_hfa=False)
        _, elo_p2_probs_map = PointInTimeFeatureBuilder.build_all_chronological_features_and_elo(
            real_finished, elo_phase2
        )

        elo_phase3 = DynamicEloModel(
            k_factor=best_elo_cfg["k_factor"],
            season_regression_theta=best_elo_cfg["season_regression_theta"],
            use_competition_hfa=best_elo_cfg["use_competition_hfa"],
        )
        if best_elo_cfg["use_competition_hfa"]:
            elo_phase3.calibrate_competition_parameters(train_records)

        features_by_match_id, elo_p3_probs_map = PointInTimeFeatureBuilder.build_all_chronological_features_and_elo(
            real_finished, elo_phase3
        )

        # Auditoría formal de fronteras temporales y clasificación pre-partido (Sección 5)
        integrity_audit = PointInTimeFeatureBuilder.audit_temporal_and_standings_integrity(
            real_finished, train_records, val_records, test_records, features_by_match_id
        )
        print(
            f"[FASE 3] Auditoria de integridad temporal y tabla pre-partido: "
            f"train_val_disjoint={integrity_audit['train_val_strictly_disjoint']}, "
            f"val_test_disjoint={integrity_audit['val_test_strictly_disjoint']}, "
            f"standings_ok={integrity_audit['standings_integrity_verified']}"
        )

        # =========================================================================
        # 3. EXPERIMENTO POISSON / DIXON-COLES (Decaimiento xi, HFA por liga, iteraciones)
        # =========================================================================
        print("[FASE 3] 3. Ejecutando busqueda en rejilla para Modelo Poisson / Dixon-Coles en T_val...")
        poisson_grid_results: List[Dict[str, Any]] = []
        best_poisson_cfg: Dict[str, Any] = {}
        best_poisson_val_brier = 999.0

        # Fase 2 baseline Poisson (xi=0.0, use_competition_hfa=False, n_iterations=1, shrinkage=4.0)
        p2_poisson_val_model = PoissonDixonColesModel(
            xi=0.0, use_competition_hfa=False, n_iterations=1, shrinkage=4.0
        ).fit(train_records)
        p2_poisson_test_model = PoissonDixonColesModel(
            xi=0.0, use_competition_hfa=False, n_iterations=1, shrinkage=4.0
        ).fit(train_records + val_records)

        p2_pois_val_mat = probs_dict_to_matrix(
            [
                p2_poisson_val_model.predict_full_distribution(
                    r.home_team_id, r.away_team_id, features_by_match_id[r.match_id], r.competition_id
                )["1X2"]
                for r in val_records
            ]
        )
        p2_pois_test_mat = probs_dict_to_matrix(
            [
                p2_poisson_test_model.predict_full_distribution(
                    r.home_team_id, r.away_team_id, features_by_match_id[r.match_id], r.competition_id
                )["1X2"]
                for r in test_records
            ]
        )

        for use_comp_hfa in (False, True):
            for xi_val in (0.0, 0.0008, 0.0015, 0.0022, 0.0030, 0.0045):
                for shrink_val in (4.0, 7.0):
                    p_cand = PoissonDixonColesModel(
                        xi=xi_val,
                        use_competition_hfa=use_comp_hfa,
                        n_iterations=5,
                        shrinkage=shrink_val,
                    ).fit(train_records)

                    v_dicts = [
                        p_cand.predict_full_distribution(
                            r.home_team_id, r.away_team_id, features_by_match_id[r.match_id], r.competition_id
                        )["1X2"]
                        for r in val_records
                    ]
                    v_mat = probs_dict_to_matrix(v_dicts)
                    v_brier = multiclass_brier_score(y_val, v_mat)
                    xg_cal_val = p_cand.evaluate_expected_goals_calibration(val_records, features_by_match_id)

                    cfg_entry = {
                        "xi": xi_val,
                        "use_competition_hfa": use_comp_hfa,
                        "shrinkage": shrink_val,
                        "n_iterations": 5,
                        "val_brier": v_brier,
                        "val_goals_calibration": xg_cal_val,
                    }
                    poisson_grid_results.append(cfg_entry)
                    if v_brier < best_poisson_val_brier:
                        best_poisson_val_brier = v_brier
                        best_poisson_cfg = cfg_entry

        print(f"[FASE 3] Mejor Poisson en T_val: xi={best_poisson_cfg['xi']}, comp_hfa={best_poisson_cfg['use_competition_hfa']}, val_brier={best_poisson_cfg['val_brier']}")

        p3_poisson_val_model = PoissonDixonColesModel(
            xi=best_poisson_cfg["xi"],
            use_competition_hfa=best_poisson_cfg["use_competition_hfa"],
            n_iterations=5,
            shrinkage=best_poisson_cfg["shrinkage"],
        ).fit(train_records)

        p3_poisson_test_model = PoissonDixonColesModel(
            xi=best_poisson_cfg["xi"],
            use_competition_hfa=best_poisson_cfg["use_competition_hfa"],
            n_iterations=5,
            shrinkage=best_poisson_cfg["shrinkage"],
        ).fit(train_records + val_records)

        p3_pois_val_full = [
            p3_poisson_val_model.predict_full_distribution(
                r.home_team_id, r.away_team_id, features_by_match_id[r.match_id], r.competition_id
            )
            for r in val_records
        ]
        p3_pois_test_full = [
            p3_poisson_test_model.predict_full_distribution(
                r.home_team_id, r.away_team_id, features_by_match_id[r.match_id], r.competition_id
            )
            for r in test_records
        ]
        p3_pois_val_mat = probs_dict_to_matrix([d["1X2"] for d in p3_pois_val_full])
        p3_pois_test_mat = probs_dict_to_matrix([d["1X2"] for d in p3_pois_test_full])

        poisson_goals_calibration_test = p3_poisson_test_model.evaluate_expected_goals_calibration(
            test_records, features_by_match_id
        )
        p2_goals_calibration_test = p2_poisson_test_model.evaluate_expected_goals_calibration(
            test_records, features_by_match_id
        )

        # =========================================================================
        # 4. EXPERIMENTO RANDOM FOREST Y XGBOOST (Hiperparámetros, Sobreajuste y Calibración)
        # =========================================================================
        print("[FASE 3] 4. Optimización controlada de Random Forest y XGBoost sobre T_val...")
        X_train = [features_by_match_id[r.match_id] for r in train_records]
        X_val = [features_by_match_id[r.match_id] for r in val_records]
        X_test = [features_by_match_id[r.match_id] for r in test_records]

        # Reproducir RF y XGB con hiperparámetros de Fase 2 sobre el mismo split para comparación exacta
        rf_phase2 = CalibratedRandomForestModel(
            n_estimators=180, max_depth=6, min_samples_leaf=10, calibration_method="sigmoid"
        ).fit(X_train, y_train)
        xgb_phase2 = CalibratedXGBoostModel(
            n_estimators=120, max_depth=3, learning_rate=0.04, min_child_weight=1.0, reg_lambda=3.0, calibration_method="sigmoid"
        ).fit(X_train, y_train)

        rf_p2_val_mat = rf_phase2.predict_proba_matrix(X_val)
        rf_p2_test_mat = rf_phase2.predict_proba_matrix(X_test)
        xgb_p2_val_mat = xgb_phase2.predict_proba_matrix(X_val)
        xgb_p2_test_mat = xgb_phase2.predict_proba_matrix(X_test)

        rf_grid_results: List[Dict[str, Any]] = []
        best_rf_val_brier = 999.0
        best_rf_cfg: Dict[str, Any] = {}
        best_rf_model: CalibratedRandomForestModel = rf_phase2

        for max_d in (4, 5, 6):
            for min_leaf in (10, 20, 30):
                for cal_m in ("sigmoid", "isotonic"):
                    rf_cand = CalibratedRandomForestModel(
                        n_estimators=240,
                        max_depth=max_d,
                        min_samples_leaf=min_leaf,
                        calibration_method=cal_m,
                    ).fit(X_train, y_train)
                    tr_mat = rf_cand.predict_proba_matrix(X_train)
                    va_mat = rf_cand.predict_proba_matrix(X_val)
                    tr_brier = multiclass_brier_score(y_train, tr_mat)
                    va_brier = multiclass_brier_score(y_val, va_mat)
                    gap = round(va_brier - tr_brier, 5)
                    row = {
                        "n_estimators": 240,
                        "max_depth": max_d,
                        "min_samples_leaf": min_leaf,
                        "calibration_method": cal_m,
                        "train_brier": tr_brier,
                        "val_brier": va_brier,
                        "overfit_gap": gap,
                    }
                    rf_grid_results.append(row)
                    if va_brier < best_rf_val_brier:
                        best_rf_val_brier = va_brier
                        best_rf_cfg = row
                        best_rf_model = rf_cand

        xgb_grid_results: List[Dict[str, Any]] = []
        best_xgb_val_brier = 999.0
        best_xgb_cfg: Dict[str, Any] = {}
        best_xgb_model: CalibratedXGBoostModel = xgb_phase2

        for max_d in (2, 3, 4):
            for mcw in (5.0, 15.0, 25.0):
                for reg_l in (3.0, 6.0, 10.0):
                    for cal_m in ("sigmoid", "isotonic"):
                        xgb_cand = CalibratedXGBoostModel(
                            n_estimators=100,
                            max_depth=max_d,
                            learning_rate=0.03,
                            min_child_weight=mcw,
                            reg_lambda=reg_l,
                            calibration_method=cal_m,
                        ).fit(X_train, y_train)
                        tr_mat = xgb_cand.predict_proba_matrix(X_train)
                        va_mat = xgb_cand.predict_proba_matrix(X_val)
                        tr_brier = multiclass_brier_score(y_train, tr_mat)
                        va_brier = multiclass_brier_score(y_val, va_mat)
                        gap = round(va_brier - tr_brier, 5)
                        row = {
                            "n_estimators": 100,
                            "max_depth": max_d,
                            "learning_rate": 0.03,
                            "min_child_weight": mcw,
                            "reg_lambda": reg_l,
                            "calibration_method": cal_m,
                            "train_brier": tr_brier,
                            "val_brier": va_brier,
                            "overfit_gap": gap,
                        }
                        xgb_grid_results.append(row)
                        if va_brier < best_xgb_val_brier:
                            best_xgb_val_brier = va_brier
                            best_xgb_cfg = row
                            best_xgb_model = xgb_cand

        print(f"[FASE 3] Mejor RF en T_val: {best_rf_cfg}")
        print(f"[FASE 3] Mejor XGB en T_val: {best_xgb_cfg}")

        rf_p3_val_mat = best_rf_model.predict_proba_matrix(X_val)
        rf_p3_test_mat = best_rf_model.predict_proba_matrix(X_test)
        xgb_p3_val_mat = best_xgb_model.predict_proba_matrix(X_val)
        xgb_p3_test_mat = best_xgb_model.predict_proba_matrix(X_test)

        elo_p2_val_mat = probs_dict_to_matrix([elo_p2_probs_map[r.match_id] for r in val_records])
        elo_p2_test_mat = probs_dict_to_matrix([elo_p2_probs_map[r.match_id] for r in test_records])
        elo_p3_val_mat = probs_dict_to_matrix([elo_p3_probs_map[r.match_id] for r in val_records])
        elo_p3_test_mat = probs_dict_to_matrix([elo_p3_probs_map[r.match_id] for r in test_records])

        # =========================================================================
        # 5. ENSAMBLE Y AUDITORÍA ESTADÍSTICA (Bootstrap por Bloques Temporales)
        # =========================================================================
        print("[FASE 3] 5. Optimizando Ensamble Fase 3 y ejecutando Bootstrap por Bloques Temporales...")
        val_matrices_p3 = {
            "POISSON": p3_pois_val_mat,
            "ELO": elo_p3_val_mat,
            "RANDOM_FOREST": rf_p3_val_mat,
            "XGBOOST": xgb_p3_val_mat,
        }
        test_matrices_p3 = {
            "POISSON": p3_pois_test_mat,
            "ELO": elo_p3_test_mat,
            "RANDOM_FOREST": rf_p3_test_mat,
            "XGBOOST": xgb_p3_test_mat,
        }
        val_briers_p3 = {k: multiclass_brier_score(y_val, m) for k, m in val_matrices_p3.items()}

        ensemble_p3 = TemporalWeightedEnsembleModel(prune_threshold=0.01)
        weights_p3 = ensemble_p3.optimize_simplex_weights(
            val_prob_matrices=val_matrices_p3,
            y_val_indices=y_val,
            val_brier_by_model=val_briers_p3,
            baseline_brier=base_val_brier,
        )

        def blend_matrices(mats: Dict[str, np.ndarray], weights: Dict[str, float]) -> np.ndarray:
            out = np.zeros_like(next(iter(mats.values())))
            for k, w in weights.items():
                if w > 0:
                    out += w * mats[k]
            out = np.clip(out, 1e-5, 0.9999)
            return out / out.sum(axis=1, keepdims=True)

        ens_p3_val_mat = blend_matrices(val_matrices_p3, weights_p3)
        ens_p3_test_mat = blend_matrices(test_matrices_p3, weights_p3)
        val_matrices_p3["ENSEMBLE"] = ens_p3_val_mat
        test_matrices_p3["ENSEMBLE"] = ens_p3_test_mat

        # También evaluar la combinación fija de Fase 2 (94.62% RF + 5.38% Poisson) sobre los modelos Fase 2
        weights_p2_fixed = {"RANDOM_FOREST": 0.9462, "POISSON": 0.0538, "ELO": 0.0, "XGBOOST": 0.0}
        test_matrices_p2 = {
            "POISSON": p2_pois_test_mat,
            "ELO": elo_p2_test_mat,
            "RANDOM_FOREST": rf_p2_test_mat,
            "XGBOOST": xgb_p2_test_mat,
        }
        test_matrices_p2["ENSEMBLE"] = blend_matrices(test_matrices_p2, weights_p2_fixed)

        # Evaluar métricas completas en Val y Test para Fase 3
        val_metrics_p3: Dict[str, Any] = {}
        test_metrics_p3: Dict[str, Any] = {}
        test_metrics_p2_same_split: Dict[str, Any] = {}

        for m_code in ("POISSON", "ELO", "RANDOM_FOREST", "XGBOOST", "ENSEMBLE"):
            val_recs = matrix_to_eval_records(val_records, val_matrices_p3[m_code], comp_map, odds_by_match)
            test_recs = matrix_to_eval_records(test_records, test_matrices_p3[m_code], comp_map, odds_by_match)
            test_recs_p2 = matrix_to_eval_records(test_records, test_matrices_p2[m_code], comp_map, odds_by_match)

            val_metrics_p3[m_code] = evaluate_predictions_scientifically(val_recs, baseline_probs)
            test_metrics_p3[m_code] = evaluate_predictions_scientifically(test_recs, baseline_probs)
            test_metrics_p2_same_split[m_code] = evaluate_predictions_scientifically(test_recs_p2, baseline_probs)

        # Pruebas de significancia estadística con Bootstrap por Bloques Móviles (MBB) en Test y Val
        losses_test_p3 = {
            m: compute_per_match_multiclass_brier(y_test, test_matrices_p3[m])
            for m in ("POISSON", "ELO", "RANDOM_FOREST", "XGBOOST", "ENSEMBLE")
        }
        losses_test_p2 = {
            m: compute_per_match_multiclass_brier(y_test, test_matrices_p2[m])
            for m in ("POISSON", "ELO", "RANDOM_FOREST", "XGBOOST", "ENSEMBLE")
        }
        losses_test_base = compute_per_match_multiclass_brier(y_test, base_test_mat)

        losses_val_p3 = {
            m: compute_per_match_multiclass_brier(y_val, val_matrices_p3[m])
            for m in ("POISSON", "ELO", "RANDOM_FOREST", "XGBOOST", "ENSEMBLE")
        }

        statistical_tests_1x2 = {
            "ensemble_vs_rf_test": paired_moving_block_bootstrap_test(
                losses_test_p3["ENSEMBLE"], losses_test_p3["RANDOM_FOREST"], "ENSEMBLE_P3", "RANDOM_FOREST_P3"
            ),
            "ensemble_vs_rf_val": paired_moving_block_bootstrap_test(
                losses_val_p3["ENSEMBLE"], losses_val_p3["RANDOM_FOREST"], "ENSEMBLE_P3 (Val)", "RANDOM_FOREST_P3 (Val)"
            ),
            "p2_94_5_combo_vs_rf_p2_test": paired_moving_block_bootstrap_test(
                losses_test_p2["ENSEMBLE"],
                losses_test_p2["RANDOM_FOREST"],
                "ENSEMBLE_P2 (94.62% RF + 5.38% Pois)",
                "RANDOM_FOREST_P2",
            ),
            "ensemble_vs_poisson_test": paired_moving_block_bootstrap_test(
                losses_test_p3["ENSEMBLE"], losses_test_p3["POISSON"], "ENSEMBLE_P3", "POISSON_P3"
            ),
            "ensemble_vs_elo_test": paired_moving_block_bootstrap_test(
                losses_test_p3["ENSEMBLE"], losses_test_p3["ELO"], "ENSEMBLE_P3", "ELO_P3"
            ),
            "ensemble_vs_xgboost_test": paired_moving_block_bootstrap_test(
                losses_test_p3["ENSEMBLE"], losses_test_p3["XGBOOST"], "ENSEMBLE_P3", "XGBOOST_P3"
            ),
            "all_vs_baseline_test": {
                m: paired_moving_block_bootstrap_test(losses_test_p3[m], losses_test_base, f"{m}_P3", "NAIVE_BASELINE")
                for m in ("POISSON", "ELO", "RANDOM_FOREST", "XGBOOST", "ENSEMBLE")
            },
            "phase3_vs_phase2_same_test_split": {
                m: paired_moving_block_bootstrap_test(losses_test_p3[m], losses_test_p2[m], f"{m}_FASE3", f"{m}_FASE2")
                for m in ("POISSON", "ELO", "RANDOM_FOREST", "XGBOOST", "ENSEMBLE")
            },
        }

        # =========================================================================
        # 6. MERCADOS ESPECÍFICOS DE GOLES (Over 1.5, Over 2.5, Under 2.5, Over 3.5, BTTS)
        # =========================================================================
        print("[FASE 3] 6. Entrenando y validando independientemente los 5 mercados de goles...")
        # Para evitar fuga en Train al generar features de Poisson para los clasificadores de goles,
        # usamos p3_poisson_val_model (entrenado en Train) para enriquecer Train y Val, y p3_poisson_test_model para Test.
        pois_train_full = [
            p3_poisson_val_model.predict_full_distribution(
                r.home_team_id, r.away_team_id, features_by_match_id[r.match_id], r.competition_id
            )
            for r in train_records
        ]

        goal_markets_report: Dict[str, Any] = {}
        goal_market_trained_artifacts: Dict[str, Any] = {}

        for mkt_code in GOAL_MARKET_CODES:
            y_tr_mkt = [extract_goal_market_target(int(r.home_goals), int(r.away_goals), mkt_code) for r in train_records]
            y_va_mkt = [extract_goal_market_target(int(r.home_goals), int(r.away_goals), mkt_code) for r in val_records]
            y_te_mkt = [extract_goal_market_target(int(r.home_goals), int(r.away_goals), mkt_code) for r in test_records]

            base_rate_tr = float(np.mean(y_tr_mkt))

            X_tr_mkt = [
                build_goal_market_feature_dict(features_by_match_id[r.match_id], pois_train_full[i], mkt_code)
                for i, r in enumerate(train_records)
            ]
            X_va_mkt = [
                build_goal_market_feature_dict(features_by_match_id[r.match_id], p3_pois_val_full[i], mkt_code)
                for i, r in enumerate(val_records)
            ]
            X_te_mkt = [
                build_goal_market_feature_dict(features_by_match_id[r.match_id], p3_pois_test_full[i], mkt_code)
                for i, r in enumerate(test_records)
            ]

            pois_va_probs = np.array(
                [extract_poisson_market_prob(p3_pois_val_full[i], mkt_code) for i in range(len(val_records))],
                dtype=np.float64,
            )
            pois_te_probs = np.array(
                [extract_poisson_market_prob(p3_pois_test_full[i], mkt_code) for i in range(len(test_records))],
                dtype=np.float64,
            )

            rf_mkt = CalibratedGoalMarketRF(market_code=mkt_code).fit(X_tr_mkt, y_tr_mkt)
            xgb_mkt = CalibratedGoalMarketXGB(market_code=mkt_code).fit(X_tr_mkt, y_tr_mkt)

            rf_va_probs = rf_mkt.predict_proba_pos(X_va_mkt)
            rf_te_probs = rf_mkt.predict_proba_pos(X_te_mkt)
            xgb_va_probs = xgb_mkt.predict_proba_pos(X_va_mkt)
            xgb_te_probs = xgb_mkt.predict_proba_pos(X_te_mkt)

            base_va_brier = float(np.mean(( base_rate_tr - np.asarray(y_va_mkt, dtype=np.float64) ) ** 2))
            ens_mkt = GoalMarketSimplexEnsemble(market_code=mkt_code)
            w_mkt = ens_mkt.optimize_weights(
                val_probs_by_model={"POISSON": pois_va_probs, "RF_GOALS": rf_va_probs, "XGB_GOALS": xgb_va_probs},
                y_val_binary=y_va_mkt,
                baseline_brier=base_va_brier,
            )
            ens_te_probs = ens_mkt.predict_proba_pos(
                {"POISSON": pois_te_probs, "RF_GOALS": rf_te_probs, "XGB_GOALS": xgb_te_probs}
            )

            eval_pois = evaluate_binary_market(
                y_te_mkt, pois_te_probs, base_rate_tr, pois_te_probs, "POISSON", mkt_code
            )
            eval_rf = evaluate_binary_market(
                y_te_mkt, rf_te_probs, base_rate_tr, pois_te_probs, "RF_GOALS", mkt_code
            )
            eval_xgb = evaluate_binary_market(
                y_te_mkt, xgb_te_probs, base_rate_tr, pois_te_probs, "XGB_GOALS", mkt_code
            )
            eval_ens = evaluate_binary_market(
                y_te_mkt, ens_te_probs, base_rate_tr, pois_te_probs, "ENSEMBLE_GOALS", mkt_code
            )

            top_rf_vars = dict(list(rf_mkt.feature_importances.items())[:8])
            top_xgb_vars = dict(list(xgb_mkt.feature_importances.items())[:8])

            goal_markets_report[mkt_code] = {
                "train_empirical_rate": round(base_rate_tr, 4),
                "test_empirical_rate": round(float(np.mean(y_te_mkt)), 4),
                "ensemble_weights_on_val": w_mkt,
                "models_test_evaluation": {
                    "POISSON": eval_pois,
                    "RF_GOALS": eval_rf,
                    "XGB_GOALS": eval_xgb,
                    "ENSEMBLE_GOALS": eval_ens,
                },
                "top_features_rf": top_rf_vars,
                "top_features_xgb": top_xgb_vars,
            }
            goal_market_trained_artifacts[mkt_code] = {
                "rf": rf_mkt,
                "xgb": xgb_mkt,
                "ensemble": ens_mkt,
                "baseline_rate": base_rate_tr,
            }

        # =========================================================================
        # 7. SEGUIMIENTO Y REGISTRO DE NUEVA VERSIÓN (v3.0.0-phase3-scientific)
        # =========================================================================
        print("[FASE 3] 7. Persistiendo nueva version v3.0.0-phase3-scientific manteniendo intactas las anteriores...")
        version_tag = "v3.0.0-phase3-scientific"
        ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
        artifact_path = ARTIFACTS_DIR / f"sportpredict_models_{version_tag}.joblib"

        # Ajustar Poisson final sobre el 100% de partidos reales para inferencia futura
        final_poisson_full = PoissonDixonColesModel(
            xi=best_poisson_cfg["xi"],
            use_competition_hfa=best_poisson_cfg["use_competition_hfa"],
            n_iterations=5,
            shrinkage=best_poisson_cfg["shrinkage"],
        ).fit(real_finished)

        joblib.dump(
            {
                "version": version_tag,
                "trained_at": datetime.now(timezone.utc).isoformat(),
                "dataset": "OPENFOOTBALL_CC0_REAL (4,338 partidos reales, 12 temporadas-liga 2021-2024)",
                "feature_columns_1x2": FEATURE_COLUMNS,
                "feature_columns_goals": GOAL_MARKET_FEATURE_COLUMNS,
                "poisson": final_poisson_full,
                "elo": elo_phase3,
                "rf": best_rf_model,
                "xgb": best_xgb_model,
                "ensemble": ensemble_p3,
                "goal_market_models": goal_market_trained_artifacts,
                "baseline_probs": baseline_probs,
            },
            artifact_path,
        )

        # Actualizar servicio en memoria con los modelos mejorados
        prediction_service.poisson = final_poisson_full
        prediction_service.elo = elo_phase3
        prediction_service.rf = best_rf_model
        prediction_service.xgb = best_xgb_model
        prediction_service.ensemble = ensemble_p3
        prediction_service.active_version = version_tag
        prediction_service.baseline_probs = baseline_probs

        # Guardar registros en MLModel y BacktestRun sin tocar las filas existentes
        model_defs = [
            (
                "POISSON",
                "Modelo A: Poisson / Dixon-Coles con Decaimiento Exponencial y HFA por Liga (Fase 3)",
                "STATISTICAL",
                {
                    "xi": best_poisson_cfg["xi"],
                    "use_competition_hfa": best_poisson_cfg["use_competition_hfa"],
                    "n_iterations": 5,
                    "shrinkage": best_poisson_cfg["shrinkage"],
                    "val_brier": val_metrics_p3["POISSON"]["brier_score"],
                    "goals_calibration_test": poisson_goals_calibration_test,
                },
                {},
            ),
            (
                "ELO",
                "Modelo B: Sistema Elo con HFA por Liga y Regresión Inter-Temporada (Fase 3)",
                "STATISTICAL",
                {
                    "k_factor": best_elo_cfg["k_factor"],
                    "season_regression_theta": best_elo_cfg["season_regression_theta"],
                    "use_competition_hfa": best_elo_cfg["use_competition_hfa"],
                    "comp_home_advantage": elo_phase3.comp_home_advantage,
                    "val_brier": val_metrics_p3["ELO"]["brier_score"],
                },
                {},
            ),
            (
                "RANDOM_FOREST",
                "Modelo C: Random Forest Regularizado y Calibrado (Fase 3)",
                "MACHINE_LEARNING",
                {
                    **best_rf_cfg,
                    "features_used": FEATURE_COLUMNS,
                },
                best_rf_model.feature_importances,
            ),
            (
                "XGBOOST",
                "Modelo D: XGBoost con Regularización Estricta y Calibración (Fase 3)",
                "MACHINE_LEARNING",
                {
                    **best_xgb_cfg,
                    "features_used": FEATURE_COLUMNS,
                },
                best_xgb_model.feature_importances,
            ),
            (
                "ENSEMBLE",
                "Modelo E: Ensamble Ponderado en Validación Temporal Sin Solapamiento (Fase 3)",
                "ENSEMBLE",
                {
                    "weights": weights_p3,
                    "excluded_models": ensemble_p3.excluded_models,
                    "val_brier_by_model": val_briers_p3,
                    "baseline_val_brier": base_val_brier,
                },
                best_rf_model.feature_importances,
            ),
        ]

        train_period_str = (
            f"{train_records[0].kickoff_utc.isoformat()} -> {train_records[-1].kickoff_utc.isoformat()} "
            f"({len(train_records)} partidos)"
        )
        val_period_str = (
            f"{val_records[0].kickoff_utc.isoformat()} -> {val_records[-1].kickoff_utc.isoformat()} "
            f"({len(val_records)} partidos)"
        )
        test_period_str = (
            f"{test_records[0].kickoff_utc.isoformat()} -> {test_records[-1].kickoff_utc.isoformat()} "
            f"({len(test_records)} partidos)"
        )

        # Evitar duplicar si se re-ejecuta el script con la misma versión
        existing_v3 = db.query(MLModel).filter(MLModel.version == version_tag).all()
        if not existing_v3:
            # Desactivar bandera is_active en versiones previas SIN borrar ni alterar sus métricas
            db.query(MLModel).filter(MLModel.is_active == True).update({"is_active": False})
            for code, name, family, hyper, feat_imp in model_defs:
                vm = val_metrics_p3[code]
                tm = test_metrics_p3[code]
                cal_m = (
                    best_rf_cfg["calibration_method"]
                    if code in ("RANDOM_FOREST", "ENSEMBLE")
                    else (best_xgb_cfg["calibration_method"] if code == "XGBOOST" else "ANALYTICAL")
                )
                w_ens = 1.0 if code == "ENSEMBLE" else weights_p3.get(code, 0.0)
                m_row = MLModel(
                    model_code=code,
                    version=version_tag,
                    display_name=name,
                    calibration_method=cal_m,
                    artifact_path=str(artifact_path),
                    train_matches_count=len(train_records),
                    val_brier_score=vm["brier_score"],
                    val_log_loss=vm["log_loss"],
                    test_brier_score=tm["brier_score"],
                    test_log_loss=tm["log_loss"],
                    ensemble_weight=w_ens,
                    hyperparameters_json=json.dumps(hyper, ensure_ascii=False),
                    feature_importance_json=json.dumps(feat_imp, ensure_ascii=False),
                    is_active=True,
                )
                db.add(m_row)
                db.flush()

                bt_row = BacktestRun(
                    run_uid=f"BT-P3-{code}-{version_tag}",
                    model_id=m_row.id,
                    market_code="1X2",
                    train_period=train_period_str[:80],
                    val_period=val_period_str[:80],
                    test_period=test_period_str[:80],
                    total_predictions=tm["total_predictions"],
                    accuracy=tm["accuracy"],
                    precision_macro=tm["precision_macro"],
                    recall_macro=tm["recall_macro"],
                    f1_macro=tm["f1_macro"],
                    brier_score=tm["brier_score"],
                    log_loss=tm["log_loss"],
                    ece_calibration=tm["ece_calibration"],
                    baseline_brier_score=tm["baseline_brier_score"],
                    market_brier_score=tm["market_brier_score"],
                    simulated_bets_count=tm["simulated_bets_count"],
                    simulated_roi_pct=tm["simulated_roi_pct"],
                    simulated_yield_pct=tm["simulated_yield_pct"],
                    calibration_curve_json=json.dumps(
                        {
                            "bins": tm["calibration_curve"],
                            "confidence_intervals_95": tm["confidence_intervals_95"],
                        },
                        ensure_ascii=False,
                    ),
                    by_competition_json=json.dumps(tm["by_competition"], ensure_ascii=False),
                    is_demo=False,
                )
                db.add(bt_row)
            db.commit()

        # Verificar total de versiones preservadas en BD
        all_versions_after = (
            db.query(MLModel.version, MLModel.model_code, MLModel.is_active, MLModel.test_brier_score)
            .order_by(MLModel.id.asc())
            .all()
        )

        # Cargar reporte de Fase 2 para comparación histórica directa
        phase2_report_path = Path(__file__).resolve().parent / "data" / "real_historical" / "phase2_training_report.json"
        phase2_saved_report = {}
        if phase2_report_path.exists():
            phase2_saved_report = json.loads(phase2_report_path.read_text(encoding="utf-8"))

        full_report = {
            "generated_at_utc": datetime.now(timezone.utc).isoformat(),
            "version": version_tag,
            "dataset_used": {
                "source": "OPENFOOTBALL_CC0_REAL (github.com/openfootball/football.json)",
                "license": "CC0-1.0 Universal (Dominio Público)",
                "total_real_matches": len(real_finished),
                "competitions": ["Premier League", "LaLiga EA Sports", "Serie A", "Bundesliga"],
                "seasons": ["2021-22", "2022-23", "2023-24"],
                "has_historical_odds": False,
                "roi_policy": "ROI no calculado por ausencia de cuotas históricas reales (prohibido inventar cuotas).",
            },
            "features_used_1x2": FEATURE_COLUMNS,
            "features_used_goal_markets": GOAL_MARKET_FEATURE_COLUMNS,
            "temporal_and_standings_integrity_audit": integrity_audit,
            "experiment_1_poisson_dixon_coles": {
                "grid_search_on_val": poisson_grid_results,
                "selected_best_config": best_poisson_cfg,
                "phase2_goals_calibration_test": p2_goals_calibration_test,
                "phase3_goals_calibration_test": poisson_goals_calibration_test,
            },
            "experiment_2_elo": {
                "grid_search_on_val": elo_grid_results,
                "selected_best_config": best_elo_cfg,
                "calibrated_competition_hfa": elo_phase3.comp_home_advantage,
                "calibrated_competition_draw_nu": elo_phase3.comp_draw_nu,
            },
            "experiment_3_rf_and_xgboost": {
                "rf_grid_on_val": rf_grid_results,
                "selected_rf_config": best_rf_cfg,
                "rf_feature_importances": best_rf_model.feature_importances,
                "xgb_grid_on_val": xgb_grid_results,
                "selected_xgb_config": best_xgb_cfg,
                "xgb_feature_importances": best_xgb_model.feature_importances,
            },
            "experiment_4_ensemble_and_comparison": {
                "phase3_simplex_weights_on_val": weights_p3,
                "phase3_excluded_models": ensemble_p3.excluded_models,
                "validation_metrics_phase3": val_metrics_p3,
                "test_metrics_phase3": test_metrics_p3,
                "test_metrics_phase2_on_exact_same_split": test_metrics_p2_same_split,
                "phase2_original_report_metrics": phase2_saved_report.get("phase2_real_training_results", {}).get(
                    "test_metrics_by_model", {}
                ),
            },
            "section_5_statistical_significance_audit": statistical_tests_1x2,
            "section_6_goal_markets_validation": goal_markets_report,
            "section_7_version_tracking": {
                "previous_versions_preserved_count": len(prev_versions_summary),
                "all_versions_in_db": [
                    {
                        "version": v[0],
                        "model_code": v[1],
                        "is_active": v[2],
                        "test_brier_score": v[3],
                    }
                    for v in all_versions_after
                ],
            },
        }

        out_path = Path(__file__).resolve().parent / "data" / "real_historical" / "phase3_scientific_report.json"
        out_path.write_text(json.dumps(full_report, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"[FASE 3] Reporte cientifico guardado en: {out_path}")
        return full_report
    finally:
        db.close()


if __name__ == "__main__":
    run_phase3_audit()
