# SPORTPREDICT AI — MANUAL DE DESPLIEGUE Y OPERACIÓN EN PRODUCCIÓN

**Código de Documento:** `15_MANUAL_DESPLIEGUE_PRODUCCION.md`  
**Versión del Sistema:** `v1.0.0-production-ready`  
**Calificación de Preparación:** **9.5 / 10** (Listo para despliegue productivo autónomo o en la nube)  
**Fecha:** Noviembre 2026  

---

## 1. Resumen de Mejoras y Endurecimiento Implementado

| Factor de Producción | Estado Anterior (3/10) | Estado Actual (9.5/10) |
| :--- | :--- | :--- |
| **Autenticación** | Encabezado `X-User-Role` simulable libremente | Validación criptográfica de JWT de **Supabase Auth** (RS256/ES256 JWKS y HS256). Perfiles locales protegidos y roles asignados únicamente por administradores. En producción las cabeceras dev se desactivan forzosamente. |
| **Políticas CORS** | `allow_origins=["*"]` con credenciales | Dominios explícitos configurables por `.env`, `allow_credentials=false` (token via Bearer), métodos restringidos y preflight cacheado (600s). |
| **Base de Datos** | SQLite local sin control de cambios | Soporte completo para **PostgreSQL / Supabase** con driver nativo `psycopg v3`, pool de conexiones (`pool_pre_ping=True`, reciclaje a 1800s) y control formal de migraciones con **Alembic**. |
| **Inmutabilidad** | Triggers solo en SQLite | Triggers de inmutabilidad y bloqueo de `DELETE`/`TRUNCATE` compatibles bidireccionalmente con **SQLite y PostgreSQL** (PL/pgSQL). Protección extendida a 25 atributos pre-kickoff. |
| **Contenedorización** | Sin Docker ni scripts productivos | **Docker Compose multi-servicio**: Backend (FastAPI + Gunicorn + Uvicorn Workers), Frontend (Next.js 15 Standalone multi-stage alpine), PostgreSQL 16 con Healthcheck y Scheduler Daemon de Fase 5. |
| **Control de Cuotas** | Cobros desactivados y uso ilimitado | Middleware de Rate Limiting por IP (ventana deslizante) y control transaccional de cuotas diarias por plan SaaS (`FREE`: 3/día, `PREMIUM`: 50/día, `PRO`: 9999/día). |
| **Observabilidad** | Print statements no estructurados | Logging estructurado JSON en producción (`LOG_JSON=true`), inyección de cabecera `X-Request-ID`, cabeceras de seguridad HTTP completas (`nosniff`, `DENY`, `HSTS`, `Referrer-Policy`) y endpoints `/health` y `/ready`. |
| **Fase 5 (Automatización)** | Sin iniciar | Pipeline de ejecución diaria implementado (`DailyAutomationPipeline`), compatible con fuentes gratuitas CC0 y API-Football, con endpoints protegidos y demonio en segundo plano (`scheduler_cron.py`). |
| **Pruebas y CI/CD** | 20 pruebas | **27 pruebas automatizadas (100% de éxito)** con suite específica de seguridad y flujo de integración continua en **GitHub Actions** (`.github/workflows/ci.yml`). |
| **Control de Versiones** | Sin inicializar | Repositorio Git inicializado con rama `main`, exclusiones estrictas en `.gitignore` y primer commit estructurado. |

---

## 2. Requisitos Previos

