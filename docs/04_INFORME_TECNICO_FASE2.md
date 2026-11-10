# SPORTPREDICT AI — INFORME TÉCNICO FASE 2: DATOS E INGESTIÓN AVANZADA

**Fecha de ejecución:** 2026-11-09  
**Versión del motor generada:** `v2.0.0-real-cc0` (`is_demo = FALSE`)  
**Estado de resultados anteriores (Fase 1):** Preservados íntegramente en base de datos (`v1.0.0`) sin modificaciones.

---

## PASO 1. AUDITORÍA DE LOS RESULTADOS ANTERIORES (FASE 1)

1. **Identificación exacta del dataset de la FASE 1:**
   - Generado por la función `_seed_demo_historical_and_upcoming_matches()` en `backend/app/db/init_db.py`.
   - Identificador de proveedor en base de datos: `source_name = 'DEMO_SEED'`, `is_demo = TRUE`.
2. **Procedencia:**
   - Generador determinista interno (`numpy.random.default_rng(42)`) parametrizado con fuerzas de ataque y defensa base por club para validar la arquitectura sin depender de conexiones externas ni claves ficticias durante la Fase 1.
3. **Naturaleza de los partidos (Reales vs Sintéticos):**
   - Los partidos de la Fase 1 son **100% sintéticos / demostrativos**, razón por la cual fueron etiquetados explícitamente con `is_demo = TRUE` en cumplimiento de la Regla General #8 (*"Toda información simulada debe identificarse claramente como DEMO"*).
4. **Número total de partidos en Fase 1:**
   - **150 partidos finalizados** (`DEMO-HIST-0001` a `DEMO-HIST-0150`) + **6 partidos programados** (`DEMO-TODAY-01..03` y `DEMO-NEXT-01..03`) + **1 partido de prueba de importación CSV** (`AUTH-REAL-0001`) = **157 registros**.
5. **Temporadas, ligas y competiciones en Fase 1:**
   - Competiciones: **LaLiga EA Sports** (`ESP_LALIGA`, 90 partidos finalizados) y **Premier League** (`ENG_EPL`, 60 partidos finalizados).
   - Temporadas simuladas: `2025/2026` (75 partidos) y `2026/2027` (75 partidos), abarcando del `2026-02-22` al `2026-10-08`.
6. **Partición cronológica utilizada en Fase 1 (`60% / 20% / 20%`):**
   - **Entrenamiento (`Train`):** `90` partidos (`2026-02-22` $\rightarrow$ `2026-07-10`).
   - **Validación Temporal (`Val`):** `30` partidos (`2026-07-18` $\rightarrow$ `2026-09-04`).
   - **Prueba Final Retenida (`Test`):** `30` partidos (`2026-09-12` $\rightarrow$ `2026-10-08`).
7. **Explicación matemática exacta del `Baseline Brier = 0.7141` (`0.714074`) de Fase 1:**
   - En los **90 partidos de entrenamiento (`Train`)** ocurrieron:
     - Victorias locales ($H$): $53 \implies p_{\text{base}, H} = \frac{53}{90} = 0.58889$
     - Empates ($D$): $17 \implies p_{\text{base}, D} = \frac{17}{90} = 0.18889$
     - Victorias visitantes ($A$): $20 \implies p_{\text{base}, A} = \frac{20}{90} = 0.22222$
   - En los **30 partidos de prueba (`Test`)** ocurrieron **12 victorias locales ($H$)**, **9 empates ($D$)** y **9 victorias visitantes ($A$)**.
   - El error cuadrático multiclase $\sum_{k \in \{H,D,A\}} (p_{\text{base}, k} - y_{i,k})^2$ por tipo de resultado real en `Test` es:
     - Cuando gana el local ($y = H$, 12 veces): $(0.58889 - 1)^2 + 0.18889^2 + 0.22222^2 = 0.16901 + 0.03568 + 0.04938 = \mathbf{0.254074}$
     - Cuando hay empate ($y = D$, 9 veces): $0.58889^2 + (0.18889 - 1)^2 + 0.22222^2 = 0.34679 + 0.65790 + 0.04938 = \mathbf{1.054074}$
     - Cuando gana el visitante ($y = A$, 9 veces): $0.58889^2 + 0.18889^2 + (0.22222 - 1)^2 = 0.34679 + 0.03568 + 0.60494 = \mathbf{0.987407}$
   - Promedio sobre los 30 partidos de prueba:
     $$\text{BS}_{\text{baseline}} = \frac{12(0.254074) + 9(1.054074) + 9(0.987407)}{30} = \frac{3.04889 + 9.48667 + 8.88667}{30} = \frac{21.42222}{30} = \mathbf{0.714074} \approx \mathbf{0.7141}$$
