from typing import Any, Dict, List, Optional, Tuple
import numpy as np
from scipy.optimize import minimize
from sklearn.base import clone
from sklearn.calibration import CalibratedClassifierCV
from sklearn.ensemble import RandomForestClassifier
from sklearn.model_selection import TimeSeriesSplit
from xgboost import XGBClassifier

from app.ml.features import FEATURE_COLUMNS, HistoricalMatchRecord
from app.ml.models.poisson_model import PoissonDixonColesModel


GOAL_MARKET_CODES = ["OVER_1_5", "OVER_2_5", "UNDER_2_5", "OVER_3_5", "BTTS"]

GOAL_MARKET_FEATURE_COLUMNS = FEATURE_COLUMNS + [
    "poisson_lambda_home",
    "poisson_lambda_away",
    "poisson_lambda_total",
    "poisson_market_prob",
]


def extract_goal_market_target(home_goals: int, away_goals: int, market_code: str) -> int:
    total = int(home_goals) + int(away_goals)
    if market_code == "OVER_1_5":
        return 1 if total >= 2 else 0
    if market_code == "OVER_2_5":
        return 1 if total >= 3 else 0
    if market_code == "UNDER_2_5":
        return 1 if total <= 2 else 0
    if market_code == "OVER_3_5":
        return 1 if total >= 4 else 0
    if market_code == "BTTS":
        return 1 if (int(home_goals) >= 1 and int(away_goals) >= 1) else 0
    raise ValueError(f"Mercado de goles no reconocido: {market_code}")


def extract_poisson_market_prob(poisson_pred: Dict[str, Any], market_code: str) -> float:
    if market_code == "OVER_1_5":
        return float(poisson_pred.get("OVER_UNDER_1_5", {}).get("OVER_1_5", 0.72))
    if market_code == "OVER_2_5":
        return float(poisson_pred.get("OVER_UNDER_2_5", {}).get("OVER_2_5", 0.52))
    if market_code == "UNDER_2_5":
        return float(poisson_pred.get("OVER_UNDER_2_5", {}).get("UNDER_2_5", 0.48))
    if market_code == "OVER_3_5":
        return float(poisson_pred.get("OVER_UNDER_3_5", {}).get("OVER_3_5", 0.28))
    if market_code == "BTTS":
        return float(poisson_pred.get("BTTS", {}).get("BTTS_YES", 0.52))
    return 0.50


def build_goal_market_feature_dict(
    base_features: Dict[str, Any],
    poisson_pred: Dict[str, Any],
    market_code: str,
) -> Dict[str, float]:
    out = {col: float(base_features.get(col, 0.0) or 0.0) for col in FEATURE_COLUMNS}
    lam_h = float(poisson_pred.get("expected_goals_home", 1.45))
    lam_a = float(poisson_pred.get("expected_goals_away", 1.15))
    out["poisson_lambda_home"] = round(lam_h, 4)
    out["poisson_lambda_away"] = round(lam_a, 4)
    out["poisson_lambda_total"] = round(lam_h + lam_a, 4)
    out["poisson_market_prob"] = round(extract_poisson_market_prob(poisson_pred, market_code), 5)
    return out


