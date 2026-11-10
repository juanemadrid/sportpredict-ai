from typing import Any, Dict, List, Optional
import numpy as np
from scipy.stats import norm
from sklearn.metrics import accuracy_score, f1_score, log_loss


def compute_per_match_multiclass_brier(y_true_indices: List[int], prob_matrix: np.ndarray) -> np.ndarray:
    """Devuelve el vector (N,) de errores cuadráticos Brier por partido para 1X2."""
    n = len(y_true_indices)
    if n == 0:
        return np.zeros(0, dtype=np.float64)
    one_hot = np.zeros((n, 3), dtype=np.float64)
    for idx, y in enumerate(y_true_indices):
        one_hot[idx, y] = 1.0
    return np.sum((prob_matrix - one_hot) ** 2, axis=1)


def compute_per_match_binary_brier(y_true_binary: List[int], prob_pos: np.ndarray) -> np.ndarray:
    """Devuelve el vector (N,) de errores cuadráticos Brier binarios (p_i - y_i)^2 por partido."""
    y_arr = np.asarray(y_true_binary, dtype=np.float64)
    p_arr = np.asarray(prob_pos, dtype=np.float64)
    return (p_arr - y_arr) ** 2


def paired_moving_block_bootstrap_test(
    losses_a: np.ndarray,
    losses_b: np.ndarray,
    model_a_name: str,
    model_b_name: str,
    block_size: int = 20,
    n_boot: int = 1000,
    seed: int = 42,
) -> Dict[str, Any]:
    """Prueba de significancia estadística pareada mediante Moving Block Bootstrap (MBB)
    por bloques temporales contiguos.

    Evalúa d_t = L_t(A) - L_t(B), donde L_t es el Brier Score del partido t.
    Un valor mean_diff < 0 indica que el Modelo A tiene menor (mejor) Brier Score que el Modelo B.
    """
    d = np.asarray(losses_a, dtype=np.float64) - np.asarray(losses_b, dtype=np.float64)
    n = len(d)
    if n < 4:
        return {
            "model_a": model_a_name,
            "model_b": model_b_name,
            "n_matches": n,
            "brier_a": round(float(np.mean(losses_a)) if n else 0.0, 5),
            "brier_b": round(float(np.mean(losses_b)) if n else 0.0, 5),
            "mean_diff_brier": 0.0,
            "ci_95_diff": [0.0, 0.0],
            "boot_std_error": 0.0,
            "z_statistic": 0.0,
            "p_value_two_sided": 1.0,
            "statistically_significant_95": False,
            "verdict": "Muestra insuficiente para prueba de bloques.",
        }

    eff_block = max(1, min(block_size, n // 2))
    n_blocks = int(np.ceil(n / eff_block))
    max_start = n - eff_block

    rng = np.random.default_rng(seed)
    boot_means = np.empty(n_boot, dtype=np.float64)

    # Pre-construir suma por bloque móvil para velocidad O(N + B * n_blocks)
    csum = np.concatenate([[0.0], np.cumsum(d)])
    block_sums = csum[eff_block:] - csum[:-eff_block]  # longitud max_start + 1

    for b in range(n_boot):
        starts = rng.integers(0, max_start + 1, size=n_blocks)
        sampled_sum = float(np.sum(block_sums[starts]))
        sampled_len = n_blocks * eff_block
        boot_means[b] = sampled_sum / sampled_len

    obs_diff = float(np.mean(d))
    brier_a = float(np.mean(losses_a))
    brier_b = float(np.mean(losses_b))
    ci_low = float(np.percentile(boot_means, 2.5))
    ci_high = float(np.percentile(boot_means, 97.5))
    se_boot = float(np.std(boot_means, ddof=1))

    if se_boot > 1e-12:
        z_stat = obs_diff / se_boot
        p_val_norm = float(2.0 * (1.0 - norm.cdf(abs(z_stat))))
    else:
        z_stat = 0.0
        p_val_norm = 1.0

    # P-valor empírico bilateral centrado bajo H0
    centered_boot = boot_means - np.mean(boot_means)
    p_val_emp = float(np.mean(np.abs(centered_boot) >= abs(obs_diff)))
    p_val = max(min(p_val_emp, 1.0), p_val_norm) if p_val_emp == 0.0 else p_val_emp

    sig_95 = bool((ci_high < 0.0) or (ci_low > 0.0))

    if sig_95 and obs_diff < 0.0:
        verdict = (
            f"Superioridad estadísticamente significativa de {model_a_name} sobre {model_b_name} al 95% "
            f"(Δ Brier = {obs_diff:+.5f}, IC95% [{ci_low:+.5f}, {ci_high:+.5f}], p = {p_val:.4f})."
        )
    elif sig_95 and obs_diff > 0.0:
        verdict = (
            f"{model_a_name} es significativamente PEOR que {model_b_name} al 95% "
            f"(Δ Brier = {obs_diff:+.5f}, IC95% [{ci_low:+.5f}, {ci_high:+.5f}], p = {p_val:.4f})."
        )
    else:
        verdict = (
            f"Diferencia NO estadísticamente significativa al 95% entre {model_a_name} y {model_b_name} "
            f"(Δ Brier = {obs_diff:+.5f}, IC95% [{ci_low:+.5f}, {ci_high:+.5f}], p = {p_val:.4f}; el 0 está dentro del IC)."
        )

    return {
        "model_a": model_a_name,
        "model_b": model_b_name,
        "n_matches": n,
        "block_size": eff_block,
        "n_bootstrap": n_boot,
        "brier_a": round(brier_a, 5),
        "brier_b": round(brier_b, 5),
        "mean_diff_brier": round(obs_diff, 5),
        "ci_95_diff": [round(ci_low, 5), round(ci_high, 5)],
        "boot_std_error": round(se_boot, 5),
        "z_statistic": round(z_stat, 4),
        "p_value_two_sided": round(p_val, 4),
        "statistically_significant_95": sig_95,
        "verdict": verdict,
    }


def compute_binary_ece(y_true_bin: np.ndarray, prob_pos: np.ndarray, n_bins: int = 5) -> float:
    n = len(y_true_bin)
    if n == 0:
        return 0.0
    edges = np.linspace(0.0, 1.0, n_bins + 1)
    ece = 0.0
    for b in range(n_bins):
        low, high = edges[b], edges[b + 1]
        mask = (prob_pos >= low) & (prob_pos <= high) if b == n_bins - 1 else (prob_pos >= low) & (prob_pos < high)
        cnt = int(np.sum(mask))
        if cnt > 0:
            ece += (cnt / n) * abs(float(np.mean(prob_pos[mask])) - float(np.mean(y_true_bin[mask])))
    return round(float(ece), 5)


def evaluate_binary_market(
    y_true_binary: List[int],
    prob_pos: np.ndarray,
    baseline_rate: float,
    poisson_prob_pos: Optional[np.ndarray] = None,
    model_name: str = "MODEL",
    market_code: str = "OVER_2_5",
) -> Dict[str, Any]:
    """Evalúa científicamente un mercado binario de goles (Over 1.5, Over 2.5, Under 2.5, Over 3.5, BTTS)."""
    n = len(y_true_binary)
    if n == 0:
        return {}

    y_arr = np.asarray(y_true_binary, dtype=int)
    p_arr = np.clip(np.asarray(prob_pos, dtype=np.float64), 1e-5, 1.0 - 1e-5)
    preds = (p_arr >= 0.5).astype(int)

    losses_model = compute_per_match_binary_brier(y_true_binary, p_arr)
    brier = float(np.mean(losses_model))
    brier_se = float(np.std(losses_model, ddof=1) / np.sqrt(n))

    base_arr = np.full(n, np.clip(baseline_rate, 1e-5, 1.0 - 1e-5), dtype=np.float64)
    losses_base = compute_per_match_binary_brier(y_true_binary, base_arr)
    base_brier = float(np.mean(losses_base))

    ll = float(log_loss(y_arr, p_arr, labels=[0, 1]))
    ece = compute_binary_ece(y_arr, p_arr, n_bins=5)
    acc = float(accuracy_score(y_arr, preds))
    f1 = float(f1_score(y_arr, preds, zero_division=0))

    vs_baseline = paired_moving_block_bootstrap_test(
        losses_a=losses_model,
        losses_b=losses_base,
        model_a_name=f"{model_name} ({market_code})",
        model_b_name=f"Baseline ({market_code})",
        block_size=20,
        n_boot=1000,
    )

    vs_poisson = None
    if poisson_prob_pos is not None:
        losses_pois = compute_per_match_binary_brier(y_true_binary, np.clip(poisson_prob_pos, 1e-5, 1.0 - 1e-5))
        vs_poisson = paired_moving_block_bootstrap_test(
            losses_a=losses_model,
            losses_b=losses_pois,
            model_a_name=f"{model_name} ({market_code})",
            model_b_name=f"Poisson ({market_code})",
            block_size=20,
            n_boot=1000,
        )

    return {
        "market_code": market_code,
        "model_name": model_name,
        "n_matches": n,
        "empirical_positive_rate": round(float(np.mean(y_arr)), 4),
        "mean_predicted_prob": round(float(np.mean(p_arr)), 4),
        "brier_score": round(brier, 5),
        "brier_ci_95": [round(max(0.0, brier - 1.96 * brier_se), 5), round(brier + 1.96 * brier_se, 5)],
        "baseline_brier_score": round(base_brier, 5),
        "log_loss": round(ll, 5),
        "ece_calibration": ece,
        "accuracy": round(acc, 4),
        "f1_score": round(f1, 4),
        "test_vs_baseline": vs_baseline,
        "test_vs_poisson": vs_poisson,
    }
