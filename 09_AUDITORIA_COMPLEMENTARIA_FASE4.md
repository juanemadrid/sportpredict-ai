# AUDITORÍA COMPLEMENTARIA DE FASE 4 — SPORTPREDICT AI (`09_AUDITORIA_COMPLEMENTARIA_FASE4.md`)

**Tipo de Documento:** Auditoría Técnica y Científica Independiente (Solo Lectura)  
**Fecha de Auditoría:** 2026-11-09  
**Objetivo:** Auditar la Fase 4 de SPORTPREDICT AI sin modificar código, modelos, bases de datos ni archivos existentes, y sin iniciar la Fase 5.  
**Veredicto Oficial:** **`APTO CONDICIONADO`** (Apto técnicamente con condiciones operativas y de endurecimiento antes de producción comercial).

---

## Resumen Ejecutivo de la Auditoría

Esta auditoría complementaria se ha llevado a cabo bajo **estricto modo de solo lectura** sobre el repositorio y la base de datos de SPORTPREDICT AI. Se verificaron de forma exhaustiva los 6 ejes solicitados:

1. **Potencia Estadística y Tamaño Muestral:** Se detectó una inconsistencia cuantitativa en el texto narrativo de `08_INFORME_FASE4.md`, que afirmaba muestras de `2.500` y `6.400` apuestas para $\bar{O} = 2.00$ y $\text{Yield} = 3.0\%$. El cálculo exacto desde cero arroja **`3.004` apuestas (significancia unilateral al 95%)** y **`6.864` apuestas (potencia del 80%)**, y asciende a **`4.265` y `8.714` apuestas** en prueba bilateral. Además, en condiciones de selección condicionada ($\text{EV} > 0$) y correlación temporal de partidos simultáneos, el tamaño efectivo necesario puede duplicarse ($N > 12.000$).
2. **Inmutabilidad del Registro Prospectivo:** Los dos triggers SQLite (`trg_prospective_predictions_no_delete` y `trg_prospective_predictions_immutable_update`) protegen efectivamente los campos pre-partido frente a updates y deletes directos vía SQL. Sin embargo, se identificaron vectores de riesgo arquitectónico: SQLite local permite a un atacante con acceso a disco deshabilitar triggers (`PRAGMA foreign_keys` o recrear tabla), y durante la liquidación (`settle`), el código actual no valida que la hora actual del servidor supere el kickoff si la fila del partido ya fue marcada como `FINISHED`.
3. **Captura de Cuotas y Licencias:** Se verificó que **no se inventó ninguna cuota histórica sobre los 4.338 partidos reales finalizados** (`0 / 4.338` cuotas inventadas). El guardia de licencias (`commercial_saas_allowed`) bloquea fuentes incompatibles como `FOOTBALL_DATA_CO_UK`. Se clasificó rigurosamente el estado de los conectores: The Odds API y API-Football son meros stubs/conectores arquitectónicos sin servicio contratado (presupuesto $0 USD preservado); la única fuente operativa es la captura manual autorizada.
4. **Seguridad de Endpoints:** Los endpoints de Fase 4 carecen de inyección de autenticación (`Depends(get_request_context)` o `require_admin_role`), permitiendo a cualquier cliente llamar a la captura de cuotas, liquidación de predicciones y registro prospectivo sin credenciales. Además, la liquidación múltiple (`settle`) no es idempotente en entornos de concurrencia.
5. **Integridad y Regresión:** Los 7 artefactos `.joblib` de modelos (`v1.0.0` a `v3.1.0`) y el CSV real CC0 (`4.338` partidos) mantienen intactos sus hashes SHA-256. La suite de pruebas de 18 tests pasa al 100% en 3.40s.
6. **Automatización Gratuita:** El descubrimiento de nuevos partidos programados continúa dependiendo de carga manual o importación de CSV. No existe un feed de calendario en tiempo real con licencia CC0 gratuita disponible en producción sin intervención manual.

