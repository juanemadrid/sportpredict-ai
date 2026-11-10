import csv
from datetime import datetime, timezone
import io
from typing import Any, Dict, Set
from sqlalchemy.orm import Session

from app.db.models import Competition, Match, MatchTeamStat, OddsSnapshot, Team, TeamAlias
from app.ingestion.base import DataProviderAdapter
from app.ml.odds_math import remove_bookmaker_margin


REQUIRED_CSV_COLUMNS = {
    "external_ref",
    "competition_code",
    "competition_name",
    "season",
    "kickoff_utc",
    "home_team",
    "away_team",
    "status",
}


class AuthorizedCSVImporter(DataProviderAdapter):
    """Importador de archivos CSV históricos autorizados (Secciones 7 y 8).
    Funciones:
    - Validar estructura obligatoria de columnas.
    - Verificar licencia compatible (prohíbe fuentes sin autorización comercial como Football-Data no autorizado).
    - Detectar duplicados (en el archivo y en la base de datos).
    - Detectar valores faltantes.
    - Normalizar nombres de equipos y competiciones mediante `team_aliases`.
    """

    provider_code = "AUTHORIZED_CSV"
    display_name = "Importador CSV Histórico Autorizado"
    license_type = "Kaggle Open License / Propio Autorizado"
    daily_quota_limit = 99999
    is_demo = False

    def is_configured(self) -> bool:
        return True

    @staticmethod
    def normalize_team_name(raw_name: str) -> str:
        clean = " ".join(raw_name.strip().split())
        synonyms = {
            "Ath Madrid": "Atlético de Madrid",
            "Atletico Madrid": "Atlético de Madrid",
            "Man United": "Manchester United",
            "Man City": "Manchester City",
            "Spurs": "Tottenham Hotspur",
            "Inter": "Inter de Milán",
            "Bayern Munich": "Bayern Múnich",
            "PSG": "Paris Saint-Germain",
        }
        return synonyms.get(clean, clean)

    def import_csv_content(
        self,
        db: Session,
        csv_text: str,
        source_name: str,
        source_license: str,
        is_demo: bool = False,
    ) -> Dict[str, Any]:
        # Regla Sección 7: No utilizar Football-Data para entrenamiento comercial ni scraping sin autorización
        if "football-data" in source_name.lower() and "autorizado" not in source_license.lower():
            raise ValueError(
                "Fuente rechazada por política de cumplimiento (Sección 7): "
                "No se permite utilizar Football-Data para fines comerciales sin autorización expresa."
            )

        reader = csv.DictReader(io.StringIO(csv_text.strip()))
        fieldnames: Set[str] = set(reader.fieldnames or [])
        missing_cols = REQUIRED_CSV_COLUMNS - fieldnames
        if missing_cols:
            raise ValueError(
                f"Estructura CSV inválida. Faltan columnas requeridas: {sorted(missing_cols)}"
            )

        processed = 0
        inserted = 0
        duplicates = 0
        missing_values = 0
        seen_refs: Set[str] = set()

        for row in reader:
            processed += 1
            ext_ref = (row.get("external_ref") or "").strip()
            home_raw = (row.get("home_team") or "").strip()
            away_raw = (row.get("away_team") or "").strip()
            kickoff_raw = (row.get("kickoff_utc") or "").strip()

            if not ext_ref or not home_raw or not away_raw or not kickoff_raw:
                missing_values += 1
                continue

            if ext_ref in seen_refs:
                duplicates += 1
                continue
            seen_refs.add(ext_ref)

            existing = db.query(Match).filter(Match.external_ref == ext_ref).first()
            if existing:
                duplicates += 1
                continue

            comp_code = (row.get("competition_code") or "GEN").strip().upper()
            comp_name = (row.get("competition_name") or comp_code).strip()
            comp = db.query(Competition).filter(Competition.code == comp_code).first()
            if not comp:
                comp = Competition(
                    code=comp_code,
                    name=comp_name,
                    country=(row.get("country") or "Internacional").strip(),
                    tier=1,
                    has_xg_coverage=bool(row.get("home_xg")),
                    source_name=source_name,
                    is_demo=is_demo,
                )
                db.add(comp)
                db.flush()

            home_team = self._get_or_create_team(db, home_raw, comp.country, source_name, is_demo)
            away_team = self._get_or_create_team(db, away_raw, comp.country, source_name, is_demo)

            kickoff_dt = datetime.fromisoformat(kickoff_raw.replace("Z", "+00:00"))
            if kickoff_dt.tzinfo is None:
                kickoff_dt = kickoff_dt.replace(tzinfo=timezone.utc)

            status_val = (row.get("status") or "FINISHED").strip().upper()
            hg = int(row["home_goals"]) if row.get("home_goals") not in (None, "") else None
            ag = int(row["away_goals"]) if row.get("away_goals") not in (None, "") else None
            if status_val == "FINISHED" and (hg is None or ag is None):
                missing_values += 1

            outcome = None
            if hg is not None and ag is not None:
                outcome = "H" if hg > ag else ("A" if ag > hg else "D")

            match = Match(
                external_ref=ext_ref,
                competition_id=comp.id,
                season=(row.get("season") or "2025/2026").strip(),
                matchday=int(row["matchday"]) if row.get("matchday") not in (None, "") else None,
                kickoff_utc=kickoff_dt,
                status=status_val,
                home_team_id=home_team.id,
                away_team_id=away_team.id,
                home_goals=hg,
                away_goals=ag,
                outcome_1x2=outcome,
                source_name=source_name,
                source_license=source_license,
                is_demo=is_demo,
            )
            db.add(match)
            db.flush()

            # Estadísticas avanzadas opcionales si existen en el CSV (sin inventar valores faltantes)
            h_xg = float(row["home_xg"]) if row.get("home_xg") not in (None, "") else None
            a_xg = float(row["away_xg"]) if row.get("away_xg") not in (None, "") else None
            h_sot = int(row["home_sot"]) if row.get("home_sot") not in (None, "") else None
            a_sot = int(row["away_sot"]) if row.get("away_sot") not in (None, "") else None
            if any(v is not None for v in (h_xg, a_xg, h_sot, a_sot)):
                db.add(
                    MatchTeamStat(
                        match_id=match.id,
                        team_id=home_team.id,
                        is_home=True,
                        xg=h_xg,
                        shots_on_target=h_sot,
                        source_name=source_name,
                        is_demo=is_demo,
                    )
                )
                db.add(
                    MatchTeamStat(
                        match_id=match.id,
                        team_id=away_team.id,
                        is_home=False,
                        xg=a_xg,
                        shots_on_target=a_sot,
                        source_name=source_name,
                        is_demo=is_demo,
                    )
                )

            # Cuotas si están presentes
            oh = float(row["odds_home"]) if row.get("odds_home") not in (None, "") else None
            od = float(row["odds_draw"]) if row.get("odds_draw") not in (None, "") else None
            oa = float(row["odds_away"]) if row.get("odds_away") not in (None, "") else None
            if oh and od and oa and oh > 1.0 and od > 1.0 and oa > 1.0:
                odds_map = {"HOME": oh, "DRAW": od, "AWAY": oa}
                fair_map, margin = remove_bookmaker_margin(odds_map)
                for sel_key, odd_val in odds_map.items():
                    db.add(
                        OddsSnapshot(
                            match_id=match.id,
                            bookmaker_name=row.get("bookmaker", "Consenso Histórico"),
                            market_code="1X2",
                            selection_code=sel_key,
                            decimal_odds=odd_val,
                            implied_prob_raw=round(1.0 / odd_val, 5),
                            overround_margin=margin,
                            implied_prob_fair=fair_map[sel_key],
                            source_name=source_name,
                            is_demo=is_demo,
                        )
                    )

            inserted += 1

        db.commit()
        log = self.register_sync_event(
            db=db,
            endpoint_or_file=f"CSV:{source_name}",
            status="SUCCESS",
            records_processed=processed,
            records_inserted=inserted,
            duplicates=duplicates,
            missing_values=missing_values,
            notes=f"Licencia verificada: {source_license}",
        )
        return {
            "sync_log_id": log.id,
            "source_name": source_name,
            "source_license": source_license,
            "is_demo": is_demo,
            "records_processed": processed,
            "records_inserted": inserted,
            "duplicates_detected": duplicates,
            "missing_values_detected": missing_values,
        }

    def _get_or_create_team(
        self,
        db: Session,
        raw_name: str,
        country: str,
        source_name: str,
        is_demo: bool,
    ) -> Team:
        canonical = self.normalize_team_name(raw_name)
        alias = (
            db.query(TeamAlias)
            .filter(TeamAlias.provider_code == self.provider_code, TeamAlias.alias_name == raw_name)
            .first()
        )
        if alias:
            team = db.query(Team).filter(Team.id == alias.team_id).first()
            if team:
                return team

        team = db.query(Team).filter(Team.canonical_name == canonical).first()
        if not team:
            short = "".join(ch for ch in canonical.upper() if ch.isalpha())[:3] or "CLB"
            team = Team(
                canonical_name=canonical,
                short_code=short,
                country=country,
                current_elo=1500.0,
                source_name=source_name,
                is_demo=is_demo,
            )
            db.add(team)
            db.flush()

        db.add(
            TeamAlias(
                team_id=team.id,
                provider_code=self.provider_code,
                alias_name=raw_name,
            )
        )
        db.flush()
        return team
