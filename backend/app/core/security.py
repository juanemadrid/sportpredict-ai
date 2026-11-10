"""Autenticación y autorización de SPORTPREDICT AI.

Producción:
    - Identidad: JWT emitido por Supabase Auth (cabecera `Authorization: Bearer <token>`).
      Se valida firma, expiración, audiencia y emisor. Soporta secreto HS256 legacy
      (`SUPABASE_JWT_SECRET`) o claves asimétricas publicadas en JWKS (`SUPABASE_URL`).
    - Rol y plan: se leen del perfil local `user_profiles`, administrado solo por ADMIN.
      Nunca se confía en cabeceras enviadas por el cliente.

Desarrollo/pruebas (ENVIRONMENT != production y AUTH_ALLOW_DEV_HEADERS=true):
    - Se permite simular rol/plan con `X-User-Role` / `X-User-Plan` para inspección local.
"""

from dataclasses import dataclass
from datetime import datetime, timezone
import logging
import threading
from typing import Any, Dict, Optional

import jwt
from fastapi import Depends, Header, HTTPException, status

from app.core.config import settings


logger = logging.getLogger("sportpredict.security")


@dataclass(frozen=True)
class PlanCapabilities:
    plan_code: str
    display_name: str
    daily_analysis_limit: int
    allowed_market_tiers: int
    includes_odds_comparator: bool
    includes_full_history: bool
    includes_model_benchmarks: bool
    billing_active: bool = False  # Cobros aún no activados: los planes los asigna un ADMIN


PLAN_CATALOG: Dict[str, PlanCapabilities] = {
    "FREE": PlanCapabilities(
        plan_code="FREE",
        display_name="Gratuito",
        daily_analysis_limit=3,
        allowed_market_tiers=1,
        includes_odds_comparator=False,
        includes_full_history=False,
        includes_model_benchmarks=False,
    ),
    "PREMIUM": PlanCapabilities(
        plan_code="PREMIUM",
        display_name="Premium",
        daily_analysis_limit=50,
        allowed_market_tiers=2,
        includes_odds_comparator=True,
        includes_full_history=True,
        includes_model_benchmarks=False,
    ),
    "PRO": PlanCapabilities(
        plan_code="PRO",
        display_name="Profesional",
        daily_analysis_limit=9999,
        allowed_market_tiers=3,
        includes_odds_comparator=True,
        includes_full_history=True,
        includes_model_benchmarks=True,
    ),
}

VALID_ROLES = ("USER", "ANALYST", "ADMIN")


@dataclass
class RequestContext:
    role: str
    plan_code: str
    capabilities: PlanCapabilities
    user_id: Optional[str] = None
    email: Optional[str] = None
    auth_method: str = "none"  # none | jwt | dev_headers


def _anonymous() -> RequestContext:
    return RequestContext(role="ANONYMOUS", plan_code="FREE", capabilities=PLAN_CATALOG["FREE"])


# -----------------------------------------------------------------------------
# Validación de JWT de Supabase
# -----------------------------------------------------------------------------
_jwks_client: Optional[jwt.PyJWKClient] = None
_jwks_lock = threading.Lock()


def _get_jwks_client() -> jwt.PyJWKClient:
    global _jwks_client
    with _jwks_lock:
        if _jwks_client is None:
            base = (settings.SUPABASE_URL or "").rstrip("/")
            _jwks_client = jwt.PyJWKClient(f"{base}/auth/v1/.well-known/jwks.json", cache_keys=True, lifespan=3600)
        return _jwks_client


