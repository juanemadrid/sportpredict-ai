from typing import Any, Dict, List
from sqlalchemy.orm import Session

from app.ingestion.base import DataProviderAdapter


class StatsBombOpenDataAdapter(DataProviderAdapter):
    """Adaptador para StatsBomb Open Data (Sección 7 - Fuentes para Investigación).
    Licencia: CC BY-NC-SA 4.0.
    Permite procesar estructuras de partidos y tiros con Goles Esperados (xG) nativos.
    """

    provider_code = "STATSBOMB_OPEN"
    display_name = "StatsBomb Open Data (Investigación)"
    license_type = "CC BY-NC-SA 4.0"
    daily_quota_limit = 5000
    is_demo = False

    def is_configured(self) -> bool:
        return True

    def summarize_events_xg(self, db: Session, events_json: List[Dict[str, Any]], match_ref: str) -> Dict[str, Any]:
        """Calcula xG acumulado, tiros y tiros a puerta a partir de una lista de eventos StatsBomb."""
        team_totals: Dict[str, Dict[str, float]] = {}
        for ev in events_json:
            if ev.get("type", {}).get("name") != "Shot":
                continue
            team_name = ev.get("team", {}).get("name", "Unknown")
            shot_data = ev.get("shot", {})
            xg_val = float(shot_data.get("statsbomb_xg", 0.0))
            outcome_name = shot_data.get("outcome", {}).get("name", "")
            on_target = outcome_name in ("Goal", "Saved", "Saved to Post")

            bucket = team_totals.setdefault(team_name, {"shots": 0.0, "shots_on_target": 0.0, "xg": 0.0})
            bucket["shots"] += 1
            if on_target:
                bucket["shots_on_target"] += 1
            bucket["xg"] = round(bucket["xg"] + xg_val, 3)

        self.register_sync_event(
            db=db,
            endpoint_or_file=f"StatsBombEvents:{match_ref}",
            status="SUCCESS",
            records_processed=len(events_json),
            records_inserted=len(team_totals),
            notes="Agregación de tiros y xG desde formato StatsBomb Open Data.",
        )
        return {
            "provider": self.provider_code,
            "license": self.license_type,
            "match_ref": match_ref,
            "team_metrics": team_totals,
        }
