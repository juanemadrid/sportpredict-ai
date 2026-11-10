import csv
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Dict, List, Optional, Set, Tuple
import httpx
from sqlalchemy.orm import Session

from app.core.config import DATA_DIR
from app.db.models import Competition, Match, Team, TeamAlias
from app.ingestion.base import DataProviderAdapter


REAL_DATA_DIR = DATA_DIR / "real_historical"
RAW_JSON_CACHE_DIR = REAL_DATA_DIR / "raw_json"

# Fuentes oficiales de dominio público (CC0-1.0) en GitHub: openfootball/football.json
# Sin restricciones comerciales — 100% compatibles con producto SaaS comercial.
OPENFOOTBALL_SOURCES = [
    ("2021-22", "en.1", "ENG_EPL", "Premier League", "Inglaterra"),
    ("2022-23", "en.1", "ENG_EPL", "Premier League", "Inglaterra"),
    ("2023-24", "en.1", "ENG_EPL", "Premier League", "Inglaterra"),
    ("2021-22", "es.1", "ESP_LALIGA", "LaLiga EA Sports", "España"),
    ("2022-23", "es.1", "ESP_LALIGA", "LaLiga EA Sports", "España"),
    ("2023-24", "es.1", "ESP_LALIGA", "LaLiga EA Sports", "España"),
    ("2021-22", "it.1", "ITA_SERIEA", "Serie A", "Italia"),
    ("2022-23", "it.1", "ITA_SERIEA", "Serie A", "Italia"),
    ("2023-24", "it.1", "ITA_SERIEA", "Serie A", "Italia"),
    ("2021-22", "de.1", "GER_BUNDESLIGA", "Bundesliga", "Alemania"),
    ("2022-23", "de.1", "GER_BUNDESLIGA", "Bundesliga", "Alemania"),
    ("2023-24", "de.1", "GER_BUNDESLIGA", "Bundesliga", "Alemania"),
]

