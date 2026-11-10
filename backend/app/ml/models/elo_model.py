from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple
import numpy as np

from app.ml.features import HistoricalMatchRecord


class DynamicEloModel:
    """MODELO B MEJORADO (FASE 3): ELO DINÁMICO CON VENTAJA DE LOCALÍA POR COMPETICIÓN,
    FACTOR K CONFIGURABLE Y REGRESIÓN A LA MEDIA ENTRE TEMPORADAS.
    """

    def __init__(
        self,
        base_rating: float = 1500.0,
        k_factor: float = 20.0,
        home_advantage: float = 58.0,
        draw_nu: float = 0.88,
        season_regression_theta: float = 0.18,
        use_competition_hfa: bool = True,
    ):
        self.base_rating = base_rating
        self.k_factor = k_factor
        self.home_advantage = home_advantage
        self.draw_nu = draw_nu
        self.season_regression_theta = season_regression_theta
        self.use_competition_hfa = use_competition_hfa

        self.comp_home_advantage: Dict[int, float] = {}
        self.comp_draw_nu: Dict[int, float] = {}
        self.ratings: Dict[int, float] = {}
        self.last_season_by_team: Dict[int, str] = {}
        self.history: Dict[int, List[Dict[str, Any]]] = {}

    def calibrate_competition_parameters(self, train_matches: List[HistoricalMatchRecord]) -> None:
        """Calibra la ventaja de localía (en puntos Elo) y el parámetro de empate (draw_nu)
        de forma independiente para cada competición exclusivamente sobre T_train.
        """
        finished = [
            m
            for m in train_matches
            if m.status == "FINISHED" and m.home_goals is not None and m.away_goals is not None
        ]
        if not finished:
            return

        # Calibración global
        total_n = len(finished)
        total_draws = sum(1 for m in finished if m.home_goals == m.away_goals)
        emp_draw = total_draws / total_n
        self.draw_nu = float(np.clip(2.0 * emp_draw / max(0.1, 1.0 - emp_draw), 0.55, 1.15))

        by_comp: Dict[int, List[HistoricalMatchRecord]] = {}
        for m in finished:
            by_comp.setdefault(m.competition_id, []).append(m)

        self.comp_home_advantage.clear()
        self.comp_draw_nu.clear()
        for cid, m_list in by_comp.items():
            if len(m_list) < 20:
                continue
            h_wins = sum(1 for m in m_list if m.home_goals > m.away_goals)
            draws = sum(1 for m in m_list if m.home_goals == m.away_goals)
            n_c = len(m_list)
            # Puntuación esperada local S_H = (Victorias_Local + 0.5 * Empates) / N
            s_home = (h_wins + 0.5 * draws) / n_c
            s_home = float(np.clip(s_home, 0.45, 0.70))
            # Inversa logística: HFA = -400 * log10(1/S_H - 1)
            hfa_c = float(-400.0 * np.log10((1.0 / s_home) - 1.0))
            self.comp_home_advantage[cid] = round(float(np.clip(hfa_c, 25.0, 95.0)), 2)

            d_rate = draws / n_c
            self.comp_draw_nu[cid] = float(np.clip(2.0 * d_rate / max(0.1, 1.0 - d_rate), 0.55, 1.15))

    def _apply_season_regression_if_needed(self, team_id: int, season: str) -> None:
        prev_season = self.last_season_by_team.get(team_id)
        if prev_season is not None and prev_season != season and self.season_regression_theta > 0.0:
            curr = self.ratings.get(team_id, self.base_rating)
            regressed = (1.0 - self.season_regression_theta) * curr + self.season_regression_theta * self.base_rating
            self.ratings[team_id] = round(float(regressed), 2)
        self.last_season_by_team[team_id] = season

    def get_rating(self, team_id: int, season: Optional[str] = None) -> float:
        if season is not None:
            self._apply_season_regression_if_needed(team_id, season)
        return round(self.ratings.get(team_id, self.base_rating), 2)

    def get_hfa(self, competition_id: Optional[int] = None) -> float:
        if self.use_competition_hfa and competition_id is not None and competition_id in self.comp_home_advantage:
            return self.comp_home_advantage[competition_id]
        return self.home_advantage

    def get_draw_nu(self, competition_id: Optional[int] = None) -> float:
        if self.use_competition_hfa and competition_id is not None and competition_id in self.comp_draw_nu:
            return self.comp_draw_nu[competition_id]
        return self.draw_nu

    def predict_1x2(
        self,
        home_team_id: int,
        away_team_id: int,
        competition_id: Optional[int] = None,
        season: Optional[str] = None,
    ) -> Dict[str, float]:
        r_home = self.get_rating(home_team_id, season)
        r_away = self.get_rating(away_team_id, season)
        return self.predict_from_ratings(r_home, r_away, competition_id)

    def predict_from_ratings(
        self,
        r_home: float,
        r_away: float,
        competition_id: Optional[int] = None,
    ) -> Dict[str, float]:
        hfa = self.get_hfa(competition_id)
        nu = self.get_draw_nu(competition_id)
        diff = (r_home + hfa) - r_away
        gamma_h = 10.0 ** (diff / 400.0)
        gamma_a = 1.0
        denom = gamma_h + gamma_a + nu * np.sqrt(gamma_h * gamma_a)

        p_home = float(gamma_h / denom)
        p_away = float(gamma_a / denom)
        p_draw = float((nu * np.sqrt(gamma_h * gamma_a)) / denom)

        total = p_home + p_draw + p_away
        return {
            "HOME": round(p_home / total, 5),
            "DRAW": round(p_draw / total, 5),
            "AWAY": round(p_away / total, 5),
        }

    def update_after_match(
        self,
        home_team_id: int,
        away_team_id: int,
        home_goals: int,
        away_goals: int,
        match_date: datetime,
        match_id: int,
        competition_id: Optional[int] = None,
        season: Optional[str] = None,
    ) -> Tuple[float, float]:
        r_home = self.get_rating(home_team_id, season)
        r_away = self.get_rating(away_team_id, season)

        hfa = self.get_hfa(competition_id)
        diff = (r_home + hfa) - r_away
        expected_home = 1.0 / (1.0 + 10.0 ** (-diff / 400.0))

        if home_goals > away_goals:
            actual_home = 1.0
        elif home_goals < away_goals:
            actual_home = 0.0
        else:
            actual_home = 0.5

        goal_diff = abs(int(home_goals) - int(away_goals))
        mov_mult = float(np.log(goal_diff + 1.0) * (2.2 / ((abs(diff) * 0.001) + 2.2))) if goal_diff > 0 else 1.0

        delta = self.k_factor * mov_mult * (actual_home - expected_home)
        new_home = round(r_home + delta, 2)
        new_away = round(r_away - delta, 2)

        self.ratings[home_team_id] = new_home
        self.ratings[away_team_id] = new_away

        self.history.setdefault(home_team_id, []).append(
            {"match_id": match_id, "date": match_date.isoformat(), "elo_before": r_home, "elo_after": new_home}
        )
        self.history.setdefault(away_team_id, []).append(
            {"match_id": match_id, "date": match_date.isoformat(), "elo_before": r_away, "elo_after": new_away}
        )
        return new_home, new_away

    def fit_chronologically(self, matches: List[HistoricalMatchRecord]) -> "DynamicEloModel":
        self.ratings.clear()
        self.last_season_by_team.clear()
        self.history.clear()
        finished = [
            m
            for m in matches
            if m.status == "FINISHED" and m.home_goals is not None and m.away_goals is not None
        ]
        finished.sort(key=lambda m: m.kickoff_utc)
        self.calibrate_competition_parameters(finished)

        for m in finished:
            self.update_after_match(
                home_team_id=m.home_team_id,
                away_team_id=m.away_team_id,
                home_goals=int(m.home_goals),
                away_goals=int(m.away_goals),
                match_date=m.kickoff_utc,
                match_id=m.match_id,
                competition_id=m.competition_id,
                season=m.season,
            )
        return self