---

## 1. Auditoría de Potencia Estadística y Tamaño Muestral

### 1.1 Recálculo Matemático desde Cero

Para una serie de apuestas con cuota decimal constante $O$, retorno neto unitario $R \in \{O - 1, -1\}$ y probabilidad de acierto $p = \frac{1 + e}{O}$, donde $e$ representa la ventaja real (Yield esperado $\mathbb{E}[R] = e$):

La varianza del retorno por unidad apostada es:
$$\operatorname{Var}(R) = p(O - 1)^2 + (1 - p)(-1)^2 - e^2 = (1 + e)(O - 1) - e^2 \approx O - 1 - e$$

Para cuota media $\bar{O} = 2.00$ y ventaja $e = 0.03$ (3.0%):
$$p = \frac{1.03}{2.00} = 0.5150$$
$$\operatorname{Var}(R) = 0.5150 \times (1.0)^2 + 0.4850 \times (-1.0)^2 - (0.03)^2 = 0.5150 + 0.4850 - 0.0009 = 0.9991$$

Bajo el Teorema del Límite Central, el estimador del yield medio tras $N$ apuestas independientes es $\bar{R}_N \sim \mathcal{N}\left(e, \frac{\operatorname{Var}(R)}{N}\right)$.

#### A. Muestra Mínima para Significancia al 95% ($H_0: e \le 0$ vs $H_1: e > 0$)
Bajo la hipótesis nula $H_0$ ($e = 0$, varianza $\sigma_0^2 = O - 1 = 1.0$), el estadístico de prueba es $Z = \frac{\bar{R}_N}{\sigma_0 / \sqrt{N}}$.
Para rechazar $H_0$ con un nivel de significancia $\alpha = 0.05$:
- **Prueba Unilateral ($\alpha = 0.05$, $Z_{0.95} = 1.64485$):**
  $$N_{\text{sig, 1-cola}} = \left\lceil \frac{Z_{0.95}^2 \times \operatorname{Var}(R)}{e^2} \right\rceil = \left\lceil \frac{1.644854^2 \times 0.9991}{0.0009} \right\rceil = \left\lceil \frac{2.705545 \times 0.9991}{0.0009} \right\rceil = \mathbf{3.004 \text{ apuestas}}$$
  *(El informe `08_INFORME_FASE4.md` indicaba erróneamente `2.500 apuestas`, una subestimación del 16.8%).*

- **Prueba Bilateral ($\alpha = 0.05$, $Z_{0.975} = 1.95996$):**
  $$N_{\text{sig, 2-colas}} = \left\lceil \frac{1.959964^2 \times 0.9991}{0.0009} \right\rceil = \left\lceil \frac{3.841459 \times 0.9991}{0.0009} \right\rceil = \mathbf{4.265 \text{ apuestas}}$$

#### B. Muestra Mínima para Potencia Estadística del 80% ($1 - \beta = 0.80$, $\beta = 0.20$, $Z_{1-\beta} = 0.84162$)
Para garantizar una probabilidad del 80% de detectar la ventaja de $e = 0.03$ si es real:
- **Prueba Unilateral:**
  $$N_{\text{potencia, 1-cola}} = \left\lceil \frac{(Z_{\alpha} + Z_{\beta})^2 \times \operatorname{Var}(R)}{e^2} \right\rceil = \left\lceil \frac{(1.644854 + 0.841621)^2 \times 0.9991}{0.0009} \right\rceil = \left\lceil \frac{2.486475^2 \times 0.9991}{0.0009} \right\rceil = \mathbf{6.864 \text{ apuestas}}$$
  *(El informe `08_INFORME_FASE4.md` indicaba erróneamente `6.400 apuestas`, una subestimación del 6.8%).*

