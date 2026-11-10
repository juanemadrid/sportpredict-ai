from typing import Any, Dict, List, Optional
import numpy as np
from sklearn.metrics import accuracy_score, f1_score, log_loss, precision_score, recall_score

from app.ml.odds_math import remove_bookmaker_margin


OUTCOME_TO_INDEX = {"H": 0, "D": 1, "A": 2}
SELECTION_KEYS = ["HOME", "DRAW", "AWAY"]


def multiclass_brier_score(y_true_indices: List[int], prob_matrix: np.ndarray) -> float:
    """Calcula el Brier Score multiclase promedio: (1/N) * sum_i sum_k (p_ik - y_ik)^2"""
    n = len(y_true_indices)
    if n == 0:
        return 0.0
    one_hot = np.zeros((n, 3), dtype=np.float64)
    for idx, y in enumerate(y_true_indices):
        one_hot[idx, y] = 1.0
    sq_err = np.sum((prob_matrix - one_hot) ** 2, axis=1)
    return round(float(np.mean(sq_err)), 5)


def compute_95_confidence_intervals(
    y_true_indices: List[int],
    prob_matrix: np.ndarray,
) -> Dict[str, List[float]]:
    """Calcula intervalos de confianza al 95% para Brier Score, Log Loss y Accuracy
    a partir de las contribuciones individuales por partido en el conjunto de prueba.
    """
    n = len(y_true_indices)
    if n < 2:
        return {
            "brier_ci_95": [0.0, 0.0],
            "log_loss_ci_95": [0.0, 0.0],
            "accuracy_ci_95": [0.0, 0.0],
        }

    one_hot = np.zeros((n, 3), dtype=np.float64)
    for idx, y in enumerate(y_true_indices):
        one_hot[idx, y] = 1.0

    # Contribución individual Brier por partido
    brier_per_match = np.sum((prob_matrix - one_hot) ** 2, axis=1)
    brier_mean = float(np.mean(brier_per_match))
    brier_se = float(np.std(brier_per_match, ddof=1) / np.sqrt(n))

    # Contribución individual Log Loss por partido
    true_probs = np.clip([prob_matrix[i, y_true_indices[i]] for i in range(n)], 1e-6, 0.999999)
    ll_per_match = -np.log(true_probs)
    ll_mean = float(np.mean(ll_per_match))
    ll_se = float(np.std(ll_per_match, ddof=1) / np.sqrt(n))

    # Contribución individual Accuracy (Bernoulli)
    preds = np.argmax(prob_matrix, axis=1)
    hits = (preds == np.array(y_true_indices)).astype(np.float64)
    acc_mean = float(np.mean(hits))
    acc_se = float(np.std(hits, ddof=1) / np.sqrt(n))

    return {
        "brier_ci_95": [round(max(0.0, brier_mean - 1.96 * brier_se), 5), round(brier_mean + 1.96 * brier_se, 5)],
        "log_loss_ci_95": [round(max(0.0, ll_mean - 1.96 * ll_se), 5), round(ll_mean + 1.96 * ll_se, 5)],
        "accuracy_ci_95": [round(max(0.0, acc_mean - 1.96 * acc_se), 4), round(min(1.0, acc_mean + 1.96 * acc_se), 4)],
    }


def compute_calibration_curve_and_ece(
    y_true_indices: List[int],
    prob_matrix: np.ndarray,
    n_bins: int = 5,
) -> tuple[float, List[Dict[str, Any]]]:
    """Calcula Expected Calibration Error (ECE) y los puntos de la curva de calibración."""
    n = len(y_true_indices)
    if n == 0:
        return 0.0, []

    one_hot = np.zeros((n, 3), dtype=np.float64)
    for idx, y in enumerate(y_true_indices):
        one_hot[idx, y] = 1.0

    flat_probs = prob_matrix.flatten()
    flat_true = one_hot.flatten()
    bin_edges = np.linspace(0.0, 1.0, n_bins + 1)

    bins_report: List[Dict[str, Any]] = []
    ece = 0.0
    total_pts = len(flat_probs)

    for b in range(n_bins):
        low, high = bin_edges[b], bin_edges[b + 1]
        if b == n_bins - 1:
            mask = (flat_probs >= low) & (flat_probs <= high)
        else:
            mask = (flat_probs >= low) & (flat_probs < high)
        count = int(np.sum(mask))
        if count > 0:
            mean_pred = float(np.mean(flat_probs[mask]))
            emp_freq = float(np.mean(flat_true[mask]))
            gap = abs(mean_pred - emp_freq)
            ece += (count / total_pts) * gap
            bins_report.append(
                {
                    "bin_range": f"{low:.2f}-{high:.2f}",
                    "count": count,
                    "mean_predicted_prob": round(mean_pred, 4),
                    "empirical_win_rate": round(emp_freq, 4),
                    "calibration_gap": round(gap, 4),
                }
            )
        else:
            bins_report.append(
                {
                    "bin_range": f"{low:.2f}-{high:.2f}",
                    "count": 0,
                    "mean_predicted_prob": round((low + high) / 2, 4),
                    "empirical_win_rate": 0.0,
                    "calibration_gap": 0.0,
                }
            )
    return round(float(ece), 5), bins_report