8. **Confirmación de ausencia de fuga temporal (*Zero Data Leakage*):**
   - Confirmado mediante inspección de código (`kickoff_utc < target_match.kickoff_utc` en `PointInTimeFeatureBuilder`) y verificado por las pruebas automatizadas `test_zero_future_data_leakage_in_feature_builder` y `test_batch_chronological_features_exact_equivalence_and_no_leakage`.

---

## PASO 2 Y 3. FUENTES DE DATOS REALES, LICENCIAS Y CALIDAD DE DATOS

### 1. Evaluación de Licencias para uso en un futuro SaaS Comercial
- **OpenFootball (`github.com/openfootball/football.json`):**
  - **Licencia:** **CC0-1.0 Universal (Dedicación al Dominio Público)**.
  - **Compatibilidad SaaS:** **100% compatible con explotación comercial y SaaS** sin restricciones de atribución ni cláusulas no comerciales. Seleccionada como fuente primaria de entrenamiento de la Fase 2 (`provider_code = 'OPENFOOTBALL_CC0'`, `is_demo = FALSE`).
- **StatsBomb Open Data (`github.com/statsbomb/open-data`):**
  - **Licencia:** **CC BY-NC-SA 4.0 (Atribución - NoComercial - CompartirIgual)**.
  - **Compatibilidad SaaS:** Se auditó su catálogo (`80` pares competición-temporada verificados en `statsbomb_competitions_catalog.json`), pero dado que su licencia incluye la restricción **NoComercial (`NC`)**, se mantiene aislada exclusivamente para investigación académica/experimental y **no se mezcla en el entrenamiento del motor comercial SaaS** para proteger la propiedad intelectual del producto.

### 2. Métricas de Ingestión y Calidad de Datos (`phase2_quality_report.json`)
- **Archivos históricos procesados:** `12` temporadas-liga oficiales (`2021-22`, `2022-23`, `2023-24` de **Premier League**, **LaLiga EA Sports**, **Serie A** y **Bundesliga**).
- **Partidos reales inspeccionados e insertados (`is_demo = FALSE`):** **`4,338` partidos reales**.
  - **Premier League (`ENG_EPL`):** `1,140` partidos (3 temporadas $\times$ 380).
  - **LaLiga EA Sports (`ESP_LALIGA`):** `1,140` partidos (3 temporadas $\times$ 380).
  - **Serie A (`ITA_SERIEA`):** `1,140` partidos (3 temporadas $\times$ 380).
  - **Bundesliga (`GER_BUNDESLIGA`):** `918` partidos (3 temporadas $\times$ 306).
- **Normalización de clubes:** `5,684` ocurrencias de nombres brutos normalizadas hacia **`95` clubes canónicos únicos** registrados con sus alias en `team_aliases`.
- **Valores faltantes detectados:** `272` partidos no contaban con marcador parcial al descanso (`ht_score = NULL`), los cuales fueron identificados y preservados con `ht_home_goals = NULL` sin inventar datos faltantes (confirmando por qué el mercado Nivel 2 `HALF_TIME_RESULT` permanece bloqueado por gobernanza).
- **Anomalías de marcador o duplicados:** `0` marcadores negativos/inconsistentes, `0` duplicados tras clave natural compuesta `(comp_code, season, date, home_team, away_team)`.
- **Copia local reproducible:** Guardada en `backend/data/real_historical/openfootball_real_matches_cc0.csv`.

---

