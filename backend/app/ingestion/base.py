from abc import ABC, abstractmethod
from datetime import date, datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Any, Dict, Optional
from sqlalchemy.orm import Session

from app.core.config import CACHE_DIR
from app.db.models import DataSource, SyncLog


class DataProviderAdapter(ABC):
    """Interfaz base para proveedores de datos deportivos intercambiables (Sección 7).
    Incluye control de cuotas diarias, caché persistente, validación de datos,
    identificación de fuente/licencia y registro de última sincronización.
    """

    provider_code: str = "BASE"
    display_name: str = "Base Provider"
    license_type: str = "Unknown"
    daily_quota_limit: int = 100
    is_demo: bool = False

    def get_or_init_source(self, db: Session) -> DataSource:
        src = db.query(DataSource).filter(DataSource.provider_code == self.provider_code).first()
        today = date.today()
        if not src:
            src = DataSource(
                provider_code=self.provider_code,
                display_name=self.display_name,
                license_type=self.license_type,
                daily_quota_limit=self.daily_quota_limit,
                requests_used_today=0,
                quota_reset_date=today,
                status="ACTIVE" if self.is_configured() else "NOT_CONFIGURED",
                is_demo=self.is_demo,
            )
            db.add(src)
            db.commit()
            db.refresh(src)
        else:
            if src.quota_reset_date != today:
                src.requests_used_today = 0
                src.quota_reset_date = today
                db.commit()
        return src

    @abstractmethod
    def is_configured(self) -> bool:
        pass

    def check_quota_available(self, db: Session) -> bool:
        src = self.get_or_init_source(db)
        return src.requests_used_today < src.daily_quota_limit

    def register_sync_event(
        self,
        db: Session,
        endpoint_or_file: str,
        status: str,
        records_processed: int = 0,
        records_inserted: int = 0,
        duplicates: int = 0,
        missing_values: int = 0,
        increment_quota: bool = False,
        notes: Optional[str] = None,
    ) -> SyncLog:
        src = self.get_or_init_source(db)
        if increment_quota:
            src.requests_used_today += 1
        src.last_sync_at = datetime.now(timezone.utc)
        if src.requests_used_today >= src.daily_quota_limit:
            src.status = "QUOTA_EXHAUSTED"
        elif self.is_configured():
            src.status = "ACTIVE"
        else:
            src.status = "NOT_CONFIGURED"

        log = SyncLog(
            source_id=src.id,
            endpoint_or_file=endpoint_or_file,
            records_processed=records_processed,
            records_inserted=records_inserted,
            duplicates_detected=duplicates,
            missing_values_detected=missing_values,
            status=status,
            notes=notes,
        )
        db.add(log)
        db.commit()
        db.refresh(log)
        return log

    def get_cached_response(self, cache_key: str, max_age_seconds: int = 21600) -> Optional[Dict[str, Any]]:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        digest = hashlib.sha256(f"{self.provider_code}:{cache_key}".encode("utf-8")).hexdigest()[:24]
        path: Path = CACHE_DIR / f"{self.provider_code.lower()}_{digest}.json"
        if not path.exists():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            cached_ts = payload.get("_cached_ts", 0)
            now_ts = datetime.now(timezone.utc).timestamp()
            if now_ts - cached_ts <= max_age_seconds:
                return payload.get("data")
        except Exception:
            return None
        return None

    def save_cached_response(self, cache_key: str, data: Dict[str, Any]) -> None:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        digest = hashlib.sha256(f"{self.provider_code}:{cache_key}".encode("utf-8")).hexdigest()[:24]
        path: Path = CACHE_DIR / f"{self.provider_code.lower()}_{digest}.json"
        payload = {
            "_cached_ts": datetime.now(timezone.utc).timestamp(),
            "_provider": self.provider_code,
            "data": data,
        }
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
