"""Motor matemático de comparación contra cuotas reales del mercado, normalización de margen,
Valor Esperado (EV), Closing Line Value (CLV) y evaluación de diferencias estadísticas (Fase 4).

Reglas científicas:
1. No inventa ni imputa cuotas faltantes (si una cuota no existe, devuelve None).
2. No confunde una diferencia puntual de probabilidad (p_model > p_market_fair) ni un EV > 0
   en un partido aislado con una ventaja rentable demostrada.
3. Calcula Closing Line Value (CLV) exclusivamente cuando existe una cuota de cierre real
   capturada antes del inicio del encuentro.
"""

from dataclasses import asdict, dataclass
import math
from typing import Any, Dict, List, Optional, Tuple
import numpy as np


SUPPORTED_PHASE4_MARKETS: Dict[str, Dict[str, Any]] = {
    "1X2": {
        "display_name": "Resultado Final (1X2)",
        "selections": ("HOME", "DRAW", "AWAY"),
        "primary_model_v3_1": "ENSEMBLE",
        "co_optimal_model_v3_1": "RANDOM_FOREST",
        "tier_level": 1,
    },
    "OVER_1_5": {
        "display_name": "Más / Menos de 1.5 Goles (Over 1.5)",
        "selections": ("OVER", "UNDER"),
        "primary_model_v3_1": "POISSON",
        "tier_level": 1,
    },
    "OVER_2_5": {
        "display_name": "Más / Menos de 2.5 Goles (Over 2.5)",
        "selections": ("OVER", "UNDER"),
        "primary_model_v3_1": "POISSON",
        "tier_level": 1,
    },
    "UNDER_2_5": {
        "display_name": "Menos de 2.5 Goles (Under 2.5)",
        "selections": ("UNDER", "OVER"),
        "primary_model_v3_1": "POISSON",
        "tier_level": 1,
    },
    "OVER_3_5": {
        "display_name": "Más / Menos de 3.5 Goles (Over 3.5)",
        "selections": ("OVER", "UNDER"),
        "primary_model_v3_1": "POISSON",
        "tier_level": 2,
    },
    "BTTS": {
        "display_name": "Ambos Equipos Marcan (BTTS Sí / No)",
        "selections": ("YES", "NO"),
        "primary_model_v3_1": "POISSON",
        "tier_level": 1,
    },
}


@dataclass
class MarketSelectionComparison:
    market_code: str
    selection_code: str
    model_version: str
    model_code: str
    prob_model: float
    fair_model_odds: float
    opening_odds: Optional[float]
    current_odds: Optional[float]
    closing_odds: Optional[float]
    bookmaker_name: Optional[str]
    captured_at_utc: Optional[str]
    implied_prob_raw: Optional[float]
    bookmaker_overround: Optional[float]
    implied_prob_fair_proportional: Optional[float]
    implied_prob_fair_power: Optional[float]
    prob_diff_vs_market_prop: Optional[float]
    prob_diff_vs_market_power: Optional[float]
    expected_value: Optional[float]
    clv_odds_pct: Optional[float]
    clv_fair_prob_pct: Optional[float]
    epistemic_std: float
    edge_z_score: Optional[float]
    edge_classification: str
    edge_explanation: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def decimal_odds_to_raw_implied_prob(decimal_odds: Optional[float]) -> Optional[float]:
    """Convierte una cuota decimal europea O > 1.0 en probabilidad implícita bruta q_raw = 1 / O."""
    if decimal_odds is None:
        return None
    val = float(decimal_odds)
    if not np.isfinite(val) or val <= 1.0:
        raise ValueError(f"La cuota decimal debe ser finita y estrictamente mayor que 1.0; recibido: {decimal_odds}")
    return round(1.0 / val, 6)