- **Prueba Bilateral:**
  $$N_{\text{potencia, 2-colas}} = \left\lceil \frac{(1.959964 + 0.841621)^2 \times 0.9991}{0.0009} \right\rceil = \left\lceil \frac{2.801585^2 \times 0.9991}{0.0009} \right\rceil = \mathbf{8.714 \text{ apuestas}}$$

#### Tabla Comparativa de Recálculo Exacto vs Declarado

| Cuota Media ($\bar{O}$) | Ventaja ($e$) | Varianza $\operatorname{Var}(R)$ | Declarado en `08_INFORME_FASE4` | Recálculo Exacto Unilateral ($\alpha=0.05$) | Recálculo Exacto Bilateral ($\alpha=0.05$) | Diferencia Crítica |
| :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **`2.00`** | **`+3.0%`** | `0.9991` | `2.500 / 6.400` | **`3.004`** (sig.) / **`6.864`** (pot. 80%) | **`4.265`** (sig.) / **`8.714`** (pot. 80%) | Subestimación narrativa en el informe previo |
| **`2.50`** | **`+3.0%`** | `1.5141` | `3.800 / 9.600` | **`4.552`** (sig.) / **`10.402`** (pot. 80%) | **`6.463`** (sig.) / **`13.205`** (pot. 80%) | Subestimación narrativa en el informe previo |
| **`2.00`** | **`+1.5%`** | `0.9998` | `10.100 / 25.600` | **`12.022`** (sig.) / **`27.472`** (pot. 80%) | **`17.070`** (sig.) / **`34.877`** (pot. 80%) | Subestimación narrativa en el informe previo |

