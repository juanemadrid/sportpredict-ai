from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple
import numpy as np


FEATURE_COLUMNS: List[str] = [
    "elo_diff",
    "home_elo_pre",
    "away_elo_pre",
    "home_pts_last5",
    "away_pts_last5",
    "home_pts_last10",
    "away_pts_last10",
    "home_gf_last5",
    "home_ga_last5",
    "away_gf_last5",
    "away_ga_last5",
    "home_gf_last10",
    "home_ga_last10",
    "away_gf_last10",
    "away_ga_last10",
    "home_home_gf_avg",
    "home_home_ga_avg",
    "away_away_gf_avg",
    "away_away_ga_avg",
    "home_over25_rate10",
    "away_over25_rate10",
    "home_btts_rate10",
    "away_btts_rate10",
    "home_clean_sheet_rate10",
    "away_clean_sheet_rate10",
    "combined_goal_env10",
    "rest_days_diff",
    "league_pos_diff",
    "h2h_home_advantage",
]


@dataclass
class HistoricalMatchRecord:
    match_id: int
    competition_id: int
    season: str
    kickoff_utc: datetime
    home_team_id: int
    away_team_id: int
    home_goals: Optional[int]
    away_goals: Optional[int]
    status: str
    home_xg: Optional[float] = None
    away_xg: Optional[float] = None
    home_shots: Optional[int] = None
    away_shots: Optional[int] = None
    home_sot: Optional[int] = None
    away_sot: Optional[int] = None
    home_corners: Optional[int] = None
    away_corners: Optional[int] = None
    home_cards: Optional[int] = None
    away_cards: Optional[int] = None
    home_missing_players: int = 0
    away_missing_players: int = 0
    source_name: str = "DEMO_SEED"
    is_demo: bool = False