def normalize_market_margin_proportional(
    odds_by_selection: Dict[str, Optional[float]],
    expected_selections: Optional[Tuple[str, ...]] = None,
) -> Tuple[Dict[str, float], Dict[str, float], Optional[float]]:
    """Normalización proporcional (multiplicativa) del margen de la casa de apuestas.
    Requiere que todas las selecciones mutuamente excluyentes y exhaustivas del mercado estén presentes
    para poder calcular el overround real sin imputar cuotas faltantes.
    Retorna: (raw_implied_probs, fair_implied_probs, overround_margin)
    """
    valid: Dict[str, float] = {}
    for k, v in odds_by_selection.items():
        if v is not None:
            fv = float(v)
            if fv <= 1.0 or not np.isfinite(fv):
                raise ValueError(f"Cuota inválida para selección {k}: {v}")
            valid[k] = fv

    if not valid:
        return {}, {}, None

    raw_probs = {k: round(1.0 / v, 6) for k, v in valid.items()}

    # Solo podemos normalizar el margen del mercado completo si están todas sus ramas exhaustivas
    if expected_selections is not None and not all(s in valid for s in expected_selections):
        return raw_probs, {}, None

    total_raw = sum(raw_probs.values())
    if total_raw <= 0.0:
        return raw_probs, {}, None

    overround = round(max(0.0, total_raw - 1.0), 6)
    fair_probs = {k: round(val / total_raw, 6) for k, val in raw_probs.items()}
    return raw_probs, fair_probs, overround


def normalize_market_margin_power(
    odds_by_selection: Dict[str, Optional[float]],
    expected_selections: Optional[Tuple[str, ...]] = None,
) -> Dict[str, float]:
    """Eliminación de margen mediante el método de Potencia (Power Method, Clarke et al. 2017),
    que ajusta por el sesgo favorito-longshot hallando el exponente k >= 1 tal que sum(q_raw_i ^ k) = 1.
    Si el mercado está incompleto o sin overround positivo, cae al método proporcional.
    """
    raw_probs, prop_probs, overround = normalize_market_margin_proportional(
        odds_by_selection, expected_selections=expected_selections
    )
    if not prop_probs:
        return {}
    if overround is None or overround <= 1e-6:
        return prop_probs

    q_vals = np.array([1.0 / float(odds_by_selection[s]) for s in prop_probs.keys()], dtype=np.float64)
    # Búsqueda binaria monótona para k en [1.0, 20.0] tal que sum(q_i ** k) == 1.0
    low, high = 1.0, 20.0
    for _ in range(60):
        mid = 0.5 * (low + high)
        s_val = float(np.sum(np.power(q_vals, mid)))
        if s_val > 1.0:
            low = mid
        else:
            high = mid
    k_opt = 0.5 * (low + high)
    powered = np.power(q_vals, k_opt)
    powered = powered / np.sum(powered)
    return {sel: round(float(val), 6) for sel, val in zip(prop_probs.keys(), powered)}


def calculate_expected_value(prob_model: float, decimal_odds: Optional[float]) -> Optional[float]:
    """Calcula el Valor Esperado (EV) por unidad apostada: EV = (p_model * cuota_decimal) - 1.0."""
    if decimal_odds is None:
        return None
    odds_f = float(decimal_odds)
    if odds_f <= 1.0 or not np.isfinite(odds_f):
        return None
    p = float(np.clip(prob_model, 1e-6, 1.0 - 1e-6))
    return round((p * odds_f) - 1.0, 6)


def calculate_closing_line_value(
    observed_odds: Optional[float],
    closing_odds: Optional[float],
    closing_fair_prob: Optional[float] = None,
) -> Tuple[Optional[float], Optional[float]]:
    """Calcula el Closing Line Value (CLV) cuando existen cuotas de cierre comparables:
    1. clv_odds_pct = (observed_odds / closing_odds) - 1.0
       Mide cuánto mejor fue la cuota capturada respecto a la cuota de cierre del operador.
    2. clv_fair_prob_pct = (observed_odds * closing_fair_prob) - 1.0
       Mide el rendimiento esperado de la cuota capturada evaluada contra la probabilidad implícita
       limpia de margen al cierre del mercado (estándar institucional de eficiencia de mercado).
    Si no existe cuota de cierre, retorna (None, None) sin inventar valores.
    """
    if observed_odds is None or closing_odds is None:
        return None, None
    obs_f = float(observed_odds)
    cls_f = float(closing_odds)
    if obs_f <= 1.0 or cls_f <= 1.0:
        return None, None

    clv_odds = round((obs_f / cls_f) - 1.0, 6)
    clv_fair: Optional[float] = None
    if closing_fair_prob is not None and 0.0 < float(closing_fair_prob) < 1.0:
        clv_fair = round((obs_f * float(closing_fair_prob)) - 1.0, 6)
    return clv_odds, clv_fair


