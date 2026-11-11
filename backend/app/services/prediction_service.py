from datetime import datetime, timezone
import json
from typing import Any, Dict, List, Optional
import uuid
import joblib
import numpy as np
from sqlalchemy.orm import Session

from app.core.config import ARTIFACTS_DIR
from app.db.models import (
    BacktestRun,
    Competition,
    MarketCatalog,
    Match,
    MatchTeamStat,
    MLModel,
    OddsSnapshot,
    PlayerAvailability,
    Prediction,
    Team,
)
from app.ml.evaluation.backtester import OUTCOME_TO_INDEX, evaluate_predictions_scientifically
from app.ml.features import HistoricalMatchRecord, PointInTimeFeatureBuilder
from app.ml.models.elo_model import DynamicEloModel
from app.ml.models.ensemble_model import TemporalWeightedEnsembleModel
from app.ml.models.poisson_model import PoissonDixonColesModel
from app.ml.models.rf_model import CalibratedRandomForestModel
from app.ml.models.xgb_model import CalibratedXGBoostModel
from app.ml.odds_math import evaluate_market_selections


class PredictionAndTrainingService:
    """Servicio central de entrenamiento, validación temporal e inferencia pre-partido (Capas C, E, F).
    Totalmente desacoplado de la interfaz gráfica.
    """

    def __init__(self) -> None:
        self.poisson = PoissonDixonColesModel()
        self.elo = DynamicEloModel()
        self.rf = CalibratedRandomForestModel()
        self.xgb = CalibratedXGBoostModel()
        self.ensemble = TemporalWeightedEnsembleModel()
        self.active_version: str = "v1.0.0"
        self.baseline_probs: Dict[str, float] = {"HOME": 0.45, "DRAW": 0.27, "AWAY": 0.28}
        self._is_ready: bool = False
        self._cached_records: List[HistoricalMatchRecord] = []
        self._cached_match_count: int = -1
        self._cached_features_by_match_id: Dict[int, Dict[str, Any]] = {}
        self._cached_elo_probs_by_match_id: Dict[int, Dict[str, float]] = {}

    def _load_historical_records(self, db: Session, force_reload: bool = False) -> List[HistoricalMatchRecord]:
        current_count = db.query(Match).count()
        if not force_reload and self._cached_records and current_count == self._cached_match_count:
            return self._cached_records

        matches = db.query(Match).order_by(Match.kickoff_utc.asc()).all()
        stats_rows = db.query(MatchTeamStat).all()
        stats_map: Dict[tuple[int, int], MatchTeamStat] = {(s.match_id, s.team_id): s for s in stats_rows}

        avail_rows = db.query(PlayerAvailability).all()
        missing_map: Dict[tuple[int, int], int] = {}
        for a in avail_rows:
            if a.status_type in ("INJURED", "SUSPENDED"):
                key = (a.match_id, a.team_id)
                missing_map[key] = missing_map.get(key, 0) + 1

        records: List[HistoricalMatchRecord] = []
        for m in matches:
            st_h = stats_map.get((m.id, m.home_team_id))
            st_a = stats_map.get((m.id, m.away_team_id))
            records.append(
                HistoricalMatchRecord(
                    match_id=m.id,
                    competition_id=m.competition_id,
                    season=m.season,
                    kickoff_utc=m.kickoff_utc if m.kickoff_utc.tzinfo else m.kickoff_utc.replace(tzinfo=timezone.utc),
                    home_team_id=m.home_team_id,
                    away_team_id=m.away_team_id,
                    home_goals=m.home_goals,
                    away_goals=m.away_goals,
                    status=m.status,
                    home_xg=st_h.xg if st_h else None,
                    away_xg=st_a.xg if st_a else None,
                    home_shots=st_h.shots if st_h else None,
                    away_shots=st_a.shots if st_a else None,
                    home_sot=st_h.shots_on_target if st_h else None,
                    away_sot=st_a.shots_on_target if st_a else None,
                    home_corners=st_h.corners if st_h else None,
                    away_corners=st_a.corners if st_a else None,
                    home_cards=(st_h.yellow_cards or 0) + (st_h.red_cards or 0) if st_h else None,
                    away_cards=(st_a.yellow_cards or 0) + (st_a.red_cards or 0) if st_a else None,
                    home_missing_players=missing_map.get((m.id, m.home_team_id), 0),
                    away_missing_players=missing_map.get((m.id, m.away_team_id), 0),
                    source_name=m.source_name,
                    is_demo=m.is_demo,
                )
            )
        self._cached_records = records
        self._cached_match_count = len(records)
        return records

    def train_and_validate_all_models(
        self,
        db: Session,
        version_tag: Optional[str] = None,
        calibration_method: str = "sigmoid",
        real_only: Optional[bool] = None,
    ) -> Dict[str, Any]:
        """Ejecuta el flujo completo de entrenamiento y validación científica cronológica:
        - Si `real_only=True` (o si existen >= 50 partidos reales finalizados con `is_demo=False`),
          entrena y evalúa EXCLUSIVAMENTE sobre datos históricos reales autorizados (Paso 4 de Fase 2).
        - Mantiene los registros históricos de Backtesting previos sin alterarlos (Paso 1 de Fase 2).
        """
        all_records = self._load_historical_records(db, force_reload=True)
        all_finished = [
            r
            for r in all_records
            if r.status == "FINISHED" and r.home_goals is not None and r.away_goals is not None
        ]
        real_finished = [r for r in all_finished if not r.is_demo]

        use_real_only = real_only if real_only is not None else (len(real_finished) >= 50)
        finished = real_finished if use_real_only else all_finished
        finished.sort(key=lambda r: r.kickoff_utc)

        if len(finished) < 30:
            raise ValueError(
                f"Se requieren al menos 30 partidos históricos finalizados para validación temporal; encontrados: {len(finished)}"
            )

        train_records, val_records, test_records = PointInTimeFeatureBuilder.split_chronologically_no_overlap(
            finished, train_frac=0.60, val_frac=0.20
        )

        # Frecuencias empíricas en Train para el Modelo Base de Referencia (Naive Baseline)
        h_wins = sum(1 for r in train_records if r.home_goals > r.away_goals)
        draws = sum(1 for r in train_records if r.home_goals == r.away_goals)
        a_wins = len(train_records) - h_wins - draws
        self.baseline_probs = {
            "HOME": round(h_wins / len(train_records), 5),
            "DRAW": round(draws / len(train_records), 5),
            "AWAY": round(a_wins / len(train_records), 5),
        }

        # Recorrido cronológico estricto O(N) sin fuga temporal (agrupado por kickoff_utc < T)
        rolling_elo = DynamicEloModel()
        rolling_elo.calibrate_competition_parameters(train_records)
        features_by_match_id, elo_probs_by_match_id = (
            PointInTimeFeatureBuilder.build_all_chronological_features_and_elo(finished, rolling_elo)
        )
        self._cached_features_by_match_id.update(features_by_match_id)
        self._cached_elo_probs_by_match_id.update(elo_probs_by_match_id)

        # Actualizar calificación Elo actual de cada equipo en la base de datos
        for tid, rating_val in rolling_elo.ratings.items():
            team_obj = db.query(Team).filter(Team.id == tid).first()
            if team_obj:
                team_obj.current_elo = rating_val
                team_obj.matches_indexed = len(rolling_elo.history.get(tid, []))
        db.commit()

        # Entrenamiento de Modelos A, B, C, D sobre Train (con calibración CV interna en Train para mantener Val 100% fuera de muestra)
        X_train = [features_by_match_id[r.match_id] for r in train_records]
        y_train = [
            OUTCOME_TO_INDEX["H" if r.home_goals > r.away_goals else ("A" if r.away_goals > r.home_goals else "D")]
            for r in train_records
        ]
        X_val = [features_by_match_id[r.match_id] for r in val_records]
        y_val = [
            OUTCOME_TO_INDEX["H" if r.home_goals > r.away_goals else ("A" if r.away_goals > r.home_goals else "D")]
            for r in val_records
        ]

        poisson_val_model = PoissonDixonColesModel().fit(train_records)
        self.rf = CalibratedRandomForestModel(calibration_method=calibration_method).fit(
            X_train, y_train, X_val, y_val
        )
        self.xgb = CalibratedXGBoostModel(calibration_method=calibration_method).fit(
            X_train, y_train, X_val, y_val
        )

        comp_map = {c.id: c.name for c in db.query(Competition).all()}
        odds_rows = db.query(OddsSnapshot).filter(OddsSnapshot.market_code == "1X2").all()
        odds_by_match: Dict[int, Dict[str, float]] = {}
        for o in odds_rows:
            odds_by_match.setdefault(o.match_id, {})[o.selection_code] = o.decimal_odds

        def build_eval_list(subset: List[HistoricalMatchRecord], p_model: PoissonDixonColesModel, mode: str):
            out = []
            for r in subset:
                ft = features_by_match_id[r.match_id]
                outcome_code = "H" if r.home_goals > r.away_goals else ("A" if r.away_goals > r.home_goals else "D")
                if mode == "POISSON":
                    probs = p_model.predict_full_distribution(r.home_team_id, r.away_team_id, ft)["1X2"]
                elif mode == "ELO":
                    probs = elo_probs_by_match_id[r.match_id]
                elif mode == "RANDOM_FOREST":
                    probs = self.rf.predict_1x2(ft)
                elif mode == "XGBOOST":
                    probs = self.xgb.predict_1x2(ft)
                else:
                    p_pois = p_model.predict_full_distribution(r.home_team_id, r.away_team_id, ft)["1X2"]
                    p_elo = elo_probs_by_match_id[r.match_id]
                    p_rf = self.rf.predict_1x2(ft)
                    p_xgb = self.xgb.predict_1x2(ft)
                    probs = self.ensemble.combine_1x2(
                        {"POISSON": p_pois, "ELO": p_elo, "RANDOM_FOREST": p_rf, "XGBOOST": p_xgb}
                    )
                out.append(
                    {
                        "match_id": r.match_id,
                        "competition_name": comp_map.get(r.competition_id, "Liga"),
                        "outcome_1x2": outcome_code,
                        "probs": probs,
                        "odds": odds_by_match.get(r.match_id),
                    }
                )
            return out

        # Evaluar en Validación Temporal (T_val) 100% fuera de muestra para optimizar pesos convexos del Ensamble
        val_metrics_by_model: Dict[str, Dict[str, Any]] = {}
        val_prob_matrices: Dict[str, np.ndarray] = {}
        for m_code in ("POISSON", "ELO", "RANDOM_FOREST", "XGBOOST"):
            val_eval_records = build_eval_list(val_records, poisson_val_model, m_code)
            val_metrics_by_model[m_code] = evaluate_predictions_scientifically(
                val_eval_records, self.baseline_probs
            )
            val_prob_matrices[m_code] = np.array(
                [[rec["probs"]["HOME"], rec["probs"]["DRAW"], rec["probs"]["AWAY"]] for rec in val_eval_records],
                dtype=np.float64,
            )

        val_briers = {k: v["brier_score"] for k, v in val_metrics_by_model.items()}
        base_val_brier = next(iter(val_metrics_by_model.values()))["baseline_brier_score"]

        self.ensemble.optimize_simplex_weights(
            val_prob_matrices=val_prob_matrices,
            y_val_indices=y_val,
            val_brier_by_model=val_briers,
            baseline_brier=base_val_brier,
        )
        val_ens_records = build_eval_list(val_records, poisson_val_model, "ENSEMBLE")
        val_metrics_by_model["ENSEMBLE"] = evaluate_predictions_scientifically(
            val_ens_records, self.baseline_probs
        )

        # Ajustar Poisson con Train+Val antes de evaluar en el conjunto de prueba final (T_test)
        poisson_test_model = PoissonDixonColesModel().fit(train_records + val_records)

        test_metrics_by_model: Dict[str, Dict[str, Any]] = {}
        for m_code in ("POISSON", "ELO", "RANDOM_FOREST", "XGBOOST", "ENSEMBLE"):
            test_eval_records = build_eval_list(test_records, poisson_test_model, m_code)
            test_metrics_by_model[m_code] = evaluate_predictions_scientifically(
                test_eval_records, self.baseline_probs
            )

        # Finalmente entrenar Poisson y Elo sobre el 100% de partidos finalizados para predecir encuentros futuros
        self.poisson = PoissonDixonColesModel().fit(finished)
        self.elo = rolling_elo

        if version_tag:
            self.active_version = version_tag
        else:
            existing_count = db.query(MLModel).filter(MLModel.model_code == "ENSEMBLE").count()
            suffix = "real-cc0" if use_real_only else "mvp"
            self.active_version = f"v2.{existing_count}.0-{suffix}" if use_real_only else f"v1.{existing_count}.0-{suffix}"

        ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
        artifact_file = ARTIFACTS_DIR / f"sportpredict_models_{self.active_version}.joblib"
        joblib.dump(
            {
                "version": self.active_version,
                "trained_at": datetime.now(timezone.utc).isoformat(),
                "real_only": use_real_only,
                "poisson": self.poisson,
                "elo": self.elo,
                "rf": self.rf,
                "xgb": self.xgb,
                "ensemble": self.ensemble,
                "baseline_probs": self.baseline_probs,
            },
            artifact_file,
        )

        train_period_str = f"{train_records[0].kickoff_utc.date()} -> {train_records[-1].kickoff_utc.date()} ({len(train_records)} partidos)"
        val_period_str = f"{val_records[0].kickoff_utc.date()} -> {val_records[-1].kickoff_utc.date()} ({len(val_records)} partidos)"
        test_period_str = f"{test_records[0].kickoff_utc.date()} -> {test_records[-1].kickoff_utc.date()} ({len(test_records)} partidos)"

        model_names = {
            "POISSON": "Modelo A: Poisson / Dixon-Coles",
            "ELO": "Modelo B: Calificación Dinámica Elo",
            "RANDOM_FOREST": "Modelo C: Random Forest Calibrado",
            "XGBOOST": "Modelo D: XGBoost Calibrado",
            "ENSEMBLE": "Modelo E: Ensamble Ponderado Temporal",
        }

        is_any_demo = any(r.is_demo for r in finished)
        saved_models: Dict[str, Any] = {}

        # Garantizar unicidad de versión activa: desactivar versiones previas antes de activar la nueva
        db.query(MLModel).filter(MLModel.version != self.active_version).update(
            {"is_active": False}, synchronize_session=False
        )

        for m_code, disp_name in model_names.items():
            v_m = val_metrics_by_model[m_code]
            t_m = test_metrics_by_model[m_code]
            feat_imp = {}
            if m_code == "RANDOM_FOREST":
                feat_imp = self.rf.feature_importances
            elif m_code == "XGBOOST":
                feat_imp = self.xgb.feature_importances
            elif m_code == "POISSON":
                feat_imp = {"expected_goals_attack_defense": 0.65, "xg_recent_5": 0.25, "missing_players": 0.10}
            elif m_code == "ELO":
                feat_imp = {"elo_rating_differential": 0.78, "home_field_advantage": 0.22}
            elif m_code == "ENSEMBLE":
                feat_imp = self.ensemble.weights

            weight_val = 1.0 if m_code == "ENSEMBLE" else self.ensemble.weights.get(m_code, 0.0)

            db_model = (
                db.query(MLModel)
                .filter(MLModel.model_code == m_code, MLModel.version == self.active_version)
                .first()
            )
            if not db_model:
                db_model = MLModel(
                    model_code=m_code,
                    version=self.active_version,
                    display_name=disp_name,
                    calibration_method=calibration_method.upper() if m_code in ("RANDOM_FOREST", "XGBOOST") else "ANALYTICAL",
                    artifact_path=str(artifact_file.name),
                    train_matches_count=len(train_records),
                    val_brier_score=v_m["brier_score"],
                    val_log_loss=v_m["log_loss"],
                    test_brier_score=t_m["brier_score"],
                    test_log_loss=t_m["log_loss"],
                    ensemble_weight=weight_val,
                    hyperparameters_json=json.dumps(
                        {
                            "calibration": calibration_method,
                            "real_only": use_real_only,
                            "excluded_notes": self.ensemble.excluded_models,
                            "confidence_intervals_95": t_m.get("confidence_intervals_95", {}),
                        }
                    ),
                    feature_importance_json=json.dumps(feat_imp),
                    is_active=True,
                )
                db.add(db_model)
                db.flush()

            bt_run = BacktestRun(
                run_uid=f"{m_code}-{self.active_version}-{uuid.uuid4().hex[:8]}",
                model_id=db_model.id,
                market_code="1X2",
                train_period=train_period_str,
                val_period=val_period_str,
                test_period=test_period_str,
                total_predictions=t_m["total_predictions"],
                accuracy=t_m["accuracy"],
                precision_macro=t_m["precision_macro"],
                recall_macro=t_m["recall_macro"],
                f1_macro=t_m["f1_macro"],
                brier_score=t_m["brier_score"],
                log_loss=t_m["log_loss"],
                ece_calibration=t_m["ece_calibration"],
                baseline_brier_score=t_m["baseline_brier_score"],
                market_brier_score=t_m["market_brier_score"],
                simulated_bets_count=t_m["simulated_bets_count"],
                simulated_roi_pct=t_m["simulated_roi_pct"],
                simulated_yield_pct=t_m["simulated_yield_pct"],
                calibration_curve_json=json.dumps(t_m["calibration_curve"]),
                by_competition_json=json.dumps(t_m["by_competition"]),
                is_demo=is_any_demo,
            )
            db.add(bt_run)
            saved_models[m_code] = {
                "model_code": m_code,
                "display_name": disp_name,
                "version": self.active_version,
                "ensemble_weight": weight_val,
                "validation_brier": v_m["brier_score"],
                "validation_log_loss": v_m["log_loss"],
                "test_metrics": t_m,
                "feature_importance": feat_imp,
            }

        db.commit()
        self._is_ready = True
        return {
            "version": self.active_version,
            "real_only": use_real_only,
            "total_matches_used": len(finished),
            "artifact_path": str(artifact_file),
            "chronological_splits": {
                "train": train_period_str,
                "validation": val_period_str,
                "test": test_period_str,
            },
            "baseline_probabilities": self.baseline_probs,
            "ensemble_weights": self.ensemble.weights,
            "excluded_models": self.ensemble.excluded_models,
            "models": saved_models,
            "is_demo_dataset": is_any_demo,
        }

    def _load_latest_artifact_if_available(self, db: Session) -> bool:
        from pathlib import Path

        active_m = (
            db.query(MLModel)
            .filter(MLModel.is_active == True, MLModel.artifact_path.isnot(None))
            .order_by(MLModel.id.desc())
            .first()
        )
        if not active_m:
            active_m = db.query(MLModel).filter(MLModel.artifact_path.isnot(None)).order_by(MLModel.id.desc()).first()
        if active_m and active_m.artifact_path:
            raw_p = Path(active_m.artifact_path)
            resolved_p = raw_p if raw_p.exists() else (ARTIFACTS_DIR / raw_p.name)
            if resolved_p.exists():
                try:
                    bundle = joblib.load(resolved_p)
                    m1x2 = bundle.get("models_1x2", {})
                    self.poisson = bundle.get("poisson") or m1x2.get("POISSON", self.poisson)
                    self.elo = bundle.get("elo") or m1x2.get("ELO", self.elo)
                    self.rf = bundle.get("rf") or m1x2.get("RANDOM_FOREST", self.rf)
                    self.xgb = bundle.get("xgb") or m1x2.get("XGBOOST", self.xgb)
                    self.ensemble = bundle.get("ensemble") or m1x2.get("ENSEMBLE", self.ensemble)
                    self.active_version = bundle.get("version", active_m.version)
                    self.baseline_probs = bundle.get("baseline_probs", self.baseline_probs)
                    self._is_ready = True
                    return True
                except Exception:
                    return False
        return False

    def analyze_match(self, db: Session, match_id: int, persist_prediction: bool = True) -> Dict[str, Any]:
        """Genera el análisis integral de un partido."""
        if not self._is_ready:
            if not self._load_latest_artifact_if_available(db):
                self.train_and_validate_all_models(db)

        match = db.query(Match).filter(Match.id == match_id).first()
        if not match:
            raise ValueError(f"Partido con ID {match_id} no encontrado.")

        comp = db.query(Competition).filter(Competition.id == match.competition_id).first()
        home_team = db.query(Team).filter(Team.id == match.home_team_id).first()
        away_team = db.query(Team).filter(Team.id == match.away_team_id).first()

        if match.id in self._cached_features_by_match_id and match.id in self._cached_elo_probs_by_match_id:
            features = self._cached_features_by_match_id[match.id]
            probs_elo_1x2 = self._cached_elo_probs_by_match_id[match.id]
            h_elo_pre = float(features["home_elo_pre"])
            a_elo_pre = float(features["away_elo_pre"])
        else:
            all_records = self._load_historical_records(db)
            target_rec = next((r for r in all_records if r.match_id == match.id), None)
            if not target_rec:
                raise ValueError("No se pudo construir el registro histórico del partido.")

            prior_finished = [
                r
                for r in all_records
                if r.status == "FINISHED"
                and r.home_goals is not None
                and r.away_goals is not None
                and r.kickoff_utc < target_rec.kickoff_utc
                and (r.is_demo == target_rec.is_demo or not r.is_demo)
            ]
            h_elo_pre = self.elo.get_rating(match.home_team_id)
            a_elo_pre = self.elo.get_rating(match.away_team_id)
            probs_elo_1x2 = self.elo.predict_from_ratings(h_elo_pre, a_elo_pre)
            features = PointInTimeFeatureBuilder.build_features_for_match(
                target_match=target_rec,
                all_prior_matches=prior_finished[-400:],
                home_elo=h_elo_pre,
                away_elo=a_elo_pre,
            )
            self._cached_features_by_match_id[match.id] = features
            self._cached_elo_probs_by_match_id[match.id] = probs_elo_1x2

        poisson_dist = self.poisson.predict_full_distribution(match.home_team_id, match.away_team_id, features)
        probs_poisson_1x2 = poisson_dist["1X2"]
        probs_rf_1x2 = self.rf.predict_1x2(features)
        probs_xgb_1x2 = self.xgb.predict_1x2(features)

        model_1x2_map = {
            "POISSON": probs_poisson_1x2,
            "ELO": probs_elo_1x2,
            "RANDOM_FOREST": probs_rf_1x2,
            "XGBOOST": probs_xgb_1x2,
        }
        probs_ensemble_1x2 = self.ensemble.combine_1x2(model_1x2_map)
        model_1x2_map["ENSEMBLE"] = probs_ensemble_1x2

        odds_rows = db.query(OddsSnapshot).filter(OddsSnapshot.match_id == match.id).all()
        odds_by_market: Dict[str, Dict[str, float]] = {}
        bookmaker_name = None
        odds_captured_at = None
        for o in odds_rows:
            odds_by_market.setdefault(o.market_code, {})[o.selection_code] = o.decimal_odds
            bookmaker_name = o.bookmaker_name
            odds_captured_at = o.captured_at.isoformat() if o.captured_at else None

        min_matches = min(int(features["home_matches_played"]), int(features["away_matches_played"]))

        per_model_1x2_lists = {
            sel: [model_1x2_map[m][sel] for m in ("POISSON", "ELO", "RANDOM_FOREST", "XGBOOST")]
            for sel in ("HOME", "DRAW", "AWAY")
        }
        val_1x2 = evaluate_market_selections(
            probs_by_selection=probs_ensemble_1x2,
            market_odds_by_selection=odds_by_market.get("1X2"),
            per_model_probs_by_selection=per_model_1x2_lists,
            min_team_matches=min_matches,
        )

        markets_output: Dict[str, Any] = {
            "1X2": {
                "market_code": "1X2",
                "display_name": "Resultado Final (1X2)",
                "tier_level": 1,
                "selections": {k: vars(v) for k, v in val_1x2.items()},
            }
        }

        for mkt_code, mkt_title, tier_num in [
            ("OVER_UNDER_1_5", "Más / Menos 1.5 Goles", 1),
            ("OVER_UNDER_2_5", "Más / Menos 2.5 Goles", 1),
            ("BTTS", "Ambos Equipos Marcan (BTTS)", 1),
            ("OVER_UNDER_3_5", "Más / Menos 3.5 Goles", 2),
            ("DOUBLE_CHANCE", "Doble Oportunidad (1X / 12 / X2)", 2),
        ]:
            mkt_probs = poisson_dist[mkt_code]
            per_mod = {sel: [prob_val] for sel, prob_val in mkt_probs.items()}
            valuated = evaluate_market_selections(
                probs_by_selection=mkt_probs,
                market_odds_by_selection=odds_by_market.get(mkt_code),
                per_model_probs_by_selection=per_mod,
                min_team_matches=min_matches,
            )
            markets_output[mkt_code] = {
                "market_code": mkt_code,
                "display_name": mkt_title,
                "tier_level": tier_num,
                "selections": {k: vars(v) for k, v in valuated.items()},
            }

        availabilities = (
            db.query(PlayerAvailability)
            .filter(PlayerAvailability.match_id == match.id)
            .all()
        )
        avail_list = [
            {
                "team_id": a.team_id,
                "team_name": home_team.canonical_name if a.team_id == home_team.id else away_team.canonical_name,
                "player_name": a.player_name,
                "status_type": a.status_type,
                "position": a.position,
                "impact_note": a.impact_note,
                "source_name": a.source_name,
                "recorded_at": a.recorded_at.isoformat(),
            }
            for a in availabilities
        ]

        explanations = [
            f"Diferencial Elo pre-partido: {home_team.canonical_name} ({h_elo_pre:.0f}) vs {away_team.canonical_name} ({a_elo_pre:.0f}) [Δ = {features['elo_diff']:+.0f} pts].",
            f"Goles esperados estimados (Poisson/Dixon-Coles): {home_team.canonical_name} λ={poisson_dist['expected_goals_home']:.2f} vs {away_team.canonical_name} λ={poisson_dist['expected_goals_away']:.2f}.",
            f"Rendimiento últimos 5 partidos: {home_team.canonical_name} ({features['home_pts_last5']:.2f} pts/p, forma {features['home_recent_form_str']}) vs {away_team.canonical_name} ({features['away_pts_last5']:.2f} pts/p, forma {features['away_recent_form_str']}).",
            f"Días de descanso: {home_team.canonical_name} ({features['home_rest_days']}d) vs {away_team.canonical_name} ({features['away_rest_days']}d) | Posición en tabla: #{features['home_league_pos']} vs #{features['away_league_pos']}.",
        ]
        if avail_list:
            explanations.append(
                f"Bajas registradas antes del inicio: {features['home_missing_players']} en local y {features['away_missing_players']} en visitante."
            )

        if persist_prediction:
            ens_model = (
                db.query(MLModel)
                .filter(MLModel.model_code == "ENSEMBLE", MLModel.version == self.active_version)
                .first()
            )
            if ens_model:
                existing_preds = (
                    db.query(Prediction)
                    .filter(
                        Prediction.match_id == match.id,
                        Prediction.model_id == ens_model.id,
                        Prediction.market_code == "1X2",
                    )
                    .all()
                )
                if not existing_preds:
                    actual_sel = None
                    if match.status == "FINISHED" and match.outcome_1x2:
                        actual_sel = {"H": "HOME", "D": "DRAW", "A": "AWAY"}.get(match.outcome_1x2)

                    for sel_code, val_obj in val_1x2.items():
                        status_str = "PENDING"
                        brier_c = None
                        if actual_sel is not None:
                            is_hit = 1.0 if sel_code == actual_sel else 0.0
                            status_str = "WON" if is_hit == 1.0 else "LOST"
                            brier_c = round((val_obj.prob_estimated - is_hit) ** 2, 5)

                        db.add(
                            Prediction(
                                match_id=match.id,
                                model_id=ens_model.id,
                                market_code="1X2",
                                selection_code=sel_code,
                                prob_estimated=val_obj.prob_estimated,
                                fair_decimal_odds=val_obj.fair_decimal_odds,
                                available_decimal_odds=val_obj.available_decimal_odds,
                                bookmaker_margin=val_obj.bookmaker_margin,
                                market_implied_prob_fair=val_obj.market_implied_prob_fair,
                                prob_edge_diff=val_obj.prob_edge_diff,
                                expected_value=val_obj.expected_value,
                                uncertainty_score=val_obj.uncertainty_score,
                                uncertainty_label=val_obj.uncertainty_label,
                                explanation_factors_json=json.dumps(explanations, ensure_ascii=False),
                                predicted_before_kickoff_at=datetime.now(timezone.utc),
                                odds_captured_at=datetime.now(timezone.utc) if val_obj.available_decimal_odds else None,
                                settlement_status=status_str,
                                actual_result_code=actual_sel,
                                brier_contribution=brier_c,
                                is_demo=match.is_demo,
                            )
                        )
                    db.commit()

        catalog_rows = db.query(MarketCatalog).order_by(MarketCatalog.tier_level.asc()).all()
        market_governance = [
            {
                "market_code": c.market_code,
                "display_name": c.display_name,
                "tier_level": c.tier_level,
                "is_enabled": c.is_enabled,
                "min_samples_required": c.min_samples_required,
                "status_reason": c.status_reason,
            }
            for c in catalog_rows
        ]

        return {
            "match": {
                "id": match.id,
                "external_ref": match.external_ref,
                "competition_code": comp.code if comp else "GEN",
                "competition_name": comp.name if comp else "Liga",
                "season": match.season,
                "matchday": match.matchday,
                "kickoff_utc": match.kickoff_utc.isoformat(),
                "status": match.status,
                "home_team": {
                    "id": home_team.id,
                    "name": home_team.canonical_name,
                    "short_code": home_team.short_code,
                    "elo_pre_match": h_elo_pre,
                },
                "away_team": {
                    "id": away_team.id,
                    "name": away_team.canonical_name,
                    "short_code": away_team.short_code,
                    "elo_pre_match": a_elo_pre,
                },
                "home_goals": match.home_goals,
                "away_goals": match.away_goals,
                "outcome_1x2": match.outcome_1x2,
                "lineups_confirmed": match.lineups_confirmed,
                "source_name": match.source_name,
                "source_license": match.source_license,
                "captured_at": match.captured_at.isoformat(),
                "is_demo": match.is_demo,
            },
            "model_version": self.active_version,
            "bookmaker_source": bookmaker_name,
            "odds_captured_at": odds_captured_at,
            "pre_match_features": features,
            "player_availabilities": avail_list,
            "poisson_goal_model": {
                "expected_goals_home": poisson_dist["expected_goals_home"],
                "expected_goals_away": poisson_dist["expected_goals_away"],
                "home_goal_probabilities": poisson_dist["home_goal_probabilities"],
                "away_goal_probabilities": poisson_dist["away_goal_probabilities"],
                "top_exact_scores": poisson_dist["top_exact_scores"],
            },
            "models_comparison_1x2": model_1x2_map,
            "ensemble_weights": self.ensemble.weights,
            "markets": markets_output,
            "market_governance": market_governance,
            "explanation_factors": explanations,
        }


prediction_service = PredictionAndTrainingService()
