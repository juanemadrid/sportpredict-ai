# SPORTPREDICT AI — INFORME DE AUDITORÍA TÉCNICA Y ESTADÍSTICA COMPLEMENTARIA DE LA FASE 3 (`06_AUDITORIA_COMPLEMENTARIA_FASE3.md`)

**Fecha de Ejecución:** Noviembre 2026  
**Tipo de Auditoría:** Auditoría Independiente de Solo Lectura (Pre-Fase 4)  
**Script de Verificación Automatizada:** [`backend/run_phase3_complementary_audit.py`](file:///f:/Proyectos/Predicciones/backend/run_phase3_complementary_audit.py)  
** Evidencia Empírica Serializada:** [`backend/data/real_historical/phase3_complementary_audit_results.json`](file:///f:/Proyectos/Predicciones/backend/data/real_historical/phase3_complementary_audit_results.json)  
**Estado de Integridad de Datos y Artefactos:**
- Base de datos [`sportpredict_local.db`](file:///f:/Proyectos/Predicciones/backend/data/sportpredict_local.db) intacta antes y después de la auditoría (`SHA-256 = 54bd5ca6e647947ca44951c8a5bc7ed669235f5da3a0098e86fbb84640f13188`, `database_unmodified = true`).
- Modelos `v1.0.0-mvp`, `v1.1.0`, `v2.0.0-real-cc0`, `v2.4.0-real-cc0`, `v2.5.0-real-cc0` y `v3.0.0-phase3-scientific` preservados sin sobrescritura.

---

## 1. HALLAZGOS CONFIRMADOS

La auditoría automatizada ejecutada sobre la totalidad del dataset histórico real autorizado (`4,338` partidos reales CC0-1.0 de las temporadas `2022/23`, `2023/24` y `2024/25` en Premier League, LaLiga EA Sports, Serie A y Bundesliga) confirma con pruebas reproducibles los siguientes puntos:

1. **Verificación Point-in-Time al 100% en el Conjunto de Prueba (`N = 868` partidos):**
   - No se limitó la inspección a la muestra previa de 40 partidos. El script [`run_phase3_complementary_audit.py`](file:///f:/Proyectos/Predicciones/backend/run_phase3_complementary_audit.py) reconstruyó desde cero las `29` variables predictivas (`feature_names`), las clasificaciones de liga pre-partido (`LeagueTableTracker`) y los ratings Elo (`DynamicEloModel`) sobre **las `868` observaciones de prueba (`Test`) y las `4,338` observaciones totales**.
   - **Resultado:** `0` violaciones de marca temporal futura (`future_timestamp_violations = 0`), `0` auto-inclusiones del partido objetivo (`self_inclusion_violations = 0`), `0` discrepancias en las 29 columnas de features en los 868 partidos (`868 / 868 = 100%` exactitud numérica con tolerancia $< 10^{-9}$), `0` discrepancias en posiciones/puntos/goles de tabla de liga pre-partido (`868 / 868`), y `0` discrepancias en los ratings Elo pre-partido en los `4,338` encuentros (`4,338 / 4,338`).
2. **Fronteras Cronológicas Estrictas y Sin Solapamiento:**
   - `Train` (`2,605` partidos): `2022-08-05T12:00:00` a `2024-03-10T12:00:00`.
   - `Validation` (`865` partidos): `2024-03-10T12:00:00` a `2024-11-10T12:00:00` (`train_max <= val_min = true`).
   - `Test` (`868` partidos): `2024-11-10T12:00:00` a `2025-05-25T12:00:00` (`val_max <= test_min = true`).
   - Intersección de `external_id` entre conjuntos: `0` partidos solapados (`overlap_ids_count = 0`).
3. **Ausencia de Fuga en el Ensamble Principal 1X2 (`ENSEMBLE`):**
   - El ensamble 1X2 (`SimplexEnsembleModel`) **no utiliza meta-features `poisson_*` entrenadas in-sample**. Combina directamente las distribuciones de probabilidad 1X2 de los 4 modelos base y optimiza sus pesos (`0.7569 XGBOOST + 0.1589 RANDOM_FOREST + 0.0842 POISSON + 0.0000 ELO`) exclusivamente sobre las predicciones **out-of-sample** del conjunto `Validation` (`865` partidos).
4. **Superioridad Confirmatoria Frente al Baseline Histórico en 1X2 y Mercados Principales de Goles:**
   - Tras aplicar corrección por comparaciones múltiples de **Holm-Bonferroni** ($\alpha = 0.05$) y verificar sensibilidad del tamaño de bloque ($L \in \{10, 20, 39, 50\}$ y bloques estratificados por competición $L_c = 10$), los 5 modelos 1X2 superan de forma altamente significativa al `Baseline Histórico` (`Brier = 0.65331`), con $p_{\text{Holm}} = 0.0005 < 0.05$ en todos los casos (`RANDOM_FOREST = 0.57943`, `ENSEMBLE = 0.58036`, `XGBOOST = 0.58162`, `ELO = 0.58332`, `POISSON = 0.59239`).
5. **Reproducibilidad Numérica Exacta (`0` Discrepancias):**
   - La re-ejecución en modo de solo lectura cargando el artefacto [`sportpredict_models_v3.0.0-phase3-scientific.joblib`](file:///f:/Proyectos/Predicciones/backend/artifacts/sportpredict_models_v3.0.0-phase3-scientific.joblib) reproduce al 100% los valores de `Brier Score` y `Log Loss` reportados en [`phase3_scientific_report.json`](file:///f:/Proyectos/Predicciones/backend/data/real_historical/phase3_scientific_report.json) (`reproducibility_discrepancies_count = 0`).

---

## 2. PROBLEMAS ENCONTRADOS

La auditoría identificó **3 problemas técnicos/metodológicos reales** que deben documentarse con total transparencia antes de la Fase 4:

### Problema 1 (Severidad Media-Alta): Meta-Features `poisson_*` Generadas In-Sample sobre `T_train` en los Modelos de Árboles para Mercados de Goles (`RF_GOALS` y `XGB_GOALS`)
- **Ubicación:** [`backend/run_phase3_scientific_audit.py`](file:///f:/Proyectos/Predicciones/backend/run_phase3_scientific_audit.py#L571-L576) y [`backend/app/ml/models/goals_market_models.py`](file:///f:/Proyectos/Predicciones/backend/app/ml/models/goals_market_models.py#L140-L157).
- **Descripción:** Para entrenar los clasificadores binarios `RF_GOALS` y `XGB_GOALS` en los 5 mercados de goles (`OVER_1_5`, `OVER_2_5`, `UNDER_2_5`, `OVER_3_5`, `BTTS`), se añadieron 4 meta-variables derivadas de Poisson (`poisson_market_prob`, `poisson_lambda_total`, `poisson_lambda_home`, `poisson_lambda_away`). Mientras que en `Validation` (`865`) y `Test` (`868`) dichas variables se generaron **out-of-sample**, en `Train` (`2,605`) se generaron evaluando `p3_poisson_val_model` sobre los mismos `2,605` partidos con los que `p3_poisson_val_model` fue ajustado (**predicciones in-sample** en lugar de *out-of-fold* temporal).
- **Consecuencia:** Como `poisson_*` in-sample tenía menor error en `T_train` que en operación real out-of-sample, los árboles `RF_GOALS` sobre-ponderaron artificialmente esas 4 variables (`50.38%` a `62.36%` de la importancia total Gini).

### Problema 2 (Severidad Media): Conclusiones de Comparaciones Múltiples entre Modelos que Pasan de "Significativas" a "Exploratorias" tras Corrección de Holm-Bonferroni
- **Ubicación:** Comparaciones pareadas en [`phase3_scientific_report.json`](file:///f:/Proyectos/Predicciones/backend/data/real_historical/phase3_scientific_report.json).
- **Descripción:** En el reporte original de Fase 3 se evaluaron 10 pruebas en 1X2 y 20 pruebas en mercados de goles utilizando el umbral individual $p_{\text{raw}} < 0.05$ sin ajuste por multiplicidad (Family-Wise Error Rate, FWER).
- **Consecuencia:** Al aplicar **Holm-Bonferroni** ($\alpha = 0.05$):
  1. En la familia de comparaciones inter-modelos 1X2 ($m = 9$): la ventaja de `ENSEMBLE vs POISSON` ($p_{\text{raw}} = 0.0060 \implies p_{\text{Holm}} = 0.0540$) y de `ENSEMBLE vs XGBOOST` ($p_{\text{raw}} = 0.0190 \implies p_{\text{Holm}} = 0.1520$) **no alcanza significancia confirmatoria estricta** bajo corrección FWER, debiendo clasificarse como **evidencia exploratoria**.
  2. En la familia de 20 pruebas de mercados de goles contra el Baseline ($m = 20$): `OVER_2_5`, `UNDER_2_5` y `OVER_3_5` mantienen significancia confirmatoria ($p_{\text{Holm}} \le 0.0240 < 0.05$), pero `OVER_1_5` ($p_{\text{raw}} = 0.0100 \implies p_{\text{Holm}} = 0.1000$) y `BTTS` ($p_{\text{raw}} = 0.0170 \implies p_{\text{Holm}} = 0.1190$) deben clasificarse como **exploratorios** cuando se corrige por las 20 pruebas simultáneas.

### Problema 3 (Severidad Baja-Media, Operativa en Base de Datos): Coexistencia de `is_active = True` en `v3.0.0-phase3-scientific` y `v2.5.0-real-cc0`
- **Ubicación:** Tabla `ml_models` en [`sportpredict_local.db`](file:///f:/Proyectos/Predicciones/backend/data/sportpredict_local.db) e integración con [`backend/tests/test_phase2_real_data.py`](file:///f:/Proyectos/Predicciones/backend/tests/test_phase2_real_data.py).
- **Descripción:** El inventario de base de datos reveló `25` registros en `ml_models`: las versiones `v1.0.0-mvp`, `v1.1.0` y `v2.0.0-real-cc0` tienen `is_active = False`, pero tanto `v3.0.0-phase3-scientific` (IDs `16–20`) como `v2.5.0-real-cc0` (IDs `26–30`) tienen `is_active = True`. Esto ocurre porque el test de Fase 2 ([`test_phase2_real_data.py`](file:///f:/Proyectos/Predicciones/backend/tests/test_phase2_real_data.py)) entrena y guarda `v2.5.0-real-cc0` con `is_active = True` sobre la base de datos local cuando se ejecuta `pytest` después del script de Fase 3, sin desactivar versiones previas.

---

## 3. AUDITORÍA DE FILTRACIÓN DE INFORMACIÓN (DATA LEAKAGE)

### 3.1 Verificación Automatizada Exhaustiva sobre los `868` Partidos de Prueba y `4,338` Totales

Se auditó el constructor [`PointInTimeFeatureBuilder`](file:///f:/Proyectos/Predicciones/backend/app/ml/features/point_in_time_features.py), el rastreador de tabla [`LeagueTableTracker`](file:///f:/Proyectos/Predicciones/backend/app/ml/features/point_in_time_features.py#L22-L120) y [`DynamicEloModel`](file:///f:/Proyectos/Predicciones/backend/app/ml/models/elo_model.py):

| Métrica de Auditoría de Fuga Temporal | Universo Evaluado | Violaciones Detectadas | Estado |
| :--- | :---: | :---: | :---: |
| Partidos del historial con `kickoff_utc >= target.kickoff_utc` | `868 / 868` (`Test`) | **`0`** | ✅ APROBADO |
| Auto-inclusión del partido objetivo en sus propias variables | `868 / 868` (`Test`) | **`0`** | ✅ APROBADO |
| Discrepancia en cualquiera de las `29` features pre-partido ($\|\Delta\| > 10^{-9}$) | `868 × 29 = 25,172` celdas | **`0`** | ✅ APROBADO |
| Discrepancia en posición, puntos, PJ y DG de clasificación de liga pre-partido | `868 / 868` (`Test`) | **`0`** | ✅ APROBADO |
| Discrepancia en ratings Elo pre-partido (`elo_home_pre`, `elo_away_pre`) en `Test` | `868 / 868` (`Test`) | **`0`** | ✅ APROBADO |
| Discrepancia en ratings Elo pre-partido en `Train + Validation` | `3,470 / 3,470` (`Train+Val`) | **`0`** | ✅ APROBADO |
| Solapamiento de `external_id` entre `Train`, `Val` y `Test` | `4,338` partidos | **`0`** | ✅ APROBADO |

#### Muestras Auditadas del Conjunto de Prueba (`Test`, `N = 868`)
- **Primer partido de `Test` (`index 0`, `match_id = 3592`):** `2024-11-10T12:00:00` (`LaLiga EA Sports`: Real Betis vs Celta Vigo). Historial previo disponible: Betis `88` partidos (`max_prev_kickoff = 2024-11-03T12:00:00 < kickoff`), Celta `88` partidos (`max_prev_kickoff = 2024-11-04T12:00:00 < kickoff`). Estado en liga antes del encuentro: Betis `7.º` (`19` pts en `12` PJ), Celta `10.º` (`16` pts en `12` PJ). Elo pre-partido: `1548.36` vs `1495.59`.
- **Partido intermedio (`index 434`, `match_id = 1711`):** `2025-02-15T12:00:00` (`Premier League`: Aston Villa vs Ipswich Town). Historial previo: Aston Villa `100` partidos (`max = 2025-02-09`), Ipswich `24` partidos (`max = 2025-02-01`). Estado en liga pre-partido: Aston Villa `8.º` (`37` pts en `24` PJ), Ipswich `19.º` (`16` pts en `24` PJ). Elo pre-partido: `1567.79` vs `1414.23`.
- **Último partido de `Test` (`index 867`, `match_id = 4074`):** `2025-05-25T12:00:00` (`Serie A`: Venezia FC vs Juventus). Historial previo: Venezia `37` partidos (`max = 2025-05-18`), Juventus `113` partidos (`max = 2025-05-18`). Estado en liga pre-partido: Venezia `19.º` (`29` pts en `37` PJ), Juventus `4.º` (`67` pts en `37` PJ). Elo pre-partido: `1435.58` vs `1593.07`.

### 3.2 Observaciones Metodológicas Internas a `T_train` (Sin Filtración hacia `T_val` ni `T_test`)

Aunque `T_val` (`865`) y `T_test` (`868`) están **100% libres de información futura**, la inspección de código fuente detectó dos detalles internos al bloque de entrenamiento `T_train` (`2,605` partidos):
1. **`OBS-1A` (`DynamicEloModel.calibrate_competition_parameters`):** Antes de recorrer cronológicamente `T_train`, el modelo Elo calcula 4 escalares de ventaja de localía (`comp_home_advantage`) y 4 escalares de tasa de empate (`comp_draw_nu`) usando el promedio global de los `2,605` partidos de `T_train`. Esto significa que dentro de `T_train` esos 8 escalares estáticos conocen la media de la temporada 2022–2024; sin embargo, **ningún dato de `T_val` ni `T_test` interviene en dicho cálculo**.
2. **`OBS-1B` (`CalibratedClassifierCV(cv=3)` en `CalibratedRandomForestModel` y `CalibratedXGBoostModel`):** Dentro de `T_train`, Scikit-Learn utiliza `StratifiedKFold(3)` estándar para ajustar el calibrador isotónico/sigmoide interno y reporta `train_brier` evaluando sobre `T_train`. Nuevamente, **esto ocurre exclusivamente dentro de `T_train` (`2,605` partidos)** y no contamina en absoluto a `T_val` (`865`) ni a `T_test` (`868`).

---

## 4. AUDITORÍA DE LOS ENSAMBLES Y META-FEATURES (`poisson_*`)

### 4.1 Diagnóstico de `poisson_market_prob`, `poisson_lambda_total`, `poisson_lambda_home`, `poisson_lambda_away`

En los modelos de mercados de goles ([`goals_market_models.py`](file:///f:/Proyectos/Predicciones/backend/app/ml/models/goals_market_models.py)), la función [`augment_features_with_poisson_signals`](file:///f:/Proyectos/Predicciones/backend/app/ml/models/goals_market_models.py#L140-L157) concatena a las 29 features point-in-time las 4 señales analíticas del modelo de Dixon-Coles.

La auditoría comparó la calidad de dichas señales en `T_train` (`2,605` partidos) bajo el esquema actual (**In-Sample**, donde `p3_poisson_val_model` fue entrenado con todo `T_train`) frente a un esquema riguroso **Out-of-Fold Temporal (Expanding Window de 5 bloques cronológicos)** donde cada bloque de `T_train` es predicho únicamente por un modelo Dixon-Coles entrenado en bloques estrictamente anteriores:

| Estadístico en `T_train` (`N = 2,605`) | Esquema Actual (In-Sample en `T_train`) | Esquema Corregido (Out-of-Fold Temporal en `T_train`) | Conjunto `Test` (`N = 868`, Out-of-Sample) |
| :--- | :---: | :---: | :---: |
| Media de `poisson_lambda_total` | `2.8669` goles | `2.8235` goles | `2.8012` goles |
| RMSE de `poisson_lambda_total` vs Goles Reales | **`1.5887`** (artificialmente bajo) | **`1.7021`** (realista) | **`1.6626`** |
| Correlación de Pearson $r(\lambda_{\text{total}}, \text{Goles Reales})$ | **`0.3376`** (inflada in-sample) | **`0.1387`** (realista out-of-sample) | **`0.1818`** |

### 4.2 Cuantificación Exacta del Impacto en Importancia de Variables y `Brier Score` de Prueba (`T_test`)

Sin modificar los modelos guardados en disco ni en base de datos, el script de auditoría entrenó réplicas en memoria de `RF_GOALS`, `XGB_GOALS` y `ENSEMBLE_GOALS` utilizando las predicciones **Out-of-Fold Temporales** en `T_train` y cuantificó la diferencia exacta en `T_test` (`868` partidos):

| Mercado | Importancia Gini de las 4 vars `poisson_*` en `RF_GOALS` (In-Sample vs OOF) | `RF_GOALS` Brier Test (In-Sample $\rightarrow$ OOF) | `XGB_GOALS` Brier Test (In-Sample $\rightarrow$ OOF) | `POISSON` Puro Brier Test (Sin cambio) | `ENSEMBLE_GOALS` Brier Test (In-Sample $\rightarrow$ OOF) | $\Delta$ Brier en `ENSEMBLE_GOALS` (OOF - InSample) | Pesos del Ensamble `(Poisson, RF, XGB)` (In-Sample $\rightarrow$ OOF) |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **`OVER_1_5`** | `50.38%` $\rightarrow$ `20.30%` | `0.16197` $\rightarrow$ `0.16137` | `0.16311` $\rightarrow$ `0.16201` | **`0.15973`** | `0.15973` $\rightarrow$ `0.15998` | `+0.00025` | `(1.00, 0.00, 0.00)` $\rightarrow$ `(0.74, 0.26, 0.00)` |
| **`OVER_2_5`** | `57.15%` $\rightarrow$ `24.16%` | `0.23362` $\rightarrow$ `0.23999` | `0.23676` $\rightarrow$ `0.23930` | **`0.23415`** | `0.23352` $\rightarrow$ `0.23432` | `+0.00080` | `(0.48, 0.52, 0.00)` $\rightarrow$ `(0.70, 0.00, 0.30)` |
| **`UNDER_2_5`** | `57.53%` $\rightarrow$ `24.08%` | `0.23383` $\rightarrow$ `0.23994` | `0.23716` $\rightarrow$ `0.23929` | **`0.23415`** | `0.23359` $\rightarrow$ `0.23433` | `+0.00074` | `(0.52, 0.48, 0.00)` $\rightarrow$ `(0.70, 0.00, 0.30)` |
| **`OVER_3_5`** | `62.36%` $\rightarrow$ `32.19%` | `0.21912` $\rightarrow$ `0.22337` | `0.22130` $\rightarrow$ `0.22295` | **`0.21648`** | `0.21648` $\rightarrow$ **`0.21632`** | **`-0.00016`** (mejora) | `(1.00, 0.00, 0.00)` $\rightarrow$ `(0.73, 0.27, 0.00)` |
| **`BTTS`** | `52.53%` $\rightarrow$ `19.53%` | `0.24219` $\rightarrow$ `0.24698` | `0.24280` $\rightarrow$ `0.24420` | **`0.24264`** | `0.24220` $\rightarrow$ `0.24336` | `+0.00116` | `(0.36, 0.14, 0.50)` $\rightarrow$ `(0.29, 0.00, 0.71)` |

**Interpretación Técnica del Hallazgo:**
1. Cuando `RF_GOALS` se entrenó con `poisson_*` in-sample, aprendió a confiar en `poisson_*` entre un `50%` y un `62%`, convirtiéndose de facto en un suavizador no lineal del propio modelo de Poisson. Por eso en `Test` obtuvo un Brier casi idéntico a Poisson (`0.23362` vs `0.23415` en `OVER_2_5`).
2. Cuando se corrige con predicciones `poisson_*` **Out-of-Fold Temporales**, `RF_GOALS` reduce el peso de `poisson_*` a `19.5%–32.2%` y reparte la importancia entre las 29 features tabulares, lo que incrementa ligeramente el Brier de `RF_GOALS` individual en `+0.0048` a `+0.0064` (excepto en `OVER_1_5`, donde **mejora** de `0.16197` a `0.16137`).
3. Sin embargo, el impacto sobre el **Ensamble de Goles (`ENSEMBLE_GOALS`)** es mínimo (`+0.00025` a `+0.00116` puntos de Brier, e incluso mejora `-0.00016` en `OVER_3_5`), porque el optimizador `GoalMarketSimplexEnsemble` sobre `T_val` reasigna automáticamente el peso mayoritario (`70%–74%`) al modelo analítico `POISSON` puro.

---

## 5. RESULTADOS DE LA AUDITORÍA ESTADÍSTICA

### 5.1 Revisión de Implementación y Justificación de `block_size = 20` en Moving Block Bootstrap

- **Estructura Temporal del Conjunto de Prueba (`N = 868`):** Abarca `27` semanas calendario (del `10-nov-2024` al `25-may-2025`) a través de `4` ligas europeas simultáneas (`224` partidos de Premier League, `226` de LaLiga, `235` de Serie A y `183` de Bundesliga).
- **Densidad por Jornada Semanal:** En cada fin de semana europeo se disputan $\approx 39$ partidos combinados ($\approx 10$ por liga) y en ventanas de 3–4 días aproximadamente `20` partidos. Un bloque de $L = 20$ captura medio ciclo semanal multi-liga, preservando la correlación contemporánea entre partidos de la misma jornada (clima, calendario UEFA, fatiga) y cumpliendo la regla asintótica de Künsch (1989) $L \approx N^{1/3}$ a $N^{1/2}$ ($868^{1/3} = 9.54$, $868^{1/2} = 29.46$, punto medio $\approx 20$).
- **Auditoría del Efecto de Borde:** En la implementación lineal de [`statistical_audit.py`](file:///f:/Proyectos/Predicciones/backend/app/ml/evaluation/statistical_audit.py#L46-L78), los bloques lineales se extraen con inicio $s \in \{0, \dots, N - L\}$. Como en todo Moving Block Bootstrap no circular, las primeras $L-1$ y últimas $L-1$ observaciones tienen menor frecuencia de muestreo. Para comprobar que este efecto de borde y la mezcla de 4 ligas en orden cronológico no distorsionan las inferencias, se ejecutaron dos pruebas adicionales:
  1. **Circular Block Bootstrap (Politis & Romano, 1992)** con $L \in \{10, 20, 39, 50\}$ (donde cada uno de los `868` partidos tiene exactamente igual probabilidad $1/868$ de ser muestreado).
  2. **Bootstrap por Bloques Estratificado por Competición** con $L_c = 10$ partidos dentro de cada liga individual (equivalente a `1` jornada completa por liga).

| Comparación Auditada (`N = 868`) | $\Delta$ Brier Puntual | Lineal $L=20$ (Original Fase 3) | Circular $L=10$ | Circular $L=20$ | Circular $L=39$ (1 Jornada 4 Ligas) | Circular $L=50$ | Estratificado por Liga ($L_c=10$) |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **`ENSEMBLE vs RANDOM_FOREST`** | **`+0.00093`** | IC `[-0.00221, +0.00409]` $p=0.5800$ | IC `[-0.00222, +0.00406]` $p=0.5760$ | IC `[-0.00220, +0.00404]` $p=0.5740$ | IC `[-0.00208, +0.00399]` $p=0.5750$ | IC `[-0.00215, +0.00383]` $p=0.5790$ | IC `[-0.00227, +0.00419]` $p=0.5910$ |
| **`ENSEMBLE vs POISSON`** | **`-0.01203`** | IC `[-0.02096, -0.00308]` $p=0.0060$ | IC `[-0.02080, -0.00306]` $p=0.0075$ | IC `[-0.02092, -0.00334]` $p=0.0065$ | IC `[-0.02067, -0.00370]` $p=0.0045$ | IC `[-0.02032, -0.00382]` $p=0.0055$ | IC `[-0.02220, -0.00181]` $p=0.0195$ |
| **`RANDOM_FOREST vs BASELINE`** | **`-0.07388`** | IC `[-0.09128, -0.05669]` $p=0.0001$ | IC `[-0.09166, -0.05619]` $p<0.0001$ | IC `[-0.09134, -0.05660]` $p<0.0001$ | IC `[-0.09088, -0.05586]` $p<0.0001$ | IC `[-0.09142, -0.05638]` $p<0.0001$ | IC `[-0.09332, -0.05434]` $p<0.0001$ |

**Conclusión de Sensibilidad:** Las conclusiones estadísticas son **100% invariantes** al tamaño de bloque $L \in [10, 50]$, al cierre circular de fronteras y a la estratificación por liga.

### 5.2 Coherencia Matemática y Corrección por Comparaciones Múltiples de Holm-Bonferroni

Se verificaron las 4 familias de contrastes de hipótesis (`39` pruebas en total), confirmando `0` incoherencias entre el signo de $\Delta \text{Brier}$, la exclusión del `0` en el IC 95%, el estadístico $Z$ y el valor $p$ bilateral. A continuación se presenta la clasificación definitiva separando hallazgos **Confirmatorios** ($p_{\text{Holm}} < 0.05$) de hallazgos **Exploratorios** ($p_{\text{raw}} < 0.05$ pero $p_{\text{Holm}} \ge 0.05$):

#### A. Familia 1: Modelos 1X2 vs Baseline Histórico ($m = 5$ pruebas) — **100% Confirmatorios**
| Rango | Comparación | $\Delta$ Brier | IC 95% (Bootstrap) | Estadístico $Z$ | $p_{\text{raw}}$ | Umbral $\alpha_{\text{Holm}}$ | $p_{\text{Holm}}$ Ajustado | Clasificación Científica |
| :---: | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| 1 | `RANDOM_FOREST vs BASELINE` | `-0.07388` | `[-0.09128, -0.05669]` | `-8.419` | `0.0001` | `0.0100` | **`0.0005`** | ✅ **CONFIRMATORIO** |
| 2 | `ENSEMBLE vs BASELINE` | `-0.07295` | `[-0.09114, -0.05456]` | `-7.916` | `0.0001` | `0.0125` | **`0.0005`** | ✅ **CONFIRMATORIO** |
| 3 | `XGBOOST vs BASELINE` | `-0.07169` | `[-0.09061, -0.05288]` | `-7.571` | `0.0001` | `0.0167` | **`0.0005`** | ✅ **CONFIRMATORIO** |
| 4 | `ELO vs BASELINE` | `-0.06999` | `[-0.08750, -0.05279]` | `-8.059` | `0.0001` | `0.0250` | **`0.0005`** | ✅ **CONFIRMATORIO** |
| 5 | `POISSON vs BASELINE` | `-0.06092` | `[-0.07577, -0.04628]` | `-8.051` | `0.0001` | `0.0500` | **`0.0005`** | ✅ **CONFIRMATORIO** |

#### B. Familia 2: Comparaciones Entre Modelos 1X2 ($m = 9$ pruebas) — **Exploratorios / No Significativos**
| Rango | Comparación | $\Delta$ Brier | IC 95% (Bootstrap) | Estadístico $Z$ | $p_{\text{raw}}$ | Umbral $\alpha_{\text{Holm}}$ | $p_{\text{Holm}}$ Ajustado | Clasificación Científica |
| :---: | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| 1 | `ENSEMBLE_P3 vs POISSON_P3` | `-0.01203` | `[-0.02096, -0.00308]` | `-2.642` | `0.0060` | `0.0056` | **`0.0540`** | ⚠️ **EXPLORATORIO** ($p_{\text{raw}} < 0.01$, roza umbral Holm) |
| 2 | `ENSEMBLE_P3 vs XGBOOST_P3` | `-0.00126` | `[-0.00237, -0.00019]` | `-2.275` | `0.0190` | `0.0063` | **`0.1520`** | ⚠️ **EXPLORATORIO** ($p_{\text{raw}} < 0.05$, no supera Holm) |
| 3 | `ELO_P3 vs ELO_P2` | `-0.00135` | `[-0.00297, +0.00025]` | `-1.663` | `0.0980` | `0.0071` | `0.6860` | ➖ No significativo |
| 4 | `RF_P3 vs RF_P2` | `-0.00226` | `[-0.00602, +0.00142]` | `-1.196` | `0.2360` | `0.0083` | `1.0000` | ➖ No significativo |
| 5 | `ENSEMBLE_P3 vs ELO_P3` | `-0.00296` | `[-0.00865, +0.00279]` | `-1.015` | `0.3070` | `0.0100` | `1.0000` | ➖ No significativo |
| 6 | `POISSON_P3 vs POISSON_P2` | `+0.00258` | `[-0.00249, +0.00797]` | `+0.955` | `0.3370` | `0.0125` | `1.0000` | ➖ No significativo |
| 7 | `XGBOOST_P3 vs XGBOOST_P2` | `-0.00174` | `[-0.00579, +0.00241]` | `-0.838` | `0.4150` | `0.0167` | `1.0000` | ➖ No significativo |
| 8 | `ENSEMBLE_P3 vs ENSEMBLE_P2` | `-0.00095` | `[-0.00383, +0.00192]` | `-0.646` | `0.5060` | `0.0250` | `1.0000` | ➖ No significativo |
| 9 | `ENSEMBLE_P3 vs RF_P3` | `+0.00093` | `[-0.00221, +0.00409]` | `+0.562` | `0.5800` | `0.0500` | `1.0000` | ➖ Empate estadístico |

#### C. Familia 3: Modelos de Mercados de Goles vs Baseline ($m = 20$ pruebas)
- **Confirmatorios tras Holm-Bonferroni ($p_{\text{Holm}} < 0.05$):**
  - **`OVER_2_5`** (4 modelos: `RF_GOALS`, `ENSEMBLE_GOALS`, `POISSON`, `XGB_GOALS` vs Baseline): $\Delta \in [-0.0150, -0.0119]$, $p_{\text{raw}} = 0.0001 \implies$ **`p_Holm = 0.0020`** ✅ **CONFIRMATORIO**.
  - **`UNDER_2_5`** (4 modelos vs Baseline): $\Delta \in [-0.0151, -0.0115]$, $p_{\text{raw}} = 0.0001 \implies$ **`p_Holm = 0.0020`** ✅ **CONFIRMATORIO**.
  - **`OVER_3_5`** (`POISSON` y `ENSEMBLE_GOALS` vs Baseline): $\Delta = -0.0108$, $p_{\text{raw}} = 0.0020 \implies$ **`p_Holm = 0.0240`** ✅ **CONFIRMATORIO**.
- **Exploratorios tras Holm-Bonferroni ($p_{\text{raw}} < 0.05$, pero $p_{\text{Holm}} \ge 0.05$ por tamaño de familia $m=20$):**
  - **`OVER_3_5`** (`RF_GOALS` y `XGB_GOALS` vs Baseline): $p_{\text{raw}} \in [0.0070, 0.0170] \implies p_{\text{Holm}} \in [0.0700, 0.1190]$ ⚠️ **EXPLORATORIO**.
  - **`OVER_1_5`** (`POISSON` y `ENSEMBLE_GOALS` vs Baseline): $\Delta = -0.0077$, $p_{\text{raw}} = 0.0100 \implies p_{\text{Holm}} = 0.1000$ ⚠️ **EXPLORATORIO**.
  - **`BTTS`** (4 modelos vs Baseline): $\Delta \in [-0.0056, -0.0049]$, $p_{\text{raw}} \in [0.0170, 0.0320] \implies p_{\text{Holm}} \in [0.1190, 0.1280]$ ⚠️ **EXPLORATORIO**.

#### D. Familia 4: Árboles de Goles (`RF_GOALS`, `XGB_GOALS`) vs `POISSON` Puro ($m = 10$ pruebas)
- **`0 de 10` pruebas son significativas** ($p_{\text{raw}} \in [0.0850, 0.8980]$, $p_{\text{Holm}} \in [0.8500, 1.0000]$). **Conclusión confirmada:** Los árboles de decisión no superan estadísticamente al modelo analítico de Poisson/Dixon-Coles en mercados de goles.

---

## 6. ESTADO DE CALIBRACIÓN

### 6.1 Calibración Multiclase y Por Clase (`HOME`, `DRAW`, `AWAY`) en el Mercado 1X2 (`Test`, `N = 868`)

Frecuencias empíricas reales en `Test`: `HOME = 42.86%`, `DRAW = 27.30%`, `AWAY = 29.84%`.

| Modelo 1X2 | Brier Multiclase | Brier Skill Score (BSS) | Log Loss | ECE (5 Bins) | ECE (10 Bins) | Sesgo `HOME` ($\bar{p} - \bar{y}$) | Sesgo `DRAW` ($\bar{p} - \bar{y}$) | Sesgo `AWAY` ($\bar{p} - \bar{y}$) | Binary Brier `(H / D / A)` |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **`RANDOM_FOREST`** | **`0.57943`** | **`+11.31%`** | **`0.96989`** | `0.02300` | `0.02300` | `+0.0099` | `-0.0300` | `+0.0202` | `0.2098 / 0.1970 / 0.1726` |
| **`ENSEMBLE`** | `0.58036` | `+11.17%` | `0.97093` | `0.03121` | `0.03145` | `+0.0122` | `-0.0300` | `+0.0178` | `0.2107 / 0.1974 / 0.1723` |
| **`XGBOOST`** | `0.58162` | `+10.97%` | `0.97254` | `0.03524` | `0.04232` | `+0.0123` | `-0.0305` | `+0.0182` | `0.2115 / 0.1978 / 0.1724` |
| **`ELO`** | `0.58332` | `+10.71%` | `0.97939` | `0.01540` | `0.02692` | `-0.0034` | `-0.0384` | `+0.0418` | `0.2096 / 0.1985 / 0.1752` |
| **`POISSON`** | `0.59239` | `+9.32%` | `0.99028` | **`0.00486`** | **`0.01316`** | `+0.0154` | `-0.0259` | `+0.0105` | `0.2150 / 0.1976 / 0.1798` |

#### Tabla de Confiabilidad (5 Bins) — `RANDOM_FOREST` vs `ENSEMBLE` vs `POISSON` (1X2 Multiclase, $868 \times 3 = 2,604$ predicciones)
| Rango de Probabilidad | `RANDOM_FOREST` `(N, Pred, Emp, Gap)` | `ENSEMBLE` `(N, Pred, Emp, Gap)` | `POISSON` `(N, Pred, Emp, Gap)` | Diagnóstico de Calibración |
| :---: | :---: | :---: | :---: | :--- |
| **`0.00 – 0.20`** | `483`: `14.53%` vs `12.42%` (`gap 2.11%`) | `468`: `14.26%` vs `11.11%` (`gap 3.15%`) | `370`: `15.06%` vs `13.51%` (`gap 1.55%`) | Excelente calibración en colas bajas |
| **`0.20 – 0.40`** | `1304`: `26.16%` vs `27.99%` (`gap 1.83%`) | `1328`: `26.22%` vs `28.54%` (`gap 2.32%`) | `1502`: `27.87%` vs `27.83%` (`gap 0.04%`) | Subestimación leve del empate (`-3.0%`) por aumento de empates en 2024/25 (`27.3%` vs `24.3%` en `Train`) |
| **`0.40 – 0.60`** | `565`: `50.23%` vs `46.73%` (`gap 3.50%`) | `567`: `50.78%` vs `46.21%` (`gap 4.57%`) | `549`: `48.92%` vs `49.18%` (`gap 0.26%`) | Ligera sobreconfianza (`3.5%–4.5%`) en favoritos moderados en árboles; `POISSON` casi perfecto (`0.26%`) |
| **`0.60 – 0.80`** | `240`: `67.92%` vs `70.42%` (`gap 2.49%`) | `230`: `67.88%` vs `72.17%` (`gap 4.29%`) | `168`: `67.10%` vs `69.64%` (`gap 2.54%`) | Buen ajuste en favoritos claros |
| **`0.80 – 1.00`** | `12`: `82.71%` vs `83.33%` (`gap 0.62%`) | `11`: `81.80%` vs `81.82%` (`gap 0.01%`) | `15`: `82.55%` vs `86.67%` (`gap 4.11%`) | Alta precisión en favoritos extremos |

### 6.2 Calibración por Mercado de Goles y Desglose por Competición (`Test`, `N = 868`)

| Mercado | Frec. Real Test | `POISSON` `(Brier / LogLoss / ECE)` | `ENSEMBLE_GOALS` `(Brier / LogLoss / ECE)` | Brier por Liga `(LaLiga / Premier / Serie A / Bundesliga)` | Liga Mejor Calibrada (Menor ECE) | Liga con Mayor Desviación de Régimen (2024/25) |
| :--- | :---: | :---: | :---: | :---: | :---: | :--- |
| **`OVER_1_5`** | `78.92%` | **`0.15973`** / `0.4945` / `0.0246` | **`0.15973`** / `0.4945` / `0.0246` | `0.2098` / **`0.1059`** / `0.1822` / `0.1350` | Bundesliga (`ECE = 0.0033`) y Serie A (`0.0078`) | Premier League (`ECE = 0.1000`: tasa real subió a `89.29%` vs `79.29%` predicho) |
| **`OVER_2_5`** | `54.26%` | `0.23415` / `0.6606` / `0.0365` | **`0.23352`** / `0.6594` / `0.0389` | `0.2321` / `0.2367` / **`0.2274`** / `0.2392` | LaLiga (`ECE = 0.0377`) | Premier League (`ECE = 0.0924`: tasa real `66.07%` vs `56.83%` predicho) |
| **`UNDER_2_5`** | `45.74%` | `0.23415` / `0.6606` / `0.0365` | **`0.23359`** / `0.6595` / `0.0388` | `0.2322` / `0.2370` / **`0.2273`** / `0.2392` | LaLiga (`ECE = 0.0325`) | Premier League (`ECE = 0.0932`: tasa real `33.93%` vs `43.25%` predicho) |
| **`OVER_3_5`** | `34.10%` | **`0.21648`** / `0.6213` / `0.0429` | **`0.21648`** / `0.6213` / `0.0429` | `0.1859` / `0.2673` / **`0.1832`** / `0.2346` | LaLiga (`ECE = 0.0187`) y Serie A (`0.0203`) | Premier League (`ECE = 0.1331`: pico atípico de `47.32%` de partidos con 4+ goles en 2024/25) |
| **`BTTS`** | `55.53%` | `0.24264` / `0.6784` / `0.0319` | **`0.24220`** / `0.6775` / `0.0249` | `0.2449` / `0.2478` / `0.2414` / **`0.2330`** | LaLiga (`ECE = 0.0307`) y Serie A (`0.0328`) | Premier League (`ECE = 0.1092`: en `BTTS` Premier League el Brier `0.2478` no supera al Baseline `0.2440`) |

---

## 7. REPRODUCIBILIDAD E INTEGRIDAD DE ARTEFACTOS

### 7.1 Comprobación de Métricas Recalculadas vs Reportadas (`N = 868`)
| Modelo (`v3.0.0-phase3-scientific`) | Brier Reportado | Brier Recalculado | Log Loss Reportado | Log Loss Recalculado | Coincidencia Exacta |
| :--- | :---: | :---: | :---: | :---: | :---: |
| **`POISSON`** | `0.59239` | `0.59239` | `0.99028` | `0.99028` | ✅ `True` (`Δ = 0.00000`) |
| **`ELO`** | `0.58332` | `0.58332` | `0.97939` | `0.97939` | ✅ `True` (`Δ = 0.00000`) |
| **`RANDOM_FOREST`** | `0.57943` | `0.57943` | `0.96989` | `0.96989` | ✅ `True` (`Δ = 0.00000`) |
| **`XGBOOST`** | `0.58162` | `0.58162` | `0.97254` | `0.97254` | ✅ `True` (`Δ = 0.00000`) |
| **`ENSEMBLE`** | `0.58036` | `0.58036` | `0.97093` | `0.97093` | ✅ `True` (`Δ = 0.00000`) |

### 7.2 Inventario Criptográfico (`SHA-256`) de Artefactos Intactos (`v1`, `v2`, `v3`)
| Archivo de Artefacto en `backend/artifacts/` | Tamaño (Bytes) | Hash `SHA-256` Verificado | Estado |
| :--- | :---: | :--- | :---: |
| `sportpredict_models_v1.0.0-mvp.joblib` | `740,822` | `8db65a188a7958ee045d084ec38021dc2a3791c5442b1cc61ef7bf07476a4d34` | ✅ Intacto |
| `sportpredict_models_v1.1.0.joblib` | `740,822` | `e3998c30b3dcb56b84a36a792c95038d73f53db9f65ac37fee312b2f5293a665` | ✅ Intacto |
| `sportpredict_models_v2.0.0-real-cc0.joblib` | `7,272,958` | `0c7b596b7c48af98206772cc3d3553b313ad43df8fed6a085c1c3c1b97f4f78e` | ✅ Intacto |
| `sportpredict_models_v2.4.0-real-cc0.joblib` | `7,299,138` | `bc281c637ad459c4b5219f4f2e1e24206286a3f8620b9c05827f90a088ffee9f` | ✅ Intacto |
| `sportpredict_models_v2.5.0-real-cc0.joblib` | `7,299,138` | `3052813e9f3cb0504fd3e9177d76770764db3f26459e7f7a848498b4f8bb7655` | ✅ Intacto |
| `sportpredict_models_v3.0.0-phase3-scientific.joblib` | `20,005,465` | `4e3b8f6309f682170b211768f2943491479badb2f2140be688e3c082145ac56a` | ✅ Intacto |
| Base de datos `backend/data/sportpredict_local.db` | SQLite DB | `54bd5ca6e647947ca44951c8a5bc7ed669235f5da3a0098e86fbb84640f13188` | ✅ Intacta |

---

## 8. CORRECCIONES METODOLÓGICAS NECESARIAS Y RIESGOS PENDIENTES

### 8.1 Correcciones Metodológicas Recomendadas (Para Ejecutar al Inicio Autorizado de la Siguiente Etapa)
1. **Corrección Out-of-Fold Temporal en el Stacking de Mercados de Goles (`goals_market_models.py`):**
   - Reemplazar las predicciones in-sample `poisson_*` sobre `T_train` por un generador **Out-of-Fold de Ventana Expansiva Cronológica** (o bien utilizar directamente el modelo analítico `POISSON` / Dixon-Coles para los mercados `OVER_1_5`, `OVER_2_5`, `UNDER_2_5`, `OVER_3_5`, `BTTS`, dado que la Familia 4 de pruebas demostró en `10/10` contrastes que los árboles no superan estadísticamente a Poisson en goles).
2. **Aislamiento de Base de Datos en `test_phase2_real_data.py` y Unicidad de `is_active` en `ml_models`:**
   - Asegurar que cuando se registra una versión activa en `ml_models`, se desactiven explícitamente las demás versiones (`UPDATE ml_models SET is_active = 0 WHERE version != :active_version`), y que `test_phase2_real_data.py` restaure la versión activa tras finalizar la prueba.
3. **Calibración Temporal Interna en `CalibratedClassifierCV`:**
   - Pasar un iterador cronológico `TimeSeriesSplit(n_splits=3)` a `CalibratedClassifierCV` dentro de `T_train` en lugar del `StratifiedKFold(3)` por defecto.

### 8.2 Riesgos Pendientes Identificados
1. **Cambio de Régimen Goleador en Premier League (`2024/25`):** En el conjunto de prueba, la Premier League experimentó un incremento estructural de goles (`66.07%` de `OVER_2_5` y `47.32%` de `OVER_3_5`), generando un `ECE` de `0.092` a `0.133` en esa liga específica y haciendo que en `BTTS Premier League` el modelo no supere al baseline (`0.2478` vs `0.2440`).
2. **Compresión de Probabilidades de Empate (`DRAW`):** Ningún modelo asigna probabilidades de empate superiores a `41%` (`0` predicciones en los bins `0.60–1.00`), y todos subestiman ligeramente la tasa media de empates de la temporada 2024/25 en `-2.59%` a `-3.84%`.
3. **Ausencia de Cuotas Históricas Reales Verificables:** El dataset `OpenFootball` CC0-1.0 no incluye cuotas de casas de apuestas, por lo que **el ROI comercial real aún no ha sido validado empíricamente** (`roi_simulated = None`).

---

## 9. RECOMENDACIÓN FUNDAMENTADA PARA LA FASE 4

### Dictamen de Auditoría: **`APTO CONDICIONADO` (APTO en Motor 1X2 y Poisson Analítico de Goles; Requiere Aplicar las 2 Correcciones Puntuales de Stacking OOF y `is_active` Antes de Exponer Mercados de Goles Basados en Árboles en Fase 4)**

**Justificación Científica del Dictamen:**
1. **Por qué el motor principal 1X2 y la arquitectura de datos son APTOS:**
   - La auditoría automatizada sobre el **100% de los `868` partidos de prueba y `4,338` partidos totales** demostró matemáticamente que **no existe filtración de información futura** (`0` violaciones temporales, `0` discrepancias en las 29 features, `0` discrepancias en tablas de liga pre-partido, `0` discrepancias en Elo).
   - Todos los modelos 1X2 superan al Baseline Histórico con significancia confirmatoria estricta bajo **Holm-Bonferroni** ($p_{\text{Holm}} = 0.0005 < 0.05$) y estabilidad absoluta frente a tamaños de bloque $L \in \{10, 20, 39, 50\}$ y bloques estratificados por competición.
   - La calibración multiclase 1X2 es sólida (`ECE = 0.0049` en `POISSON`, `0.0230` en `RANDOM_FOREST`, `0.0312` en `ENSEMBLE`), y la reproducibilidad de los artefactos `v1`, `v2` y `v3` es exacta (`0` discrepancias).
2. **Por qué la aprobación está CONDICIONADA a dos ajustes rápidos antes de producir la Fase 4:**
   - **Condición 1 (Stacking de Goles):** Antes de desplegar comercialmente predicciones de mercados de goles en la Fase 4, debe corregirse la generación in-sample de las 4 meta-variables `poisson_*` en `T_train` para `RF_GOALS`/`XGB_GOALS` (generando una nueva versión limpia `v3.1.0` sin sobrescribir `v3.0.0`), o bien servir directamente las probabilidades analíticas de `POISSON` (Dixon-Coles) en los mercados de goles, dado que los árboles no aportan mejora estadísticamente significativa sobre Poisson (`0/10` pruebas significativas en la Familia 4).
   - **Condición 2 (Higiene de Versión Activa en DB):** Desactivar `is_active` en `v2.5.0-real-cc0` dentro de `ml_models` para que únicamente la versión vigente de Fase 3 quede marcada como activa.