def classify_statistical_difference(
    prob_model: float,
    implied_prob_fair: Optional[float],
    expected_value: Optional[float],
    epistemic_std: float,
    min_ev_threshold: float = 0.02,
    min_z_threshold: float = 1.645,
) -> Tuple[Optional[float], str, str]:
    """Clasifica rigurosamente la diferencia entre la probabilidad del modelo y la del mercado,
    evitando confundir cualquier diferencia positiva con una ventaja rentable demostrada.

    Categorías posibles:
    - NO_ODDS_AVAILABLE: No existe cuota real observada para esta selección.
    - NO_STATISTICAL_EDGE: EV <= 0 o la probabilidad del modelo es inferior/igual a la del mercado.
    - POSITIVE_EV_WITHIN_NOISE: EV > 0 pero la diferencia (p_model - q_fair) no supera la dispersión
      epistémica entre modelos (z < 1.645) o EV < 2.0%; diferencia indistinguible del ruido muestral.
    - CANDIDATE_STATISTICAL_EDGE: EV >= 2.0% y diferencia (p_model - q_fair) >= 1.645 * std_epistémica.
      Nota: Incluso en este estado, requiere validación en muestra prospectiva antes de afirmar rentabilidad.
    """
    if implied_prob_fair is None or expected_value is None:
        return (
            None,
            "NO_ODDS_AVAILABLE",
            "Sin cuota real observada para contrastar contra el mercado.",
        )

    diff = float(prob_model) - float(implied_prob_fair)
    eff_std = max(float(epistemic_std), 0.015)
    z_score = round(diff / eff_std, 4)

    if expected_value <= 0.0 or diff <= 0.0:
        return (
            z_score,
            "NO_STATISTICAL_EDGE",
            f"Sin ventaja frente al mercado (Δp = {diff:+.4f}, EV = {expected_value*100:+.2f}% ≤ 0).",
        )

    if expected_value < min_ev_threshold or z_score < min_z_threshold:
        return (
            z_score,
            "POSITIVE_EV_WITHIN_NOISE",
            f"Diferencia positiva (Δp = {diff:+.4f}, EV = {expected_value*100:+.2f}%), pero dentro de la banda de incertidumbre del modelo (z = {z_score:.2f} < {min_z_threshold:.2f}); NO constituye ventaja estadística demostrada.",
        )

    return (
        z_score,
        "CANDIDATE_STATISTICAL_EDGE",
        f"Diferencia estadística candidata (Δp = {diff:+.4f}, EV = {expected_value*100:+.2f}%, z = {z_score:.2f}); hipótesis sujeta a verificación en muestra prospectiva.",
    )