def decode_supabase_jwt(token: str) -> Dict[str, Any]:
    """Valida un access token de Supabase y devuelve sus claims. Lanza jwt.PyJWTError si es inválido."""
    issuer = f"{settings.SUPABASE_URL.rstrip('/')}/auth/v1" if settings.SUPABASE_URL else None
    options = {"require": ["exp", "sub"], "verify_iss": bool(issuer)}
    header = jwt.get_unverified_header(token)
    alg = header.get("alg", "")

    if alg == "HS256":
        if not settings.SUPABASE_JWT_SECRET:
            raise jwt.InvalidTokenError("Token HS256 recibido pero SUPABASE_JWT_SECRET no está configurado.")
        key: Any = settings.SUPABASE_JWT_SECRET
        algorithms = ["HS256"]
    elif alg in ("RS256", "ES256"):
        if not settings.SUPABASE_URL:
            raise jwt.InvalidTokenError("Token asimétrico recibido pero SUPABASE_URL no está configurado.")
        key = _get_jwks_client().get_signing_key_from_jwt(token).key
        algorithms = [alg]
    else:
        raise jwt.InvalidTokenError(f"Algoritmo JWT no permitido: {alg!r}")

    return jwt.decode(
        token,
        key=key,
        algorithms=algorithms,
        audience=settings.SUPABASE_JWT_AUDIENCE,
        issuer=issuer,
        options=options,
        leeway=30,
    )


def _resolve_profile_from_claims(claims: Dict[str, Any]) -> RequestContext:
    """Crea (si no existe) y devuelve el perfil local asociado al `sub` del token."""
    # Importación diferida: evita ciclos y respeta el reemplazo de SessionLocal en pruebas.
    import app.db.session as db_session
    from app.db.models import UserProfile

    user_id = str(claims["sub"])
    email = (claims.get("email") or "").strip().lower() or None
    app_meta = claims.get("app_metadata") or {}

    db = db_session.SessionLocal()
    try:
        profile = db.get(UserProfile, user_id)
        now = datetime.now(timezone.utc)
        if profile is None:
            initial_role = "USER"
            if email and email in settings.admin_emails_set:
                initial_role = "ADMIN"
            elif str(app_meta.get("role", "")).upper() in VALID_ROLES:
                # app_metadata solo es modificable con la service role key (no por el usuario).
                initial_role = str(app_meta["role"]).upper()
            profile = UserProfile(id=user_id, email=email, role=initial_role, plan_code="FREE", last_seen_at=now)
            db.add(profile)
        else:
            if email and email in settings.admin_emails_set and profile.role != "ADMIN":
                profile.role = "ADMIN"
            if email and profile.email != email:
                profile.email = email
            last = profile.last_seen_at
            if last is None or last.tzinfo is None or (now - last).total_seconds() > 300:
                profile.last_seen_at = now
        db.commit()

        if not profile.is_active:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Cuenta desactivada por un administrador.")

        caps = PLAN_CATALOG.get(profile.plan_code, PLAN_CATALOG["FREE"])
        role = profile.role if profile.role in VALID_ROLES else "USER"
        return RequestContext(
            role=role,
            plan_code=caps.plan_code,
            capabilities=caps,
            user_id=user_id,
            email=email,
            auth_method="jwt",
        )
    finally:
        db.close()


def get_request_context(
    x_user_role: Optional[str] = Header(default=None, alias="X-User-Role"),
    x_user_plan: Optional[str] = Header(default=None, alias="X-User-Plan"),
    authorization: Optional[str] = Header(default=None, alias="Authorization"),
) -> RequestContext:
    """Resuelve la identidad, el rol y el plan de la solicitud.

    1. Si llega `Authorization: Bearer <jwt>`, se valida contra Supabase (401 si es inválido).
    2. Si no hay token y el modo de cabeceras de desarrollo está habilitado (nunca en producción),
       se aceptan `X-User-Role` / `X-User-Plan`.
    3. En cualquier otro caso la solicitud es ANÓNIMA.
    """
    if isinstance(authorization, str) and authorization.strip():
        scheme, _, token = authorization.strip().partition(" ")
        if scheme.lower() != "bearer" or not token:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Cabecera Authorization inválida: se espera 'Bearer <token>'.",
                headers={"WWW-Authenticate": "Bearer"},
            )
        if not settings.is_auth_configured:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Autenticación no configurada en el servidor (SUPABASE_URL / SUPABASE_JWT_SECRET).",
            )
        try:
            claims = decode_supabase_jwt(token.strip())
        except jwt.PyJWTError as exc:
            logger.info("JWT rechazado: %s", exc)
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token de sesión inválido o expirado.",
                headers={"WWW-Authenticate": "Bearer"},
            ) from exc
        return _resolve_profile_from_claims(claims)

    if settings.dev_headers_enabled:
        raw_role = x_user_role.upper() if isinstance(x_user_role, str) and x_user_role else "ANONYMOUS"
        if raw_role not in VALID_ROLES:
            return _anonymous()
        plan_key = x_user_plan.upper() if isinstance(x_user_plan, str) and x_user_plan else "PRO"
        caps = PLAN_CATALOG.get(plan_key, PLAN_CATALOG["FREE"])
        return RequestContext(
            role=raw_role,
            plan_code=caps.plan_code,
            capabilities=caps,
            user_id=f"dev-{raw_role.lower()}",
            auth_method="dev_headers",
        )

    return _anonymous()


