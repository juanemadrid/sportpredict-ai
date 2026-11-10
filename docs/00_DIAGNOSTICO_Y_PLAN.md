# SPORTPREDICT AI — FASE 0: Diagnóstico del Entorno y Plan de Implementación

**Fecha de inspección:** 2026-11-09  
**Directorio de trabajo:** `f:\Proyectos\Predicciones`  
**Estado de aislamiento:** 100% independiente (sin relación ni modificaciones sobre otros proyectos o bases de datos existentes).

---

## 1. Diagnóstico del Entorno de Desarrollo

Se realizó una auditoría no intrusiva sobre el sistema operativo y las herramientas instaladas en la estación de trabajo:

| Componente | Estado Detectado | Versión / Detalle | Acción en el Proyecto |
| :--- | :--- | :--- | :--- |
| **Directorio `f:\Proyectos\Predicciones`** | Vacío y aislado | `0` archivos previos | Inicialización limpia sin riesgo de colisión con otros sistemas. |
| **Sistema Operativo** | Windows | Windows 10/11 (PowerShell) | Scripts y rutas compatibles con Windows y contenedores Linux. |
| **Node.js** | Instalado y operativo | `v24.15.0` (`C:\Program Files\nodejs`) | Utilizado para el frontend en **React / Next.js (TypeScript)**. |
| **npm / npx** | Instalado y operativo | `11.12.1` | Gestión de paquetes del frontend. |
| **Git** | Instalado y operativo | `2.54.0.windows.1` | Control de versiones del código y esquemas. |
| **Docker** | Instalado | `29.8.0` (build `88096ef`) | Disponible para empaquetado futuro si se requiere. |
| **Python** | Alias de Microsoft Store sin intérprete global activo | `WindowsApps\python.exe` (stub) | Aprovisionamiento de un entorno Python 3.12 **aislado localmente** en el proyecto (`backend/.venv` mediante `uv`) para no alterar configuraciones globales del sistema. |
| **PostgreSQL / Supabase** | Sin credenciales configuradas aún | Independiente | Se entrega el esquema DDL completo para **Supabase PostgreSQL** (`database/schema.sql` con RLS) y un motor SQLAlchemy que opera localmente sobre SQLite aislado (`sportpredict_local.db`) hasta que se conecte la cadena `DATABASE_URL` del proyecto Supabase independiente. |
| **API-Football** | Sin clave configurada aún | Modo `NOT_CONFIGURED` | El adaptador detecta la ausencia de clave real sin simular conexiones ficticias, activando control de cuota (100 req/día) y caché tan pronto el usuario agregue su API Key real en `.env`. |

---

## 2. Verificación de Reglas de Gobernanza

1. **Aislamiento total:** Todo el código, entorno virtual, base de datos local de desarrollo y artefactos residen exclusivamente dentro de `f:\Proyectos\Predicciones`.
2. **Cero claves ficticias ni conexiones simuladas:** El archivo `.env.example` deja las credenciales vacías (`API_FOOTBALL_KEY=`, `SUPABASE_URL=`, `SUPABASE_ANON_KEY=`). El sistema reporta explícitamente el estado real de cada conector (`NOT_CONFIGURED`, `CONNECTED`, `QUOTA_EXHAUSTED`).
3. **Trazabilidad `DEMO` vs `REAL`:** Cada registro en base de datos (`matches`, `odds_snapshots`, `predictions`, `data_sources`) incorpora los campos obligatorios `is_demo` (`BOOLEAN`), `source_name`, `source_license` y `captured_at` (`TIMESTAMPTZ`). La interfaz gráfica muestra una etiqueta visible **`[DATOS DEMO - SEMILLA HISTÓRICA VERIFICABLE]`** cuando se visualizan datos demostrativos.
4. **Rigor estadístico y prohibición de fuga de datos (*Data Leakage*):** El constructor de variables (`PointInTimeFeatureBuilder`) filtra estrictamente partidos con `kickoff_utc < target_match.kickoff_utc`. Ninguna estadística post-partido puede filtrarse al vector de entrada de un pronóstico.

---

## 3. Plan de Trabajo por Fases (Fases 0 a 6)