# Diccionario de normalización canónica de clubes reales (Paso 3)
CANONICAL_TEAM_MAP = {
    "Manchester United FC": "Manchester United",
    "Manchester City FC": "Manchester City",
    "Arsenal FC": "Arsenal",
    "Liverpool FC": "Liverpool",
    "Chelsea FC": "Chelsea",
    "Tottenham Hotspur FC": "Tottenham Hotspur",
    "Newcastle United FC": "Newcastle United",
    "Aston Villa FC": "Aston Villa",
    "West Ham United FC": "West Ham United",
    "Brighton & Hove Albion FC": "Brighton & Hove Albion",
    "Wolverhampton Wanderers FC": "Wolverhampton Wanderers",
    "Crystal Palace FC": "Crystal Palace",
    "Everton FC": "Everton",
    "Fulham FC": "Fulham",
    "Brentford FC": "Brentford",
    "AFC Bournemouth": "Bournemouth",
    "Nottingham Forest FC": "Nottingham Forest",
    "Leicester City FC": "Leicester City",
    "Leeds United FC": "Leeds United",
    "Southampton FC": "Southampton",
    "Burnley FC": "Burnley",
    "Sheffield United FC": "Sheffield United",
    "Luton Town FC": "Luton Town",
    "Watford FC": "Watford",
    "Norwich City FC": "Norwich City",
    "Real Madrid CF": "Real Madrid",
    "FC Barcelona": "FC Barcelona",
    "Club Atlético de Madrid": "Atlético de Madrid",
    "Sevilla FC": "Sevilla FC",
    "Real Betis Balompié": "Real Betis",
    "Real Sociedad de Fútbol": "Real Sociedad",
    "Villarreal CF": "Villarreal CF",
    "Athletic Club": "Athletic Club",
    "Valencia CF": "Valencia CF",
    "CA Osasuna": "CA Osasuna",
    "RC Celta de Vigo": "Celta de Vigo",
    "Rayo Vallecano de Madrid": "Rayo Vallecano",
    "Getafe CF": "Getafe CF",
    "RCD Espanyol de Barcelona": "RCD Espanyol",
    "RCD Mallorca": "RCD Mallorca",
    "Girona FC": "Girona FC",
    "UD Almería": "UD Almería",
    "Cádiz CF": "Cádiz CF",
    "Elche CF": "Elche CF",
    "Real Valladolid CF": "Real Valladolid",
    "Deportivo Alavés": "Deportivo Alavés",
    "UD Las Palmas": "UD Las Palmas",
    "Granada CF": "Granada CF",
    "Levante UD": "Levante UD",
    "FC Internazionale Milano": "Inter de Milán",
    "AC Milan": "AC Milan",
    "Juventus FC": "Juventus",
    "SSC Napoli": "SSC Napoli",
    "AS Roma": "AS Roma",
    "SS Lazio": "SS Lazio",
    "Atalanta BC": "Atalanta",
    "ACF Fiorentina": "Fiorentina",
    "Bologna FC 1909": "Bologna",
    "Torino FC": "Torino",
    "Udinese Calcio": "Udinese",
    "US Sassuolo Calcio": "Sassuolo",
    "US Lecce": "Lecce",
    "US Cremonese": "Cremonese",
    "US Salernitana 1919": "Salernitana",
    "AC Monza": "Monza",
    "Empoli FC": "Empoli",
    "Hellas Verona FC": "Hellas Verona",
    "Spezia Calcio": "Spezia",
    "UC Sampdoria": "Sampdoria",
    "Genoa CFC": "Genoa",
    "Cagliari Calcio": "Cagliari",
    "Frosinone Calcio": "Frosinone",
    "Venezia FC": "Venezia",
    "FC Bayern München": "Bayern Múnich",
    "Borussia Dortmund": "Borussia Dortmund",
    "RB Leipzig": "RB Leipzig",
    "Bayer 04 Leverkusen": "Bayer Leverkusen",
    "SC Freiburg": "SC Freiburg",
    "Eintracht Frankfurt": "Eintracht Frankfurt",
    "1. FC Union Berlin": "Union Berlin",
    "VfL Wolfsburg": "VfL Wolfsburg",
    "Borussia Mönchengladbach": "Borussia Mönchengladbach",
    "VfB Stuttgart": "VfB Stuttgart",
    "TSG 1899 Hoffenheim": "TSG Hoffenheim",
    "1. FSV Mainz 05": "Mainz 05",
    "1. FC Köln": "1. FC Köln",
    "FC Augsburg": "FC Augsburg",
    "SV Werder Bremen": "Werder Bremen",
    "VfL Bochum 1848": "VfL Bochum",
    "Hertha BSC": "Hertha BSC",
    "FC Schalke 04": "Schalke 04",
    "Arminia Bielefeld": "Arminia Bielefeld",
    "SpVgg Greuther Fürth": "Greuther Fürth",
    "1. FC Heidenheim 1846": "1. FC Heidenheim",
    "SV Darmstadt 98": "Darmstadt 98",
}