def generate_temporal_oof_poisson_predictions(
    train_records: List[HistoricalMatchRecord],
    features_by_match_id: Dict[int, Dict[str, Any]],
    xi: float = 0.0015,
    rho: float = -0.13,
    use_competition_hfa: bool = True,
    n_iterations: int = 8,
    min_fit_matches: int = 20,
    expanding_step_size: int = 80,
) -> Tuple[Dict[int, Dict[str, Any]], Dict[str, Any]]:
    """Genera las predicciones de Poisson/Dixon-Coles para todo el conjunto de entrenamiento (T_train)
    mediante Out-of-Fold Temporal con ventana expansiva estricta.

    Garantiza matemáticamente que para CADA partido objetivo `m` en `train_records`:
      1. El modelo Poisson que genera sus variables (`poisson_market_prob`, `poisson_lambda_total`,
         `poisson_lambda_home`, `poisson_lambda_away`) se entrena EXCLUSIVAMENTE con partidos `r`
         tales que `r.kickoff_utc < m.kickoff_utc`.
      2. Ningún resultado contemporáneo o futuro interviene jamás en la predicción de `m` (`0` leakage).
    """
    sorted_train = sorted(train_records, key=lambda r: (r.kickoff_utc, r.match_id))

    # Agrupar por kickoff_utc exacto para que partidos simultáneos jamás se filtren entre sí
    groups_by_ts: List[Tuple[Any, List[HistoricalMatchRecord]]] = []
    for r in sorted_train:
        if not groups_by_ts or groups_by_ts[-1][0] != r.kickoff_utc:
            groups_by_ts.append((r.kickoff_utc, [r]))
        else:
            groups_by_ts[-1][1].append(r)

    oof_preds: Dict[int, Dict[str, Any]] = {}
    prior_matches: List[HistoricalMatchRecord] = []
    last_fitted_count: int = -1
    current_model: Optional[PoissonDixonColesModel] = None

    temporal_violations = 0
    self_inclusion_violations = 0
    folds_executed = 0
    audit_trace_samples: List[Dict[str, Any]] = []

    for ts_idx, (current_ts, group_matches) in enumerate(groups_by_ts):
        # Determinar si corresponde re-ajustar el modelo de ventana expansiva con prior_matches
        n_prior = len(prior_matches)
        if n_prior == 0:
            current_model = PoissonDixonColesModel(
                rho=rho, xi=xi, n_iterations=n_iterations, use_competition_hfa=use_competition_hfa
            )
        elif n_prior < expanding_step_size:
            # En la fase inicial de calentamiento, actualizar cada vez que se superen múltiplos de min_fit_matches
            if n_prior >= min_fit_matches and (last_fitted_count < min_fit_matches or (n_prior - last_fitted_count) >= min_fit_matches):
                current_model = PoissonDixonColesModel(
                    rho=rho, xi=xi, n_iterations=n_iterations, use_competition_hfa=use_competition_hfa
                ).fit(prior_matches)
                last_fitted_count = n_prior
                folds_executed += 1
        else:
            if (n_prior - last_fitted_count) >= expanding_step_size or current_model is None or not current_model.is_fitted:
                current_model = PoissonDixonColesModel(
                    rho=rho, xi=xi, n_iterations=n_iterations, use_competition_hfa=use_competition_hfa
                ).fit(prior_matches)
                last_fitted_count = n_prior
                folds_executed += 1

        if current_model is None:
            current_model = PoissonDixonColesModel(
                rho=rho, xi=xi, n_iterations=n_iterations, use_competition_hfa=use_competition_hfa
            )

        # Verificación estricta de invariante temporal sobre todos los partidos usados en el ajuste actual
        max_prior_ts = prior_matches[-1].kickoff_utc if prior_matches else None
        for m in group_matches:
            if max_prior_ts is not None and not (max_prior_ts < m.kickoff_utc):
                temporal_violations += 1
            if any(p.match_id == m.match_id for p in prior_matches):
                self_inclusion_violations += 1

            ft = features_by_match_id[m.match_id]
            oof_preds[m.match_id] = current_model.predict_full_distribution(
                m.home_team_id,
                m.away_team_id,
                ft,
                competition_id=m.competition_id,
            )

            if len(audit_trace_samples) < 5 or ts_idx in (len(groups_by_ts) // 2, len(groups_by_ts) - 1):
                if len(audit_trace_samples) < 8:
                    audit_trace_samples.append(
                        {
                            "match_id": m.match_id,
                            "target_kickoff_utc": m.kickoff_utc.isoformat(),
                            "prior_matches_available": n_prior,
                            "model_fitted_on_count": max(0, last_fitted_count),
                            "max_prior_kickoff_utc": max_prior_ts.isoformat() if max_prior_ts else None,
                            "strictly_past_only": True if (max_prior_ts is None or max_prior_ts < m.kickoff_utc) else False,
                        }
                    )

        # Solo después de predecir todo el grupo simultáneo `current_ts`, incorporar `group_matches` al historial
        prior_matches.extend(group_matches)

    audit_summary = {
        "total_train_matches": len(sorted_train),
        "total_predictions_generated": len(oof_preds),
        "distinct_timestamps_in_train": len(groups_by_ts),
        "expanding_window_refits_count": folds_executed,
        "expanding_step_size": expanding_step_size,
        "min_fit_matches": min_fit_matches,
        "temporal_violations_count": temporal_violations,
        "self_inclusion_violations_count": self_inclusion_violations,
        "strictly_past_only_guaranteed": (temporal_violations == 0 and self_inclusion_violations == 0),
        "sample_trace": audit_trace_samples,
    }
    return oof_preds, audit_summary


class CalibratedGoalMarketRF:
    """Modelo Random Forest binario calibrado temporalmente para mercados específicos de goles (Over/Under y BTTS)."""

    def __init__(
        self,
        market_code: str,
        n_estimators: int = 200,
        max_depth: int = 4,
        min_samples_leaf: int = 25,
        calibration_method: str = "sigmoid",
        use_temporal_cv: bool = True,
        random_state: int = 42,
    ):
        self.market_code = market_code
        self.n_estimators = n_estimators
        self.max_depth = max_depth
        self.min_samples_leaf = min_samples_leaf
        self.calibration_method = calibration_method
        self.use_temporal_cv = use_temporal_cv
        self.random_state = random_state

        self.base_rf = RandomForestClassifier(
            n_estimators=n_estimators,
            max_depth=max_depth,
            min_samples_leaf=min_samples_leaf,
            n_jobs=1,
            random_state=random_state,
        )
        self.calibrated_model: Any = None
        self.feature_importances: Dict[str, float] = {}
        self.is_fitted: bool = False

    @staticmethod
    def _dict_to_vector(feature_dict: Dict[str, Any]) -> np.ndarray:
        return np.array(
            [float(feature_dict.get(col, 0.0) or 0.0) for col in GOAL_MARKET_FEATURE_COLUMNS],
            dtype=np.float64,
        )

    def fit(self, X_train: List[Dict[str, Any]], y_train: List[int]) -> "CalibratedGoalMarketRF":
        X_tr = np.vstack([self._dict_to_vector(d) for d in X_train])
        y_tr = np.asarray(y_train, dtype=int)

        self.base_rf.fit(X_tr, y_tr)
        importances = self.base_rf.feature_importances_
        self.feature_importances = {
            col: round(float(imp), 4)
            for col, imp in sorted(zip(GOAL_MARKET_FEATURE_COLUMNS, importances), key=lambda x: x[1], reverse=True)
        }

        if len(X_train) >= 60 and len(set(y_train)) == 2:
            try:
                cv_splitter = TimeSeriesSplit(n_splits=3) if self.use_temporal_cv else 3
                cal = CalibratedClassifierCV(
                    estimator=clone(self.base_rf),
                    method=self.calibration_method,
                    cv=cv_splitter,
                )
                cal.fit(X_tr, y_tr)
                self.calibrated_model = cal
            except Exception:
                self.calibrated_model = self.base_rf
        else:
            self.calibrated_model = self.base_rf

        self.is_fitted = True
        return self

    def predict_proba_pos(self, X_list: List[Dict[str, Any]]) -> np.ndarray:
        if not X_list:
            return np.zeros(0, dtype=np.float64)
        if not self.is_fitted or self.calibrated_model is None:
            return np.full(len(X_list), 0.50, dtype=np.float64)
        mat = np.vstack([self._dict_to_vector(d) for d in X_list])
        probs = self.calibrated_model.predict_proba(mat)[:, 1]
        return np.clip(probs, 0.01, 0.99)


class CalibratedGoalMarketXGB:
    """Modelo XGBoost binario calibrado temporalmente con regularización estricta para mercados específicos de goles."""

    def __init__(
        self,
        market_code: str,
        n_estimators: int = 80,
        max_depth: int = 3,
        learning_rate: float = 0.03,
        min_child_weight: float = 15.0,
        reg_lambda: float = 5.0,
        calibration_method: str = "sigmoid",
        use_temporal_cv: bool = True,
        random_state: int = 42,
    ):
        self.market_code = market_code
        self.n_estimators = n_estimators
        self.max_depth = max_depth
        self.learning_rate = learning_rate
        self.min_child_weight = min_child_weight
        self.reg_lambda = reg_lambda
        self.calibration_method = calibration_method
        self.use_temporal_cv = use_temporal_cv
        self.random_state = random_state

        self.base_xgb = XGBClassifier(
            n_estimators=n_estimators,
            max_depth=max_depth,
            learning_rate=learning_rate,
            min_child_weight=min_child_weight,
            subsample=0.75,
            colsample_bytree=0.75,
            reg_alpha=1.0,
            reg_lambda=reg_lambda,
            objective="binary:logistic",
            eval_metric="logloss",
            n_jobs=1,
            random_state=random_state,
            verbosity=0,
        )
        self.calibrated_model: Any = None
        self.feature_importances: Dict[str, float] = {}
        self.is_fitted: bool = False

    @staticmethod
    def _dict_to_vector(feature_dict: Dict[str, Any]) -> np.ndarray:
        return np.array(
            [float(feature_dict.get(col, 0.0) or 0.0) for col in GOAL_MARKET_FEATURE_COLUMNS],
            dtype=np.float64,
        )

    def fit(self, X_train: List[Dict[str, Any]], y_train: List[int]) -> "CalibratedGoalMarketXGB":
        X_tr = np.vstack([self._dict_to_vector(d) for d in X_train])
        y_tr = np.asarray(y_train, dtype=int)

        self.base_xgb.fit(X_tr, y_tr)
        importances = self.base_xgb.feature_importances_
        self.feature_importances = {
            col: round(float(imp), 4)
            for col, imp in sorted(zip(GOAL_MARKET_FEATURE_COLUMNS, importances), key=lambda x: x[1], reverse=True)
        }

        if len(X_train) >= 60 and len(set(y_train)) == 2:
            try:
                cv_splitter = TimeSeriesSplit(n_splits=3) if self.use_temporal_cv else 3
                cal = CalibratedClassifierCV(
                    estimator=clone(self.base_xgb),
                    method=self.calibration_method,
                    cv=cv_splitter,
                )
                cal.fit(X_tr, y_tr)
                self.calibrated_model = cal
            except Exception:
                self.calibrated_model = self.base_xgb
        else:
            self.calibrated_model = self.base_xgb

        self.is_fitted = True
        return self

    def predict_proba_pos(self, X_list: List[Dict[str, Any]]) -> np.ndarray:
        if not X_list:
            return np.zeros(0, dtype=np.float64)
        if not self.is_fitted or self.calibrated_model is None:
            return np.full(len(X_list), 0.50, dtype=np.float64)
        mat = np.vstack([self._dict_to_vector(d) for d in X_list])
        probs = self.calibrated_model.predict_proba(mat)[:, 1]
        return np.clip(probs, 0.01, 0.99)


class GoalMarketSimplexEnsemble:
    """Optimiza en el símplex los pesos de combinación (Poisson, RF_Goals, XGB_Goals) para cada mercado de goles.
    Cumple la regla de parsimonia científica: no fuerza ensambles cuando Poisson/Dixon-Coles ofrece
    resultados mejores o equivalentes.
    """

    def __init__(self, market_code: str, prune_threshold: float = 0.01):
        self.market_code = market_code
        self.prune_threshold = prune_threshold
        self.weights: Dict[str, float] = {"POISSON": 1.0, "RF_GOALS": 0.0, "XGB_GOALS": 0.0}
        self.primary_model_code: str = "POISSON"
        self.selection_rationale: str = ""

    def optimize_weights(
        self,
        val_probs_by_model: Dict[str, np.ndarray],
        y_val_binary: List[int],
        baseline_brier: float,
        min_val_brier_gain_over_poisson: float = 0.0005,
    ) -> Dict[str, float]:
        y_arr = np.asarray(y_val_binary, dtype=np.float64)
        val_brier = {
            code: float(np.mean((probs - y_arr) ** 2))
            for code, probs in val_probs_by_model.items()
        }
        eligible = [c for c, b in val_brier.items() if b <= baseline_brier]
        if not eligible:
            eligible = [min(val_brier, key=val_brier.get)]

        vecs = [val_probs_by_model[c] for c in eligible]
        m_cnt = len(eligible)

        def obj(w: np.ndarray) -> float:
            blend = np.zeros_like(y_arr)
            for idx, weight in enumerate(w):
                blend += weight * vecs[idx]
            return float(np.mean((blend - y_arr) ** 2))

        w0 = np.ones(m_cnt, dtype=np.float64) / m_cnt
        bounds = [(0.0, 1.0) for _ in range(m_cnt)]
        constraints = {"type": "eq", "fun": lambda w: float(np.sum(w) - 1.0)}
        res = minimize(obj, w0, method="SLSQP", bounds=bounds, constraints=constraints)
        raw_w = res.x if res.success else w0

        pruned = {
            code: (float(raw_w[i]) if float(raw_w[i]) >= self.prune_threshold else 0.0)
            for i, code in enumerate(eligible)
        }
        tot = sum(pruned.values())
        if tot <= 0:
            best_c = min(eligible, key=lambda c: val_brier[c])
            pruned[best_c] = 1.0
            tot = 1.0

        candidate_weights = {
            code: round(pruned.get(code, 0.0) / tot, 4)
            for code in val_probs_by_model.keys()
        }

        # Evaluar si la combinación mejora significativamente sobre Poisson en Validación
        blend_val = np.zeros_like(y_arr)
        for code, arr in val_probs_by_model.items():
            blend_val += candidate_weights.get(code, 0.0) * arr
        blend_brier = float(np.mean((blend_val - y_arr) ** 2))
        poisson_brier = val_brier.get("POISSON", blend_brier)

        if (poisson_brier - blend_brier) < min_val_brier_gain_over_poisson:
            # Regla de parsimonia: no forzar ensamble si Poisson es equivalente o superior
            self.weights = candidate_weights
            self.primary_model_code = "POISSON"
            self.selection_rationale = (
                f"Poisson/Dixon-Coles retenido como modelo principal (Val Brier Poisson={poisson_brier:.5f} vs "
                f"Blend={blend_brier:.5f}, ganancia={poisson_brier - blend_brier:+.5f} < umbral {min_val_brier_gain_over_poisson})."
            )
        else:
            self.weights = candidate_weights
            self.primary_model_code = "ENSEMBLE_GOALS"
            self.selection_rationale = (
                f"Ensamble OOF supera el umbral en Validación (Val Brier Poisson={poisson_brier:.5f} vs "
                f"Blend={blend_brier:.5f}, ganancia={poisson_brier - blend_brier:+.5f})."
            )
        return self.weights

    def predict_proba_pos(self, probs_by_model: Dict[str, np.ndarray]) -> np.ndarray:
        first_arr = next(iter(probs_by_model.values()))
        blend = np.zeros_like(first_arr, dtype=np.float64)
        w_sum = 0.0
        for code, arr in probs_by_model.items():
            w = self.weights.get(code, 0.0)
            if w > 0:
                blend += w * arr
                w_sum += w
        if w_sum <= 0:
            return first_arr
        return np.clip(blend / w_sum, 0.01, 0.99)
