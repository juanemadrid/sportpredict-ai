import json
from pathlib import Path
import sys

BACKEND_ROOT = Path(__file__).resolve().parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.core.config import DATA_DIR
from app.db.init_db import init_database
from app.db.session import SessionLocal
from app.ingestion.real_open_data_fetcher import OpenFootballRealDataAdapter
from app.services.prediction_service import prediction_service


def main() -> None:
    db = SessionLocal()
    try:
        # Asegura que el estado de la Fase 1 esté inicializado sin alterarlo
        init_database(db)

        print("1. Ejecutando ingestión de datos históricos reales (OpenFootball CC0-1.0 Public Domain)...")
        adapter = OpenFootballRealDataAdapter()
        quality_report = adapter.download_and_ingest_real_history(db=db)

        out_dir = DATA_DIR / "real_historical"
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "phase2_quality_report.json").write_text(
            json.dumps(quality_report, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print("Reporte de calidad guardado:", json.dumps(quality_report, ensure_ascii=False))

        print("2. Entrenando modelos v2.0.0-real-cc0 exclusivamente con partidos históricos reales (is_demo=False)...")
        training_report = prediction_service.train_and_validate_all_models(
            db=db,
            version_tag="v2.0.0-real-cc0",
            calibration_method="sigmoid",
            real_only=True,
        )
        (out_dir / "phase2_training_report.json").write_text(
            json.dumps(training_report, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print("Entrenamiento Fase 2 completado:", training_report["version"])
        print("Particiones cronológicas:", json.dumps(training_report["chronological_splits"], ensure_ascii=False))
        print("Pesos del Ensamble:", json.dumps(training_report["ensemble_weights"], ensure_ascii=False))
        print("Notas de exclusión/poda:", json.dumps(training_report["excluded_models"], ensure_ascii=False))
        for m_code, m_info in training_report["models"].items():
            tm = m_info["test_metrics"]
            print(
                f"  {m_code:14s} | Weight: {m_info['ensemble_weight']:.4f} | "
                f"Val Brier: {m_info['validation_brier']:.5f} | "
                f"Test Brier: {tm['brier_score']:.5f} (CI95: {tm['confidence_intervals_95'].get('brier_ci_95')}) | "
                f"Base Brier: {tm['baseline_brier_score']:.5f} | "
                f"Test LogLoss: {tm['log_loss']:.5f} | "
                f"ECE: {tm['ece_calibration']:.5f} | "
                f"Acc: {tm['accuracy']:.4f}"
            )
    finally:
        db.close()


if __name__ == "__main__":
    main()
