"""Observabilidad y endurecimiento HTTP: logging estructurado, request-id, cabeceras de
seguridad, limitación de tasa por IP y manejo centralizado de errores."""

from collections import deque
import json
import logging
import sys
import threading
import time
from typing import Deque, Dict
import uuid

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from app.core.config import settings


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(record.created)) + "Z",
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        for key in ("request_id", "method", "path", "status", "duration_ms", "client_ip", "user_id"):
            val = getattr(record, key, None)
            if val is not None:
                payload[key] = val
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


def configure_logging() -> None:
    root = logging.getLogger()
    if getattr(root, "_sportpredict_configured", False):
        return
    handler = logging.StreamHandler(sys.stdout)
    if settings.LOG_JSON:
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s [%(name)s] %(message)s"))
    root.handlers = [handler]
    root.setLevel(settings.LOG_LEVEL.upper())
    root._sportpredict_configured = True  # type: ignore[attr-defined]


access_logger = logging.getLogger("sportpredict.access")
error_logger = logging.getLogger("sportpredict.error")


def client_ip(request: Request) -> str:
    if settings.TRUSTED_PROXY_HEADERS:
        fwd = request.headers.get("x-forwarded-for")
        if fwd:
            return fwd.split(",")[0].strip()
        real = request.headers.get("x-real-ip")
        if real:
            return real.strip()
    return request.client.host if request.client else "unknown"


class SlidingWindowRateLimiter:
    """Limitador en memoria por clave (ventana deslizante de 60 s).
    Nota: es por proceso. Con varias réplicas, el límite efectivo se multiplica por réplica.
    """

    def __init__(self, limit_per_minute: int) -> None:
        self.limit = limit_per_minute
        self._hits: Dict[str, Deque[float]] = {}
        self._lock = threading.Lock()
        self._last_gc = time.monotonic()

    def allow(self, key: str) -> bool:
        now = time.monotonic()
        with self._lock:
            q = self._hits.setdefault(key, deque())
            while q and now - q[0] > 60.0:
                q.popleft()
            if len(q) >= self.limit:
                return False
            q.append(now)
            if now - self._last_gc > 300:
                for k in [k for k, v in self._hits.items() if not v or now - v[-1] > 60.0]:
                    self._hits.pop(k, None)
                self._last_gc = now
            return True


SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "Permissions-Policy": "geolocation=(), microphone=(), camera=()",
    "Cross-Origin-Opener-Policy": "same-origin",
}


class RequestContextMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, limiter: SlidingWindowRateLimiter) -> None:  # type: ignore[no-untyped-def]
        super().__init__(app)
        self.limiter = limiter

    async def dispatch(self, request: Request, call_next):  # type: ignore[no-untyped-def]
        request_id = request.headers.get("x-request-id") or uuid.uuid4().hex
        request.state.request_id = request_id
        ip = client_ip(request)
        start = time.perf_counter()

        path = request.url.path
        if self.limiter.limit > 0 and path not in ("/health", "/ready") and request.method != "OPTIONS":
            if not self.limiter.allow(ip):
                resp = JSONResponse(
                    status_code=429,
                    content={"detail": "Demasiadas solicitudes. Intenta de nuevo en un minuto.", "request_id": request_id},
                    headers={"Retry-After": "60"},
                )
                resp.headers["X-Request-ID"] = request_id
                return resp

        response = await call_next(request)
        duration_ms = round((time.perf_counter() - start) * 1000, 1)
        response.headers["X-Request-ID"] = request_id
        for k, v in SECURITY_HEADERS.items():
            response.headers.setdefault(k, v)
        if settings.is_production:
            response.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")

        if path not in ("/health",):
            access_logger.info(
                "%s %s %s %sms",
                request.method,
                path,
                response.status_code,
                duration_ms,
                extra={
                    "request_id": request_id,
                    "method": request.method,
                    "path": path,
                    "status": response.status_code,
                    "duration_ms": duration_ms,
                    "client_ip": ip,
                },
            )
        return response


def install_observability(app: FastAPI) -> None:
    app.add_middleware(RequestContextMiddleware, limiter=SlidingWindowRateLimiter(settings.RATE_LIMIT_PER_MINUTE))

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception):  # type: ignore[no-untyped-def]
        request_id = getattr(request.state, "request_id", None)
        error_logger.exception(
            "Error no controlado en %s %s", request.method, request.url.path, extra={"request_id": request_id}
        )
        detail = "Error interno del servidor." if settings.is_production else f"{type(exc).__name__}: {exc}"
        return JSONResponse(status_code=500, content={"detail": detail, "request_id": request_id})
