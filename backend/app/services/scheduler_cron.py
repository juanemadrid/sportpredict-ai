"""Daemon periódico para ejecución automática del ciclo de Fase 5 en producción.
Ejecuta el ciclo cada N minutos (por defecto 360 = 6 horas).
"""

import argparse
import logging
import sys
import time

from app.core.config import settings
import app.db.session as db_session
from app.services.scheduler import daily_automation

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s [%(name)s] %(message)s")
logger = logging.getLogger("sportpredict.scheduler_daemon")


def run_cycle_once() -> None:
    db = db_session.SessionLocal()
    try:
        report = daily_automation.run_daily_cycle(db)
        logger.info(
            "Ciclo de Fase 5 completado con éxito: %s prospectivos registrados, %s liquidados",
            report.get("prospective_registered", 0),
            report.get("prospective_settled", 0),
        )
    finally:
        db.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Ejecutor de ciclo de Fase 5")
    parser.add_argument("--once", action="store_true", help="Ejecuta el ciclo una sola vez y finaliza (apto para cron)")
    args = parser.parse_args()

    if args.once:
        run_cycle_once()
        return

    interval_seconds = max(settings.SCHEDULER_INTERVAL_MINUTES * 60, 300)
    logger.info("Iniciando scheduler daemon de Fase 5 (intervalo: %s segundos)...", interval_seconds)

    while True:
        try:
            run_cycle_once()
        except Exception as exc:
            logger.exception("Error durante la ejecución del ciclo diario: %s", exc)

        time.sleep(interval_seconds)


if __name__ == "__main__":
    main()
