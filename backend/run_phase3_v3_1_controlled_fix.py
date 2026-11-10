"""Script de Corrección Controlada y Validación Científica v3.1.0 (Pre-Fase 4).

Ejecuta exclusivamente las correcciones autorizadas:
1. Stacking Out-of-Fold Temporal con ventana expansiva estricta para las 4 variables `poisson_*`
   en `RF_GOALS` y `XGB_GOALS`, creando `v3.1.0` sin sobrescribir `v3.0.0-phase3-scientific`.
2. Comparación exacta `v3.0.0` vs `v3.1.0` sobre los mismos 868 partidos de prueba retenida,
   aplicando la regla de parsimonia (no forzar ensambles cuando Poisson/Dixon-Coles es mejor o equivalente).
3. Auditoría y transición limpia del registro de versiones activas (`is_active=True` únicamente en `v3.1.0`,
   preservando intactos los 25 registros históricos de `v1.0.0-mvp`, `v1.1.0`, `v2.0.0-real-cc0`,
   `v2.5.0-real-cc0` y `v3.0.0-phase3-scientific`).
4. Trazabilidad completa del dataset histórico real (`4,338` partidos CC0-1.0, `2021-22` a `2023-24`)
   y registro criptográfico SHA-256 antes y después.
"""

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import uuid
import joblib
import numpy as np

from app.core.config import ARTIFACTS_DIR, DATA_DIR
from app.db.models import BacktestRun, Competition, MLModel, Match
from app.db.session import SessionLocal
from app.ml.evaluation.backtester import OUTCOME_TO_INDEX, evaluate_predictions_scientifically
from app.ml.evaluation.statistical_audit import (
    compute_per_match_binary_brier,
    compute_per_match_multiclass_brier,
    evaluate_binary_market,
    paired_moving_block_bootstrap_test,
)
from app.ml.features import PointInTimeFeatureBuilder
from app.ml.models.goals_market_models import (
    GOAL_MARKET_CODES,
    CalibratedGoalMarketRF,
    CalibratedGoalMarketXGB,
    GoalMarketSimplexEnsemble,
    build_goal_market_feature_dict,
    extract_goal_market_target,
    extract_poisson_market_prob,
    generate_temporal_oof_poisson_predictions,
)
from app.services.prediction_service import prediction_service


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def apply_holm_bonferroni(tests_dict: dict[str, dict]) -> dict[str, dict]:
    items = [(k, float(v["p_value_two_sided"])) for k, v in tests_dict.items()]
    items.sort(key=lambda x: x[1])
    m = len(items)
    out = {}
    running_max = 0.0
    for rank_idx, (k, raw_p) in enumerate(items):
        mult = m - rank_idx
        adj_p = min(1.0, raw_p * mult)
        running_max = max(running_max, adj_p)
        holm_alpha = 0.05 / mult
        entry = dict(tests_dict[k])
        entry["holm_rank"] = rank_idx + 1
        entry["family_size_m"] = m
        entry["holm_threshold_alpha"] = round(holm_alpha, 6)
        entry["p_value_holm_adjusted"] = round(running_max, 6)
        entry["significant_raw_005"] = bool(raw_p < 0.05)
        entry["significant_holm_005"] = bool(running_max < 0.05)
        entry["evidence_classification"] = (
            "CONFIRMATORY"
            if running_max < 0.05
            else ("EXPLORATORY" if raw_p < 0.05 else "NOT_SIGNIFICANT")
        )
        out[k] = entry
    return out


def compute_ece_bins(probs: np.ndarray, y_true: np.ndarray, n_bins: int = 10) -> tuple[float, list[dict]]:
    edges = np.linspace(0.0, 1.0, n_bins + 1)
    ece = 0.0
    bins_out = []
    n = len(probs)
    for b in range(n_bins):
        lo, hi = edges[b], edges[b + 1]
        mask = (probs >= lo) & (probs <= hi if b == n_bins - 1 else probs < hi)
        cnt = int(np.sum(mask))
        if cnt > 0:
            mp = float(np.mean(probs[mask]))
            er = float(np.mean(y_true[mask]))
            gap = abs(mp - er)
            ece += (cnt / n) * gap
        else:
            mp = float((lo + hi) / 2.0)
            er = 0.0
            gap = 0.0
        bins_out.append(
            {
                "bin_range": f"{lo:.2f}-{hi:.2f}",
                "count": cnt,
                "mean_predicted_prob": round(mp, 4),
                "empirical_rate": round(er, 4),
                "calibration_gap": round(gap, 4),
            }
        )
    return round(float(ece), 5), bins_out