def compare_market_probabilities_and_odds(
    market_code: str,
    model_version: str,
    model_code: str,
    probs_by_selection: Dict[str, float],
    current_odds_by_selection: Optional[Dict[str, Optional[float]]] = None,
    opening_odds_by_selection: Optional[Dict[str, Optional[float]]] = None,
    closing_odds_by_selection: Optional[Dict[str, Optional[float]]] = None,
    per_model_probs_by_selection: Optional[Dict[str, List[float]]] = None,
    bookmaker_name: Optional[str] = None,
    captured_at_utc: Optional[str] = None,
) -> Dict[str, MarketSelectionComparison]:
    """Ejecuta la comparación matemática completa de un mercado (1X2, OVER_1_5, OVER_2_5,
    UNDER_2_5, OVER_3_5, BTTS) entre SPORTPREDICT AI (v3.1.0) y las cuotas observadas.
    """
    mkt_meta = SUPPORTED_PHASE4_MARKETS.get(market_code, {})
    expected_sels: Optional[Tuple[str, ...]] = mkt_meta.get("selections")

    curr_odds = current_odds_by_selection or {}
    open_odds = opening_odds_by_selection or {}
    close_odds = closing_odds_by_selection or {}

    raw_curr, fair_prop_curr, overround_curr = normalize_market_margin_proportional(
        curr_odds, expected_selections=expected_sels
    )
    fair_power_curr = normalize_market_margin_power(
        curr_odds, expected_selections=expected_sels
    )
    _, fair_prop_close, _ = normalize_market_margin_proportional(
        close_odds, expected_selections=expected_sels
    )

    out: Dict[str, MarketSelectionComparison] = {}
    for sel, p_raw in probs_by_selection.items():
        p_model = round(float(np.clip(p_raw, 1e-4, 0.9999)), 6)
        fair_m_odds = round(1.0 / p_model, 4)

        o_open = open_odds.get(sel)
        o_curr = curr_odds.get(sel)
        o_close = close_odds.get(sel)

        q_raw = raw_curr.get(sel)
        q_prop = fair_prop_curr.get(sel)
        q_pow = fair_power_curr.get(sel)
        q_close_fair = fair_prop_close.get(sel)

        diff_prop = round(p_model - q_prop, 6) if q_prop is not None else None
        diff_pow = round(p_model - q_pow, 6) if q_pow is not None else None
        ev_val = calculate_expected_value(p_model, o_curr)
        clv_odds, clv_fair = calculate_closing_line_value(o_curr, o_close, q_close_fair)

        cand_list = (per_model_probs_by_selection or {}).get(sel, [p_model])
        epistemic_std = round(float(np.std(cand_list)) if len(cand_list) > 1 else 0.025, 5)

        z_val, edge_cls, edge_exp = classify_statistical_difference(
            prob_model=p_model,
            implied_prob_fair=q_prop,
            expected_value=ev_val,
            epistemic_std=epistemic_std,
        )

        out[sel] = MarketSelectionComparison(
            market_code=market_code,
            selection_code=sel,
            model_version=model_version,
            model_code=model_code,
            prob_model=p_model,
            fair_model_odds=fair_m_odds,
            opening_odds=float(o_open) if o_open is not None else None,
            current_odds=float(o_curr) if o_curr is not None else None,
            closing_odds=float(o_close) if o_close is not None else None,
            bookmaker_name=bookmaker_name if o_curr is not None else None,
            captured_at_utc=captured_at_utc if o_curr is not None else None,
            implied_prob_raw=q_raw,
            bookmaker_overround=overround_curr if o_curr is not None else None,
            implied_prob_fair_proportional=q_prop,
            implied_prob_fair_power=q_pow,
            prob_diff_vs_market_prop=diff_prop,
            prob_diff_vs_market_power=diff_pow,
            expected_value=ev_val,
            clv_odds_pct=clv_odds,
            clv_fair_prob_pct=clv_fair,
            epistemic_std=epistemic_std,
            edge_z_score=z_val,
            edge_classification=edge_cls,
            edge_explanation=edge_exp,
        )
    return out


def required_prospective_sample_size_for_edge(
    average_decimal_odds: float = 2.00,
    expected_yield_edge: float = 0.03,
    alpha_one_sided: float = 0.05,
    power: float = 0.80,
) -> Dict[str, Any]:
    """Calcula el tamaño de muestra prospectivo mínimo N_min necesario para demostrar estadísticamente
    que una ventaja (yield esperado > 0) no es producto del azar, bajo aproximación normal de la varianza
    de retornos unitarios: Var(R) ≈ O - 1 + EV - EV^2 ≈ O - 1.
    """
    odds_f = max(1.05, float(average_decimal_odds))
    edge_f = max(0.005, float(expected_yield_edge))
    # Cuantiles normales estándar para alpha=0.05 (unilateral 1.6449) y power=0.80 (0.8416)
    z_alpha = 1.644854 if abs(alpha_one_sided - 0.05) < 1e-4 else 1.959964
    z_beta = 0.841621 if abs(power - 0.80) < 1e-4 else 1.281552

    # Varianza del retorno por apuesta unitaria cuando p * O = 1 + edge
    p_win = min(0.99, (1.0 + edge_f) / odds_f)
    var_return = p_win * ((odds_f - 1.0) ** 2) + (1.0 - p_win) * (1.0 ** 2) - (edge_f ** 2)

    n_for_significance_only = int(math.ceil(((z_alpha ** 2) * var_return) / (edge_f ** 2)))
    n_for_80pct_power = int(math.ceil((((z_alpha + z_beta) ** 2) * var_return) / (edge_f ** 2)))

    return {
        "average_decimal_odds": round(odds_f, 3),
        "assumed_true_yield_edge": round(edge_f, 4),
        "return_variance_per_bet": round(var_return, 4),
        "min_bets_for_95pct_significance_z1645": n_for_significance_only,
        "min_bets_for_80pct_power_at_95pct": n_for_80pct_power,
        "scientific_note": (
            f"Para una cuota media de {odds_f:.2f} y una ventaja real hipotética del {edge_f*100:.1f}%, "
            f"se requieren al menos {n_for_significance_only} predicciones prospectivas verificadas para rechazar "
            f"la hipótesis nula de azar al 95% (z >= 1.645), y {n_for_80pct_power} para alcanzar una potencia estadística del 80%."
        ),
    }
