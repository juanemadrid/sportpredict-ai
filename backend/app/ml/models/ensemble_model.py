from typing import Dict, List
import numpy as np
from scipy.optimize import minimize


class TemporalWeightedEnsembleModel:
    """MODELO E: ENSAMBLE PONDERADO MEDIANTE OPTIMIZACIÓN CONVEXA EN VALIDACIÓN TEMPORAL.
    - Evalúa las matrices de probabilidad fuera de muestra de cada modelo candidato
      (Poisson, Elo, Random Forest, XGBoost) sobre la ventana de validación temporal (T_val).
    - Descarta inmediatamente cualquier modelo cuyo Brier Score en validación sea peor que el
      modelo base de referencia (Baseline).
    - Resuelve un problema de optimización convexa en el símplex (SLSQP: w_m >= 0, sum(w_m) = 1)
      minimizando directamente el Brier Score del conjunto combinado en T_val.
    - NO fuerza pesos positivos para modelos que no aportan valor marginal real: si el peso
      óptimo de un modelo es < 0.01, se poda a 0.0000.
    """

    def __init__(self, prune_threshold: float = 0.01):
        self.prune_threshold = prune_threshold
        self.weights: Dict[str, float] = {
            "POISSON": 0.40,
            "ELO": 0.30,
            "RANDOM_FOREST": 0.15,
            "XGBOOST": 0.15,
        }
        self.excluded_models: Dict[str, str] = {}

    def optimize_simplex_weights(
        self,
        val_prob_matrices: Dict[str, np.ndarray],
        y_val_indices: List[int],
        val_brier_by_model: Dict[str, float],
        baseline_brier: float,
    ) -> Dict[str, float]:
        self.excluded_models.clear()
        n = len(y_val_indices)
        if n == 0 or not val_prob_matrices:
            return self.weights

        one_hot = np.zeros((n, 3), dtype=np.float64)
        for idx, y in enumerate(y_val_indices):
            one_hot[idx, y] = 1.0

        eligible_codes: List[str] = []
        for m_code, brier_val in val_brier_by_model.items():
            if brier_val > baseline_brier:
                self.excluded_models[m_code] = (
                    f"Peso 0.0: Brier en validación ({brier_val:.4f}) no supera al Baseline ({baseline_brier:.4f})."
                )
            else:
                eligible_codes.append(m_code)

        if not eligible_codes:
            best_code = min(val_brier_by_model, key=val_brier_by_model.get)
            eligible_codes = [best_code]

        m_count = len(eligible_codes)
        mats = [val_prob_matrices[c] for c in eligible_codes]

        def objective_brier(w: np.ndarray) -> float:
            blend = np.zeros_like(mats[0])
            for idx, weight in enumerate(w):
                blend += weight * mats[idx]
            sq_err = np.sum((blend - one_hot) ** 2, axis=1)
            return float(np.mean(sq_err))

        w0 = np.ones(m_count, dtype=np.float64) / m_count
        bounds = [(0.0, 1.0) for _ in range(m_count)]
        constraints = {"type": "eq", "fun": lambda w: float(np.sum(w) - 1.0)}

        res = minimize(
            objective_brier,
            w0,
            method="SLSQP",
            bounds=bounds,
            constraints=constraints,
            options={"ftol": 1e-9, "maxiter": 300},
        )
        raw_weights = res.x if res.success else w0

        # Podar modelos cuyo peso óptimo sea irrelevante (< prune_threshold) para no forzar pesos positivos
        pruned_weights = {}
        for idx, code in enumerate(eligible_codes):
            w_val = float(raw_weights[idx])
            if w_val < self.prune_threshold:
                pruned_weights[code] = 0.0
                self.excluded_models[code] = (
                    f"Peso 0.0: No aporta reducción marginal de Brier Score en el ensamble sobre T_val (Brier individual={val_brier_by_model[code]:.4f})."
                )
            else:
                pruned_weights[code] = w_val

        total_w = sum(pruned_weights.values())
        if total_w <= 0:
            best_c = min(eligible_codes, key=lambda c: val_brier_by_model[c])
            pruned_weights[best_c] = 1.0
            total_w = 1.0

        self.weights = {
            code: round(pruned_weights.get(code, 0.0) / total_w, 4)
            for code in val_brier_by_model.keys()
        }
        return self.weights

    def optimize_weights_from_validation(
        self,
        val_brier_by_model: Dict[str, float],
        val_logloss_by_model: Dict[str, float],
        baseline_brier: float,
    ) -> Dict[str, float]:
        """Método de respaldo si solo se dispone de escalares de validación."""
        self.excluded_models.clear()
        eligible = {k: v for k, v in val_brier_by_model.items() if v <= baseline_brier}
        if not eligible:
            best_k = min(val_brier_by_model, key=val_brier_by_model.get)
            eligible = {best_k: val_brier_by_model[best_k]}
        best_b = min(eligible.values())
        scores = {k: float(np.exp(-15.0 * (v - best_b))) for k, v in eligible.items()}
        tot = sum(scores.values())
        self.weights = {k: round(scores.get(k, 0.0) / tot, 4) for k in val_brier_by_model}
        return self.weights

    def combine_1x2(self, model_predictions_1x2: Dict[str, Dict[str, float]]) -> Dict[str, float]:
        combined = {"HOME": 0.0, "DRAW": 0.0, "AWAY": 0.0}
        active_weight_sum = 0.0

        for model_code, probs in model_predictions_1x2.items():
            w = self.weights.get(model_code, 0.0)
            if w <= 0:
                continue
            for sel in ("HOME", "DRAW", "AWAY"):
                combined[sel] += w * float(probs.get(sel, 0.0))
            active_weight_sum += w

        if active_weight_sum <= 0:
            n = max(1, len(model_predictions_1x2))
            for probs in model_predictions_1x2.values():
                for sel in ("HOME", "DRAW", "AWAY"):
                    combined[sel] += float(probs.get(sel, 0.0)) / n
        else:
            for sel in ("HOME", "DRAW", "AWAY"):
                combined[sel] /= active_weight_sum

        total = sum(combined.values())
        return {k: round(v / total, 5) for k, v in combined.items()}