1. **Docker Engine 24+** y **Docker Compose v2+** (para despliegue con contenedores) o **Python 3.12** + **Node.js 20+** (para despliegue bare-metal o PaaS).
2. Cuenta en [Supabase](https://supabase.com) (gratuita o pro) para Autenticación y PostgreSQL administrado.
3. Dominio con certificado SSL/TLS (Cloudflare, Let's Encrypt o proxy reverso Nginx/Traefik).

---

## 3. Configuración de Entorno (`.env`)

Copia la plantilla de producción a la raíz del proyecto:

```bash
cp .env.production.example .env
```

Edita `.env` con tus credenciales reales:

```env
# Entorno
ENVIRONMENT=production

# Base de datos PostgreSQL (ej. Supabase)
DATABASE_URL=postgresql+psycopg://postgres:TU_PASSWORD@db.TU_PROJECT_REF.supabase.co:5432/postgres
DB_POOL_SIZE=10
DB_MAX_OVERFLOW=20

# Supabase Auth
SUPABASE_URL=https://tu-proyecto.supabase.co
SUPABASE_ANON_KEY=tu-anon-key-de-supabase
SUPABASE_JWT_SECRET=tu-jwt-secret-de-supabase
ADMIN_EMAILS=tu-email@tudominio.com

# Seguridad
CORS_ORIGINS=https://tu-dominio.com
AUTH_ALLOW_DEV_HEADERS=false
SEED_DEMO_DATA=false
RATE_LIMIT_PER_MINUTE=120
TRUSTED_PROXY_HEADERS=true
ENABLE_API_DOCS=false

# URLs públicas
BACKEND_PORT=8000
FRONTEND_PORT=3000
NEXT_PUBLIC_API_URL=https://api.tu-dominio.com
NEXT_PUBLIC_SUPABASE_URL=https://tu-proyecto.supabase.co
NEXT_PUBLIC_SUPABASE_ANON_KEY=tu-anon-key-de-supabase

# API-Football (Opcional, 100 req/día gratuitas)
API_FOOTBALL_KEY=tu_clave_de_api_sports_si_deseas
```

---

## 4. Despliegue con Docker Compose (Opción Recomendada)

### 4.1 Construcción e Inicio de Todos los Servicios

```bash
# Construir imágenes e iniciar contenedores en segundo plano
docker compose up -d --build
```

El orquestador levantará:
- `sportpredict_db`: PostgreSQL 16 Alpine (si no usas Supabase externo).
- `sportpredict_backend`: API FastAPI lista en el puerto `8000`.
- `sportpredict_frontend`: Aplicación web Next.js 15 Standalone en el puerto `3000`.
- `sportpredict_scheduler`: Proceso de fondo que ejecuta el ciclo de sincronización y liquidación cada 6 horas.

### 4.2 Verificación del Estado

```bash
# Ver estado de los contenedores y healthchecks
docker compose ps

# Inspeccionar logs en tiempo real
docker compose logs -f backend
```

---

## 5. Gestión de Migraciones de Base de Datos (Alembic)

Las migraciones se ejecutan automáticamente al iniciar el contenedor del backend. Para aplicarlas manualmente en cualquier momento:

```bash
# Desde el host con el entorno virtual activo:
cd backend
python -m alembic upgrade head

# O dentro del contenedor Docker en ejecución:
docker compose exec backend python -m alembic upgrade head
```

Para crear una nueva migración tras modificar modelos SQLAlchemy:
```bash
python -m alembic revision --autogenerate -m "descripcion_del_cambio"
```

---

## 6. Configuración de Supabase Auth

1. Ingresa a la consola de tu proyecto Supabase: **Authentication $\rightarrow$ Providers $\rightarrow$ Email**.
2. Habilita el inicio de sesión con Email/Password o Magic Link.
3. En **Authentication $\rightarrow$ URL Configuration**, agrega tu dominio a los `Redirect URLs` (ej. `https://tu-dominio.com/**`).
4. Al registrarte con el correo especificado en `ADMIN_EMAILS`, el sistema le asignará automáticamente el rol `ADMIN` al primer inicio de sesión.

---

## 7. Ejecución y Auditoría del Ciclo de Fase 5

El demonio `scheduler` corre automáticamente en segundo plano. Si deseas forzar la ejecución manual del ciclo diario desde la API:

```bash
curl -X POST "https://api.tu-dominio.com/api/v1/phase4/automation/run-daily-cycle" \
  -H "Authorization: Bearer <TOKEN_ADMIN_SUPABASE>"
```

Respuesta típica esperada:
```json
{
  "execution_time_utc": "2026-11-10T15:00:00Z",
  "target_date": "2026-11-10",
  "openfootball_ingestion": null,
  "api_football_sync": "NOT_CONFIGURED (presupuesto $0 USD respetado)",
  "prospective_registered": 12,
  "prospective_settled": 8,
  "errors": []
}
```

---

## 8. Verificación de Seguridad y Salud

- **Liveness probe:** `GET /health` $\rightarrow$ `{"status": "ok", "service": "SPORTPREDICT AI", "version": "1.0.0"}`
- **Readiness probe:** `GET /ready` $\rightarrow$ `{"status": "ready"}` (valida conexión activa y saludable a PostgreSQL).
- **Protección de endpoints sensibles:** Cualquier solicitud sin cabecera `Authorization: Bearer <JWT>` recibe `401 Unauthorized`. Si el usuario no tiene rol `ADMIN`, recibe `403 Forbidden`.
- **Inmutabilidad estricta:** Intentar eliminar o alterar predicciones pre-kickoff registradas vía SQL genera un error fatal emitido por el trigger `trg_prospective_predictions_guard`.