def evaluate_predictions_scientifically(
    records: List[Dict[str, Any]],
    baseline_probs: Dict[str, float],
    ev_threshold: float = 0.03,
) -> Dict[str, Any]:
    """Evalúa un conjunto de pronósticos emitidos estrictamente pre-partido frente a resultados reales."""
    if not records:
        return {
            "total_predictions": 0,
            "accuracy": 0.0,
            "precision_macro": 0.0,
            "recall_macro": 0.0,
            "f1_macro": 0.0,
            "brier_score": 0.6667,
            "log_loss": 1.0986,
            "ece_calibration": 0.0,
            "baseline_brier_score": 0.6667,
            "market_brier_score": None,
            "simulated_bets_count": 0,
            "simulated_roi_pct": 0.0,
            "simulated_yield_pct": 0.0,
            "confidence_intervals_95": {},
            "calibration_curve": [],
            "by_competition": {},
        }

    y_true = [OUTCOME_TO_INDEX[r["outcome_1x2"]] for r in records]
    prob_matrix = np.array(
        [[r["probs"]["HOME"], r["probs"]["DRAW"], r["probs"]["AWAY"]] for r in records],
        dtype=np.float64,
    )
    prob_matrix = np.clip(prob_matrix, 1e-5, 0.9999)
    prob_matrix = prob_matrix / prob_matrix.sum(axis=1, keepdims=True)
    y_pred = np.argmax(prob_matrix, axis=1).tolist()

    acc = round(float(accuracy_score(y_true, y_pred)), 4)
    prec = round(float(precision_score(y_true, y_pred, average="macro", zero_division=0)), 4)
    rec = round(float(recall_score(y_true, y_pred, average="macro", zero_division=0)), 4)
    f1 = round(float(f1_score(y_true, y_pred, average="macro", zero_division=0)), 4)
    brier = multiclass_brier_score(y_true, prob_matrix)
    ll = round(float(log_loss(y_true, prob_matrix, labels=[0, 1, 2])), 5)
    ece, cal_curve = compute_calibration_curve_and_ece(y_true, prob_matrix)
    ci_95 = compute_95_confidence_intervals(y_true, prob_matrix)

    # Benchmark 1: Modelo de referencia sencillo (frecuencia histórica empírica del set de entrenamiento)
    base_matrix = np.tile(
        np.array([baseline_probs["HOME"], baseline_probs["DRAW"], baseline_probs["AWAY"]], dtype=np.float64),
        (len(records), 1),
    )
    baseline_brier = multiclass_brier_score(y_true, base_matrix)

    # Benchmark 2: Probabilidades implícitas del mercado sin margen (cuando existen cuotas)
    mkt_rows = []
    mkt_y = []
    for idx, r in enumerate(records):
        odds = r.get("odds")
        if odds and all(odds.get(k, 0) > 1.0 for k in SELECTION_KEYS):
            fair_mkt, _ = remove_bookmaker_margin(odds)
            mkt_rows.append([fair_mkt["HOME"], fair_mkt["DRAW"], fair_mkt["AWAY"]])
            mkt_y.append(y_true[idx])
    market_brier: Optional[float] = None
    if mkt_rows:
        market_brier = multiclass_brier_score(mkt_y, np.array(mkt_rows, dtype=np.float64))

    # Simulación de Backtesting financiero (solo cuando existen cuotas reales/válidas asociadas al partido)
    bets_placed = 0
    net_profit_units = 0.0
    for idx, r in enumerate(records):
        odds = r.get("odds")
        if not odds:
            continue
        best_sel = None
        best_ev = -1.0
        for sel_idx, sel_key in enumerate(SELECTION_KEYS):
            p = float(prob_matrix[idx, sel_idx])
            o = float(odds.get(sel_key, 0.0))
            if o > 1.0:
                ev = (p * o) - 1.0
                if ev > ev_threshold and ev > best_ev:
                    best_ev = ev
                    best_sel = (sel_idx, o)
        if best_sel is not None:
            bets_placed += 1
            sel_idx, taken_odds = best_sel
            if y_true[idx] == sel_idx:
                net_profit_units += taken_odds - 1.0
            else:
                net_profit_units -= 1.0

    yield_pct = round((net_profit_units / bets_placed) * 100.0, 2) if bets_placed > 0 else 0.0
    roi_pct = yield_pct

    # Desglose por competición
    by_comp: Dict[str, List[int]] = {}
    for idx, r in enumerate(records):
        cname = r.get("competition_name", "General")
        by_comp.setdefault(cname, []).append(idx)

    comp_summary: Dict[str, Any] = {}
    for cname, indices in by_comp.items():
        sub_y = [y_true[i] for i in indices]
        sub_p = prob_matrix[indices]
        sub_pred = [y_pred[i] for i in indices]
        comp_summary[cname] = {
            "matches": len(indices),
            "accuracy": round(float(accuracy_score(sub_y, sub_pred)), 4),
            "brier_score": multiclass_brier_score(sub_y, sub_p),
            "log_loss": round(float(log_loss(sub_y, sub_p, labels=[0, 1, 2])), 5),
        }

    return {
        "total_predictions": len(records),
        "accuracy": acc,
        "precision_macro": prec,
        "recall_macro": rec,
        "f1_macro": f1,
        "brier_score": brier,
        "log_loss": ll,
        "ece_calibration": ece,
        "baseline_brier_score": baseline_brier,
        "market_brier_score": market_brier,
        "simulated_bets_count": bets_placed,
        "simulated_roi_pct": roi_pct,
        "simulated_yield_pct": yield_pct,
        "confidence_intervals_95": ci_95,
        "calibration_curve": cal_curve,
        "by_competition": comp_summary,
    }
