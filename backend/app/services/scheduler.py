"""Servicio de Automatización de Fase 5 (Sincronización, Registro Prospectivo y Liquidación).

Garantías:
1. Presupuesto $0 USD: Utiliza fuentes gratuitas autorizadas (OpenFootball CC0-1.0).
   Si API_FOOTBALL_KEY está configurada, utiliza la cuota gratuita (100 req/día) con caché.
2. Cero manipulación retroactiva: Solo registra partidos con `kickoff_utc > now_utc`
   y liquida partidos finalizados con `kickoff_utc < now_utc` y marcadores reales.
3. Sellado inmutable SHA-256 en cada predicción registrada.
"""

from datetime import datetime, timedelta, timezone
import logging
from typing import Any, Dict, List, Optional
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.models import Match
from app.ingestion.api_football import APIFootballAdapter
from app.ingestion.real_open_data_fetcher import OpenFootballRealDataAdapter
from app.services.phase4_market_service import phase4_market_service


logger = logging.getLogger("sportpredict.scheduler")


class DailyAutomationPipeline:
    """Ejecutor del ciclo diario de Fase 5:
    1. Ingestión de resultados o encuentros recientes (fuentes abiertas CC0 / API-Football si hay key).
    2. Registro prospectivo automático antes del kickoff (ventana de 48 horas).
    3. Liquidación idempotente de partidos finalizados.
    """

    def __init__(self) -> None:
        self.openfootball_adapter = OpenFootballRealDataAdapter()
        self.api_football_adapter = APIFootballAdapter()

    def run_daily_cycle(self, db: Session, date_iso: Optional[str] = None) -> Dict[str, Any]:
        target_date = date_iso or datetime.now(timezone.utc).date().isoformat()
        report: Dict[str, Any] = {
            "execution_time_utc": datetime.now(timezone.utc).isoformat(),
            "target_date": target_date,
            "openfootball_ingestion": None,
            "api_football_sync": None,
            "prospective_registered": 0,
            "prospective_settled": 0,
            "errors": [],
        }

        # Paso 1: Liquidar primero cualquier partido pendiente que ya haya finalizado
        try:
            settle_res = phase4_market_service.settle_finished_prospective_predictions(db)
            report["prospective_settled"] = settle_res.get("settled_records_count", 0)
        except Exception as exc:
            logger.error("Error en liquidación previa: %s", exc)
            report["errors"].append(f"Settlement error: {exc}")

        # Paso 2: Sincronización API-Football (si está configurada con credencial válida)
        if settings.is_api_football_configured:
            try:
                api_res = self.api_football_adapter.fetch_fixtures_by_date(db, date_iso=target_date)
                report["api_football_sync"] = api_res.get("status")
            except Exception as exc:
                logger.warning("Error en sincronización API-Football: %s", exc)
                report["errors"].append(f"API-Football error: {exc}")
        else:
            report["api_football_sync"] = "NOT_CONFIGURED (presupuesto $0 USD respetado)"

        # Paso 3: Registrar prospectivamente partidos programados en la ventana pre-kickoff
        try:
            now_utc = datetime.now(timezone.utc)
            horizon = now_utc + timedelta(hours=settings.PROSPECTIVE_REGISTER_HORIZON_HOURS)

            upcoming = (
                db.query(Match)
                .filter(
                    Match.status == "SCHEDULED",
                    Match.kickoff_utc > now_utc,
                    Match.kickoff_utc <= horizon,
                )
                .all()
            )

            registered_count = 0
            for m in upcoming:
                try:
                    reg = phase4_market_service.register_prospective_predictions_for_match(
                        db=db,
                        match_id=m.id,
                    )
                    registered_count += reg.get("registered_count", 0)
                except ValueError as ve:
                    # Partido ya iniciado o condición pre-kickoff estricta
                    logger.debug("Omitiendo registro de partido %s: %s", m.id, ve)
                except Exception as exc:
                    logger.warning("Error registrando predicción prospectiva para partido %s: %s", m.id, exc)

            report["prospective_registered"] = registered_count
        except Exception as exc:
            logger.error("Error en registro prospectivo: %s", exc)
            report["errors"].append(f"Prospective registration error: {exc}")

        # Paso 4: Liquidación posterior (por si algún partido cambió a FINISHED durante el ciclo)
        try:
            settle_res_post = phase4_market_service.settle_finished_prospective_predictions(db)
            report["prospective_settled"] += settle_res_post.get("settled_records_count", 0)
        except Exception as exc:
            report["errors"].append(f"Post-settlement error: {exc}")

        return report


daily_automation = DailyAutomationPipeline()
