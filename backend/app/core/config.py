from pathlib import Path
from typing import List, Optional
from pydantic_settings import BaseSettings, SettingsConfigDict


BASE_DIR = Path(__file__).resolve().parent.parent.parent
DATA_DIR = BASE_DIR / "data"
ARTIFACTS_DIR = BASE_DIR / "artifacts" / "models"
CACHE_DIR = DATA_DIR / "cache"


class Settings(BaseSettings):
    """Configuración central de SPORTPREDICT AI.
    Cumple estrictamente la regla de NO introducir claves API ficticias ni simular conexiones.
    """

    PROJECT_NAME: str = "SPORTPREDICT AI"
    VERSION: str = "1.0.0"
    # development | test | production
    ENVIRONMENT: str = "development"

    # Si DATABASE_URL está vacío, utiliza SQLite local aislado dentro del proyecto (solo desarrollo).
    # En producción es obligatorio PostgreSQL (Supabase o propio).
    DATABASE_URL: Optional[str] = None
    DB_POOL_SIZE: int = 5
    DB_MAX_OVERFLOW: int = 10

    # Supabase Auth (independiente)
    SUPABASE_URL: Optional[str] = None
    SUPABASE_ANON_KEY: Optional[str] = None
    # Secreto JWT legacy (HS256). Si se deja vacío se validan tokens asimétricos vía JWKS.
    SUPABASE_JWT_SECRET: Optional[str] = None
    SUPABASE_JWT_AUDIENCE: str = "authenticated"

    # Correos que reciben rol ADMIN automáticamente al primer inicio de sesión (separados por coma).
    ADMIN_EMAILS: str = ""

    # Solo desarrollo/pruebas: permite simular rol/plan con cabeceras X-User-Role / X-User-Plan.
    # Se ignora SIEMPRE cuando ENVIRONMENT=production.
    AUTH_ALLOW_DEV_HEADERS: bool = False

    # Seguridad HTTP
    CORS_ORIGINS: str = "http://localhost:3000"
    RATE_LIMIT_PER_MINUTE: int = 120
    TRUSTED_PROXY_HEADERS: bool = False
    ENABLE_API_DOCS: bool = True

    # Datos
    SEED_DEMO_DATA: bool = True

    # Observabilidad
    LOG_LEVEL: str = "INFO"
    LOG_JSON: bool = False

    # Planificador (Fase 5)
    SCHEDULER_INTERVAL_MINUTES: int = 360
    PROSPECTIVE_REGISTER_HORIZON_HOURS: int = 48

    # API-Football v3 (sin clave ficticia; vacío = NOT_CONFIGURED)
    API_FOOTBALL_KEY: Optional[str] = None
    API_FOOTBALL_BASE_URL: str = "https://v3.football.api-sports.io"
    API_FOOTBALL_DAILY_LIMIT: int = 100

    model_config = SettingsConfigDict(
        env_file=str(BASE_DIR.parent / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @property
    def is_production(self) -> bool:
        return self.ENVIRONMENT.strip().lower() == "production"

    @property
    def dev_headers_enabled(self) -> bool:
        return self.AUTH_ALLOW_DEV_HEADERS and not self.is_production

    @property
    def cors_origins_list(self) -> List[str]:
        origins = [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]
        for default_origin in ["http://localhost:3000", "https://juanemadrid.github.io"]:
            if default_origin not in origins:
                origins.append(default_origin)
        return origins

    @property
    def admin_emails_set(self) -> set:
        return {e.strip().lower() for e in self.ADMIN_EMAILS.split(",") if e.strip()}

    @property
    def effective_database_url(self) -> str:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        if self.DATABASE_URL and self.DATABASE_URL.strip():
            url = self.DATABASE_URL.strip()
            # Normaliza URLs de Supabase/Heroku al driver psycopg v3.
            if url.startswith("postgres://"):
                url = "postgresql+psycopg://" + url[len("postgres://"):]
            elif url.startswith("postgresql://"):
                url = "postgresql+psycopg://" + url[len("postgresql://"):]
            return url
        db_path = (DATA_DIR / "sportpredict_local.db").as_posix()
        return f"sqlite:///{db_path}"

    @property
    def is_postgres(self) -> bool:
        return self.effective_database_url.startswith("postgresql")

    @property
    def is_supabase_configured(self) -> bool:
        return bool(self.DATABASE_URL and "postgres" in self.DATABASE_URL.lower())

    @property
    def is_auth_configured(self) -> bool:
        return bool(self.SUPABASE_URL or self.SUPABASE_JWT_SECRET)

    @property
    def is_api_football_configured(self) -> bool:
        return bool(self.API_FOOTBALL_KEY and len(self.API_FOOTBALL_KEY.strip()) > 5)

    def validate_for_production(self) -> List[str]:
        """Devuelve la lista de errores de configuración que impiden arrancar en producción."""
        errors: List[str] = []
        if not self.is_production:
            return errors
        if not self.is_postgres:
            errors.append("DATABASE_URL debe apuntar a PostgreSQL en producción.")
        if not self.SUPABASE_URL:
            errors.append("SUPABASE_URL es obligatorio en producción (validación de JWT).")
        if "*" in self.cors_origins_list or not self.cors_origins_list:
            errors.append("CORS_ORIGINS debe listar dominios explícitos (no '*') en producción.")
        if self.SEED_DEMO_DATA:
            errors.append("SEED_DEMO_DATA debe ser false en producción.")
        return errors


settings = Settings()
