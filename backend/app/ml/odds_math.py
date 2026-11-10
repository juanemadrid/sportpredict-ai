from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple
import numpy as np


@dataclass
class SelectionValuation:
    selection_code: str
    prob_estimated: float
    fair_decimal_odds: float
    available_decimal_odds: Optional[float]
    bookmaker_margin: Optional[float]
    market_implied_prob_fair: Optional[float]
    prob_edge_diff: Optional[float]
    expected_value: Optional[float]
    uncertainty_score: float
    uncertainty_label: str


def calculate_fair_odds(probability: float) -> float:
    """Calcula la cuota decimal justa a partir de la probabilidad estimada."""
    p = float(np.clip(probability, 1e-4, 0.9999))
    return round(1.0 / p, 3)


def remove_bookmaker_margin(odds_by_selection: Dict[str, float]) -> Tuple[Dict[str, float], float]:
    """Retira el margen de la casa de apuestas (overround) para obtener las probabilidades
    implícitas justas del mercado.
    Retorna: (probabilidades_justas_mercado, margen_overround)
    """
    valid = {k: float(v) for k, v in odds_by_selection.items() if v is not None and v > 1.0}
    if not valid:
        return {}, 0.0
    raw_implied = {k: 1.0 / v for k, v in valid.items()}
    total_implied = sum(raw_implied.values())
    overround = max(0.0, total_implied - 1.0)
    fair_probs = {k: round(val / total_implied, 5) for k, val in raw_implied.items()}
    return fair_probs, round(overround, 5)


def compute_expected_value(prob_estimated: float, decimal_odds: Optional[float]) -> Optional[float]:
    """Fórmula oficial Sección 6: EV = (probabilidad * cuota decimal) - 1"""
    if decimal_odds is None or decimal_odds <= 1.0:
        return None
    ev = (float(prob_estimated) * float(decimal_odds)) - 1.0
    return round(ev, 5)


def estimate_uncertainty(
    model_probabilities: List[float],
    historical_matches_count: int,
) -> Tuple[float, str]:
    """Cuantifica el nivel de incertidumbre combinando:
    1. Dispersión epistémica entre los distintos modelos independientes (Poisson, Elo, RF, XGBoost).
    2. Penalización por tamaño de muestra histórico de los equipos.
    Nunca confunde confianza/acuerdo entre modelos con certeza de victoria.
    """
    if len(model_probabilities) > 1:
        dispersion = float(np.std(model_probabilities))
    else:
        dispersion = 0.06

    sample_penalty = max(0.0, (20 - min(historical_matches_count, 20)) / 20.0) * 0.12
    score = float(np.clip(dispersion * 1.8 + sample_penalty, 0.01, 0.99))
    score = round(score, 4)

    if score <= 0.075:
        label = "BAJA"
    elif score <= 0.15:
        label = "MEDIA"
    else:
        label = "ALTA"
    return score, label


def evaluate_market_selections(
    probs_by_selection: Dict[str, float],
    market_odds_by_selection: Optional[Dict[str, float]],
    per_model_probs_by_selection: Dict[str, List[float]],
    min_team_matches: int,
) -> Dict[str, SelectionValuation]:
    """Evalúa todas las selecciones de un mercado calculando cuota justa, margen del operador,
    probabilidad implícita limpia, diferencia (edge), EV e incertidumbre.
    """
    fair_market_probs: Dict[str, float] = {}
    margin: Optional[float] = None
    if market_odds_by_selection:
        fair_market_probs, margin = remove_bookmaker_margin(market_odds_by_selection)

    results: Dict[str, SelectionValuation] = {}
    for sel, prob in probs_by_selection.items():
        p = round(float(np.clip(prob, 0.001, 0.999)), 5)
        fair_odds = calculate_fair_odds(p)
        avail_odds = market_odds_by_selection.get(sel) if market_odds_by_selection else None
        mkt_fair_p = fair_market_probs.get(sel) if fair_market_probs else None
        edge = round(p - mkt_fair_p, 5) if mkt_fair_p is not None else None
        ev = compute_expected_value(p, avail_odds)
        model_list = per_model_probs_by_selection.get(sel, [p])
        unc_score, unc_label = estimate_uncertainty(model_list, min_team_matches)

        results[sel] = SelectionValuation(
            selection_code=sel,
            prob_estimated=p,
            fair_decimal_odds=fair_odds,
            available_decimal_odds=avail_odds,
            bookmaker_margin=margin if avail_odds is not None else None,
            market_implied_prob_fair=mkt_fair_p,
            prob_edge_diff=edge,
            expected_value=ev,
            uncertainty_score=unc_score,
            uncertainty_label=unc_label,
        )
    return results