class PointInTimeFeatureBuilder:
    """Constructor de variables deportivas sin fuga de información futura (Sección 4 y Fase 3).
    Garantiza matemáticamente que para cualquier partido con fecha T, únicamente se
    consultan partidos finalizados con fecha estrictamente menor a T (kickoff_utc < T).
    """

    @staticmethod
    def split_chronologically_no_overlap(
        finished_matches: List[HistoricalMatchRecord],
        train_frac: float = 0.60,
        val_frac: float = 0.20,
    ) -> Tuple[List[HistoricalMatchRecord], List[HistoricalMatchRecord], List[HistoricalMatchRecord]]:
        """Divide los partidos ordenados cronológicamente garantizando que las fronteras temporales
        entre Train, Validation y Test sean estrictamente disjuntas:
        max(Train.kickoff_utc) < min(Val.kickoff_utc) y max(Val.kickoff_utc) < min(Test.kickoff_utc).
        """
        sorted_m = sorted(finished_matches, key=lambda m: m.kickoff_utc)
        n = len(sorted_m)
        idx_train = int(n * train_frac)
        idx_val = int(n * (train_frac + val_frac))

        # Avanzar frontera Train/Val hasta el siguiente cambio estricto de timestamp
        while idx_train < idx_val - 1 and sorted_m[idx_train - 1].kickoff_utc == sorted_m[idx_train].kickoff_utc:
            idx_train += 1

        # Avanzar frontera Val/Test hasta el siguiente cambio estricto de timestamp
        while idx_val < n - 1 and sorted_m[idx_val - 1].kickoff_utc == sorted_m[idx_val].kickoff_utc:
            idx_val += 1

        return sorted_m[:idx_train], sorted_m[idx_train:idx_val], sorted_m[idx_val:]

    @staticmethod
    def build_features_for_match(
        target_match: HistoricalMatchRecord,
        all_prior_matches: List[HistoricalMatchRecord],
        home_elo: float,
        away_elo: float,
    ) -> Dict[str, Any]:
        strict_prior = [
            m
            for m in all_prior_matches
            if m.status == "FINISHED"
            and m.home_goals is not None
            and m.away_goals is not None
            and m.kickoff_utc < target_match.kickoff_utc
        ]
        strict_prior.sort(key=lambda x: x.kickoff_utc)

        home_stats = PointInTimeFeatureBuilder._team_window_metrics(
            team_id=target_match.home_team_id,
            target_kickoff=target_match.kickoff_utc,
            prior_matches=strict_prior,
        )
        away_stats = PointInTimeFeatureBuilder._team_window_metrics(
            team_id=target_match.away_team_id,
            target_kickoff=target_match.kickoff_utc,
            prior_matches=strict_prior,
        )

        h2h_matches = [
            m
            for m in strict_prior
            if {m.home_team_id, m.away_team_id} == {target_match.home_team_id, target_match.away_team_id}
        ]
        h2h_home_pts = 0.0
        for m in h2h_matches[-6:]:
            if m.home_team_id == target_match.home_team_id:
                h2h_home_pts += 1.0 if m.home_goals > m.away_goals else (0.5 if m.home_goals == m.away_goals else 0.0)
            else:
                h2h_home_pts += 1.0 if m.away_goals > m.home_goals else (0.5 if m.home_goals == m.away_goals else 0.0)
        h2h_adv = (h2h_home_pts / len(h2h_matches[-6:])) - 0.5 if h2h_matches else 0.0

        standings = PointInTimeFeatureBuilder._compute_point_in_time_table(
            competition_id=target_match.competition_id,
            season=target_match.season,
            prior_matches=strict_prior,
        )
        home_pos = standings.get(target_match.home_team_id, 10)
        away_pos = standings.get(target_match.away_team_id, 10)

        elo_diff = round(home_elo - away_elo, 2)
        rest_diff = float(home_stats["rest_days"] - away_stats["rest_days"])
        pos_diff = float(away_pos - home_pos)
        missing_diff = float(target_match.away_missing_players - target_match.home_missing_players)
        combined_env = round(
            0.5 * (home_stats["gf_last10"] + away_stats["ga_last10"])
            + 0.5 * (away_stats["gf_last10"] + home_stats["ga_last10"]),
            3,
        )

        return {
            "match_id": target_match.match_id,
            "competition_id": target_match.competition_id,
            "season": target_match.season,
            "kickoff_utc": target_match.kickoff_utc.isoformat(),
            "source_name": target_match.source_name,
            "elo_diff": elo_diff,
            "home_elo_pre": round(home_elo, 2),
            "away_elo_pre": round(away_elo, 2),
            "home_matches_played": home_stats["matches_count"],
            "away_matches_played": away_stats["matches_count"],
            "home_pts_last5": home_stats["pts_last5"],
            "away_pts_last5": away_stats["pts_last5"],
            "home_pts_last10": home_stats["pts_last10"],
            "away_pts_last10": away_stats["pts_last10"],
            "home_gf_last5": home_stats["gf_last5"],
            "home_ga_last5": home_stats["ga_last5"],
            "away_gf_last5": away_stats["gf_last5"],
            "away_ga_last5": away_stats["ga_last5"],
            "home_gf_last10": home_stats["gf_last10"],
            "home_ga_last10": home_stats["ga_last10"],
            "away_gf_last10": away_stats["gf_last10"],
            "away_ga_last10": away_stats["ga_last10"],
            "home_home_gf_avg": home_stats["home_gf_avg"],
            "home_home_ga_avg": home_stats["home_ga_avg"],
            "away_away_gf_avg": away_stats["away_gf_avg"],
            "away_away_ga_avg": away_stats["away_ga_avg"],
            "home_over25_rate10": home_stats["over25_rate10"],
            "away_over25_rate10": away_stats["over25_rate10"],
            "home_btts_rate10": home_stats["btts_rate10"],
            "away_btts_rate10": away_stats["btts_rate10"],
            "home_clean_sheet_rate10": home_stats["clean_sheet_rate10"],
            "away_clean_sheet_rate10": away_stats["clean_sheet_rate10"],
            "combined_goal_env10": combined_env,
            "home_xg_last5": home_stats["xg_last5"],
            "away_xg_last5": away_stats["xg_last5"],
            "home_sot_last5": home_stats["sot_last5"],
            "away_sot_last5": away_stats["sot_last5"],
            "home_corners_last5": home_stats["corners_last5"],
            "away_corners_last5": away_stats["corners_last5"],
            "home_cards_last5": home_stats["cards_last5"],
            "away_cards_last5": away_stats["cards_last5"],
            "home_rest_days": home_stats["rest_days"],
            "away_rest_days": away_stats["rest_days"],
            "rest_days_diff": rest_diff,
            "home_league_pos": home_pos,
            "away_league_pos": away_pos,
            "league_pos_diff": pos_diff,
            "h2h_matches_count": len(h2h_matches),
            "h2h_home_advantage": round(h2h_adv, 4),
            "home_missing_players": target_match.home_missing_players,
            "away_missing_players": target_match.away_missing_players,
            "missing_players_diff": missing_diff,
            "home_recent_form_str": home_stats["form_str"],
            "away_recent_form_str": away_stats["form_str"],
        }

    @staticmethod
    def build_all_chronological_features_and_elo(
        finished_matches: List[HistoricalMatchRecord],
        elo_model: Any,
    ) -> Tuple[Dict[int, Dict[str, Any]], Dict[int, Dict[str, float]]]:
        """Procesa miles de partidos en orden cronológico estricto agrupando por marca de tiempo `kickoff_utc`."""
        sorted_matches = sorted(finished_matches, key=lambda m: m.kickoff_utc)
        team_history: Dict[int, List[HistoricalMatchRecord]] = {}
        h2h_history: Dict[Tuple[int, int], List[HistoricalMatchRecord]] = {}
        season_tables: Dict[Tuple[int, str], Dict[int, List[int]]] = {}

        features_by_match_id: Dict[int, Dict[str, Any]] = {}
        elo_probs_by_match_id: Dict[int, Dict[str, float]] = {}

        i = 0
        n = len(sorted_matches)
        while i < n:
            current_ts = sorted_matches[i].kickoff_utc
            batch: List[HistoricalMatchRecord] = []
            while i < n and sorted_matches[i].kickoff_utc == current_ts:
                batch.append(sorted_matches[i])
                i += 1

            # FASE A (Pre-Partido): Extraer variables y probabilidades Elo usando SOLO información < current_ts
            for rec in batch:
                h_elo_pre = elo_model.get_rating(rec.home_team_id, rec.season)
                a_elo_pre = elo_model.get_rating(rec.away_team_id, rec.season)
                elo_probs_by_match_id[rec.match_id] = elo_model.predict_from_ratings(
                    h_elo_pre, a_elo_pre, rec.competition_id
                )

                h_prior = team_history.get(rec.home_team_id, [])
                a_prior = team_history.get(rec.away_team_id, [])
                home_stats = PointInTimeFeatureBuilder._team_window_metrics(
                    rec.home_team_id, rec.kickoff_utc, h_prior
                )
                away_stats = PointInTimeFeatureBuilder._team_window_metrics(
                    rec.away_team_id, rec.kickoff_utc, a_prior
                )

                pair_key = (min(rec.home_team_id, rec.away_team_id), max(rec.home_team_id, rec.away_team_id))
                h2h_list = h2h_history.get(pair_key, [])
                h2h_home_pts = 0.0
                for m in h2h_list[-6:]:
                    if m.home_team_id == rec.home_team_id:
                        h2h_home_pts += 1.0 if m.home_goals > m.away_goals else (0.5 if m.home_goals == m.away_goals else 0.0)
                    else:
                        h2h_home_pts += 1.0 if m.away_goals > m.home_goals else (0.5 if m.home_goals == m.away_goals else 0.0)
                h2h_adv = (h2h_home_pts / len(h2h_list[-6:])) - 0.5 if h2h_list else 0.0

                tbl = season_tables.get((rec.competition_id, rec.season), {})
                ranked = sorted(tbl.items(), key=lambda item: (item[1][0], item[1][1], item[1][2]), reverse=True)
                standings = {tid: idx + 1 for idx, (tid, _) in enumerate(ranked)}
                home_pos = standings.get(rec.home_team_id, 10)
                away_pos = standings.get(rec.away_team_id, 10)

                elo_diff = round(h_elo_pre - a_elo_pre, 2)
                rest_diff = float(home_stats["rest_days"] - away_stats["rest_days"])
                pos_diff = float(away_pos - home_pos)
                missing_diff = float(rec.away_missing_players - rec.home_missing_players)
                combined_env = round(
                    0.5 * (home_stats["gf_last10"] + away_stats["ga_last10"])
                    + 0.5 * (away_stats["gf_last10"] + home_stats["ga_last10"]),
                    3,
                )

                features_by_match_id[rec.match_id] = {
                    "match_id": rec.match_id,
                    "competition_id": rec.competition_id,
                    "season": rec.season,
                    "kickoff_utc": rec.kickoff_utc.isoformat(),
                    "source_name": rec.source_name,
                    "elo_diff": elo_diff,
                    "home_elo_pre": round(h_elo_pre, 2),
                    "away_elo_pre": round(a_elo_pre, 2),
                    "home_matches_played": home_stats["matches_count"],
                    "away_matches_played": away_stats["matches_count"],
                    "home_pts_last5": home_stats["pts_last5"],
                    "away_pts_last5": away_stats["pts_last5"],
                    "home_pts_last10": home_stats["pts_last10"],
                    "away_pts_last10": away_stats["pts_last10"],
                    "home_gf_last5": home_stats["gf_last5"],
                    "home_ga_last5": home_stats["ga_last5"],
                    "away_gf_last5": away_stats["gf_last5"],
                    "away_ga_last5": away_stats["ga_last5"],
                    "home_gf_last10": home_stats["gf_last10"],
                    "home_ga_last10": home_stats["ga_last10"],
                    "away_gf_last10": away_stats["gf_last10"],
                    "away_ga_last10": away_stats["ga_last10"],
                    "home_home_gf_avg": home_stats["home_gf_avg"],
                    "home_home_ga_avg": home_stats["home_ga_avg"],
                    "away_away_gf_avg": away_stats["away_gf_avg"],
                    "away_away_ga_avg": away_stats["away_ga_avg"],
                    "home_over25_rate10": home_stats["over25_rate10"],
                    "away_over25_rate10": away_stats["over25_rate10"],
                    "home_btts_rate10": home_stats["btts_rate10"],
                    "away_btts_rate10": away_stats["btts_rate10"],
                    "home_clean_sheet_rate10": home_stats["clean_sheet_rate10"],
                    "away_clean_sheet_rate10": away_stats["clean_sheet_rate10"],
                    "combined_goal_env10": combined_env,
                    "home_xg_last5": home_stats["xg_last5"],
                    "away_xg_last5": away_stats["xg_last5"],
                    "home_sot_last5": home_stats["sot_last5"],
                    "away_sot_last5": away_stats["sot_last5"],
                    "home_corners_last5": home_stats["corners_last5"],
                    "away_corners_last5": away_stats["corners_last5"],
                    "home_cards_last5": home_stats["cards_last5"],
                    "away_cards_last5": away_stats["cards_last5"],
                    "home_rest_days": home_stats["rest_days"],
                    "away_rest_days": away_stats["rest_days"],
                    "rest_days_diff": rest_diff,
                    "home_league_pos": home_pos,
                    "away_league_pos": away_pos,
                    "league_pos_diff": pos_diff,
                    "h2h_matches_count": len(h2h_list),
                    "h2h_home_advantage": round(h2h_adv, 4),
                    "home_missing_players": rec.home_missing_players,
                    "away_missing_players": rec.away_missing_players,
                    "missing_players_diff": missing_diff,
                    "home_recent_form_str": home_stats["form_str"],
                    "away_recent_form_str": away_stats["form_str"],
                }

            # FASE B (Post-Partido): Actualizar historiales, tabla de clasificación y Elo con los resultados del lote
            for rec in batch:
                team_history.setdefault(rec.home_team_id, []).append(rec)
                team_history.setdefault(rec.away_team_id, []).append(rec)
                pair_key = (min(rec.home_team_id, rec.away_team_id), max(rec.home_team_id, rec.away_team_id))
                h2h_history.setdefault(pair_key, []).append(rec)

                tbl = season_tables.setdefault((rec.competition_id, rec.season), {})
                for tid in (rec.home_team_id, rec.away_team_id):
                    if tid not in tbl:
                        tbl[tid] = [0, 0, 0]
                hg, ag = int(rec.home_goals), int(rec.away_goals)
                tbl[rec.home_team_id][1] += hg - ag
                tbl[rec.home_team_id][2] += hg
                tbl[rec.away_team_id][1] += ag - hg
                tbl[rec.away_team_id][2] += ag
                if hg > ag:
                    tbl[rec.home_team_id][0] += 3
                elif hg < ag:
                    tbl[rec.away_team_id][0] += 3
                else:
                    tbl[rec.home_team_id][0] += 1
                    tbl[rec.away_team_id][0] += 1

                elo_model.update_after_match(
                    home_team_id=rec.home_team_id,
                    away_team_id=rec.away_team_id,
                    home_goals=hg,
                    away_goals=ag,
                    match_date=rec.kickoff_utc,
                    match_id=rec.match_id,
                    competition_id=rec.competition_id,
                    season=rec.season,
                )

        return features_by_match_id, elo_probs_by_match_id

    @staticmethod
    def audit_temporal_and_standings_integrity(
        all_finished: List[HistoricalMatchRecord],
        train_records: List[HistoricalMatchRecord],
        val_records: List[HistoricalMatchRecord],
        test_records: List[HistoricalMatchRecord],
        features_by_match_id: Dict[int, Dict[str, Any]],
    ) -> Dict[str, Any]:
        """Auditoría científica de fronteras temporales y clasificación de liga pre-partido (Sección 5 de Fase 3)."""
        max_train_dt = max(m.kickoff_utc for m in train_records)
        min_val_dt = min(m.kickoff_utc for m in val_records)
        max_val_dt = max(m.kickoff_utc for m in val_records)
        min_test_dt = min(m.kickoff_utc for m in test_records)

        train_val_disjoint = max_train_dt < min_val_dt
        val_test_disjoint = max_val_dt < min_test_dt

        # Auditar clasificación de liga en una muestra determinista de partidos de Train, Val y Test
        sorted_all = sorted(all_finished, key=lambda m: m.kickoff_utc)
        sample_indices = np.linspace(10, len(sorted_all) - 1, num=min(40, len(sorted_all) - 10), dtype=int)
        standings_mismatches = 0
        for idx in sample_indices:
            target = sorted_all[int(idx)]
            strict_prior = [m for m in sorted_all[: int(idx)] if m.kickoff_utc < target.kickoff_utc]
            exact_table = PointInTimeFeatureBuilder._compute_point_in_time_table(
                target.competition_id, target.season, strict_prior
            )
            expected_h_pos = exact_table.get(target.home_team_id, 10)
            expected_a_pos = exact_table.get(target.away_team_id, 10)
            feat = features_by_match_id[target.match_id]
            if feat["home_league_pos"] != expected_h_pos or feat["away_league_pos"] != expected_a_pos:
                standings_mismatches += 1

        return {
            "train_max_kickoff_utc": max_train_dt.isoformat(),
            "val_min_kickoff_utc": min_val_dt.isoformat(),
            "val_max_kickoff_utc": max_val_dt.isoformat(),
            "test_min_kickoff_utc": min_test_dt.isoformat(),
            "train_val_strictly_disjoint": train_val_disjoint,
            "val_test_strictly_disjoint": val_test_disjoint,
            "standings_audit_sample_size": len(sample_indices),
            "standings_pre_match_mismatches": standings_mismatches,
            "standings_integrity_verified": (standings_mismatches == 0),
        }

    @staticmethod
    def _team_window_metrics(
        team_id: int,
        target_kickoff: datetime,
        prior_matches: List[HistoricalMatchRecord],
    ) -> Dict[str, Any]:
        team_matches = [m for m in prior_matches if m.home_team_id == team_id or m.away_team_id == team_id]
        if not team_matches:
            return {
                "matches_count": 0,
                "pts_last5": 1.35,
                "pts_last10": 1.35,
                "gf_last5": 1.30,
                "ga_last5": 1.30,
                "gf_last10": 1.30,
                "ga_last10": 1.30,
                "home_gf_avg": 1.45,
                "home_ga_avg": 1.15,
                "away_gf_avg": 1.15,
                "away_ga_avg": 1.45,
                "over25_rate10": 0.52,
                "btts_rate10": 0.52,
                "clean_sheet_rate10": 0.28,
                "xg_last5": 1.30,
                "sot_last5": 4.2,
                "corners_last5": 4.8,
                "cards_last5": 2.1,
                "rest_days": 7,
                "form_str": "-----",
            }

        recent_slice = team_matches[-15:]

        def extract_tuple(m: HistoricalMatchRecord):
            is_home = m.home_team_id == team_id
            gf = m.home_goals if is_home else m.away_goals
            ga = m.away_goals if is_home else m.home_goals
            pts = 3 if gf > ga else (1 if gf == ga else 0)
            res_char = "V" if gf > ga else ("E" if gf == ga else "D")
            xg = (m.home_xg if is_home else m.away_xg)
            sot = (m.home_sot if is_home else m.away_sot)
            cor = (m.home_corners if is_home else m.away_corners)
            crd = (m.home_cards if is_home else m.away_cards)
            return {
                "is_home": is_home,
                "gf": float(gf),
                "ga": float(ga),
                "pts": float(pts),
                "char": res_char,
                "over25": 1.0 if (gf + ga) > 2.5 else 0.0,
                "btts": 1.0 if (gf >= 1 and ga >= 1) else 0.0,
                "clean_sheet": 1.0 if ga == 0 else 0.0,
                "xg": float(xg) if xg is not None else float(gf),
                "sot": float(sot) if sot is not None else 4.0,
                "corners": float(cor) if cor is not None else 4.8,
                "cards": float(crd) if crd is not None else 2.0,
            }

        extracted = [extract_tuple(m) for m in recent_slice]
        last5 = extracted[-5:]
        last10 = extracted[-10:]
        home_only = [e for e in extracted if e["is_home"]]
        away_only = [e for e in extracted if not e["is_home"]]

        last_match_dt = team_matches[-1].kickoff_utc
        delta_days = max(2, min(21, int((target_kickoff - last_match_dt).total_seconds() // 86400)))

        return {
            "matches_count": len(team_matches),
            "pts_last5": round(float(np.mean([x["pts"] for x in last5])), 3),
            "pts_last10": round(float(np.mean([x["pts"] for x in last10])), 3),
            "gf_last5": round(float(np.mean([x["gf"] for x in last5])), 3),
            "ga_last5": round(float(np.mean([x["ga"] for x in last5])), 3),
            "gf_last10": round(float(np.mean([x["gf"] for x in last10])), 3),
            "ga_last10": round(float(np.mean([x["ga"] for x in last10])), 3),
            "home_gf_avg": round(float(np.mean([x["gf"] for x in home_only])), 3) if home_only else 1.45,
            "home_ga_avg": round(float(np.mean([x["ga"] for x in home_only])), 3) if home_only else 1.15,
            "away_gf_avg": round(float(np.mean([x["gf"] for x in away_only])), 3) if away_only else 1.15,
            "away_ga_avg": round(float(np.mean([x["ga"] for x in away_only])), 3) if away_only else 1.45,
            "over25_rate10": round(float(np.mean([x["over25"] for x in last10])), 3),
            "btts_rate10": round(float(np.mean([x["btts"] for x in last10])), 3),
            "clean_sheet_rate10": round(float(np.mean([x["clean_sheet"] for x in last10])), 3),
            "xg_last5": round(float(np.mean([x["xg"] for x in last5])), 3),
            "sot_last5": round(float(np.mean([x["sot"] for x in last5])), 2),
            "corners_last5": round(float(np.mean([x["corners"] for x in last5])), 2),
            "cards_last5": round(float(np.mean([x["cards"] for x in last5])), 2),
            "rest_days": delta_days,
            "form_str": "".join(x["char"] for x in last5),
        }

    @staticmethod
    def _compute_point_in_time_table(
        competition_id: int,
        season: str,
        prior_matches: List[HistoricalMatchRecord],
    ) -> Dict[int, int]:
        season_matches = [
            m for m in prior_matches if m.competition_id == competition_id and m.season == season
        ]
        table: Dict[int, List[int]] = {}
        for m in season_matches:
            for tid in (m.home_team_id, m.away_team_id):
                if tid not in table:
                    table[tid] = [0, 0, 0]
            hg, ag = int(m.home_goals), int(m.away_goals)
            table[m.home_team_id][1] += hg - ag
            table[m.home_team_id][2] += hg
            table[m.away_team_id][1] += ag - hg
            table[m.away_team_id][2] += ag
            if hg > ag:
                table[m.home_team_id][0] += 3
            elif hg < ag:
                table[m.away_team_id][0] += 3
            else:
                table[m.home_team_id][0] += 1
                table[m.away_team_id][0] += 1

        ranked = sorted(table.items(), key=lambda item: (item[1][0], item[1][1], item[1][2]), reverse=True)
        return {tid: idx + 1 for idx, (tid, _) in enumerate(ranked)}