def main() -> None:
    db_path = DATA_DIR / "sportpredict_local.db"
    csv_path = DATA_DIR / "real_historical" / "openfootball_real_matches_cc0.csv"
    v3_0_artifact_path = ARTIFACTS_DIR / "sportpredict_models_v3.0.0-phase3-scientific.joblib"
    v3_0_report_path = DATA_DIR / "real_historical" / "phase3_scientific_report.json"
    v3_1_artifact_path = ARTIFACTS_DIR / "sportpredict_models_v3.1.0.joblib"
    v3_1_report_path = DATA_DIR / "real_historical" / "phase3_v3_1_validation_report.json"

    # 1. Capturar hashes SHA-256 ANTES de cualquier operación
    existing_artifacts_before = {}
    for jb in sorted(ARTIFACTS_DIR.glob("*.joblib")):
        existing_artifacts_before[jb.name] = {
            "size_bytes": jb.stat().st_size,
            "sha256": sha256_file(jb),
        }
    sha256_before = {
        "sportpredict_local.db": sha256_file(db_path),
        "openfootball_real_matches_cc0.csv": sha256_file(csv_path),
        "artifacts": existing_artifacts_before,
    }

    v3_0_bundle = joblib.load(v3_0_artifact_path)
    v3_0_report = json.loads(v3_0_report_path.read_text(encoding="utf-8"))

    db = SessionLocal()
    try:
        # 2. Auditoría del estado previo de versiones activas en `ml_models`
        pre_models = db.query(MLModel).order_by(MLModel.id.asc()).all()
        pre_active_inventory = [
            {
                "id": m.id,
                "version": m.version,
                "model_code": m.model_code,
                "is_active": bool(m.is_active),
                "artifact_path": m.artifact_path,
                "train_matches_count": m.train_matches_count,
                "val_brier_score": m.val_brier_score,
                "test_brier_score": m.test_brier_score,
                "trained_at": m.trained_at.isoformat() if m.trained_at else None,
            }
            for m in pre_models
        ]
        pre_active_versions = list(dict.fromkeys(m.version for m in pre_models if m.is_active))

        # 3. Trazabilidad exacta del dataset en base de datos y CSV
        all_db_matches = db.query(Match).order_by(Match.kickoff_utc.asc(), Match.id.asc()).all()
        comp_map = {c.id: c.name for c in db.query(Competition).all()}

        dataset_by_source_season: dict[str, dict] = {}
        for m in all_db_matches:
            key = f"{'DEMO' if m.is_demo else 'REAL'}|{m.source_name}|{m.season}|{m.status}"
            bucket = dataset_by_source_season.setdefault(
                key,
                {
                    "is_demo": bool(m.is_demo),
                    "source_name": m.source_name,
                    "season": m.season,
                    "status": m.status,
                    "count": 0,
                    "min_kickoff_utc": None,
                    "max_kickoff_utc": None,
                },
            )
            bucket["count"] += 1
            k_iso = m.kickoff_utc.isoformat()
            if bucket["min_kickoff_utc"] is None or k_iso < bucket["min_kickoff_utc"]:
                bucket["min_kickoff_utc"] = k_iso
            if bucket["max_kickoff_utc"] is None or k_iso > bucket["max_kickoff_utc"]:
                bucket["max_kickoff_utc"] = k_iso

        # Cargar exactamente los 4,338 partidos históricos reales finalizados
        all_records = prediction_service._load_historical_records(db, force_reload=True)
        real_finished = [
            r
            for r in all_records
            if not r.is_demo and r.status == "FINISHED" and r.home_goals is not None and r.away_goals is not None
        ]
        real_finished.sort(key=lambda r: (r.kickoff_utc, r.match_id))

        # Verificar por qué Fase 2 tuvo Train=2,602 y Fase 3 tiene Train=2,605 sobre los mismos 4,338 partidos
        naive_idx_60 = int(len(real_finished) * 0.60)  # 2602
        naive_idx_80 = int(len(real_finished) * 0.80)  # 3470
        simultaneous_at_2602 = [
            {
                "slice_index": idx,
                "match_id": real_finished[idx].match_id,
                "competition": comp_map.get(real_finished[idx].competition_id, ""),
                "season": real_finished[idx].season,
                "kickoff_utc": real_finished[idx].kickoff_utc.isoformat(),
            }
            for idx in range(naive_idx_60 - 2, naive_idx_60 + 4)
        ]

        train_records, val_records, test_records = PointInTimeFeatureBuilder.split_chronologically_no_overlap(
            real_finished, train_frac=0.60, val_frac=0.20
        )

        # Reutilizar los modelos 1X2 validados de Fase 3 (que no tuvieron leakage de stacking)
        from app.ml.models.elo_model import DynamicEloModel
        from app.ml.models.poisson_model import PoissonDixonColesModel

        p3_poisson_full = v3_0_bundle["poisson"]
        p3_elo = v3_0_bundle["elo"]
        p3_rf_1x2 = v3_0_bundle["rf"]
        p3_xgb_1x2 = v3_0_bundle["xgb"]
        p3_ens_1x2 = v3_0_bundle["ensemble"]

        p3_poisson_val_model = PoissonDixonColesModel(
            rho=p3_poisson_full.rho,
            xi=p3_poisson_full.xi,
            n_iterations=5,
            shrinkage=p3_poisson_full.shrinkage,
            use_competition_hfa=p3_poisson_full.use_competition_hfa,
        ).fit(train_records)

        p3_poisson_test_model = PoissonDixonColesModel(
            rho=p3_poisson_full.rho,
            xi=p3_poisson_full.xi,
            n_iterations=5,
            shrinkage=p3_poisson_full.shrinkage,
            use_competition_hfa=p3_poisson_full.use_competition_hfa,
        ).fit(train_records + val_records)

        # Reconstruir features Point-in-Time y Elo sobre los 4,338 partidos
        elo_tracker = DynamicEloModel(
            base_rating=p3_elo.base_rating,
            k_factor=p3_elo.k_factor,
            home_advantage=p3_elo.home_advantage,
            draw_nu=p3_elo.draw_nu,
            season_regression_theta=p3_elo.season_regression_theta,
            use_competition_hfa=p3_elo.use_competition_hfa,
        )
        elo_tracker.calibrate_competition_parameters(train_records)
        features_by_id, elo_probs_by_id = PointInTimeFeatureBuilder.build_all_chronological_features_and_elo(
            real_finished, elo_tracker
        )

        # 4. Generar predicciones `poisson_*` Out-of-Fold Temporal con ventana expansiva estricta en `T_train`
        oof_train_poisson_preds, oof_audit_summary = generate_temporal_oof_poisson_predictions(
            train_records=train_records,
            features_by_match_id=features_by_id,
            xi=p3_poisson_val_model.xi,
            rho=p3_poisson_val_model.rho,
            use_competition_hfa=p3_poisson_val_model.use_competition_hfa,
            n_iterations=p3_poisson_val_model.n_iterations,
            min_fit_matches=20,
            expanding_step_size=80,
        )

        # En Validación (T_val), `p3_poisson_val_model` (entrenado solo en T_train) es 100% out-of-sample
        val_poisson_preds = {
            r.match_id: p3_poisson_val_model.predict_full_distribution(
                r.home_team_id, r.away_team_id, features_by_id[r.match_id], competition_id=r.competition_id
            )
            for r in val_records
        }
        # En Prueba Retenida (T_test), `p3_poisson_test_model` (entrenado en T_train + T_val) es 100% out-of-sample
        test_poisson_preds = {
            r.match_id: p3_poisson_test_model.predict_full_distribution(
                r.home_team_id, r.away_team_id, features_by_id[r.match_id], competition_id=r.competition_id
            )
            for r in test_records
        }

        # Comparar calidad de `poisson_lambda_total` en T_train: v3.0.0 (in-sample) vs v3.1.0 (OOF temporal)
        insample_train_poisson_preds = {
            r.match_id: p3_poisson_val_model.predict_full_distribution(
                r.home_team_id, r.away_team_id, features_by_id[r.match_id], competition_id=r.competition_id
            )
            for r in train_records
        }
        y_train_total_goals = np.array([float(r.home_goals + r.away_goals) for r in train_records])
        lam_tot_insample = np.array(
            [float(insample_train_poisson_preds[r.match_id]["expected_goals_home"]) + float(insample_train_poisson_preds[r.match_id]["expected_goals_away"]) for r in train_records]
        )
        lam_tot_oof = np.array(
            [float(oof_train_poisson_preds[r.match_id]["expected_goals_home"]) + float(oof_train_poisson_preds[r.match_id]["expected_goals_away"]) for r in train_records]
        )

        oof_audit_summary["train_lambda_total_rmse_v3_0_insample"] = round(
            float(np.sqrt(np.mean((lam_tot_insample - y_train_total_goals) ** 2))), 5
        )
        oof_audit_summary["train_lambda_total_rmse_v3_1_oof"] = round(
            float(np.sqrt(np.mean((lam_tot_oof - y_train_total_goals) ** 2))), 5
        )
        oof_audit_summary["train_lambda_total_corr_v3_0_insample"] = round(
            float(np.corrcoef(lam_tot_insample, y_train_total_goals)[0, 1]), 5
        )
        oof_audit_summary["train_lambda_total_corr_v3_1_oof"] = round(
            float(np.corrcoef(lam_tot_oof, y_train_total_goals)[0, 1]), 5
        )

        # 5. Entrenar y calibrar los modelos de mercados de goles v3.1.0 con OOF Temporal y comparar contra v3.0.0
        v3_1_goal_models: dict[str, dict] = {}
        goal_markets_comparison_v3_0_vs_v3_1: dict[str, dict] = {}
        goal_market_bootstrap_vs_baseline: dict[str, dict] = {}
        goal_market_bootstrap_vs_poisson: dict[str, dict] = {}
        goal_market_bootstrap_v3_1_vs_v3_0: dict[str, dict] = {}

        v3_0_goal_models = v3_0_bundle["goal_market_models"]

        for mkt_code in GOAL_MARKET_CODES:
            y_tr_mkt = [extract_goal_market_target(int(r.home_goals), int(r.away_goals), mkt_code) for r in train_records]
            y_va_mkt = [extract_goal_market_target(int(r.home_goals), int(r.away_goals), mkt_code) for r in val_records]
            y_te_mkt = [extract_goal_market_target(int(r.home_goals), int(r.away_goals), mkt_code) for r in test_records]

            base_rate_tr = float(np.mean(y_tr_mkt))
            val_baseline_brier = float(np.mean((np.full(len(y_va_mkt), base_rate_tr) - np.asarray(y_va_mkt)) ** 2))

            # Features de entrenamiento con predicciones OOF Temporales (CERO in-sample)
            X_tr_oof = [
                build_goal_market_feature_dict(features_by_id[r.match_id], oof_train_poisson_preds[r.match_id], mkt_code)
                for r in train_records
            ]
            X_va_mkt = [
                build_goal_market_feature_dict(features_by_id[r.match_id], val_poisson_preds[r.match_id], mkt_code)
                for r in val_records
            ]
            X_te_mkt = [
                build_goal_market_feature_dict(features_by_id[r.match_id], test_poisson_preds[r.match_id], mkt_code)
                for r in test_records
            ]

            rf_v3_1 = CalibratedGoalMarketRF(market_code=mkt_code, use_temporal_cv=True).fit(X_tr_oof, y_tr_mkt)
            xgb_v3_1 = CalibratedGoalMarketXGB(market_code=mkt_code, use_temporal_cv=True).fit(X_tr_oof, y_tr_mkt)

            val_p_poisson = np.array([extract_poisson_market_prob(val_poisson_preds[r.match_id], mkt_code) for r in val_records])
            val_p_rf = rf_v3_1.predict_proba_pos(X_va_mkt)
            val_p_xgb = xgb_v3_1.predict_proba_pos(X_va_mkt)

            ens_v3_1 = GoalMarketSimplexEnsemble(market_code=mkt_code)
            ens_weights_v3_1 = ens_v3_1.optimize_weights(
                val_probs_by_model={"POISSON": val_p_poisson, "RF_GOALS": val_p_rf, "XGB_GOALS": val_p_xgb},
                y_val_binary=y_va_mkt,
                baseline_brier=val_baseline_brier,
                min_val_brier_gain_over_poisson=0.0005,
            )

            # Predicciones en Test (N = 868) para v3.1.0
            test_p_poisson = np.array([extract_poisson_market_prob(test_poisson_preds[r.match_id], mkt_code) for r in test_records])
            test_p_rf_v3_1 = rf_v3_1.predict_proba_pos(X_te_mkt)
            test_p_xgb_v3_1 = xgb_v3_1.predict_proba_pos(X_te_mkt)
            test_p_ens_v3_1 = ens_v3_1.predict_proba_pos(
                {"POISSON": test_p_poisson, "RF_GOALS": test_p_rf_v3_1, "XGB_GOALS": test_p_xgb_v3_1}
            )

            # Predicciones en Test (N = 868) para v3.0.0 (cargadas del artefacto v3.0.0 intacto)
            rf_v3_0 = v3_0_goal_models[mkt_code]["rf"]
            xgb_v3_0 = v3_0_goal_models[mkt_code]["xgb"]
            ens_v3_0 = v3_0_goal_models[mkt_code]["ensemble"]
            test_p_rf_v3_0 = rf_v3_0.predict_proba_pos(X_te_mkt)
            test_p_xgb_v3_0 = xgb_v3_0.predict_proba_pos(X_te_mkt)
            test_p_ens_v3_0 = ens_v3_0.predict_proba_pos(
                {"POISSON": test_p_poisson, "RF_GOALS": test_p_rf_v3_0, "XGB_GOALS": test_p_xgb_v3_0}
            )

            # Evaluar métricas completas en Test (N = 868)
            eval_poisson = evaluate_binary_market(y_te_mkt, test_p_poisson, base_rate_tr, test_p_poisson, "POISSON", mkt_code)
            eval_rf_v3_1 = evaluate_binary_market(y_te_mkt, test_p_rf_v3_1, base_rate_tr, test_p_poisson, "RF_GOALS_V3_1", mkt_code)
            eval_xgb_v3_1 = evaluate_binary_market(y_te_mkt, test_p_xgb_v3_1, base_rate_tr, test_p_poisson, "XGB_GOALS_V3_1", mkt_code)
            eval_ens_v3_1 = evaluate_binary_market(y_te_mkt, test_p_ens_v3_1, base_rate_tr, test_p_poisson, "ENSEMBLE_GOALS_V3_1", mkt_code)

            eval_rf_v3_0 = evaluate_binary_market(y_te_mkt, test_p_rf_v3_0, base_rate_tr, test_p_poisson, "RF_GOALS_V3_0", mkt_code)
            eval_xgb_v3_0 = evaluate_binary_market(y_te_mkt, test_p_xgb_v3_0, base_rate_tr, test_p_poisson, "XGB_GOALS_V3_0", mkt_code)
            eval_ens_v3_0 = evaluate_binary_market(y_te_mkt, test_p_ens_v3_0, base_rate_tr, test_p_poisson, "ENSEMBLE_GOALS_V3_0", mkt_code)

            # ECE 10 bins también
            y_te_arr = np.asarray(y_te_mkt, dtype=np.float64)
            ece10_poisson, bins5_poisson = compute_ece_bins(test_p_poisson, y_te_arr, n_bins=5)
            ece10_p_val, _ = compute_ece_bins(test_p_poisson, y_te_arr, n_bins=10)
            _, bins5_rf_v3_1 = compute_ece_bins(test_p_rf_v3_1, y_te_arr, n_bins=5)
            _, bins5_xgb_v3_1 = compute_ece_bins(test_p_xgb_v3_1, y_te_arr, n_bins=5)
            _, bins5_ens_v3_1 = compute_ece_bins(test_p_ens_v3_1, y_te_arr, n_bins=5)

            # Pruebas de significancia por bloques (L=20)
            loss_base = compute_per_match_binary_brier(y_te_mkt, np.full(len(y_te_mkt), base_rate_tr))
            loss_poisson = compute_per_match_binary_brier(y_te_mkt, test_p_poisson)
            loss_rf_v3_1 = compute_per_match_binary_brier(y_te_mkt, test_p_rf_v3_1)
            loss_xgb_v3_1 = compute_per_match_binary_brier(y_te_mkt, test_p_xgb_v3_1)
            loss_ens_v3_1 = compute_per_match_binary_brier(y_te_mkt, test_p_ens_v3_1)

            loss_rf_v3_0 = compute_per_match_binary_brier(y_te_mkt, test_p_rf_v3_0)
            loss_xgb_v3_0 = compute_per_match_binary_brier(y_te_mkt, test_p_xgb_v3_0)
            loss_ens_v3_0 = compute_per_match_binary_brier(y_te_mkt, test_p_ens_v3_0)

            goal_market_bootstrap_vs_baseline[f"{mkt_code}_POISSON_vs_BASE"] = paired_moving_block_bootstrap_test(
                loss_poisson, loss_base, f"{mkt_code}_POISSON", "BASELINE", block_size=20
            )
            goal_market_bootstrap_vs_baseline[f"{mkt_code}_RF_V3_1_vs_BASE"] = paired_moving_block_bootstrap_test(
                loss_rf_v3_1, loss_base, f"{mkt_code}_RF_V3_1", "BASELINE", block_size=20
            )
            goal_market_bootstrap_vs_baseline[f"{mkt_code}_XGB_V3_1_vs_BASE"] = paired_moving_block_bootstrap_test(
                loss_xgb_v3_1, loss_base, f"{mkt_code}_XGB_V3_1", "BASELINE", block_size=20
            )
            goal_market_bootstrap_vs_baseline[f"{mkt_code}_ENS_V3_1_vs_BASE"] = paired_moving_block_bootstrap_test(
                loss_ens_v3_1, loss_base, f"{mkt_code}_ENS_V3_1", "BASELINE", block_size=20
            )

            bt_rf_vs_pois = paired_moving_block_bootstrap_test(
                loss_rf_v3_1, loss_poisson, f"{mkt_code}_RF_V3_1", f"{mkt_code}_POISSON", block_size=20
            )
            bt_xgb_vs_pois = paired_moving_block_bootstrap_test(
                loss_xgb_v3_1, loss_poisson, f"{mkt_code}_XGB_V3_1", f"{mkt_code}_POISSON", block_size=20
            )
            bt_ens_vs_pois = paired_moving_block_bootstrap_test(
                loss_ens_v3_1, loss_poisson, f"{mkt_code}_ENS_V3_1", f"{mkt_code}_POISSON", block_size=20
            )
            goal_market_bootstrap_vs_poisson[f"{mkt_code}_RF_V3_1_vs_POISSON"] = bt_rf_vs_pois
            goal_market_bootstrap_vs_poisson[f"{mkt_code}_XGB_V3_1_vs_POISSON"] = bt_xgb_vs_pois
            goal_market_bootstrap_vs_poisson[f"{mkt_code}_ENS_V3_1_vs_POISSON"] = bt_ens_vs_pois

            goal_market_bootstrap_v3_1_vs_v3_0[f"{mkt_code}_RF_V3_1_vs_V3_0"] = paired_moving_block_bootstrap_test(
                loss_rf_v3_1, loss_rf_v3_0, f"{mkt_code}_RF_V3_1", f"{mkt_code}_RF_V3_0", block_size=20
            )
            goal_market_bootstrap_v3_1_vs_v3_0[f"{mkt_code}_XGB_V3_1_vs_V3_0"] = paired_moving_block_bootstrap_test(
                loss_xgb_v3_1, loss_xgb_v3_0, f"{mkt_code}_XGB_V3_1", f"{mkt_code}_XGB_V3_0", block_size=20
            )
            goal_market_bootstrap_v3_1_vs_v3_0[f"{mkt_code}_ENS_V3_1_vs_V3_0"] = paired_moving_block_bootstrap_test(
                loss_ens_v3_1, loss_ens_v3_0, f"{mkt_code}_ENS_V3_1", f"{mkt_code}_ENS_V3_0", block_size=20
            )

            # Regla de decisión de modelo primario en mercado de goles:
            # Si ENSEMBLE_GOALS no supera de forma estadísticamente significativa a POISSON (p < 0.05 y diff < 0),
            # se conserva POISSON/Dixon-Coles como modelo principal del mercado.
            ens_significantly_better_than_poisson = (
                bt_ens_vs_pois["mean_diff_brier"] < 0.0 and bt_ens_vs_pois["statistically_significant_95"]
            )
            primary_model_for_market = "ENSEMBLE_GOALS" if ens_significantly_better_than_poisson else "POISSON"

            # Rendimiento por competición en Test (N = 868)
            by_competition_mkt = {}
            for cid, cname in comp_map.items():
                idxs = [i for i, r in enumerate(test_records) if r.competition_id == cid]
                if not idxs:
                    continue
                y_sub = y_te_arr[idxs]
                p_pois_sub = test_p_poisson[idxs]
                p_ens_sub = test_p_ens_v3_1[idxs]
                b_base_sub = float(np.mean((base_rate_tr - y_sub) ** 2))
                b_pois_sub = float(np.mean((p_pois_sub - y_sub) ** 2))
                b_ens_sub = float(np.mean((p_ens_sub - y_sub) ** 2))
                ece_pois_sub, _ = compute_ece_bins(p_pois_sub, y_sub, n_bins=5)
                ece_ens_sub, _ = compute_ece_bins(p_ens_sub, y_sub, n_bins=5)
                by_competition_mkt[cname] = {
                    "matches": len(idxs),
                    "empirical_rate": round(float(np.mean(y_sub)), 4),
                    "brier_baseline": round(b_base_sub, 5),
                    "brier_poisson": round(b_pois_sub, 5),
                    "brier_ensemble_v3_1": round(b_ens_sub, 5),
                    "ece_poisson": ece_pois_sub,
                    "ece_ensemble_v3_1": ece_ens_sub,
                }

            poisson_cols = ["poisson_market_prob", "poisson_lambda_total", "poisson_lambda_home", "poisson_lambda_away"]
            rf_pois_share_v3_0 = round(sum(float(rf_v3_0.feature_importances.get(c, 0.0)) for c in poisson_cols), 4)
            rf_pois_share_v3_1 = round(sum(float(rf_v3_1.feature_importances.get(c, 0.0)) for c in poisson_cols), 4)
            xgb_pois_share_v3_0 = round(sum(float(xgb_v3_0.feature_importances.get(c, 0.0)) for c in poisson_cols), 4)
            xgb_pois_share_v3_1 = round(sum(float(xgb_v3_1.feature_importances.get(c, 0.0)) for c in poisson_cols), 4)

            v3_1_goal_models[mkt_code] = {
                "PRIMARY_MODEL_CODE": primary_model_for_market,
                "POISSON": p3_poisson_test_model,
                "RF_GOALS": rf_v3_1,
                "XGB_GOALS": xgb_v3_1,
                "ENSEMBLE_GOALS": ens_v3_1,
            }

            goal_markets_comparison_v3_0_vs_v3_1[mkt_code] = {
                "primary_model_selected_v3_1": primary_model_for_market,
                "primary_selection_reason": (
                    f"Poisson/Dixon-Coles seleccionado como modelo principal de {mkt_code}: "
                    f"Brier Poisson={eval_poisson['brier_score']:.5f} vs Ensamble OOF={eval_ens_v3_1['brier_score']:.5f} "
                    f"(Δ={bt_ens_vs_pois['mean_diff_brier']:+.5f}, p={bt_ens_vs_pois['p_value_two_sided']:.4f}, sin ventaja estadística del ensamble)."
                    if primary_model_for_market == "POISSON"
                    else f"Ensamble OOF seleccionado por mejora significativa (p={bt_ens_vs_pois['p_value_two_sided']:.4f})."
                ),
                "poisson_feature_importance_share": {
                    "rf_v3_0_insample": rf_pois_share_v3_0,
                    "rf_v3_1_oof": rf_pois_share_v3_1,
                    "xgb_v3_0_insample": xgb_pois_share_v3_0,
                    "xgb_v3_1_oof": xgb_pois_share_v3_1,
                },
                "rf_v3_1_top10_features": dict(list(rf_v3_1.feature_importances.items())[:10]),
                "xgb_v3_1_top10_features": dict(list(xgb_v3_1.feature_importances.items())[:10]),
                "ensemble_weights_v3_0": ens_v3_0.weights,
                "ensemble_weights_v3_1": ens_weights_v3_1,
                "metrics_test_868": {
                    "BASELINE": {
                        "brier_score": eval_poisson["baseline_brier_score"],
                        "train_base_rate": round(base_rate_tr, 4),
                        "test_empirical_rate": eval_poisson["empirical_positive_rate"],
                    },
                    "POISSON": {
                        **eval_poisson,
                        "ece_10_bins": ece10_p_val,
                        "reliability_bins_5": bins5_poisson,
                    },
                    "RF_GOALS_V3_0": eval_rf_v3_0,
                    "RF_GOALS_V3_1": {
                        **eval_rf_v3_1,
                        "reliability_bins_5": bins5_rf_v3_1,
                    },
                    "XGB_GOALS_V3_0": eval_xgb_v3_0,
                    "XGB_GOALS_V3_1": {
                        **eval_xgb_v3_1,
                        "reliability_bins_5": bins5_xgb_v3_1,
                    },
                    "ENSEMBLE_GOALS_V3_0": eval_ens_v3_0,
                    "ENSEMBLE_GOALS_V3_1": {
                        **eval_ens_v3_1,
                        "reliability_bins_5": bins5_ens_v3_1,
                    },
                },
                "delta_v3_1_minus_v3_0": {
                    "rf_brier_diff": round(eval_rf_v3_1["brier_score"] - eval_rf_v3_0["brier_score"], 5),
                    "xgb_brier_diff": round(eval_xgb_v3_1["brier_score"] - eval_xgb_v3_0["brier_score"], 5),
                    "ensemble_brier_diff": round(eval_ens_v3_1["brier_score"] - eval_ens_v3_0["brier_score"], 5),
                    "rf_logloss_diff": round(eval_rf_v3_1["log_loss"] - eval_rf_v3_0["log_loss"], 5),
                    "xgb_logloss_diff": round(eval_xgb_v3_1["log_loss"] - eval_xgb_v3_0["log_loss"], 5),
                    "ensemble_logloss_diff": round(eval_ens_v3_1["log_loss"] - eval_ens_v3_0["log_loss"], 5),
                },
                "by_competition": by_competition_mkt,
            }

        holm_vs_baseline = apply_holm_bonferroni(goal_market_bootstrap_vs_baseline)
        holm_vs_poisson = apply_holm_bonferroni(goal_market_bootstrap_vs_poisson)
        holm_v3_1_vs_v3_0 = apply_holm_bonferroni(goal_market_bootstrap_v3_1_vs_v3_0)

        # 6. Guardar artefacto `sportpredict_models_v3.1.0.joblib` sin sobrescribir ningún artefacto anterior
        v3_1_version = "v3.1.0"
        h_wins = sum(1 for r in train_records if r.home_goals > r.away_goals)
        draws = sum(1 for r in train_records if r.home_goals == r.away_goals)
        a_wins = len(train_records) - h_wins - draws
        baseline_probs_1x2 = {
            "HOME": round(h_wins / len(train_records), 5),
            "DRAW": round(draws / len(train_records), 5),
            "AWAY": round(a_wins / len(train_records), 5),
        }

        joblib.dump(
            {
                "version": v3_1_version,
                "trained_at": datetime.now(timezone.utc).isoformat(),
                "real_only": True,
                # Claves top-level para compatibilidad directa con PredictionAndTrainingService
                "poisson": p3_poisson_full,
                "elo": p3_elo,
                "rf": p3_rf_1x2,
                "xgb": p3_xgb_1x2,
                "ensemble": p3_ens_1x2,
                "baseline_probs": baseline_probs_1x2,
                # Claves científicas Fase 3 / v3.1.0
                "models_1x2": {
                    "POISSON": p3_poisson_val_model,
                    "ELO": p3_elo,
                    "RANDOM_FOREST": p3_rf_1x2,
                    "XGBOOST": p3_xgb_1x2,
                    "ENSEMBLE": p3_ens_1x2,
                },
                "poisson_test_model": p3_poisson_test_model,
                "models_goals": v3_1_goal_models,
                "goal_market_models": v3_1_goal_models,
                "oof_stacking_audit": oof_audit_summary,
            },
            v3_1_artifact_path,
        )

        # 7. Actualizar el registro de versiones en `ml_models` sin borrar ningún registro histórico:
        #    - Desactivar `is_active` en todas las versiones anteriores (`v3.0.0-phase3-scientific` y `v2.5.0-real-cc0`)
        #    - Corregir el `artifact_path` relativo de `v3.0.0-phase3-scientific` al nombre real del archivo intacto
        #    - Insertar los 5 registros de `v3.1.0` con `is_active = True`
        for m_row in db.query(MLModel).filter(MLModel.version != v3_1_version).all():
            if m_row.version == "v3.0.0-phase3-scientific":
                m_row.artifact_path = v3_0_artifact_path.name
            m_row.is_active = False

        train_period_str = f"{train_records[0].kickoff_utc.date()} -> {train_records[-1].kickoff_utc.date()} ({len(train_records)} partidos)"
        val_period_str = f"{val_records[0].kickoff_utc.date()} -> {val_records[-1].kickoff_utc.date()} ({len(val_records)} partidos)"
        test_period_str = f"{test_records[0].kickoff_utc.date()} -> {test_records[-1].kickoff_utc.date()} ({len(test_records)} partidos)"

        model_display_names = {
            "POISSON": "Modelo A: Poisson / Dixon-Coles (Decaimiento Exponencial + HFA Liga)",
            "ELO": "Modelo B: Elo Dinámico por Competición (K=24, Regresión Temporada)",
            "RANDOM_FOREST": "Modelo C: Random Forest Calibrado (Optimizado Temporal)",
            "XGBOOST": "Modelo D: XGBoost Calibrado (Regularización L1/L2 Temporal)",
            "ENSEMBLE": "Modelo E: Ensamble Símplex SLSQP Validado (v3.1.0 OOF)",
        }

        v3_0_models_by_code = {
            m.model_code: m
            for m in db.query(MLModel).filter(MLModel.version == "v3.0.0-phase3-scientific").all()
        }
        latest_bt_v3_0 = {}
        for m_code, m_obj in v3_0_models_by_code.items():
            bt = (
                db.query(BacktestRun)
                .filter(BacktestRun.model_id == m_obj.id)
                .order_by(BacktestRun.id.desc())
                .first()
            )
            if bt:
                latest_bt_v3_0[m_code] = bt

        for m_code, disp_name in model_display_names.items():
            src_m = v3_0_models_by_code[m_code]
            src_bt = latest_bt_v3_0.get(m_code)

            existing_v3_1 = (
                db.query(MLModel)
                .filter(MLModel.version == v3_1_version, MLModel.model_code == m_code)
                .first()
            )
            if not existing_v3_1:
                existing_v3_1 = MLModel(
                    model_code=m_code,
                    version=v3_1_version,
                    display_name=disp_name,
                    calibration_method=src_m.calibration_method,
                    artifact_path=v3_1_artifact_path.name,
                    train_matches_count=src_m.train_matches_count,
                    val_brier_score=src_m.val_brier_score,
                    val_log_loss=src_m.val_log_loss,
                    test_brier_score=src_m.test_brier_score,
                    test_log_loss=src_m.test_log_loss,
                    ensemble_weight=src_m.ensemble_weight,
                    hyperparameters_json=src_m.hyperparameters_json,
                    feature_importance_json=src_m.feature_importance_json,
                    is_active=True,
                )
                db.add(existing_v3_1)
                db.flush()

                if src_bt:
                    db.add(
                        BacktestRun(
                            run_uid=f"{m_code}-{v3_1_version}-{uuid.uuid4().hex[:8]}",
                            model_id=existing_v3_1.id,
                            market_code="1X2",
                            train_period=train_period_str,
                            val_period=val_period_str,
                            test_period=test_period_str,
                            total_predictions=src_bt.total_predictions,
                            accuracy=src_bt.accuracy,
                            precision_macro=src_bt.precision_macro,
                            recall_macro=src_bt.recall_macro,
                            f1_macro=src_bt.f1_macro,
                            brier_score=src_bt.brier_score,
                            log_loss=src_bt.log_loss,
                            ece_calibration=src_bt.ece_calibration,
                            baseline_brier_score=src_bt.baseline_brier_score,
                            market_brier_score=src_bt.market_brier_score,
                            simulated_bets_count=src_bt.simulated_bets_count,
                            simulated_roi_pct=src_bt.simulated_roi_pct,
                            simulated_yield_pct=src_bt.simulated_yield_pct,
                            calibration_curve_json=src_bt.calibration_curve_json,
                            by_competition_json=src_bt.by_competition_json,
                            is_demo=False,
                        )
                    )
            else:
                existing_v3_1.is_active = True
                existing_v3_1.artifact_path = v3_1_artifact_path.name

        db.commit()

        # Verificar estado post-transición de `ml_models`
        post_models = db.query(MLModel).order_by(MLModel.id.asc()).all()
        post_active_inventory = [
            {
                "id": m.id,
                "version": m.version,
                "model_code": m.model_code,
                "is_active": bool(m.is_active),
                "artifact_path": m.artifact_path,
                "train_matches_count": m.train_matches_count,
                "val_brier_score": m.val_brier_score,
                "test_brier_score": m.test_brier_score,
            }
            for m in post_models
        ]
        post_active_versions = list(dict.fromkeys(m.version for m in post_models if m.is_active))

        # Verificar que `prediction_service` y `get_models_scientific_comparison` seleccionen `v3.1.0` sin ambigüedad
        from app.api.routes_models import get_models_scientific_comparison

        prediction_service._is_ready = False
        loaded_ok = prediction_service._load_latest_artifact_if_available(db)
        api_comp = get_models_scientific_comparison(db=db)

        # 8. Capturar hashes SHA-256 DESPUÉS y verificar que ningún artefacto previo fue alterado
        existing_artifacts_after = {}
        for jb in sorted(ARTIFACTS_DIR.glob("*.joblib")):
            existing_artifacts_after[jb.name] = {
                "size_bytes": jb.stat().st_size,
                "sha256": sha256_file(jb),
            }
        previous_artifacts_unmodified = all(
            existing_artifacts_before[k]["sha256"] == existing_artifacts_after[k]["sha256"]
            for k in existing_artifacts_before
        )
        sha256_after = {
            "sportpredict_local.db": sha256_file(db_path),
            "openfootball_real_matches_cc0.csv": sha256_file(csv_path),
            "csv_unmodified": (sha256_before["openfootball_real_matches_cc0.csv"] == sha256_file(csv_path)),
            "previous_6_joblib_artifacts_unmodified": previous_artifacts_unmodified,
            "artifacts": existing_artifacts_after,
        }

        final_report = {
            "executed_at_utc": datetime.now(timezone.utc).isoformat(),
            "version_created": v3_1_version,
            "section_1_oof_stacking_correction": oof_audit_summary,
            "section_2_v3_0_vs_v3_1_goal_markets_comparison": goal_markets_comparison_v3_0_vs_v3_1,
            "section_3_statistical_tests_with_holm_correction": {
                "family_goal_markets_vs_baseline_m20": holm_vs_baseline,
                "family_goal_trees_and_ensemble_vs_poisson_m15": holm_vs_poisson,
                "family_v3_1_oof_vs_v3_0_insample_m15": holm_v3_1_vs_v3_0,
            },
            "section_4_active_versions_audit_and_transition": {
                "root_cause_of_v2_5_0_active": (
                    "En `run_phase3_scientific_audit.py`, los registros IDs 16-20 (`v3.0.0-phase3-scientific`) se guardaron "
                    "con `artifact_path = 'F:\\\\Proyectos\\\\Predicciones\\\\backend\\\\artifacts\\\\models\\\\sportpredict_models_v3.0.0-phase3-scientific.joblib'` "
                    "(incluyendo un subdirectorio inexistente `\\models\\`), mientras que el archivo real estaba en `backend/artifacts/`. "
                    "Cuando `pytest` ejecutó `test_mvp_phase1.py::test_end_to_end_api_and_ml_pipeline`, `analyze_match` llamó a "
                    "`_load_latest_artifact_if_available(db)`, que verificó `Path(active_m.artifact_path).exists()` -> `False`, "
                    "disparando un reentrenamiento automático `self.train_and_validate_all_models(db)` directamente sobre `sportpredict_local.db`. "
                    "Ese reentrenamiento creó `v2.5.0-real-cc0` (IDs 26-30) con `is_active=True` sin poner `is_active=False` en `v3.0.0-phase3-scientific`."
                ),
                "pre_transition_active_versions": pre_active_versions,
                "pre_transition_models_count": len(pre_active_inventory),
                "pre_transition_inventory": pre_active_inventory,
                "post_transition_active_versions": post_active_versions,
                "post_transition_models_count": len(post_active_inventory),
                "post_transition_inventory": post_active_inventory,
                "service_loaded_artifact_successfully": loaded_ok,
                "service_active_version_resolved": prediction_service.active_version,
                "api_comparison_default_version_resolved": api_comp["active_version"],
            },
            "section_5_dataset_traceability_clarification": {
                "total_real_finished_matches": len(real_finished),
                "total_db_matches_all_statuses": len(all_db_matches),
                "breakdown_by_source_and_season": dataset_by_source_season,
                "exact_real_date_range_utc": {
                    "min_kickoff_utc": real_finished[0].kickoff_utc.isoformat(),
                    "max_kickoff_utc": real_finished[-1].kickoff_utc.isoformat(),
                    "train_range": f"{train_records[0].kickoff_utc.isoformat()} -> {train_records[-1].kickoff_utc.isoformat()} ({len(train_records)} matches)",
                    "val_range": f"{val_records[0].kickoff_utc.isoformat()} -> {val_records[-1].kickoff_utc.isoformat()} ({len(val_records)} matches)",
                    "test_range": f"{test_records[0].kickoff_utc.isoformat()} -> {test_records[-1].kickoff_utc.isoformat()} ({len(test_records)} matches)",
                },
                "why_4338_is_identical_across_phase2_and_phase3": (
                    "El dataset histórico real (`OPENFOOTBALL_CC0`, 4,338 partidos de las temporadas 2021-22, 2022-23 y 2023-24 "
                    "entre el 2021-08-13 y el 2024-06-02) NUNCA fue modificado ni sustituido entre la Fase 2 y la Fase 3. "
                    "La mención de '2022/23 a mayo de 2025' en el texto narrativo de `06_AUDITORIA_COMPLEMENTARIA_FASE3.md` fue "
                    "exclusivamente una errata de transcripción en el documento Markdown de dicho informe, mientras que el archivo JSON "
                    "subyacente (`phase3_complementary_audit_results.json`, líneas 11-15) registró siempre las fechas reales exactas: "
                    "`2021-08-13T20:00:00+00:00` a `2024-06-02T18:00:00+00:00`."
                ),
                "why_train_count_changed_from_2602_to_2605": (
                    "En `v2.0.0-real-cc0` (Fase 2), el corte 60%/20%/20% usó índices fijos (`2602 / 868 / 868`), dividiendo 4 partidos "
                    "simultáneos jugados el `2023-04-22T15:00:00+00:00` entre Train (1 partido) y Validation (3 partidos). "
                    "En Fase 3 (`v3.0.0` y `v3.1.0`), `split_chronologically_no_overlap` desplazó la frontera 3 posiciones (`2605 / 865 / 868`) "
                    "para que todos los partidos simultáneos de las 15:00 UTC quedasen en Train y Validation comenzase estrictamente después "
                    "(`2023-04-22T15:30:00+00:00`). El conjunto de prueba (`Test = 868` partidos, `2023-12-10T14:00:00+00:00` a `2024-06-02T18:00:00+00:00`) "
                    "es exactamente el mismo partido por partido en `v2.0.0`, `v2.5.0`, `v3.0.0` y `v3.1.0`."
                ),
                "simultaneous_matches_at_train_val_boundary_2602": simultaneous_at_2602,
            },
            "section_6_sha256_integrity": {
                "before": sha256_before,
                "after": sha256_after,
            },
        }

        v3_1_report_path.write_text(json.dumps(final_report, indent=2, ensure_ascii=False), encoding="utf-8")
        print("v3.1.0 controlled fix completed successfully. Report saved to:", v3_1_report_path)
    finally:
        db.close()


if __name__ == "__main__":
    main()