def require_authenticated_context(ctx: RequestContext) -> RequestContext:
    """Valida que la solicitud provenga de un usuario autenticado (USER, ANALYST o ADMIN).
    Rechaza usuarios no autenticados (sin header o anónimos) con HTTP 401 UNAUTHORIZED.
    """
    if ctx.role == "ANONYMOUS":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Autenticación requerida: debe incluir credenciales válidas o cabecera de autenticación.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return ctx


def require_admin_role(ctx: RequestContext) -> None:
    """Valida que el usuario esté autenticado (401 si anónimo) y posea rol de administrador (403 si no es ADMIN)."""
    if ctx.role == "ANONYMOUS":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Autenticación requerida: debe autenticarse para realizar esta operación.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if ctx.role != "ADMIN":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Acceso restringido: esta operación requiere rol ADMIN (entrenamiento o administración).",
        )


# -----------------------------------------------------------------------------
# Dependencias FastAPI reutilizables
# -----------------------------------------------------------------------------
def current_user(ctx: RequestContext = Depends(get_request_context)) -> RequestContext:
    """Dependencia: exige usuario autenticado (401 si anónimo).
    Reutiliza el resultado cacheado de `get_request_context` dentro de la misma solicitud.
    """
    return require_authenticated_context(ctx)


def current_admin(ctx: RequestContext = Depends(current_user)) -> RequestContext:
    """Dependencia: exige rol ADMIN (401 anónimo / 403 no-admin)."""
    require_admin_role(ctx)
    return ctx


def enforce_daily_analysis_quota(ctx: RequestContext, metric: str = "match_analysis") -> Dict[str, int]:
    """Incrementa y valida el contador diario del usuario según su plan. 429 si se excede.
    Los ADMIN y las sesiones de desarrollo no consumen cuota.
    """
    limit = ctx.capabilities.daily_analysis_limit
    if ctx.role == "ADMIN" or ctx.auth_method != "jwt" or not ctx.user_id:
        return {"used": 0, "limit": limit}

    import app.db.session as db_session
    from app.db.models import UsageCounter

    today = datetime.now(timezone.utc).date()
    db = db_session.SessionLocal()
    try:
        row = (
            db.query(UsageCounter)
            .filter(
                UsageCounter.user_id == ctx.user_id,
                UsageCounter.usage_date == today,
                UsageCounter.metric == metric,
            )
            .with_for_update()
            .first()
        )
        if row is None:
            row = UsageCounter(user_id=ctx.user_id, usage_date=today, metric=metric, count=0)
            db.add(row)
        if row.count >= limit:
            db.rollback()
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=(
                    f"Límite diario del plan {ctx.capabilities.display_name} alcanzado "
                    f"({limit} análisis/día). Se restablece a las 00:00 UTC."
                ),
            )
        row.count += 1
        db.commit()
        return {"used": row.count, "limit": limit}
    finally:
        db.close()


def usage_today(user_id: Optional[str], metric: str = "match_analysis") -> int:
    if not user_id:
        return 0
    import app.db.session as db_session
    from app.db.models import UsageCounter

    db = db_session.SessionLocal()
    try:
        row = (
            db.query(UsageCounter)
            .filter(
                UsageCounter.user_id == user_id,
                UsageCounter.usage_date == datetime.now(timezone.utc).date(),
                UsageCounter.metric == metric,
            )
            .first()
        )
        return row.count if row else 0
    finally:
        db.close()