## PASO 4 Y 5. ENTRENAMIENTO REAL (`v2.0.0-real-cc0`) Y COMPARACIÓN CIENTÍFICA

### 1. Partición Estrictamente Cronológica (Exclusivamente Datos Reales, $N = 4,338$)
- **Entrenamiento (`Train` - 60%):** **`2,602` partidos reales** (`2021-08-13` $\rightarrow$ `2023-04-22`).
  - Frecuencia empírica real en `Train` (*Naive Baseline*): Local $43.58\%$, Empate $25.33\%$, Visitante $31.09\%$.
- **Validación Temporal (`Val` - 20%):** **`868` partidos reales** (`2023-04-22` $\rightarrow$ `2023-12-10`).
- **Prueba Final Retenida (`Test` - 20%):** **`868` partidos reales** (`2023-12-10` $\rightarrow$ `2024-06-02`).

### 2. Tabla Comparativa: FASE 1 (Sintético $N_{\text{test}}=30$) vs FASE 2 (Real $N_{\text{test}}=868$)

| Modelo | Fase 1 Test Brier ($N=30$) | **Fase 2 Val Brier ($N=868$)** | **Fase 2 Test Brier ($N=868$) ↓** | **IC 95% Brier (Fase 2)** | **Fase 2 Log Loss ↓** | **Fase 2 ECE ↓** | **Fase 2 Accuracy ↑** | **Peso Ensamble (SLSQP)** |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **Referencia Ingenua (*Baseline*)** | `0.71407` | `0.66263` | `0.65334` | — | `1.07680` | — | `44.93%` | — |
| **Modelo A: Poisson / Dixon-Coles** | `0.62604` | `0.58403` | `0.58981` | `[0.57013, 0.60948]` | `0.98714` | **`0.00437`** | `52.07%` | **`5.38%`** |
| **Modelo B: Elo Dinámico** | `0.64583` | `0.58208` | `0.58467` | `[0.56821, 0.60113]` | `0.97831` | `0.03120` | **`52.88%`** | `0.00%` *(Podado)* |
| **Modelo C: Random Forest Calibrado** | `0.68457` | **`0.56963`** | `0.58168` | `[0.56083, 0.60253]` | `0.97460` | `0.03810` | `52.53%` | **`94.62%`** |
| **Modelo D: XGBoost Calibrado** | `0.67487` | `0.57249` | `0.58336` | `[0.56351, 0.60320]` | `0.97742` | `0.03573` | **`52.88%`** | `0.00%` *(Podado)* |
| **Modelo E: Ensamble (SLSQP)** | `0.64825` | **`0.56959`** | **`0.58131`** | **`[0.56065, 0.60198]`** | **`0.97416`** | `0.03651` | `52.76%` | **`100.00%`** |

### 3. Análisis Científico: ¿Continúa siendo Poisson superior en Fase 2?
- **Cambio de régimen por tamaño muestral ($N_{\text{train}} = 90 \rightarrow 2,602$):**
  - En la **Fase 1** ($N_{\text{train}}=90$), los modelos de árboles (`Random Forest` y `XGBoost`) disponían de muy pocos ejemplos para 31 variables predictivas, sufriendo varianza alta, por lo que el modelo paramétrico **Poisson (`0.62604`)** fue el mejor.
  - En la **Fase 2**, al entrenar con **`2,602` partidos reales** y calibrar mediante validación cruzada interna (`cv=3` en `Train`), **todos los modelos (C, D y B) superan a Poisson en Brier Score y Log Loss sobre los `868` partidos reales de prueba** (`RF: 0.58168`, `XGB: 0.58336`, `Elo: 0.58467` vs `Poisson: 0.58981`).
  - **Por qué ocurre esto:** `Random Forest` y `XGBoost` integran simultáneamente el diferencial Elo (`elo_diff`: importancia del `19.19%` en RF y `17.83%` en XGB), la diferencia de posición en tabla (`league_pos_diff`: `8.83%`), el rendimiento de goles y puntos en los últimos 5 y 10 partidos, los días de descanso y el historial H2H.
  - **Valor complementario de Poisson:** Aun así, **Poisson logra el menor error de calibración global (`ECE = 0.00437`)**, y el optimizador convexo `SLSQP` en validación le asigna un **`5.38%` de peso junto con `94.62%` a Random Forest**, logrando que el **Ensamble (`0.58131` Brier, `0.97416` LogLoss)** supere a todos los modelos individuales en el conjunto de prueba final.
  - **Poda sin pesos forzados:** Cumpliendo la regla de *no forzar pesos positivos*, el optimizador `SLSQP` asignó **`0.00%` a Elo y `0.00%` a XGBoost** en el ensamble porque su señal ya estaba capturada por `Random Forest + Poisson`.

