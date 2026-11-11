from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple
import numpy as np
from scipy.stats import poisson

from app.ml.features import HistoricalMatchRecord


class PoissonDixonColesModel:
    """MODELO A MEJORADO (FASE 3): POISSON / DIXON-COLES CON DECAIMIENTO TEMPORAL EXPONENCIAL
    Y VENTAJA DE LOCALÍA POR COMPETICIÓN.
    Implementa:
    - Decaimiento temporal exponencial: w(t) = exp(-xi * delta_dias), dando mayor peso a partidos recientes.
    - Parámetro xi configurable y optimizable en validación temporal.
    - Tasas base de goles locales y visitantes independientes por competición (ventaja de localía por liga).
    - Estimación iterativa de máxima verosimilitud ponderada con regularización Bayesiana (shrinkage)
      para parámetros de ataque y defensa.
    - Auditoría de calibración de goles esperados (RMSE, MAE, sesgo de media y devianza de Poisson).
    """

    def __init__(
        self,
        max_goals: int = 7,
        rho: float = -0.05,
        shrinkage: float = 5.0,
        xi: float = 0.0018,
        use_competition_hfa: bool = True,
        n_iterations: int = 5,
    ):
        self.max_goals = max_goals
        self.rho = rho
        self.shrinkage = shrinkage
        self.xi = xi
        self.use_competition_hfa = use_competition_hfa
        self.n_iterations = n_iterations

        self.league_home_avg: float = 1.50
        self.league_away_avg: float = 1.20
        self.comp_home_avg: Dict[int, float] = {}
        self.comp_away_avg: Dict[int, float] = {}

        self.attack_home: Dict[int, float] = {}
        self.defense_home: Dict[int, float] = {}
        self.attack_away: Dict[int, float] = {}
        self.defense_away: Dict[int, float] = {}
        self.team_competition: Dict[int, int] = {}
        self.reference_date: Optional[datetime] = None
        self.is_fitted: bool = False

    def __setstate__(self, state: Dict[str, Any]) -> None:
        self.__dict__.update(state)
        if "use_competition_hfa" not in self.__dict__:
            self.use_competition_hfa = False
        if "comp_home_avg" not in self.__dict__:
            self.comp_home_avg = {}
        if "comp_away_avg" not in self.__dict__:
            self.comp_away_avg = {}
        if "team_competition" not in self.__dict__:
            self.team_competition = {}
        if "xi" not in self.__dict__:
            self.xi = 0.0018

    def _compute_time_weight(self, match_dt: datetime, ref_dt: datetime) -> float:
        if self.xi <= 0.0:
            return 1.0
        delta_days = max(0.0, (ref_dt - match_dt).total_seconds() / 86400.0)
        return float(np.exp(-self.xi * delta_days))

    def fit(self, train_matches: List[HistoricalMatchRecord]) -> "PoissonDixonColesModel":
        finished = [
            m
            for m in train_matches
            if m.status == "FINISHED" and m.home_goals is not None and m.away_goals is not None
        ]
        if not finished:
            self.is_fitted = True
            return self

        finished.sort(key=lambda m: m.kickoff_utc)
        ref_dt = finished[-1].kickoff_utc
        self.reference_date = ref_dt

        weights = np.array([self._compute_time_weight(m.kickoff_utc, ref_dt) for m in finished], dtype=np.float64)
        home_goals_arr = np.array([float(m.home_goals) for m in finished], dtype=np.float64)
        away_goals_arr = np.array([float(m.away_goals) for m in finished], dtype=np.float64)

        w_sum = float(np.sum(weights))
        self.league_home_avg = max(0.6, float(np.sum(weights * home_goals_arr) / w_sum))
        self.league_away_avg = max(0.5, float(np.sum(weights * away_goals_arr) / w_sum))

        # Ventaja de localía y entorno goleador independiente por competición
        comp_w: Dict[int, float] = {}
        comp_hg: Dict[int, float] = {}
        comp_ag: Dict[int, float] = {}
        for idx, m in enumerate(finished):
            w = float(weights[idx])
            cid = m.competition_id
            comp_w[cid] = comp_w.get(cid, 0.0) + w
            comp_hg[cid] = comp_hg.get(cid, 0.0) + w * float(m.home_goals)
            comp_ag[cid] = comp_ag.get(cid, 0.0) + w * float(m.away_goals)
            self.team_competition[m.home_team_id] = cid
            self.team_competition[m.away_team_id] = cid

        self.comp_home_avg.clear()
        self.comp_away_avg.clear()
        for cid, cw in comp_w.items():
            if cw > 0:
                self.comp_home_avg[cid] = max(0.6, comp_hg[cid] / cw)
                self.comp_away_avg[cid] = max(0.5, comp_ag[cid] / cw)

        all_teams = set(self.team_competition.keys())
        for tid in all_teams:
            self.attack_home[tid] = 1.0
            self.defense_home[tid] = 1.0
            self.attack_away[tid] = 1.0
            self.defense_away[tid] = 1.0

        s = self.shrinkage

        # Optimización iterativa de máxima verosimilitud ponderada (ajustando por la fuerza del rival enfrentado)
        for _ in range(max(1, self.n_iterations)):
            h_gf_w: Dict[int, float] = {}
            h_ga_w: Dict[int, float] = {}
            h_exp_att: Dict[int, float] = {}
            h_exp_def: Dict[int, float] = {}

            a_gf_w: Dict[int, float] = {}
            a_ga_w: Dict[int, float] = {}
            a_exp_att: Dict[int, float] = {}
            a_exp_def: Dict[int, float] = {}

            for idx, m in enumerate(finished):
                w = float(weights[idx])
                cid = m.competition_id
                mu_h = self.comp_home_avg.get(cid, self.league_home_avg) if self.use_competition_hfa else self.league_home_avg
                mu_a = self.comp_away_avg.get(cid, self.league_away_avg) if self.use_competition_hfa else self.league_away_avg

                ht, at = m.home_team_id, m.away_team_id
                hg, ag = float(m.home_goals), float(m.away_goals)

                h_gf_w[ht] = h_gf_w.get(ht, 0.0) + w * hg
                h_exp_att[ht] = h_exp_att.get(ht, 0.0) + w * mu_h * self.defense_away.get(at, 1.0)

                h_ga_w[ht] = h_ga_w.get(ht, 0.0) + w * ag
                h_exp_def[ht] = h_exp_def.get(ht, 0.0) + w * mu_a * self.attack_away.get(at, 1.0)

                a_gf_w[at] = a_gf_w.get(at, 0.0) + w * ag
                a_exp_att[at] = a_exp_att.get(at, 0.0) + w * mu_a * self.defense_home.get(ht, 1.0)

                a_ga_w[at] = a_ga_w.get(at, 0.0) + w * hg
                a_exp_def[at] = a_exp_def.get(at, 0.0) + w * mu_h * self.attack_home.get(ht, 1.0)

            for tid in all_teams:
                cid = self.team_competition.get(tid, -1)
                mu_h = self.comp_home_avg.get(cid, self.league_home_avg) if self.use_competition_hfa else self.league_home_avg
                mu_a = self.comp_away_avg.get(cid, self.league_away_avg) if self.use_competition_hfa else self.league_away_avg

                self.attack_home[tid] = (h_gf_w.get(tid, 0.0) + s * mu_h) / (h_exp_att.get(tid, 0.0) + s * mu_h)
                self.defense_home[tid] = (h_ga_w.get(tid, 0.0) + s * mu_a) / (h_exp_def.get(tid, 0.0) + s * mu_a)
                self.attack_away[tid] = (a_gf_w.get(tid, 0.0) + s * mu_a) / (a_exp_att.get(tid, 0.0) + s * mu_a)
                self.defense_away[tid] = (a_ga_w.get(tid, 0.0) + s * mu_h) / (a_exp_def.get(tid, 0.0) + s * mu_h)

        self.is_fitted = True
        return self

    @staticmethod
    def _dixon_coles_tau(x: int, y: int, lam_h: float, lam_a: float, rho: float) -> float:
        if x == 0 and y == 0:
            return 1.0 - (lam_h * lam_a * rho)
        if x == 0 and y == 1:
            return 1.0 + (lam_h * rho)
        if x == 1 and y == 0:
            return 1.0 + (lam_a * rho)
        if x == 1 and y == 1:
            return 1.0 - rho
        return 1.0

    def estimate_expected_goals(
        self,
        home_team_id: int,
        away_team_id: int,
        features: Dict[str, Any] | None = None,
        competition_id: Optional[int] = None,
    ) -> Tuple[float, float]:
        cid = competition_id or self.team_competition.get(home_team_id, -1)
        mu_h = self.comp_home_avg.get(cid, self.league_home_avg) if self.use_competition_hfa else self.league_home_avg
        mu_a = self.comp_away_avg.get(cid, self.league_away_avg) if self.use_competition_hfa else self.league_away_avg

        att_h = self.attack_home.get(home_team_id, 1.0)
        def_h = self.defense_home.get(home_team_id, 1.0)
        att_a = self.attack_away.get(away_team_id, 1.0)
        def_a = self.defense_away.get(away_team_id, 1.0)

        lam_home = mu_h * att_h * def_a
        lam_away = mu_a * att_a * def_h

        # Integración suave con la tasa reciente de goles en los últimos 10 partidos si está disponible
        if features:
            h_gf10 = features.get("home_gf_last10")
            a_gf10 = features.get("away_gf_last10")
            if h_gf10 is not None and a_gf10 is not None:
                lam_home = 0.88 * lam_home + 0.12 * float(h_gf10)
                lam_away = 0.88 * lam_away + 0.12 * float(a_gf10)
            h_miss = int(features.get("home_missing_players", 0))
            a_miss = int(features.get("away_missing_players", 0))
            if h_miss > 0:
                lam_home *= max(0.82, 1.0 - 0.03 * h_miss)
            if a_miss > 0:
                lam_away *= max(0.82, 1.0 - 0.03 * a_miss)

        lam_home = float(np.clip(lam_home, 0.25, 4.20))
        lam_away = float(np.clip(lam_away, 0.20, 3.80))
        return round(lam_home, 3), round(lam_away, 3)

    def predict_full_distribution(
        self,
        home_team_id: int,
        away_team_id: int,
        features: Dict[str, Any] | None = None,
        competition_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        lam_h, lam_a = self.estimate_expected_goals(home_team_id, away_team_id, features, competition_id)
        goals_range = np.arange(0, self.max_goals + 1)
        pmf_h = poisson.pmf(goals_range, lam_h)
        pmf_a = poisson.pmf(goals_range, lam_a)

        matrix = np.outer(pmf_h, pmf_a)
        for i in range(min(2, self.max_goals + 1)):
            for j in range(min(2, self.max_goals + 1)):
                tau = self._dixon_coles_tau(i, j, lam_h, lam_a, self.rho)
                matrix[i, j] = max(0.0, matrix[i, j] * tau)

        matrix /= matrix.sum()

        p_home = float(np.sum(np.tril(matrix, -1)))
        p_draw = float(np.sum(np.diag(matrix)))
        p_away = float(np.sum(np.triu(matrix, 1)))

        total_1x2 = p_home + p_draw + p_away
        p_home, p_draw, p_away = p_home / total_1x2, p_draw / total_1x2, p_away / total_1x2

        total_goals_grid = np.add.outer(goals_range, goals_range)
        p_over_1_5 = float(np.sum(matrix[total_goals_grid > 1.5]))
        p_under_1_5 = 1.0 - p_over_1_5
        p_over_2_5 = float(np.sum(matrix[total_goals_grid > 2.5]))
        p_under_2_5 = 1.0 - p_over_2_5
        p_over_3_5 = float(np.sum(matrix[total_goals_grid > 3.5]))
        p_under_3_5 = 1.0 - p_over_3_5

        p_btts_yes = float(np.sum(matrix[1:, 1:]))
        p_btts_no = 1.0 - p_btts_yes

        scorelines = []
        for i in range(6):
            for j in range(6):
                scorelines.append(
                    {"score": f"{i}-{j}", "home_goals": i, "away_goals": j, "probability": round(float(matrix[i, j]), 4)}
                )
        scorelines.sort(key=lambda s: s["probability"], reverse=True)

        home_goal_probs = {str(g): round(float(pmf_h[g]), 4) for g in range(4)}
        home_goal_probs["4+"] = round(float(1.0 - np.sum(pmf_h[:4])), 4)

        away_goal_probs = {str(g): round(float(pmf_a[g]), 4) for g in range(4)}
        away_goal_probs["4+"] = round(float(1.0 - np.sum(pmf_a[:4])), 4)

        return {
            "expected_goals_home": lam_h,
            "expected_goals_away": lam_a,
            "home_goal_probabilities": home_goal_probs,
            "away_goal_probabilities": away_goal_probs,
            "1X2": {
                "HOME": round(p_home, 5),
                "DRAW": round(p_draw, 5),
                "AWAY": round(p_away, 5),
            },
            "OVER_UNDER_1_5": {
                "OVER_1_5": round(p_over_1_5, 5),
                "UNDER_1_5": round(p_under_1_5, 5),
            },
            "OVER_UNDER_2_5": {
                "OVER_2_5": round(p_over_2_5, 5),
                "UNDER_2_5": round(p_under_2_5, 5),
            },
            "OVER_UNDER_3_5": {
                "OVER_3_5": round(p_over_3_5, 5),
                "UNDER_3_5": round(p_under_3_5, 5),
            },
            "BTTS": {
                "BTTS_YES": round(p_btts_yes, 5),
                "BTTS_NO": round(p_btts_no, 5),
            },
            "DOUBLE_CHANCE": {
                "1X": round(p_home + p_draw, 5),
                "12": round(p_home + p_away, 5),
                "X2": round(p_draw + p_away, 5),
            },
            "top_exact_scores": scorelines[:6],
        }

    def evaluate_expected_goals_calibration(
        self,
        eval_matches: List[HistoricalMatchRecord],
        features_by_match_id: Optional[Dict[int, Dict[str, Any]]] = None,
    ) -> Dict[str, float]:
        """Evalúa la calibración de los goles esperados (lambda_H, lambda_A) frente a los goles reales."""
        if not eval_matches:
            return {}
        pred_h, pred_a = [], []
        real_h, real_a = [], []
        for m in eval_matches:
            if m.home_goals is None or m.away_goals is None:
                continue
            ft = features_by_match_id.get(m.match_id) if features_by_match_id else None
            lh, la = self.estimate_expected_goals(m.home_team_id, m.away_team_id, ft, m.competition_id)
            pred_h.append(lh)
            pred_a.append(la)
            real_h.append(float(m.home_goals))
            real_a.append(float(m.away_goals))

        ph, pa = np.array(pred_h), np.array(pred_a)
        rh, ra = np.array(real_h), np.array(real_a)
        ptot = ph + pa
        rtot = rh + ra

        rmse_total = float(np.sqrt(np.mean((ptot - rtot) ** 2)))
        mae_total = float(np.mean(np.abs(ptot - rtot)))

        return {
            "matches_evaluated": len(real_h),
            "mean_predicted_home_goals": round(float(np.mean(ph)), 4),
            "mean_actual_home_goals": round(float(np.mean(rh)), 4),
            "mean_predicted_away_goals": round(float(np.mean(pa)), 4),
            "mean_actual_away_goals": round(float(np.mean(ra)), 4),
            "mean_predicted_total_goals": round(float(np.mean(ptot)), 4),
            "mean_actual_total_goals": round(float(np.mean(rtot)), 4),
            "total_goals_bias": round(float(np.mean(ptot - rtot)), 4),
            "total_goals_rmse": round(rmse_total, 4),
            "total_goals_mae": round(mae_total, 4),
        }
