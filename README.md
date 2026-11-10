# SPORTPREDICT AI
**Plataforma SaaS de Análisis Estadístico y Predicción Deportiva mediante Machine Learning (Calibrado, Inmutable y Listo para Producción)**

---

## 1. Principios de Ingeniería, Seguridad y Gobernanza
- **Aislamiento Total y Sin Claves Ficticias:** Variables de entorno limpias en `.env.example` y `.env.production.example`. Sin conexiones simuladas.
- **Autenticación Robusta en Producción:** Verificación criptográfica de JWT de **Supabase Auth** (JWKS asimétrico RS256/ES256 y simétrico HS256). Perfiles locales protegidos y roles gestionados por administradores.
- **Inmutabilidad Criptográfica SHA-256:** Las predicciones prospectivas se firman antes del kickoff (`predicted_at < kickoff_utc`). Triggers a nivel de base de datos (**PostgreSQL y SQLite**) impiden `DELETE`, `TRUNCATE` o `UPDATE` retroactivo sobre los atributos pre-partido.
- **Cero Fuga Temporal (*Zero Data Leakage*):** Toda variable y rating Elo dinámico se calcula estrictamente con partidos finalizados antes de la fecha objetivo.
- **Gobernanza de Datos DEMO vs REAL:** Trazabilidad explícita (`is_demo`, `source_name`, `source_license`) con separación contable en base de datos e interfaz.
- **Control de Cuotas y Rate Limiting:** Limitador por IP con ventana deslizante (120 req/min) y límites diarios por plan SaaS (`FREE`: 3, `PREMIUM`: 50, `PRO`: 9999).

---

## 2. Estructura del Proyecto

```text
f:\Proyectos\Predicciones\
├── docker-compose.yml                          # Orquestación de contenedores (backend, frontend, postgres, scheduler)
├── .env.example                                # Plantilla de variables para desarrollo local
├── .env.production.example                     # Plantilla de variables para producción
├── .github/workflows/ci.yml                    # Pipeline CI/CD automatizado en GitHub Actions
├── docs/
│   ├── 00_DIAGNOSTICO_Y_PLAN.md               # Diagnóstico Fase 0 y Plan de Fases
│   ├── 01_ARQUITECTURA_DECISIONES.md          # Decisiones de Arquitectura (ADRs)
│   ├── 02_PROTOCOLO_VALIDACION_ML.md          # Protocolo de Validación ML
│   ├── 03_CUMPLIMIENTO_Y_JUEGO_RESPONSABLE.md # Marco normativo (+18) y regulación Colombia
│   ├── ... (Informes Fases 2, 3, 4)
│   ├── 11_PLAN_TECNICO_FASE5.md               # Plan Técnico de Fase 5
│   ├── 14_AUDITORIA_FINAL_HASH_Y_ESTADISTICA.md # Auditoría de potencia y hashes
│   └── 15_MANUAL_DESPLIEGUE_PRODUCCION.md     # Manual completo de despliegue productivo
├── database/
│   ├── schema.sql                             # DDL PostgreSQL / Supabase
│   └── seed_reference.sql                     # Catálogo de planes SaaS y fuentes
├── backend/
│   ├── Dockerfile                             # Imagen optimizada Python 3.12 + Gunicorn + Uvicorn
│   ├── alembic.ini & alembic/                 # Migraciones de base de datos versionadas
│   ├── pyproject.toml & requirements.txt
│   ├── app/
│   │   ├── main.py                            # Servidor FastAPI con observabilidad y CORS estricto
│   │   ├── core/                              # Configuración (.env), seguridad (JWT/RBAC) y observabilidad
│   │   ├── db/                                # Modelos SQLAlchemy, sesiones y triggers
│   │   ├── ingestion/                         # Adaptadores OpenFootball CC0, API-Football y CSV
│   │   ├── ml/                                # Poisson/Dixon-Coles, Elo, RF, XGBoost y Ensamble
│   │   ├── services/                          # Valuación Fase 4, predicción y scheduler Fase 5
│   │   └── api/                               # Rutas REST (Sistema, Usuarios, Partidos, Modelos, Fase 4)
│   └── tests/                                 # 27 pruebas automatizadas (100% aprobadas)
└── frontend/
    ├── Dockerfile                             # Imagen multi-stage Alpine Next.js 15 Standalone
    ├── package.json                           # Next.js 15, React 19, TypeScript, Tailwind CSS
    └── src/                                   # Interfaz SaaS institucional Azul Oscuro (12 módulos)
```

---

## 3. Despliegue Rápido en Producción (Docker Compose)

1. **Configurar el entorno:**
   ```bash
   cp .env.production.example .env
   # Configura DATABASE_URL, SUPABASE_URL, SUPABASE_ANON_KEY y CORS_ORIGINS
   ```

2. **Levantar el stack multi-servicio:**
   ```bash
   docker compose up -d --build
   ```

3. **Verificar estado de salud:**
   ```bash
   docker compose ps
   curl http://localhost:8000/health
   curl http://localhost:8000/ready
   ```

---

## 4. Ejecución Local de Pruebas Automatizadas

```powershell
cd backend
.\.venv\Scripts\python.exe -m pytest -v
```

Las 27 pruebas cubren:
- Integridad temporal y cero fuga de información futura.
- Backtesting científico, Brier Score y calibración de probabilidades.
- Sello SHA-256 e inmutabilidad de predicciones pre-kickoff.
- Validación de configuración de producción y rechazo de cabeceras de depuración.
- Validación de tokens JWT y control de cuotas por plan SaaS.
- Rutas administrativas protegidas (401 para anónimos, 403 para no-admin, 200 para admin).

---

## 5. Manuales y Referencias de Operación
- Consulta el documento [`docs/15_MANUAL_DESPLIEGUE_PRODUCCION.md`](docs/15_MANUAL_DESPLIEGUE_PRODUCCION.md) para la guía paso a paso de aprovisionamiento de Supabase, gestión de certificados SSL y despliegue en VPS o plataformas Cloud (Railway, Render, Fly).