### FASE 0: Diagnóstico y Arquitectura *(Actual - Completada)*
- Auditoría del entorno de desarrollo y herramientas disponibles.
- Definición de arquitectura desacoplada en 6 capas (A: UI, B: API de Negocio, C: Servicio de Predicción, D: Ingestión de Datos, E: Entrenamiento ML, F: Evaluación y Backtesting).
- Documentación de decisiones arquitectónicas (ADR), protocolo de validación científica y marco de cumplimiento legal (+18, servicio informativo, Colombia).

### FASE 1: Fundamentos y Primer MVP Funcional *(Actual - En ejecución)*
- Estructura modular del proyecto (`backend/`, `frontend/`, `database/`, `docs/`, `notebooks/`).
- Modelo de base de datos relacional completo para PostgreSQL/Supabase (`database/schema.sql`) y ORM SQLAlchemy (`backend/app/db/models.py`).
- Backend FastAPI operativo con endpoints de diagnóstico, proveedores, partidos, cálculo de probabilidades, valor esperado (EV), registro inmutable de predicciones y backtesting cronológico.
- Implementación funcional de los modelos base y ML:
  - **Modelo A:** Poisson Independiente y ajuste Dixon-Coles para goles esperados ($\lambda_H, \lambda_A$), matriz de marcadores exactos, 1X2, Más/Menos 1.5, 2.5, 3.5 y Ambos Marcan (BTTS).
  - **Modelo B:** Elo Dinámico con ventaja de localía y actualización cronológica partido a partido.
  - **Modelo C:** Random Forest con calibración de probabilidades (`CalibratedClassifierCV`).
  - **Modelo D:** XGBoost con calibración e importancia de variables.
  - **Modelo E:** Ensamble ponderado inversamente por Brier Score en ventana de validación temporal.
- Frontend Next.js con identidad visual **Azul Oscuro**, limpio, responsivo y estructurado en los 12 módulos del producto SaaS.

### FASE 2: Datos e Ingestión Avanzada
- Importador CSV autorizado con auditoría de duplicados, valores faltantes, normalización canónica de nombres de equipos (`team_aliases`) y validación de licencias.
- Conector `APIFootballAdapter` con caché persistente, control estricto del límite gratuito de 100 peticiones diarias y bitácora de sincronización (`sync_logs`).
- Conector `StatsBombOpenDataAdapter` para investigación con datos abiertos autorizados (incluyendo xG cuando esté disponible).

### FASE 3: Profundización del Motor de Machine Learning
- Expansión de variables deportivas (ventanas móviles de 5 y 10 partidos, rendimiento específico local/visitante, días de descanso, historial H2H, posición en tabla, tiros a puerta, córners, tarjetas, xG y disponibilidad de plantilla pre-partido).
- Almacenamiento versionado de artefactos (`.joblib` + manifiesto JSON con hash del dataset y métricas de validación).
- Flujo de exportación e importación desde **Google Colab** (`notebooks/sportpredict_colab_training.ipynb`).

### FASE 4: Validación Científica y Backtesting
- Partición estrictamente cronológica (`Entrenamiento -> Validación Temporal -> Prueba Final Retenida`).
- Reporte reproducible con Accuracy, Precision, Recall, F1, Brier Score, Log Loss, Curvas de Calibración (ECE), ROI simulado y Yield.
- Comparación obligatoria contra: (1) Modelo de referencia ingenuo (frecuencia histórica), (2) Probabilidad implícita del mercado sin margen (overround removido), y (3) Versiones previas de los modelos.

### FASE 5: Mercados Progresivos y Registro Pre-Partido
- Gobernanza de mercados por niveles (Nivel 1 activo con validación; Niveles 2 y 3 bloqueados automáticamente por cobertura de datos hasta cumplir umbral mínimo de muestra y Brier Score).
- Bloqueo criptográfico/temporal de pronósticos antes de `kickoff_utc` y liquidación automática contra resultados reales.

### FASE 6: Aplicación Comercial SaaS
- Integración con Supabase Auth, control de acceso por roles (`USER`, `ANALYST`, `ADMIN`) y límites por plan (`GRATUITO`, `PREMIUM`, `PROFESIONAL`) sin pasarelas de cobro activas aún.
- Optimización móvil y auditoría de seguridad.