### 4. Rendimiento por Competición Real en Prueba Final ($N_{\text{test}} = 868$, Modelo E: Ensamble)

| Competición | Partidos Evaluados (`Test`) | Accuracy | Brier Score ↓ | Log Loss ↓ |
| :--- | :---: | :---: | :---: | :---: |
| **Premier League (`ENG_EPL`)** | `224` | **`55.36%`** | **`0.56352`** | **`0.95229`** |
| **LaLiga EA Sports (`ESP_LALIGA`)** | `226` | `54.42%` | `0.57762` | `0.96943` |
| **Bundesliga (`GER_BUNDESLIGA`)** | `183` | `49.73%` | `0.59142` | `0.98793` |
| **Serie A (`ITA_SERIEA`)** | `235` | `51.06%` | `0.59395` | `0.98882` |

---

## PASO 6. ERRORES ENCONTRADOS, LIMITACIONES Y RECOMENDACIONES PARA FASE 3

### 1. Errores Encontrados y Resueltos Durante la Ingestión Real
1. **Colisión de clave externa por prefijo de 3 letras en Serie A (`2023-01-14`):**
   - *Causa:* Clubes como `US Lecce` y `US Cremonese` compartían el prefijo `"US "` y jugaron en la misma fecha (`2023-01-14`) contra rivales con prefijo `"AC "` (`AC Milan` y `AC Monza`), disparando la restricción `UNIQUE constraint failed: matches.external_ref`.
   - *Solución aplicada:* Se reemplazó el sufijo truncado de 3 letras por un hash determinista SHA-1 de 10 caracteres sobre la clave natural canónica completa `(comp_code, season, date, norm_home, norm_away)` y se amplió el diccionario `CANONICAL_TEAM_MAP`.

### 2. Limitaciones Actuales del Dataset Abierto (`CC0-1.0`)
1. **Ausencia de cuotas históricas reales en OpenFootball:** Dado que `openfootball/football.json` es un repositorio deportivo puro y no de casas de apuestas, `market_brier_score` es `NULL` y `simulated_bets_count = 0` en los `868` partidos reales de prueba (no se inventaron cuotas falsas para los partidos reales).
2. **Ausencia de estadísticas de micro-eventos (xG, tiros a puerta, córners, tarjetas) en OpenFootball:** Variables como `home_sot_last5`, `home_corners_last5` y `home_cards_last5` tienen importancia `0.0` en este corte porque la fuente CC0 provee marcadores FT/HT pero no conteo de córners ni tiros.

### 3. Recomendaciones Técnicas para la FASE 3 (Profundización del Motor de ML)
1. **Decaimiento temporal exponencial en Poisson (Dixon-Coles $\xi$):** Ponderar los partidos de entrenamiento con $w(\Delta t) = e^{-\xi \Delta t}$ para que el estado de forma reciente pese más que los partidos de hace dos temporadas al estimar $\alpha_i, \beta_i$.
2. **Elo específico por competición y margen de goles ajustado:** Permitir un factor de ventaja local ($\text{HFA}$) dinámico por liga (ya que en Serie A y Bundesliga la ventaja local post-2021 difiere de LaLiga).
3. **Incorporación de fuente autorizada de cuotas históricas y tiros/córners:** Para evaluar el ROI/Yield real frente al mercado y desbloquear en el futuro los mercados de Nivel 3 (`CORNERS_OU`, `CARDS_OU`, `SHOTS_ON_TARGET`).