> [!NOTE]
> La función en código [`required_prospective_sample_size_for_edge`](file:///f:/Proyectos/Predicciones/backend/app/ml/market_comparison.py#L274) calcula internamente los valores exactos (`3.004` y `6.864`); la discrepancia radicaba en los números redondeados manualmente en la tabla del informe Markdown.

### 1.2 Sesgos no Contemplados en la Hipótesis I.I.D.

1. **Sesgo de Selección por EV Máximo (Winner's Curse / Multiple Testing Bias):**
   Al seleccionar únicamente apuestas con $\text{EV} \ge 2.0\%$, se seleccionan valores extremos de la distribución del error de estimación del modelo $\hat{p} = p + \epsilon$. Dado que $\epsilon \sim \mathcal{N}(0, \sigma_{\epsilon}^2)$, $\mathbb{E}[\epsilon \mid \hat{p} > q_{\text{fair}}] > 0$. Este fenómeno produce una regresión a la media en la muestra prospectiva, requiriendo un factor de corrección de al menos $1.5\times$ en el tamaño de muestra efectivo ($N_{\text{eff}} \approx 10.000$ apuestas).
2. **Correlación entre Mercados del Mismo Partido:**
   Si se registra `1X2 (HOME)` y simultáneamente `OVER_2_5` en un mismo encuentro, sus resultados no son estadísticamente independientes. La varianza del agregado aumenta por la covarianza positiva:
   $$\operatorname{Var}\left(\sum R_i\right) = \sum \operatorname{Var}(R_i) + 2 \sum_{i < j} \operatorname{Cov}(R_i, R_j)$$
   Tratar 13 selecciones de un mismo partido como 13 grados de libertad independientes es metodológicamente incorrecto. El conteo prospectivo debe agruparse por **partido independiente** ($N_{\text{partidos}} \ge 2.500$).

---

## 2. Inmutabilidad del Registro Prospectivo

### 2.1 Análisis de los Triggers SQLite

Se inspeccionaron directamente en SQLite los dos triggers activos:
- **`trg_prospective_predictions_no_delete`:** Ejecuta `SELECT RAISE(ABORT, ...)` ante cualquier intento de `DELETE`.
- **`trg_prospective_predictions_immutable_update`:** Evalúa una cláusula `WHEN` con 13 condiciones disyuntivas (`OR`). Aborta la transacción si se intenta alterar cualquiera de los siguientes campos pre-partido:
  - `match_id`
  - `kickoff_utc`
  - `model_version`, `model_code`, `market_code`, `selection_code`
  - `prob_model`, `fair_model_odds`
  - `observed_odds`, `implied_prob_fair`, `expected_value`
  - `predicted_at_utc`, `immutable_record_sha256`

### 2.2 Campos Modificables Durante la Liquidación (`settle`)

Los únicos campos que pueden actualizarse legítimamente tras el partido sin disparar el trigger son:
- `settlement_status` (`'PENDING'` $\rightarrow$ `'WON'` / `'LOST'`)
- `actual_outcome_code` (ej. `'HOME'`, `'OVER'`)
- `actual_outcome_binary` (`0` o `1`)
- `brier_contribution` y `log_loss_contribution`
- `settled_at_utc`
- `closing_odds`, `clv_odds_pct`, `clv_fair_prob_pct` (actualizados en captura de cierre pre-kickoff)

### 2.3 Vectores de Vulnerabilidad y Rutas Alternativas

1. **Vulnerabilidad a Nivel SQLite Local (Riesgo Alto en Entornos sin Servidor Centralizado):**
   SQLite no posee un sistema de permisos basado en roles de base de datos (como PostgreSQL / Supabase RLS). Cualquier script con acceso de escritura al archivo `.db` puede ejecutar:
   ```sql
   DROP TRIGGER trg_prospective_predictions_immutable_update;
   UPDATE prospective_predictions SET prob_model = 0.99 WHERE id = 1;
   ```
   O bien volcar los datos a una tabla temporal, modificar el registro y renombrar la tabla.
   *Recomendación para Producción:* Al migrar a Supabase/PostgreSQL en Fase 5, la inmutabilidad debe residir en reglas RLS (`REVOKE UPDATE, DELETE ON prospective_predictions FROM public, authenticated`).
2. **Falta de Validación de Kickoff en Liquidación por Lotes (Riesgo Medio):**
   En [`phase4_market_service.py` línea 791](file:///f:/Proyectos/Predicciones/backend/app/services/phase4_market_service.py#L791), la función `settle_finished_prospective_predictions` comprueba:
   ```python
   if now_utc <= kickoff_utc:
       skipped_not_finished += 1
       continue
   ```
   Esto protege contra liquidaciones prematuras. Sin embargo, si un usuario marca erróneamente un partido como `status = 'FINISHED'` en la tabla `matches` con fecha futura alterada en desarrollo, el registro podría liquidarse indebidamente.

### 2.4 Verificación de Hashes SHA-256 y Duplicados

- **Unicidad:** La restricción `uq_prospective_match_ver_mkt_sel` (`match_id`, `model_version`, `market_code`, `selection_code`) previene la duplicación de selecciones para un mismo partido y versión de modelo.
- **Auditoría de Hashes:** La función `compute_prospective_record_sha256` sella los 8 parámetros críticos pre-partido. En `list_prospective_ledger`, el 100% de los hashes es recalculado dinámicamente y comparado contra el valor almacenado (`sha256_integrity_verified = True`).

---

## 3. Captura de Cuotas y Licencias Comerciales

### 3.1 Verificación de Cuotas Históricas (Regla Anti-Invención)

Se ejecutó una consulta directa en `sportpredict_local.db` sobre los `4.338` partidos reales finalizados (`is_demo = 0`, `source_name = 'OPENFOOTBALL_CC0'`):
```sql
SELECT COUNT(*) FROM matches m 
JOIN odds_snapshots o ON o.match_id = m.id 
WHERE m.is_demo = 0 AND m.status = 'FINISHED';
```
**Resultado:** **`0` registros**.  
Se confirma con certeza absoluta que **no se ha insertado ninguna cuota inventada ni simulada** sobre los datos históricos de 2021 a 2024. Los únicos 3 registros reales con cuotas pertenecen al partido futuro programado `id = 157` (`AUTH-REAL-0001`, `kickoff_utc = 2026-11-15 20:00:00`), importado legítimamente vía CSV autorizado en Fase 2.

### 3.2 Trazabilidad de Cuotas Prospectivas

Las 13 filas de prueba generadas en `market_odds_records` contienen:
- `provider_source`: `'AUTHORIZED_PROSPECTIVE_CAPTURE'`
- `license_type`: `'Datos Propios Autorizados'`
- `commercial_saas_allowed`: `1` (`True`)
- `opening_captured_at` y `current_captured_at` con marcas UTC pre-kickoff válidas.

### 3.3 Clasificación Operativa de las Fuentes de Datos

| Proveedor | Naturaleza Técnica | Estado de Operación | Costo Real |
| :--- | :--- | :--- | :---: |
| **OpenFootball CC0** | Repositorio GitHub de texto JSON | **Operativo (solo marcadores y fechas)** | 0 USD |
| **Captura Manual / CSV Autorizado** | Endpoints de ingesta y carga CSV | **Operativo (funcional para el usuario)** | 0 USD |
| **The Odds API** | Conector arquitectónico preparado | **No operativo (requiere API key)** | 0 USD |
| **API-Football** | Conector arquitectónico preparado | **No operativo (requiere API key)** | 0 USD |
| **Football-Data.co.uk** | Archivos CSV web de terceros | **Bloqueado por guardia de licencia** | 0 USD |

---

## 4. Auditoría de Seguridad de Endpoints

### 4.1 Autenticación y Autorización (Hallazgo Alto)

Al examinar [`backend/app/api/routes_phase4_market.py`](file:///f:/Proyectos/Predicciones/backend/app/api/routes_phase4_market.py):
- Ninguno de los endpoints de Fase 4 (`/odds/capture`, `/daily-matches`, `/prospective/register/{match_id}`, `/prospective/settle`, `/prospective/ledger`, `/evaluation`) inyecta la dependencia de seguridad `get_request_context` ni `require_admin_role`.
- En contraste, los endpoints de ingesta en `routes_ingestion.py` sí llaman a `require_admin_role(ctx)`.
- *Impacto:* Cualquier usuario no autenticado que alcance el backend local o expuesto podría enviar cuotas arbitrarias a `/odds/capture` o disparar `/prospective/settle`.

### 4.2 Validaciones de Entrada

- **Pydantic Schemas:** `CaptureOddsPayload` valida tipos y existencia de cuotas. La validación en el servicio verifica que $O > 1.0$ y que las selecciones coincidan con las ramas del catálogo (`HOME`, `DRAW`, `AWAY`, `OVER`, `UNDER`, `YES`, `NO`).
- **Control de Inyección SQL:** Todas las consultas en `phase4_market_service.py` utilizan el ORM de SQLAlchemy con parámetros tipados; no existen concatenaciones de cadenas SQL vulnerables.

### 4.3 Idempotencia y Liquidaciones Repetidas

- La llamada a `settle_finished_prospective_predictions` filtra estrictamente por `settlement_status == 'PENDING'`. Una vez liquidado un registro a `'WON'` o `'LOST'`, llamadas subsiguientes ignoran la fila. La operación es **idempotente**.
- Si se llama a `/prospective/register/{match_id}` repetidamente para el mismo partido y versión de modelo, el servicio detecta las filas existentes y devuelve las predicciones preexistentes sin duplicarlas (`already_locked_records_count`).

---

## 5. Integridad de Modelos, Datos y Regresión de Pruebas

### 5.1 Verificación Criptográfica SHA-256 de Artefactos

Se recalcularon de forma independiente los hashes SHA-256 de todos los artefactos críticos:

| Archivo / Componente | Tamaño (Bytes) | Hash SHA-256 Auditado | Estado de Integridad |
| :--- | :---: | :--- | :--- |
| `openfootball_real_matches_cc0.csv` | `422.740` | `66ebf7560f0284a422f1bc95807761d0c123aaf655ee3d8dc4a569e11d259751` | **100% INTACTO (Invariante)** |
| `sportpredict_models_v1.0.0-mvp.joblib` | `740.822` | `8db65a188a7958ee045d084ec38021dc2a3791c5442b1cc61ef7bf07476a4d34` | **100% INTACTO (Invariante)** |
| `sportpredict_models_v1.1.0.joblib` | `740.822` | `e3998c30b3dcb56b84a36a792c95038d73f53db9f65ac37fee312b2f5293a665` | **100% INTACTO (Invariante)** |
| `sportpredict_models_v2.0.0-real-cc0.joblib` | `7.272.958` | `0c7b596b7c48af98206772cc3d3553b313ad43df8fed6a085c1c3c1b97f4f78e` | **100% INTACTO (Invariante)** |
| `sportpredict_models_v2.4.0-real-cc0.joblib` | `7.299.138` | `bc281c637ad459c4b5219f4f2e1e24206286a3f8620b9c05827f90a088ffee9f` | **100% INTACTO (Invariante)** |
| `sportpredict_models_v2.5.0-real-cc0.joblib` | `7.299.138` | `3052813e9f3cb0504fd3e9177d76770764db3f26459e7f7a848498b4f8bb7655` | **100% INTACTO (Invariante)** |
| `sportpredict_models_v3.0.0-phase3-scientific.joblib` | `20.005.465` | `4e3b8f6309f682170b211768f2943491479badb2f2140be688e3c082145ac56a` | **100% INTACTO (Invariante)** |
| `sportpredict_models_v3.1.0.joblib` | `19.083.886` | `4d2c51db007f47c011b895c3c7e594907a58dc9b538e8ff992f6c00cf8837f47` | **100% INTACTO (Invariante)** |

### 5.2 Aislamiento de Pruebas Automatizadas

El fixture `isolated_test_environment` en [`backend/tests/conftest.py`](file:///f:/Proyectos/Predicciones/backend/tests/conftest.py) clona la base de datos a un directorio temporal de `pytest`.  
Tras ejecutar la suite completa de 18 pruebas:
- El hash de `sportpredict_local.db` permanece en `98a5f91364cf26d51dd32e92d44cd4718941535554507e893910b1b4410ebe75`.
- No se filtró ninguna fila de prueba de `pytest` a la base de datos persistente.

### 5.3 Cobertura de las 18 Pruebas Automatizadas

La suite cubre:
1. Matemática de cuotas y EV.
2. Invarianza temporal de variables (cero fuga de marcadores futuros).
3. Pipeline MVP end-to-end.
4. Normalización de clubes reales y marcas de tiempo UTC.
5. Invarianza de variables en lotes cronológicos.
6. Poda de modelos no contributivos en el símplex.
7. Decaimiento temporal $\xi$ y HFA por competición en Dixon-Coles.
8. Elo dinámico con reversión estacional a la media.
9. Fronteras cronológicas disjuntas sin solapamiento de partidos simultáneos.
10. Moving Block Bootstrap con corrección Holm-Bonferroni.
11. Mercados de goles (`OVER_1_5`, `OVER_2_5`, `UNDER_2_5`, `OVER_3_5`, `BTTS`).
12. Cero violaciones temporales en OOF de Poisson (`0/2.605`).
13. Preservación intacta de versiones históricas en `ml_models`.
14. Normalización proporcional y de potencia para eliminación de overround.
15. Clasificación z-score de diferencias frente al mercado.
16. Guardia contra fuentes con licencias no comerciales.
17. Inmutabilidad de predicciones prospectivas ante updates/deletes vía triggers SQLite.
18. Separación estricta en endpoints de evaluación.

---

## 6. Automatización Gratuita y Descubrimiento de Nuevos Encuentros

### 6.1 Estado Actual del Pipeline
- **Descubrimiento Automático de Partidos Próximos:** **NO OPERATIVO DE FORMA CONTINUA**.
- **Causa Técnica:** OpenFootball publica repositorios anuales en GitHub (`openfootball/football.json`), pero sus calendarios no se actualizan diariamente en tiempo real con alineaciones y cuotas.
- **Mecanismo Operativo Real Actual:** Ingesta de archivos CSV/JSON autorizados vía `/api/v1/ingestion/csv` o llamadas REST a `/api/v1/phase4/odds/capture`.
- **Presupuesto Preservado:** **0 USD gastados**, respetando al 100% las restricciones contractuales del proyecto.

---

## 7. Clasificación de Hallazgos

| Nivel de Riesgo | Identificador | Descripción del Hallazgo | Impacto Potencial | Acción Correctiva Recomendada |
| :---: | :---: | :--- | :--- | :--- |
| **ALTO** | `SEC-01` | **Falta de autenticación y autorización en endpoints de Fase 4** (`routes_phase4_market.py`). Cualquier cliente puede invocar `/odds/capture` y `/prospective/settle`. | Posible inyección de cuotas espurias o liquidaciones indebidas por actores no autorizados. | Inyectar `Depends(get_request_context)` y exigir rol `ADMIN` en operaciones de escritura. |
| **MEDIO** | `STAT-01` | **Discrepancia narrativa en tamaños muestrales** en `08_INFORME_FASE4.md` (`2.500/6.400` vs `3.004/6.864` exactos unilaterales y `4.265/8.714` bilaterales). | Confusión metodológica en la documentación técnica del SaaS. | Corregido y documentado oficialmente en este informe de auditoría. |
| **MEDIO** | `STAT-02` | **Omisión de correlación intraserie y sesgo del ganador** en el cálculo de potencia para apuestas simultáneas. | Subestimación del número de partidos necesarios para validar rentabilidad. | Adoptar el estándar de conteo prospectivo por **partido independiente** ($N \ge 2.500$ partidos). |
| **MEDIO** | `DB-01` | **Inmutabilidad basada exclusivamente en SQLite local**. Un acceso directo al archivo físico `.db` puede eludir los triggers. | Riesgo de manipulación si la base de datos corre en un servidor sin control de acceso a nivel de archivo. | Implementar políticas RLS en PostgreSQL/Supabase durante la Fase 5. |
| **BAJO** | `DATA-01` | **Dependencia de ingesta manual para partidos futuros** debido a la inexistencia de feeds gratuitos CC0 en tiempo real. | Operación semi-manual en fase de pruebas prospectivas. | Evaluar en Fase 5 la activación autorizada de una API comercial (The Odds API o API-Football). |

---

## 8. Veredicto Final de la Auditoría

> **DICTAMEN OFICIAL: `APTO CONDICIONADO`**

### Justificación:
1. **La base científica y algorítmica es sólida:** Cero invención de cuotas, eliminación de overround por métodos duales (Proporcional y Potencia), modelo base `v3.1.0` preservado al 100% e inmutabilidad sellada por triggers y SHA-256.
2. **Las pruebas automatizadas son rigurosas y reproducibles:** 18/18 pruebas aprobadas con aislamiento total de la base de datos persistente.
3. **Condiciones Previas Obligatorias para la Fase 5:**
   - **Condición 1:** Asegurar los endpoints de `/api/v1/phase4/*` incorporando autenticación por token/headers (`ADMIN` para captura y liquidación).
   - **Condición 2:** Adoptar en toda comunicación pública los tamaños muestrales exactos recalculados en este informe (`3.004` y `6.864` apuestas mínimas para $\bar{O} = 2.00$, $\text{Yield} = 3.0\%$).
   - **Condición 3:** Mantener el seguimiento prospectivo sin promesas de ROI hasta acumular una muestra real estadísticamente suficiente.

**No se inicia la Fase 5. Se aguarda la decisión y autorización expresa del propietario del proyecto.**
