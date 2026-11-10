from typing import Any, Dict
import httpx
from sqlalchemy.orm import Session

from app.core.config import settings
from app.ingestion.base import DataProviderAdapter


class APIFootballAdapter(DataProviderAdapter):
    """Adaptador independiente para API-Football (v3.football.api-sports.io).
    - Respeta el límite gratuito de 100 solicitudes diarias.
    - Implementa caché local por endpoint/parámetros para minimizar consumo.
    - NUNCA utiliza claves ficticias ni simula conexiones si la clave no está configurada.
    """

    provider_code = "API_FOOTBALL"
    display_name = "API-Football v3 (api-sports.io)"
    license_type = "API-Sports Terms (Free Tier 100 req/día)"
    daily_quota_limit = settings.API_FOOTBALL_DAILY_LIMIT
    is_demo = False

    def is_configured(self) -> bool:
        return settings.is_api_football_configured

    def fetch_fixtures_by_date(self, db: Session, date_iso: str) -> Dict[str, Any]:
        cache_key = f"fixtures:date={date_iso}"
        cached = self.get_cached_response(cache_key, max_age_seconds=14400)
        if cached is not None:
            self.register_sync_event(
                db=db,
                endpoint_or_file=f"/fixtures?date={date_iso}",
                status="CACHE_HIT",
                records_processed=len(cached.get("response", [])),
                increment_quota=False,
                notes="Respuesta servida desde caché local sin consumir cuota diaria.",
            )
            return {"status": "CACHE_HIT", "is_demo": False, "data": cached}

        if not self.is_configured():
            self.register_sync_event(
                db=db,
                endpoint_or_file=f"/fixtures?date={date_iso}",
                status="NOT_CONFIGURED",
                increment_quota=False,
                notes="API_FOOTBALL_KEY no configurada en .env. No se simulan conexiones.",
            )
            return {
                "status": "NOT_CONFIGURED",
                "is_demo": False,
                "message": (
                    "API-Football no tiene una clave real configurada en .env (API_FOOTBALL_KEY). "
                    "Por política de integridad, no se introducen claves ficticias ni se simulan llamadas."
                ),
            }

        if not self.check_quota_available(db):
            self.register_sync_event(
                db=db,
                endpoint_or_file=f"/fixtures?date={date_iso}",
                status="BLOCKED_QUOTA",
                increment_quota=False,
                notes="Límite diario de 100 solicitudes alcanzado.",
            )
            return {
                "status": "QUOTA_EXHAUSTED",
                "is_demo": False,
                "message": "Se alcanzó el límite diario de 100 solicitudes de API-Football.",
            }

        headers = {"x-apisports-key": settings.API_FOOTBALL_KEY.strip()}
        url = f"{settings.API_FOOTBALL_BASE_URL}/fixtures"
        try:
            with httpx.Client(timeout=12.0) as client:
                resp = client.get(url, params={"date": date_iso}, headers=headers)
                resp.raise_for_status()
                payload = resp.json()
            self.save_cached_response(cache_key, payload)
            items = payload.get("response", [])
            self.register_sync_event(
                db=db,
                endpoint_or_file=f"/fixtures?date={date_iso}",
                status="SUCCESS",
                records_processed=len(items),
                increment_quota=True,
                notes="Sincronización real desde API-Football v3.",
            )
            return {"status": "SUCCESS", "is_demo": False, "data": payload}
        except Exception as exc:
            self.register_sync_event(
                db=db,
                endpoint_or_file=f"/fixtures?date={date_iso}",
                status="ERROR",
                increment_quota=True,
                notes=f"Error de red/API: {exc}",
            )
            return {"status": "ERROR", "is_demo": False, "message": str(exc)}
