# SPORTPREDICT AI
**Plataforma SaaS de Análisis Estadístico y Predicción Deportiva mediante Machine Learning**

---

## 1. Principios de Ingeniería y Gobernanza
- **Aislamiento total:** Todo el proyecto reside en `f:\Proyectos\Predicciones` sin modificar ningún otro proyecto, plataforma o base de datos existente.
- **Sin claves API ficticias ni conexiones simuladas:** Las variables de entorno en `.env.example` están limpias. Si `API_FOOTBALL_KEY` o `DATABASE_URL` (Supabase) no están configuradas aún, el sistema reporta con transparencia su estado real (`NOT_CONFIGURED` / `SQLITE_LOCAL_ISOLATED`).
- **Trazabilidad explícita `DEMO` vs `REAL`:** Cada registro en base de datos incorpora `is_demo`, `source_name`, `source_license` y `captured_at`.
- **Cero fuga de información futura (*Zero Data Leakage*):** Todas las variables pre-partido (`PointInTimeFeatureBuilder`) y las calificaciones dinámicas Elo se calculan utilizando exclusivamente encuentros con `kickoff_utc < target_match.kickoff_utc`.

---

## 2. Estructura del Proyecto

```text
f:\Proyectos\Predicciones\
├── README.md
├── .env.example
├── .gitignore
├── docs/
│   ├── 00_DIAGNOSTICO_Y_PLAN.md               # Diagnóstico Fase 0 y Plan Fases 0-6
│   ├── 01_ARQUITECTURA_DECISIONES.md          # Separación de capas A-F y ADRs
│   ├── 02_PROTOCOLO_VALIDACION_ML.md          # Partición temporal, Brier, LogLoss, ECE, EV
│   └── 03_CUMPLIMIENTO_Y_JUEGO_RESPONSABLE.md # Marco informativo (+18) y regulación Colombia
├── database/
│   ├── schema.sql                             # DDL PostgreSQL / Supabase (12 tablas e índices)
│   └── seed_reference.sql                     # Catálogo de planes SaaS, fuentes y mercados Niveles 1-3
├── backend/
│   ├── pyproject.toml
│   ├── requirements.txt
│   ├── app/
│   │   ├── main.py                            # Servidor FastAPI (Capa B)
│   │   ├── core/                              # Configuración (.env) y seguridad RBAC / Planes SaaS
│   │   ├── db/                                # Modelos SQLAlchemy e inicializador verificable
│   │   ├── ingestion/                         # Capa D: Adaptadores CSV, API-Football (100/día + caché), StatsBomb
│   │   ├── ml/                                # Capas E y F: Variables Point-in-Time, Modelos A-E, Backtesting
│   │   ├── services/                          # Capa C: Servicio de Predicción y Registro Inmutable
│   │   └── api/                               # Rutas REST para los 12 módulos
│   └── tests/
│       └── test_mvp_phase1.py                 # Suite de pruebas reproducibles (pytest)
├── notebooks/
│   └── sportpredict_colab_training.ipynb      # Cuaderno experimental para Google Colab
└── frontend/
    ├── package.json                           # Next.js 15, React 19, TypeScript, Tailwind CSS
    └── src/                                   # Capa A: Interfaz Azul Oscuro con los 12 módulos SaaS
```

---

## 3. Cómo Reentrenar y Evaluar los Modelos
1. **Desde la API o el Panel Administrativo (Módulo 10):**
   - Importar un archivo CSV autorizado (`POST /api/v1/ingestion/csv`).
   - Ejecutar `POST /api/v1/models/train` con `{"calibration_method": "sigmoid"}` o `"isotonic"`.
   - El sistema genera un artefacto versionado en `backend/artifacts/models/sportpredict_models_<version>.joblib` y registra las métricas científicas en `backtest_runs`.
2. **Desde Línea de Comandos (Pruebas Reproducibles):**
   ```powershell
   cd f:\Proyectos\Predicciones\backend
   .\.venv\Scripts\pytest -v
   ```