class OpenFootballRealDataAdapter(DataProviderAdapter):
    """Adaptador oficial para datos históricos reales de dominio público (OpenFootball CC0-1.0)
    y auditoría de catálogo StatsBomb Open Data (CC BY-NC-SA 4.0).
    """

    provider_code = "OPENFOOTBALL_CC0"
    display_name = "OpenFootball Historical Dataset (Dominio Público CC0-1.0)"
    license_type = "CC0-1.0 Universal Public Domain (Apto para SaaS Comercial)"
    daily_quota_limit = 99999
    is_demo = False

    def is_configured(self) -> bool:
        return True

    @staticmethod
    def normalize_team_name(raw_name: str) -> Tuple[str, bool]:
        """Normaliza el nombre del equipo y devuelve (nombre_canonico, fue_normalizado)."""
        cleaned = " ".join(raw_name.strip().split())
        if cleaned in CANONICAL_TEAM_MAP:
            mapped = CANONICAL_TEAM_MAP[cleaned]
            return mapped, (mapped != raw_name)
        simplified = re.sub(r"^(US|AC|AS|SS|UC|FC|CF|RC|CA|UD|RCD)\s+", "", cleaned)
        simplified = re.sub(r"\s+(FC|CF|Calcio|1909|1919|1848|1846|05|98|04)$", "", simplified)
        return simplified, (simplified != raw_name)

    @staticmethod
    def parse_matchday(round_str: str) -> Optional[int]:
        if not round_str:
            return None
        m = re.search(r"(\d+)", str(round_str))
        return int(m.group(1)) if m else None

    @staticmethod
    def normalize_kickoff_utc(date_str: str, time_str: Optional[str]) -> Tuple[Optional[datetime], bool]:
        """Normaliza fecha y hora a UTC ISO-8601. Devuelve (datetime_utc, tenia_hora_explicita)."""
        if not date_str:
            return None, False
        has_time = bool(time_str and re.match(r"^\d{1,2}:\d{2}$", str(time_str).strip()))
        t_part = str(time_str).strip() if has_time else "15:00"
        if len(t_part) == 4:
            t_part = "0" + t_part
        try:
            dt = datetime.fromisoformat(f"{date_str.strip()}T{t_part}:00+00:00")
            return dt.astimezone(timezone.utc), has_time
        except Exception:
            return None, False

    def download_and_ingest_real_history(
        self,
        db: Session,
        seasons_Filter: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """Descarga (o lee de caché en disco) los partidos históricos reales desde openfootball/football.json (CC0-1.0),
        ejecuta las validaciones de calidad de datos del Paso 3, guarda copia CSV auditable
        en disco e inserta los registros reales (`is_demo = False`) en la base de datos.
        """
        REAL_DATA_DIR.mkdir(parents=True, exist_ok=True)
        RAW_JSON_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        csv_archive_path: Path = REAL_DATA_DIR / "openfootball_real_matches_cc0.csv"

        quality_report = {
            "source_provider": self.provider_code,
            "license": self.license_type,
            "files_fetched": 0,
            "raw_records_inspected": 0,
            "valid_matches_inserted": 0,
            "already_in_db_skipped": 0,
            "duplicates_in_source_removed": 0,
            "missing_scores_rejected": 0,
            "missing_time_defaulted_to_15utc": 0,
            "missing_ht_score_count": 0,
            "invalid_score_anomalies": 0,
            "team_names_normalized_count": 0,
            "distinct_teams_normalized": 0,
            "by_competition": {},
            "by_season": {},
            "statsbomb_catalog_checked": False,
            "statsbomb_competitions_found": 0,
        }

        seen_natural_keys: Set[str] = set()
        normalized_teams_set: Set[str] = set()
        csv_rows_to_export: List[Dict[str, Any]] = []

        sb_catalog_file = REAL_DATA_DIR / "statsbomb_competitions_catalog.json"
        if sb_catalog_file.exists():
            try:
                sb_comps = json.loads(sb_catalog_file.read_text(encoding="utf-8"))
                quality_report["statsbomb_catalog_checked"] = True
                quality_report["statsbomb_competitions_found"] = len(sb_comps)
            except Exception:
                pass

        with httpx.Client(timeout=20.0, follow_redirects=True) as client:
            if not quality_report["statsbomb_catalog_checked"]:
                try:
                    sb_url = "https://raw.githubusercontent.com/statsbomb/open-data/master/data/competitions.json"
                    sb_resp = client.get(sb_url)
                    if sb_resp.status_code == 200:
                        sb_comps = sb_resp.json()
                        quality_report["statsbomb_catalog_checked"] = True
                        quality_report["statsbomb_competitions_found"] = len(sb_comps)
                        sb_catalog_file.write_text(sb_resp.text, encoding="utf-8")
                except Exception:
                    pass

            for season, file_prefix, comp_code, comp_name, country in OPENFOOTBALL_SOURCES:
                if seasons_Filter and season not in seasons_Filter:
                    continue

                local_json_path = RAW_JSON_CACHE_DIR / f"{season}_{file_prefix}.json"
                payload = None
                if local_json_path.exists():
                    payload = json.loads(local_json_path.read_text(encoding="utf-8"))
                else:
                    url = f"https://raw.githubusercontent.com/openfootball/football.json/master/{season}/{file_prefix}.json"
                    resp = client.get(url)
                    if resp.status_code == 200:
                        local_json_path.write_text(resp.text, encoding="utf-8")
                        payload = resp.json()

                if not payload:
                    continue

                quality_report["files_fetched"] += 1
                matches_list = payload.get("matches", [])

                comp_obj = db.query(Competition).filter(Competition.code == comp_code).first()
                if not comp_obj:
                    comp_obj = Competition(
                        code=comp_code,
                        name=comp_name,
                        country=country,
                        tier=1,
                        has_xg_coverage=False,
                        source_name=self.provider_code,
                        is_demo=False,
                    )
                    db.add(comp_obj)
                    db.flush()

                for raw_m in matches_list:
                    quality_report["raw_records_inspected"] += 1
                    date_str = raw_m.get("date")
                    time_str = raw_m.get("time")
                    raw_home = raw_m.get("team1", "")
                    raw_away = raw_m.get("team2", "")
                    round_str = raw_m.get("round", "")
                    score_obj = raw_m.get("score", {})

                    if not date_str or not raw_home or not raw_away:
                        quality_report["missing_scores_rejected"] += 1
                        continue

                    ft_scores = score_obj.get("ft")
                    if not ft_scores or len(ft_scores) != 2 or ft_scores[0] is None or ft_scores[1] is None:
                        quality_report["missing_scores_rejected"] += 1
                        continue

                    hg, ag = int(ft_scores[0]), int(ft_scores[1])
                    if hg < 0 or ag < 0 or hg > 20 or ag > 20:
                        quality_report["invalid_score_anomalies"] += 1
                        continue

                    ht_scores = score_obj.get("ht")
                    ht_h, ht_a = None, None
                    if ht_scores and len(ht_scores) == 2 and ht_scores[0] is not None and ht_scores[1] is not None:
                        ht_h, ht_a = int(ht_scores[0]), int(ht_scores[1])
                        if ht_h > hg or ht_a > ag or ht_h < 0 or ht_a < 0:
                            quality_report["invalid_score_anomalies"] += 1
                            ht_h, ht_a = None, None
                    else:
                        quality_report["missing_ht_score_count"] += 1

                    kickoff_dt, had_time = self.normalize_kickoff_utc(date_str, time_str)
                    if kickoff_dt is None:
                        quality_report["missing_scores_rejected"] += 1
                        continue
                    if not had_time:
                        quality_report["missing_time_defaulted_to_15utc"] += 1

                    norm_home, h_changed = self.normalize_team_name(raw_home)
                    norm_away, a_changed = self.normalize_team_name(raw_away)
                    if h_changed:
                        quality_report["team_names_normalized_count"] += 1
                    if a_changed:
                        quality_report["team_names_normalized_count"] += 1
                    normalized_teams_set.add(norm_home)
                    normalized_teams_set.add(norm_away)

                    if norm_home == norm_away:
                        quality_report["invalid_score_anomalies"] += 1
                        continue

                    natural_key = f"{comp_code}:{season}:{date_str}:{norm_home}:{norm_away}"
                    if natural_key in seen_natural_keys:
                        quality_report["duplicates_in_source_removed"] += 1
                        continue
                    seen_natural_keys.add(natural_key)

                    key_hash = hashlib.sha1(natural_key.encode("utf-8")).hexdigest()[:10]
                    ext_ref = f"OF-{comp_code}-{season}-{date_str}-{key_hash}"
                    existing_match = db.query(Match).filter(Match.external_ref == ext_ref).first()
                    if existing_match:
                        quality_report["already_in_db_skipped"] += 1
                        continue

                    home_team = self._get_or_create_real_team(db, raw_home, norm_home, country)
                    away_team = self._get_or_create_real_team(db, raw_away, norm_away, country)

                    outcome = "H" if hg > ag else ("A" if ag > hg else "D")
                    matchday_num = self.parse_matchday(round_str)

                    new_match = Match(
                        external_ref=ext_ref,
                        competition_id=comp_obj.id,
                        season=season,
                        matchday=matchday_num,
                        kickoff_utc=kickoff_dt,
                        status="FINISHED",
                        home_team_id=home_team.id,
                        away_team_id=away_team.id,
                        home_goals=hg,
                        away_goals=ag,
                        ht_home_goals=ht_h,
                        ht_away_goals=ht_a,
                        outcome_1x2=outcome,
                        lineups_confirmed=True,
                        source_name=self.provider_code,
                        source_license=self.license_type,
                        is_demo=False,
                    )
                    db.add(new_match)

                    quality_report["valid_matches_inserted"] += 1
                    quality_report["by_competition"][comp_name] = (
                        quality_report["by_competition"].get(comp_name, 0) + 1
                    )
                    quality_report["by_season"][season] = quality_report["by_season"].get(season, 0) + 1

                    csv_rows_to_export.append(
                        {
                            "external_ref": ext_ref,
                            "competition_code": comp_code,
                            "competition_name": comp_name,
                            "country": country,
                            "season": season,
                            "matchday": matchday_num or "",
                            "kickoff_utc": kickoff_dt.isoformat(),
                            "home_team": norm_home,
                            "away_team": norm_away,
                            "status": "FINISHED",
                            "home_goals": hg,
                            "away_goals": ag,
                            "ht_home_goals": ht_h if ht_h is not None else "",
                            "ht_away_goals": ht_a if ht_a is not None else "",
                            "outcome_1x2": outcome,
                            "source_name": self.provider_code,
                            "source_license": self.license_type,
                        }
                    )

        db.commit()
        quality_report["distinct_teams_normalized"] = len(normalized_teams_set)

        if csv_rows_to_export:
            fieldnames = list(csv_rows_to_export[0].keys())
            with csv_archive_path.open("w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(csv_rows_to_export)

        self.register_sync_event(
            db=db,
            endpoint_or_file=str(csv_archive_path.name),
            status="SUCCESS",
            records_processed=quality_report["raw_records_inspected"],
            records_inserted=quality_report["valid_matches_inserted"],
            duplicates=quality_report["duplicates_in_source_removed"] + quality_report["already_in_db_skipped"],
            missing_values=quality_report["missing_scores_rejected"] + quality_report["missing_ht_score_count"],
            notes=f"Ingestión real OpenFootball CC0-1.0 ({quality_report['valid_matches_inserted']} partidos reales)",
        )
        return quality_report

    def _get_or_create_real_team(
        self,
        db: Session,
        raw_name: str,
        canonical_name: str,
        country: str,
    ) -> Team:
        alias = (
            db.query(TeamAlias)
            .filter(TeamAlias.provider_code == self.provider_code, TeamAlias.alias_name == raw_name)
            .first()
        )
        if alias:
            t = db.query(Team).filter(Team.id == alias.team_id).first()
            if t:
                t.is_demo = False
                return t

        team = db.query(Team).filter(Team.canonical_name == canonical_name).first()
        if not team:
            alpha = "".join(ch for ch in canonical_name.upper() if ch.isalpha())
            short_code = alpha[:3] if len(alpha) >= 3 else "CLB"
            team = Team(
                canonical_name=canonical_name,
                short_code=short_code,
                country=country,
                current_elo=1500.0,
                source_name=self.provider_code,
                is_demo=False,
            )
            db.add(team)
            db.flush()
        else:
            team.is_demo = False

        db.add(
            TeamAlias(
                team_id=team.id,
                provider_code=self.provider_code,
                alias_name=raw_name,
            )
        )
        db.flush()
        return team
