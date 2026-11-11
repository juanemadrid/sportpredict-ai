"""Script de inicialización segura e idempotente de base de datos para producción.

Se ejecuta una sola vez en el contenedor antes de levantar los workers del servidor web
para evitar condiciones de carrera (race conditions) en DDL con PostgreSQL.
"""
import logging
import sys

from app.core.config import settings
import app.db.session as db_session
from app.db.init_db import init_database
from app.services.phase4_market_service import phase4_market_service

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("sportpredict.ensure_db")


def main() -> None:
    logger.info("Iniciando ensure_db (db_type=%s)...", "postgresql" if settings.is_postgres else "sqlite")
    db = db_session.SessionLocal()
    try:
        init_database(db)
        phase4_market_service.ensure_phase4_tables_and_triggers(db)
        from app.services.prediction_service import prediction_service
        prediction_service.train_and_validate_all_models(db, version_tag="v1.0.0-prod")
        try:
            from app.ingestion.sync_real_today_matches import sync_real_matches
            sync_real_matches()
        except Exception as sync_exc:
            logger.warning("Sincronización inicial de partidos reales diferida: %s", sync_exc)
        logger.info("Base de datos, modelos IA y catálogos inicializados exitosamente.")
    except Exception as exc:
        logger.error("Error durante ensure_db: %s", exc, exc_info=True)
        sys.exit(1)
    finally:
        db.close()


if __name__ == "__main__":
    main()
