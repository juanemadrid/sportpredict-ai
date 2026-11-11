from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.security import RequestContext, get_request_context, require_admin_role
from app.db.models import DataSource, SyncLog
from app.db.session import get_db
from app.ingestion.api_football import APIFootballAdapter
from app.ingestion.csv_importer import AuthorizedCSVImporter
from app.ingestion.real_open_data_fetcher import OpenFootballRealDataAdapter

router = APIRouter(prefix="/api/v1/ingestion", tags=["Data Ingestion & Providers"])


class CSVImportPayload(BaseModel):
    csv_content: str = Field(max_length=5_000_000)
    source_name: str = Field(default="Kaggle_Authorized_Dataset", max_length=120)
    source_license: str = Field(default="CC BY-SA 4.0 / Autorizado", max_length=200)
    is_demo: bool = False


class APIFootballSyncPayload(BaseModel):
    # Por defecto: fecha actual (UTC). Formato YYYY-MM-DD.
    date_iso: Optional[str] = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")


@router.post("/openfootball/sync")
def sync_openfootball_public_domain_history(
    db: Session = Depends(get_db),
    ctx: RequestContext = Depends(get_request_context),
):
    """Descarga e importa el conjunto histórico real de fútbol europeo desde OpenFootball (CC0-1.0 Dominio Público),
    ejecutando el pipeline de calidad de datos de la FASE 2 (normalización, deduplicación, validación de marcadores).
    """
    require_admin_role(ctx)
    adapter = OpenFootballRealDataAdapter()
    return adapter.download_and_ingest_real_history(db=db)


@router.post("/csv")
def import_authorized_csv(
    payload: CSVImportPayload,
    db: Session = Depends(get_db),
    ctx: RequestContext = Depends(get_request_context),
):
    """Importa un archivo CSV autorizado validando columnas, duplicados, nulos,
    normalización de equipos y licencia compatible (Secciones 7 y 8).
    """
    require_admin_role(ctx)
    importer = AuthorizedCSVImporter()
    try:
        result = importer.import_csv_content(
            db=db,
            csv_text=payload.csv_content,
            source_name=payload.source_name,
            source_license=payload.source_license,
            is_demo=payload.is_demo,
        )
        return result
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/api-football/sync")
def sync_api_football_date(
    payload: APIFootballSyncPayload,
    db: Session = Depends(get_db),
    ctx: RequestContext = Depends(get_request_context),
):
    """Sincroniza encuentros desde API-Football respetando caché y límite de 100 solicitudes/día.
    Si no existe API_FOOTBALL_KEY real en .env, informa estado NOT_CONFIGURED sin simular llamadas.
    """
    require_admin_role(ctx)
    adapter = APIFootballAdapter()
    return adapter.fetch_fixtures_by_date(
        db=db, date_iso=payload.date_iso or datetime.now(timezone.utc).date().isoformat()
    )


@router.post("/today-real/sync")
def sync_today_real_fixtures_endpoint(
    db: Session = Depends(get_db),
    ctx: RequestContext = Depends(get_request_context),
):
    """Sincroniza los partidos reales de hoy y carga mercados de Betplay (Córners, Goles, BTTS, 1X2)."""
    require_admin_role(ctx)
    from app.ingestion.sync_real_today_matches import sync_real_matches
    sync_real_matches()
    return {"status": "SUCCESS", "message": "Partidos reales de hoy y cuotas de Betplay sincronizados."}


@router.get("/logs")
def get_ingestion_sync_logs(
    db: Session = Depends(get_db),
    ctx: RequestContext = Depends(get_request_context),
):
    require_admin_role(ctx)
    logs = db.query(SyncLog).order_by(SyncLog.executed_at.desc()).limit(40).all()
    sources = {s.id: s.provider_code for s in db.query(DataSource).all()}
    return {
        "count": len(logs),
        "items": [
            {
                "id": l.id,
                "provider_code": sources.get(l.source_id, "UNKNOWN"),
                "endpoint_or_file": l.endpoint_or_file,
                "records_processed": l.records_processed,
                "records_inserted": l.records_inserted,
                "duplicates_detected": l.duplicates_detected,
                "missing_values_detected": l.missing_values_detected,
                "status": l.status,
                "notes": l.notes,
                "executed_at": l.executed_at.isoformat(),
            }
            for l in logs
        ],
    }
