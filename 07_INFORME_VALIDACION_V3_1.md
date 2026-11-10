# SPORTPREDICT AI — INFORME DE VALIDACIÓN TÉCNICA Y ESTADÍSTICA V3.1.0 (`07_INFORME_VALIDACION_V3_1.md`)

**Fecha de emisión:** 2026-11-09  
**Versión auditada y validada:** `v3.1.0` (`sportpredict_models_v3.1.0.joblib`)  
**Alcance:** Ejecución y verificación de las correcciones controladas autorizadas tras la Auditoría Complementaria de la Fase 3 (`06_AUDITORIA_COMPLEMENTARIA_FASE3.md`), **sin iniciar la Fase 4**.  
**Artefacto de datos de respaldo reproducible:** [`phase3_v3_1_validation_report.json`](file:///f:/Proyectos/Predicciones/backend/data/real_historical/phase3_v3_1_validation_report.json)  
**Script de ejecución y auditoría reproducible:** [`run_phase3_v3_1_controlled_fix.py`](file:///f:/Proyectos/Predicciones/backend/run_phase3_v3_1_controlled_fix.py)

---

## Resumen Ejecutivo y Estado de las Correcciones

Las tres observaciones técnicas y de gobernanza detectadas en la Auditoría Complementaria de la Fase 3 han sido resueltas, verificadas experimentalmente y selladas criptográficamente sin sobrescribir ningún modelo previo (`v1.0.0-mvp`, `v1.1.0`, `v2.0.0-real-cc0`, `v2.4.0-real-cc0`, `v2.5.0-real-cc0`, `v3.0.0-phase3-scientific`) ni alterar el dataset histórico real (`OPENFOOTBALL_CC0`):

| # | Bloqueante identificado en `06_AUDITORIA_COMPLEMENTARIA_FASE3.md` | Solución implementada en `v3.1.0` | Verificación empírica | Estado |
| :--- | :--- | :--- | :--- | :--- |
| **1** | **Stacking in-sample en mercados de goles (`v3.0.0`):** Las 4 variables `poisson_*` en `T_train` (`2,605` partidos) se habían generado con una instancia Poisson ajustada sobre el mismo `T_train`. | Implementación de `generate_temporal_oof_poisson_predictions` en [`goals_market_models.py`](file:///f:/Proyectos/Predicciones/backend/app/ml/models/goals_market_models.py#L44-L162) mediante **Out-of-Fold Temporal con ventana expansiva** (`34` reajustes cronológicos) y calibración temporal `TimeSeriesSplit(n_splits=3)` en `RF_GOALS` y `XGB_GOALS`. | `2,605 / 2,605` partidos de `T_train` auditados: `temporal_violations_count = 0`, `self_inclusion_violations_count = 0`. Selección no forzada de `POISSON` como modelo principal en los 5 mercados de goles. | **CORREGIDO Y VALIDADO** |
| **2** | **Ambigüedad de versiones activas en `ml_models` y contaminación por `pytest`:** `v2.5.0-real-cc0` (IDs `26–30`) y `v3.0.0-phase3-scientific` (IDs `16–20`) tenían `is_active = True` simultáneamente tras ejecutar `pytest`. | Corrección de resolución de rutas de artefactos y unicidad de versión activa en [`prediction_service.py`](file:///f:/Proyectos/Predicciones/backend/app/services/prediction_service.py#L81-L108) y [`routes_models.py`](file:///f:/Proyectos/Predicciones/backend/app/api/routes_models.py#L140-L152). Aislamiento total de pruebas en [`conftest.py`](file:///f:/Proyectos/Predicciones/backend/tests/conftest.py#L1-L82) sobre base de datos SQLite temporal. | Sólo `v3.1.0` (IDs `31–35`) permanece con `is_active = True` entre los `30` registros históricos. Hash SHA-256 de `sportpredict_local.db` idéntico antes y después de correr las `13` pruebas de `pytest`. | **CORREGIDO Y VALIDADO** |
| **3** | **Trazabilidad documental del dataset entre Fase 2 y Fase 3:** Discrepancia narrativa de fechas (`2021/22–2023/24` vs mención de `2025` en prosa) y cambio de `Train` de `2,602` (`v2.0.0`) a `2,605` (`v3.0.0`). | Auditoría completa del contenido de `sportpredict_local.db` y `openfootball_real_matches_cc0.csv` por fuente, temporada, competición y frontera de corte temporal. | Los `4,338` partidos reales (`2021-08-13` a `2024-06-02`) son 100% idénticos (SHA-256 invariante). El ajuste `2,602 -> 2,605` obedece exclusivamente a 4 partidos simultáneos jugados el `2023-04-22T15:00:00Z`. | **ACLARADO Y DOCUMENTADO** |

---

## 1. Corrección del Stacking de Mercados de Goles (`v3.1.0`)

### 1.1 Procedimiento Out-of-Fold Temporal con Ventana Expansiva
En [`backend/app/ml/models/goals_market_models.py`](file:///f:/Proyectos/Predicciones/backend/app/ml/models/goals_market_models.py#L44-L162), se implementó la función `generate_temporal_oof_poisson_predictions`, que construye las cuatro señales de Poisson (`poisson_market_prob`, `poisson_lambda_total`, `poisson_lambda_home`, `poisson_lambda_away`) para los `2,605` partidos de `T_train` bajo restricción temporal estricta:

1. **Agrupación por instante exacto de kickoff (`kickoff_utc`):** Los `2,605` partidos de `T_train` (`2021-08-13T20:00:00+00:00` a `2023-04-22T15:00:00+00:00`) contienen `1,773` marcas de tiempo únicas. Ningún partido simultáneo (`r.kickoff_utc == m.kickoff_utc`) entra jamás en la ventana de ajuste del otro.
2. **Warmup inicial estrictamente causal (`min_warmup_matches = 120`):** Para los primeros `123` partidos al inicio absoluto de la temporada `2021-22` (cuando aún no existen `120` partidos previos en la ventana), el generador calcula probabilidades mediante un estimador analítico de tasas empíricas acumuladas usando exclusivamente los partidos con `r.kickoff_utc < m.kickoff_utc` (con fallback a la media a priori neutral `lambda_home = 1.45`, `lambda_away = 1.15` en la jornada inaugural donde existen `0` partidos previos).
3. **Ventana expansiva de Poisson / Dixon-Coles (`refit_step_matches = 80`):** A partir del partido `124` de `T_train`, se reentrena desde cero una instancia limpia de [`PoissonDixonColesModel`](file:///f:/Proyectos/Predicciones/backend/app/ml/models/poisson_model.py#L20-L240) (`decay_xi = 0.0015`, `regularization = 0.008`, `use_competition_hfa = True`) cada `80` nuevos partidos acumulados (`34` reajustes completos a lo largo de `T_train`), garantizando que para todo bloque de partidos en el instante $t_k$, el conjunto de entrenamiento de Poisson cumple:
   $$\mathcal{H}_{\text{Poisson}}(t_k) = \left\{ r \in T_{\text{train}} \;\middle|\; r.\text{kickoff\_utc} < t_k \right\}$$
4. **Calibración temporal interna de `RF_GOALS` y `XGB_GOALS`:** Tanto [`CalibratedGoalMarketRF`](file:///f:/Proyectos/Predicciones/backend/app/ml/models/goals_market_models.py#L165-L270) como [`CalibratedGoalMarketXGB`](file:///f:/Proyectos/Predicciones/backend/app/ml/models/goals_market_models.py#L273-L385) fueron actualizados para emplear `TimeSeriesSplit(n_splits=3)` dentro de `CalibratedClassifierCV(method="sigmoid")`, preservando el orden cronológico también durante la calibración sigmoidal de Platt.
5. **Validación (`T_val = 865`) y Prueba Retenida (`T_test = 868`):**
   - Para `T_val`, las 4 variables `poisson_*` provienen del modelo `PoissonDixonColesModel` ajustado exclusivamente sobre `T_train` (`2,605` partidos, `<= 2023-04-22T15:00:00Z`).
   - Para `T_test`, las 4 variables `poisson_*` provienen del modelo `PoissonDixonColesModel` ajustado sobre `T_train + T_val` (`3,470` partidos, `<= 2023-12-10T12:30:00Z`), estrictamente anterior al primer partido de `T_test` (`2023-12-10T14:00:00Z`).

### 1.2 Verificación Automatizada de Cero Fuga en `T_train` (`N = 2,605`)

| Métrica de Auditoría Out-of-Fold Temporal (`T_train`) | Resultado en `v3.0.0` (In-Sample) | Resultado en `v3.1.0` (Temporal OOF) |
| :--- | :---: | :---: |
| Partidos totales en `T_train` | `2,605` | `2,605` |
| Timestamps únicos (`kickoff_utc`) en `T_train` | `1,773` | `1,773` |
| Partidos en ventana de warmup causal (`< 120` previos) | `0` (ajuste global in-sample) | `123` |
| Partidos predichos con reajuste expansivo `PoissonDixonColesModel` | `0` (1 solo ajuste global) | `2,482` (`34` reajustes) |
| Violaciones de orden temporal (`max_train_kickoff >= target_kickoff`) | `2,604` (in-sample) | **`0`** |
| Violaciones de autoinclusión (`target_match_id in fit_history`) | `2,605` (in-sample) | **`0`** |
| RMSE de `poisson_lambda_total` frente a goles reales en `T_train` | `1.58867` (optimista in-sample) | **`1.69347`** (realista OOF) |
| Correlación de Pearson $r(\lambda_{\text{total}}, \text{goles reales})$ en `T_train` | `0.33760` (inflada in-sample) | **`0.14889`** (realista OOF) |

### 1.3 Impacto en la Importancia de Variables (`poisson_*`) en `RF_GOALS` y `XGB_GOALS`
Al eliminar el optimismo in-sample de las 4 variables `poisson_*` en `T_train`, los árboles de `RF_GOALS` y `XGB_GOALS` dejaron de sobreponderar artificialmente la señal de Poisson y redistribuyeron el peso hacia las variables históricas pre-partido (`rolling_xg_proxy`, `elo_rating`, `goals_for_avg`, promedios de liga):

| Mercado | Suma de importancia Gini de las 4 `poisson_*` en `RF_GOALS` (`v3.0.0` In-Sample) | Suma de importancia Gini de las 4 `poisson_*` en `RF_GOALS` (`v3.1.0` OOF) | Suma de importancia Gain de las 4 `poisson_*` en `XGB_GOALS` (`v3.0.0` In-Sample) | Suma de importancia Gain de las 4 `poisson_*` en `XGB_GOALS` (`v3.1.0` OOF) |
| :--- | :---: | :---: | :---: | :---: |
| **`OVER_1_5`** | `51.83%` | **`20.38%`** (`-31.45 pp`) | `20.93%` | **`12.84%`** (`-8.09 pp`) |
| **`OVER_2_5`** | `57.64%` | **`27.19%`** (`-30.45 pp`) | `27.32%` | **`15.49%`** (`-11.83 pp`) |
| **`UNDER_2_5`** | `57.64%` | **`27.19%`** (`-30.45 pp`) | `27.31%` | **`15.49%`** (`-11.82 pp`) |
| **`OVER_3_5`** | `62.36%` | **`34.87%`** (`-27.49 pp`) | `30.48%` | **`19.83%`** (`-10.65 pp`) |
| **`BTTS`** | `50.38%` | **`19.70%`** (`-30.68 pp`) | `22.91%` | **`12.38%`** (`-10.53 pp`) |

---

## 2. Comparación Científica `v3.0.0` frente a `v3.1.0` (`N = 868` Partidos de Prueba)

### 2.1 Mercado Principal `1X2` (Invarianza Verificada)
Los 5 modelos del mercado `1X2` (`POISSON`, `ELO`, `RANDOM_FOREST`, `XGBOOST`, `ENSEMBLE`) no utilizaban variables `poisson_*` apiladas en su matriz de 27 características pre-partido (verificado en la Sección 2.1 de `06_AUDITORIA_COMPLEMENTARIA_FASE3.md`). Por tanto, sus predicciones y métricas sobre los `868` partidos de prueba son **exactamente idénticas** entre `v3.0.0` y `v3.1.0` (`max_abs_diff = 0.0`):

| Modelo (`1X2`) | Brier `v3.0.0` | Brier `v3.1.0` | $\Delta$ Brier | Log Loss `v3.0.0` | Log Loss `v3.1.0` | ECE (10 bins) | Accuracy (`N = 868`) | Peso en Ensamble `1X2` |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **`BASELINE`** (Frecuencias `T_train`) | `0.66066` | `0.66066` | `0.00000` | `1.08469` | `1.08469` | — | `44.70%` | — |
| **`POISSON`** (Dixon-Coles $\xi=0.0015$, HFA Liga) | `0.59239` | `0.59239` | `0.00000` | `0.98664` | `0.98664` | `0.03299` | `51.61%` | `0.00%` |
| **`ELO`** ($K=24$, HFA Liga, Regresión `0.85`) | `0.58332` | `0.58332` | `0.00000` | `0.97214` | `0.97214` | `0.02581` | `52.88%` | `16.43%` |
| **`RANDOM_FOREST`** (Calibrado Temporal) | **`0.57943`** | **`0.57943`** | `0.00000` | **`0.96627`** | **`0.96627`** | **`0.02350`** | **`53.57%`** | `51.78%` |
| **`XGBOOST`** (L1/L2 Calibrado Temporal) | `0.58162` | `0.58162` | `0.00000` | `0.96987` | `0.96987` | `0.02732` | `52.76%` | `31.79%` |
| **`ENSEMBLE`** (Símplex SLSQP en `T_val`) | `0.58036` | `0.58036` | `0.00000` | `0.96768` | `0.96768` | `0.02471` | `53.34%` | `100.00%` |

### 2.2 Comparación `v3.0.0` vs `v3.1.0` en los 5 Mercados de Goles (`N = 868` Partidos de Prueba)

La siguiente tabla compara el desempeño en prueba retenida (`868` partidos, `2023-12-10` a `2024-06-02`) de cada modelo secundario antes (`v3.0.0`, con `poisson_*` in-sample en `T_train`) y después (`v3.1.0`, con `poisson_*` Out-of-Fold Temporal en `T_train`), junto con la prueba de significancia por **Moving Block Bootstrap** (`B = 1,000` réplicas, bloque $L = 20$) y corrección de **Holm-Bonferroni** ($m = 15$ comparaciones `v3.1.0 vs v3.0.0`):

| Mercado | Modelo | Brier `v3.0.0` | Brier `v3.1.0` | $\Delta$ Brier (`v3.1 - v3.0`) | IC 95% Bootstrap $\Delta$ Brier | $p_{\text{raw}}$ | $p_{\text{Holm}}$ ($m=15$) | Log Loss `v3.0.0` | Log Loss `v3.1.0` | ECE `v3.1.0` (5 bins) |
| :--- | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **`OVER_1_5`** | `POISSON` | `0.15973` | `0.15973` | `0.00000` | — | — | — | `0.49370` | `0.49370` | `0.01106` |
| **`OVER_1_5`** | `RF_GOALS` | `0.16056` | `0.16342` | `+0.00286` | `[-0.00060, +0.00668]` | `0.1060` | `0.9540` | `0.49596` | `0.50351` | `0.02116` |
| **`OVER_1_5`** | `XGB_GOALS` | `0.16124` | `0.16489` | `+0.00365` | `[+0.00041, +0.00733]` | `0.0250` | `0.3500` | `0.49794` | `0.50711` | `0.02350` |
| **`OVER_1_5`** | `ENSEMBLE_GOALS` | `0.15973` | `0.16000` | `+0.00027` | `[-0.00068, +0.00130]` | `0.5820` | `1.0000` | `0.49370` | `0.49433` | `0.01081` |
| **`OVER_2_5`** | `POISSON` | `0.23396` | `0.23396` | `0.00000` | — | — | — | `0.66060` | `0.66060` | `0.04579` |
| **`OVER_2_5`** | `RF_GOALS` | `0.23362` | `0.23922` | `+0.00560` | `[+0.00130, +0.01032]` | `0.0080` | `0.1200` | `0.65985` | `0.67164` | `0.04933` |
| **`OVER_2_5`** | `XGB_GOALS` | `0.23469` | `0.24021` | `+0.00552` | `[+0.00072, +0.01028]` | `0.0250` | `0.3500` | `0.66213` | `0.67367` | `0.05660` |
| **`OVER_2_5`** | `ENSEMBLE_GOALS` | `0.23352` | `0.23395` | `+0.00043` | `[-0.00127, +0.00205]` | `0.6190` | `1.0000` | `0.65963` | `0.66058` | `0.04507` |
| **`UNDER_2_5`** | `POISSON` | `0.23396` | `0.23396` | `0.00000` | — | — | — | `0.66060` | `0.66060` | `0.04579` |
| **`UNDER_2_5`** | `RF_GOALS` | `0.23375` | `0.23930` | `+0.00555` | `[+0.00112, +0.01036]` | `0.0130` | `0.1820` | `0.66013` | `0.67181` | `0.05044` |
| **`UNDER_2_5`** | `XGB_GOALS` | `0.23465` | `0.24025` | `+0.00560` | `[+0.00083, +0.01031]` | `0.0250` | `0.3500` | `0.66205` | `0.67375` | `0.05747` |
| **`UNDER_2_5`** | `ENSEMBLE_GOALS` | `0.23359` | `0.23395` | `+0.00036` | `[-0.00119, +0.00187]` | `0.6500` | `1.0000` | `0.65978` | `0.66057` | `0.04523` |
| **`OVER_3_5`** | `POISSON` | `0.21648` | `0.21648` | `0.00000` | — | — | — | `0.62319` | `0.62319` | `0.03693` |
| **`OVER_3_5`** | `RF_GOALS` | `0.21812` | `0.21897` | `+0.00085` | `[-0.00327, +0.00555]` | `0.6910` | `1.0000` | `0.62670` | `0.62903` | `0.04056` |
| **`OVER_3_5`** | `XGB_GOALS` | `0.21916` | `0.22002` | `+0.00086` | `[-0.00361, +0.00546]` | `0.7090` | `1.0000` | `0.62900` | `0.63116` | `0.04457` |
| **`OVER_3_5`** | `ENSEMBLE_GOALS` | `0.21648` | **`0.21612`** | **`-0.00036`** | `[-0.00157, +0.00072]` | `0.5360` | `1.0000` | `0.62319` | **`0.62246`** | `0.03609` |
| **`BTTS`** | `POISSON` | `0.24283` | `0.24283` | `0.00000` | — | — | — | `0.67895` | `0.67895` | `0.03329` |
| **`BTTS`** | `RF_GOALS` | `0.24219` | `0.24644` | `+0.00425` | `[+0.00005, +0.00856]` | `0.0480` | `0.4800` | `0.67766` | `0.68637` | `0.04687` |
| **`BTTS`** | `XGB_GOALS` | `0.24266` | `0.24666` | `+0.00400` | `[-0.00003, +0.00836]` | `0.0540` | `0.4860` | `0.67861` | `0.68684` | `0.04930` |
| **`BTTS`** | `ENSEMBLE_GOALS` | `0.24220` | `0.24277` | `+0.00057` | `[-0.00158, +0.00283]` | `0.6120` | `1.0000` | `0.67768` | `0.67883` | `0.03616` |

### 2.3 Conclusión Científica de la Comparación `v3.0.0` vs `v3.1.0`
1. **Confirmación de la hipótesis de la auditoría complementaria:** En `v3.0.0`, la aparente superioridad marginal de `RF_GOALS` y `XGB_GOALS` sobre `POISSON` en `OVER_2_5` (`0.23362` vs `0.23396`), `UNDER_2_5` (`0.23375` vs `0.23396`) y `BTTS` (`0.24219` vs `0.24283`) era producto de que el clasificador tabular había aprendido en `T_train` que `poisson_market_prob` tenía menor error del que realmente posee fuera de muestra.
2. **Al entrenar con predicciones Out-of-Fold Temporales (`v3.1.0`):**
   - `RF_GOALS` y `XGB_GOALS` obtienen un Brier Score entre `+0.0025` y `+0.0063` puntos superior (peor) que el modelo bivariado analítico `Poisson / Dixon-Coles` en los 5 mercados de goles.
   - A su vez, el optimizador de ensamble en validación (`T_val`) lo detecta automáticamente y asigna entre **`61.31%` y `89.74%` del peso a `POISSON`** en todos los mercados (`89.03%` en `OVER_1_5`, `89.54%` en `OVER_2_5`, `89.74%` en `UNDER_2_5`, `69.85%` en `OVER_3_5`, `61.31%` en `BTTS`).
   - En consecuencia, `ENSEMBLE_GOALS` en `v3.1.0` converge prácticamente al mismo Brier Score que `POISSON` (diferencias entre `-0.00035` y `+0.00027`, con $p_{\text{raw}} \in [0.5360, 0.9700]$ y $p_{\text{Holm}} = 1.0000$).

---

## 3. Resultados Detallados por Mercado y Selección No Forzada del Modelo Principal

Siguiendo la instrucción explícita (*"No forzar ensambles. Si Poisson/Dixon-Coles ofrece resultados equivalentes o mejores, conservarlo como modelo principal de esos mercados"*), `v3.1.0` aplica el criterio de parsimonia estadística: un ensamble sólo reemplaza al modelo analítico `POISSON` como modelo principal (`PRIMARY_MODEL_CODE`) si logra una mejora estadísticamente significativa ($p < 0.05$) en prueba retenida.

### 3.1 Tabla Consolidada de Selección de Modelo Principal por Mercado (`v3.1.0`)

| Mercado | Baseline Brier (`T_test`) | Mejor Individual (`Brier`) | Ensamble `v3.1.0` (`Brier`) | Pesos del Ensamble `v3.1.0` (`POISSON / RF / XGB`) | $\Delta$ Brier (`Ensamble - Poisson`) | $p_{\text{raw}}$ (`Ens vs Pois`) | $p_{\text{Holm}}$ ($m=5$) | **Modelo Principal Seleccionado (`PRIMARY_MODEL_CODE`)** |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :--- |
| **`1X2`** | `0.66066` | `RANDOM_FOREST` (`0.57943`) | `0.58036` | `0% Pois / 16.4% Elo / 51.8% RF / 31.8% XGB` | `-0.01203` vs Pois (`+0.00093` vs RF) | `0.0010` vs Pois (`0.5560` vs RF) | `0.0050` vs Pois | **`ENSEMBLE`** (con `RANDOM_FOREST` co-óptimo expuesto en API) |
| **`OVER_1_5`** | `0.16368` | **`POISSON` (`0.15973`)** | `0.16000` | `89.03% / 8.80% / 2.18%` | `+0.00027` | `0.5820` | `1.0000` | **`POISSON` (`Poisson / Dixon-Coles`)** |
| **`OVER_2_5`** | `0.24395` | **`POISSON` (`0.23396`)** | `0.23395` | `89.54% / 10.46% / 0.00%` | `-0.00001` | `0.9700` | `1.0000` | **`POISSON` (`Poisson / Dixon-Coles`)** |
| **`UNDER_2_5`** | `0.24395` | **`POISSON` (`0.23396`)** | `0.23395` | `89.74% / 10.26% / 0.00%` | `-0.00002` | `0.9430` | `1.0000` | **`POISSON` (`Poisson / Dixon-Coles`)** |
| **`OVER_3_5`** | `0.22335` | **`POISSON` (`0.21648`)** | `0.21612` | `69.85% / 17.42% / 12.73%` | `-0.00035` | `0.5360` | `1.0000` | **`POISSON` (`Poisson / Dixon-Coles`)** |
| **`BTTS`** | `0.24542` | **`POISSON` (`0.24283`)** | `0.24277` | `61.31% / 18.35% / 20.34%` | `-0.00005` | `0.9560` | `1.0000` | **`POISSON` (`Poisson / Dixon-Coles`)** |

### 3.2 Significancia Estadística frente al Baseline Histórica (Moving Block Bootstrap + Holm-Bonferroni)
Comparando los modelos principales seleccionados frente al Baseline histórico (frecuencia marginal de `T_train`) sobre los `868` partidos de prueba:

| Comparación frente a Baseline (`N = 868`, Bloque $L=20$, $B=1,000$) | $\Delta$ Brier (`Modelo - Baseline`) | IC 95% Bootstrap | Estadístico $z$ | $p_{\text{raw}}$ | $p_{\text{Holm}}$ | Clasificación de Evidencia |
| :--- | :---: | :---: | :---: | :---: | :---: | :--- |
| **`1X2`: `RANDOM_FOREST` vs `BASELINE`** | **`-0.08123`** | `[-0.10665, -0.05692]` | `-6.378` | `< 0.0001` | **`< 0.0010`** | **`SIGNIFICANT_HOLM`** |
| **`1X2`: `ENSEMBLE` vs `BASELINE`** | **`-0.08030`** | `[-0.10494, -0.05658]` | `-6.447` | `< 0.0001` | **`< 0.0010`** | **`SIGNIFICANT_HOLM`** |
| **`OVER_2_5`: `POISSON` vs `BASELINE`** | **`-0.00999`** | `[-0.01850, -0.00083]` | `-2.192` | `0.0320` | `0.1590` | **`SUGGESTIVE_RAW_ONLY`** ($p_{\text{raw}} < 0.05$, IC 95% excluye el `0`) |
| **`UNDER_2_5`: `POISSON` vs `BASELINE`** | **`-0.00999`** | `[-0.01850, -0.00083]` | `-2.192` | `0.0320` | `0.1590` | **`SUGGESTIVE_RAW_ONLY`** ($p_{\text{raw}} < 0.05$, IC 95% excluye el `0`) |
| **`OVER_3_5`: `POISSON` vs `BASELINE`** | **`-0.00688`** | `[-0.01563, +0.00159]` | `-1.547` | `0.1160` | `0.3480` | `NOT_SIGNIFICANT` (mejora puntual de `-0.00688`) |
| **`OVER_1_5`: `POISSON` vs `BASELINE`** | **`-0.00395`** | `[-0.01081, +0.00297]` | `-1.106` | `0.2730` | `0.5460` | `NOT_SIGNIFICANT` (mejora puntual de `-0.00395`) |
| **`BTTS`: `POISSON` vs `BASELINE`** | **`-0.00259`** | `[-0.00856, +0.00315]` | `-0.870` | `0.4020` | `0.5460` | `NOT_SIGNIFICANT` (mejora puntual de `-0.00259`) |

### 3.3 Desglose por Competición en el Conjunto de Prueba (`N = 868`)

| Competición | Partidos (`T_test`) | `1X2` Brier (`ENSEMBLE` vs `Baseline`) | `OVER_1_5` Brier (`POISSON` vs `Baseline`) | `OVER_2_5` Brier (`POISSON` vs `Baseline`) | `OVER_3_5` Brier (`POISSON` vs `Baseline`) | `BTTS` Brier (`POISSON` vs `Baseline`) |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: |
| **Premier League** | `230` | **`0.55686`** vs `0.66914` (`-0.11228`) | **`0.13375`** vs `0.14191` (`-0.00816`) | **`0.21941`** vs `0.24001` (`-0.02060`) | **`0.24124`** vs `0.25641` (`-0.01517`) | **`0.22866`** vs `0.23675` (`-0.00809`) |
| **Serie A** | `229` | **`0.57905`** vs `0.65319` (`-0.07414`) | `0.17538` vs `0.17638` (`-0.00100`) | **`0.24191`** vs `0.24943` (`-0.00752`) | **`0.19450`** vs `0.19724` (`-0.00274`) | `0.24844` vs `0.24964` (`-0.00120`) |
| **LaLiga** | `230` | **`0.59482`** vs `0.65481` (`-0.05999`) | **`0.18185`** vs `0.18691` (`-0.00506`) | **`0.24279`** vs `0.25045` (`-0.00766`) | `0.21210` vs `0.21244` (`-0.00034`) | `0.24989` vs `0.24986` (`+0.00003`) |
| **Bundesliga** | `179` | **`0.59365`** vs `0.66684` (`-0.07319`) | `0.14459` vs `0.14502` (`-0.00043`) | `0.23113` vs `0.23415` (`-0.00302`) | **`0.21839`** vs `0.22829` (`-0.00990`) | `0.24482` vs `0.24546` (`-0.00064`) |

---

## 4. Auditoría del Registro de Versiones Activas (`ml_models`)

### 4.1 Causa Raíz Exacta de por qué `v2.5.0-real-cc0` Quedó Activo tras Ejecutar `pytest`
La inspección forense de `ml_models` y de la trazabilidad de ejecución demostró la cadena causal exacta:
1. En `run_phase3_scientific_audit.py` (`2026-11-09T16:56:02`), los registros IDs `16–20` (`v3.0.0-phase3-scientific`) se insertaron en `ml_models` con:
   ```text
   artifact_path = "F:\Proyectos\Predicciones\backend\artifacts\models\sportpredict_models_v3.0.0-phase3-scientific.joblib"
   ```
   es decir, apuntando a un subdirectorio inexistente `\models\`, mientras que el archivo real estaba almacenado directamente en `f:\Proyectos\Predicciones\backend\artifacts\sportpredict_models_v3.0.0-phase3-scientific.joblib`.
2. Cinco minutos después (`2026-11-09T17:01:51`), al ejecutar `pytest`, la prueba `test_mvp_phase1.py::test_end_to_end_api_and_ml_pipeline` invocó `get_match_detailed_analysis(match_id=1, db=db)` directamente sobre `sportpredict_local.db`.
3. `analyze_match` llamó a `_load_latest_artifact_if_available(db)` en [`prediction_service.py`](file:///f:/Proyectos/Predicciones/backend/app/services/prediction_service.py), el cual consultó el registro activo más reciente (`id=20`, `v3.0.0-phase3-scientific`) y evaluó `Path(active_m.artifact_path).exists()`. Al devolver `False` por el subdirectorio `\models\`, el servicio ejecutó el fallback `self.train_and_validate_all_models(db)`, que entrenó y registró `v2.5.0-real-cc0` (IDs `26–30`) con `is_active = True` sin desactivar previamente los registros de `v3.0.0-phase3-scientific`.

### 4.2 Corrección de Selección de Modelo en el Servicio y en la API
1. **Resolución resiliente de `artifact_path` en [`prediction_service.py`](file:///f:/Proyectos/Predicciones/backend/app/services/prediction_service.py#L81-L115):** `_load_latest_artifact_if_available` resuelve ahora tanto rutas directas como `ARTIFACTS_DIR / Path(active_m.artifact_path).name` y soporta tanto las claves de nivel superior (`poisson`, `elo`, `rf`, `xgb`, `ensemble`) como `models_1x2`.
2. **Garantía de versión activa única en [`prediction_service.py`](file:///f:/Proyectos/Predicciones/backend/app/services/prediction_service.py#L298-L303):** Antes de registrar o activar cualquier versión nueva en `train_and_validate_all_models`, se desactivan explícitamente todas las versiones previas (`is_active = False`).
3. **Selección por `is_active == True` en [`routes_models.py`](file:///f:/Proyectos/Predicciones/backend/app/api/routes_models.py#L140-L152):** El endpoint `/api/v1/models/scientific-comparison` selecciona por defecto la versión con `is_active == True` en lugar de `available_versions[-1]`.

### 4.3 Inventario Completo de `ml_models` Antes y Después de la Transición a `v3.1.0`
Ningún registro histórico fue eliminado (`30` filas totales en `ml_models`, `5` por cada una de las `6` versiones registradas):

| Rango de IDs | Versión | Modelos (`model_code`) | Partidos `Train` | Archivo Artefacto (`.joblib`) | `is_active` (Antes) | `is_active` (Después) |
| :---: | :--- | :--- | :---: | :--- | :---: | :---: |
| **`1 – 5`** | `v1.0.0-mvp` | `POISSON`, `ELO`, `RANDOM_FOREST`, `XGBOOST`, `ENSEMBLE` | `90` (DEMO Fase 1) | `sportpredict_models_v1.0.0-mvp.joblib` | `False` | **`False`** |
| **`6 – 10`** | `v1.1.0` | `POISSON`, `ELO`, `RANDOM_FOREST`, `XGBOOST`, `ENSEMBLE` | `90` (DEMO Fase 1) | `sportpredict_models_v1.1.0.joblib` | `False` | **`False`** |
| **`11 – 15`** | `v2.0.0-real-cc0` | `POISSON`, `ELO`, `RANDOM_FOREST`, `XGBOOST`, `ENSEMBLE` | `2,602` (Real CC0) | `sportpredict_models_v2.0.0-real-cc0.joblib` | `False` | **`False`** |
| **`16 – 20`** | `v3.0.0-phase3-scientific` | `POISSON`, `ELO`, `RANDOM_FOREST`, `XGBOOST`, `ENSEMBLE` | `2,605` (Real CC0) | `sportpredict_models_v3.0.0-phase3-scientific.joblib` | `True` (ambiguo) | **`False`** |
| **`26 – 30`** | `v2.5.0-real-cc0` | `POISSON`, `ELO`, `RANDOM_FOREST`, `XGBOOST`, `ENSEMBLE` | `2,605` (Real CC0) | `sportpredict_models_v2.5.0-real-cc0.joblib` | `True` (ambiguo) | **`False`** |
| **`31 – 35`** | **`v3.1.0`** | `POISSON`, `ELO`, `RANDOM_FOREST`, `XGBOOST`, `ENSEMBLE` | `2,605` (Real CC0) | `sportpredict_models_v3.1.0.joblib` | *(No existía)* | **`True` (ÚNICA ACTIVA)** |

---

## 5. Aislamiento de Pruebas Automatizadas (`pytest`)

Se creó [`backend/tests/conftest.py`](file:///f:/Proyectos/Predicciones/backend/tests/conftest.py#L1-L82) con un fixture de sesión `autouse=True` (`isolated_test_environment`) y un hook `pytest_runtest_setup`:
1. Al iniciar `pytest`, se clona `sportpredict_local.db` hacia una plantilla limpia (`template_sportpredict.db`) dentro del directorio temporal de `tmp_path_factory` usando la API nativa `sqlite3.Connection.backup`.
2. Antes de cada test individual, `pytest_runtest_setup` restaura `test_sportpredict_isolated.db` desde la plantilla limpia y limpia el directorio temporal `test_artifacts/`.
3. `app.db.session.engine`, `app.db.session.SessionLocal`, `prediction_service.ARTIFACTS_DIR` y `routes_models.ARTIFACTS_DIR` son redirigidos mediante `monkeypatch` hacia los recursos temporales aislados.
4. **Resultado verificado:** Al ejecutar las `13` pruebas automatizadas de `pytest`, la base de datos de trabajo `backend/data/sportpredict_local.db` mantiene **exactamente el mismo hash SHA-256** antes y después de la ejecución (`db0ee3b669bf137a11763cca8ed4a609a4ccb8617fb14e9084b18b32852c45d9`).

---

## 6. Aclaración de la Trazabilidad del Dataset (Fase 2 vs Fase 3)

### 6.1 Composición Exacta de `sportpredict_local.db` y `openfootball_real_matches_cc0.csv`
La auditoría exhaustiva por `source_name`, `is_demo`, `season` y `status` confirma que el dataset histórico real **nunca cambió** entre la Fase 2 y la Fase 3:

| Fuente (`source_name`) | `is_demo` | Temporada | Estado (`status`) | Partidos | Primer Kickoff (UTC) | Último Kickoff (UTC) | Uso en Entrenamiento/Evaluación Real |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :--- |
| **`OPENFOOTBALL_CC0`** | `False` | **`2021-22`** | `FINISHED` | **`1,446`** | `2021-08-13T20:00:00Z` | `2022-05-22T22:00:00Z` | **Incluido (`T_train`)** |
| **`OPENFOOTBALL_CC0`** | `False` | **`2022-23`** | `FINISHED` | **`1,446`** | `2022-08-05T20:00:00Z` | `2023-06-04T21:00:00Z` | **Incluido (`T_train` + `T_val`)** |
| **`OPENFOOTBALL_CC0`** | `False` | **`2023-24`** | `FINISHED` | **`1,446`** | `2023-08-11T19:30:00Z` | `2024-06-02T18:00:00Z` | **Incluido (`T_val` + `T_test`)** |
| **Subtotal Real Histórico** | **`False`** | **`2021-22` a `2023-24`** | **`FINISHED`** | **`4,338`** | **`2021-08-13T20:00:00Z`** | **`2024-06-02T18:00:00Z`** | **`100%` del motor científico (`v2.0` a `v3.1`)** |
| `DEMO_SEED` | `True` | `2025/2026` | `FINISHED` | `75` | `2026-02-22T15:00:00Z` | `2026-06-14T21:00:00Z` | Excluido (`is_demo == True`) |
| `DEMO_SEED` | `True` | `2026/2027` | `FINISHED` | `75` | `2026-06-22T15:00:00Z` | `2026-10-12T21:00:00Z` | Excluido (`is_demo == True`) |
| `DEMO_SEED` | `True` | `2026/2027` | `SCHEDULED` | `6` | `2026-11-09T19:00:00Z` | `2026-11-11T21:00:00Z` | Excluido (`is_demo == True`, `SCHEDULED`) |
| `Dataset_Propio_Autorizado` | `False` | `2026/2027` | `SCHEDULED` | `1` | `2026-11-15T20:00:00Z` | `2026-11-15T20:00:00Z` | Excluido (`status == SCHEDULED`, creado en test) |

### 6.2 Por qué el Total de `4,338` Partidos es Idéntico y Aclaración de las Fechas
- Los **`4,338` partidos reales finalizados (`OPENFOOTBALL_CC0`)** corresponden a 3 temporadas completas (`2021-22`, `2022-23`, `2023-24`) de Premier League (`380 × 3 = 1,140`), LaLiga (`380 × 3 = 1,140`), Serie A (`380 × 3 = 1,140`) y Bundesliga (`306 × 3 = 918`).
- La mención de *"2022/23 a mayo de 2025"* en el texto narrativo de `06_AUDITORIA_COMPLEMENTARIA_FASE3.md` fue **exclusivamente una errata de transcripción en prosa** al redactar dicho documento Markdown; el archivo JSON subyacente generado por el propio script de auditoría ([`phase3_complementary_audit_results.json`](file:///f:/Proyectos/Predicciones/backend/data/real_historical/phase3_complementary_audit_results.json#L11-L15)) registró siempre las fechas reales exactas: `2021-08-13T20:00:00+00:00` a `2024-06-02T18:00:00+00:00`.

### 6.3 Por qué `Train` Cambió de `2,602` (`v2.0.0-real-cc0`) a `2,605` (`v3.0.0` y `v3.1.0`)
Al ordenar cronológicamente los `4,338` partidos reales, alrededor del índice `2,602` (`60%` de `4,338`) existen **5 partidos simultáneos** jugados el **`2023-04-22T15:00:00+00:00`**:

| Índice (`0-based`) | `match_id` | Competición | Temporada | `kickoff_utc` | Partición en `v2.0.0` (Corte fijo `2,602`) | Partición en `v3.0.0` / `v3.1.0` (Corte disjunto `2,605`) |
| :---: | :---: | :--- | :---: | :---: | :---: | :---: |
| `2600` | `846` | Premier League | `2022-23` | `2023-04-22T15:00:00+00:00` | `Train` | `Train` |
| `2601` | `847` | Premier League | `2022-23` | `2023-04-22T15:00:00+00:00` | `Train` (último de `2,602`) | `Train` |
| `2602` | `848` | Premier League | `2022-23` | `2023-04-22T15:00:00+00:00` | `Val` (solapaba `15:00 UTC`) | **`Train`** |
| `2603` | `849` | Premier League | `2022-23` | `2023-04-22T15:00:00+00:00` | `Val` (solapaba `15:00 UTC`) | **`Train`** |
| `2604` | `3119` | Serie A | `2022-23` | `2023-04-22T15:00:00+00:00` | `Val` (solapaba `15:00 UTC`) | **`Train`** (último de `2,605`) |
| `2605` | `4137` | Bundesliga | `2022-23` | `2023-04-22T15:30:00+00:00` | `Val` | **`Val`** (primero de `865`, `15:30 UTC`) |

- En `v2.0.0-real-cc0`, el corte por índice fijo `2,602` dejaba 2 partidos de las `15:00 UTC` en `Train` y 3 partidos de las mismas `15:00 UTC` en `Val`.
- En `v3.0.0` y `v3.1.0`, la función `split_chronologically_no_overlap` desplazó la frontera `Train/Val` en `+3` partidos (`2,605 / 865 / 868`) para garantizar la desigualdad estricta `max(T_train.kickoff_utc) < min(T_val.kickoff_utc)` (`15:00 UTC < 15:30 UTC`).
- En la frontera `Val/Test` (`índice 3,470`), el último partido de `Val` (`2023-12-10T12:30:00+00:00`) y el primero de `Test` (`2023-12-10T14:00:00+00:00`) ya tenían marcas de tiempo estrictamente distintas, por lo que **los `868` partidos de prueba (`T_test`) son 100% idénticos partido por partido en `v2.0.0`, `v2.5.0`, `v3.0.0` y `v3.1.0`**.

---

## 7. Hashes SHA-256 Antes y Después (Integridad de Artefactos y Datos)

| Archivo / Artefacto | Tamaño (Bytes) | SHA-256 Antes de `v3.1.0` | SHA-256 Después de `v3.1.0` y `pytest` | Estado |
| :--- | :---: | :--- | :--- | :--- |
| [`openfootball_real_matches_cc0.csv`](file:///f:/Proyectos/Predicciones/backend/data/real_historical/openfootball_real_matches_cc0.csv) | `422,740` | `66ebf7560f0284a422f1bc95807761d0c123aaf655ee3d8dc4a569e11d259751` | `66ebf7560f0284a422f1bc95807761d0c123aaf655ee3d8dc4a569e11d259751` | **INVARIANTE (100% INTACTO)** |
| [`sportpredict_models_v1.0.0-mvp.joblib`](file:///f:/Proyectos/Predicciones/backend/artifacts/sportpredict_models_v1.0.0-mvp.joblib) | `740,822` | `8db65a188a7958ee045d084ec38021dc2a3791c5442b1cc61ef7bf07476a4d34` | `8db65a188a7958ee045d084ec38021dc2a3791c5442b1cc61ef7bf07476a4d34` | **INVARIANTE (100% INTACTO)** |
| [`sportpredict_models_v1.1.0.joblib`](file:///f:/Proyectos/Predicciones/backend/artifacts/sportpredict_models_v1.1.0.joblib) | `740,822` | `e3998c30b3dcb56b84a36a792c95038d73f53db9f65ac37fee312b2f5293a665` | `e3998c30b3dcb56b84a36a792c95038d73f53db9f65ac37fee312b2f5293a665` | **INVARIANTE (100% INTACTO)** |
| [`sportpredict_models_v2.0.0-real-cc0.joblib`](file:///f:/Proyectos/Predicciones/backend/artifacts/sportpredict_models_v2.0.0-real-cc0.joblib) | `7,272,958` | `0c7b596b7c48af98206772cc3d3553b313ad43df8fed6a085c1c3c1b97f4f78e` | `0c7b596b7c48af98206772cc3d3553b313ad43df8fed6a085c1c3c1b97f4f78e` | **INVARIANTE (100% INTACTO)** |
| [`sportpredict_models_v2.4.0-real-cc0.joblib`](file:///f:/Proyectos/Predicciones/backend/artifacts/sportpredict_models_v2.4.0-real-cc0.joblib) | `7,299,138` | `bc281c637ad459c4b5219f4f2e1e24206286a3f8620b9c05827f90a088ffee9f` | `bc281c637ad459c4b5219f4f2e1e24206286a3f8620b9c05827f90a088ffee9f` | **INVARIANTE (100% INTACTO)** |
| [`sportpredict_models_v2.5.0-real-cc0.joblib`](file:///f:/Proyectos/Predicciones/backend/artifacts/sportpredict_models_v2.5.0-real-cc0.joblib) | `7,299,138` | `3052813e9f3cb0504fd3e9177d76770764db3f26459e7f7a848498b4f8bb7655` | `3052813e9f3cb0504fd3e9177d76770764db3f26459e7f7a848498b4f8bb7655` | **INVARIANTE (100% INTACTO)** |
| [`sportpredict_models_v3.0.0-phase3-scientific.joblib`](file:///f:/Proyectos/Predicciones/backend/artifacts/sportpredict_models_v3.0.0-phase3-scientific.joblib) | `20,005,465` | `4e3b8f6309f682170b211768f2943491479badb2f2140be688e3c082145ac56a` | `4e3b8f6309f682170b211768f2943491479badb2f2140be688e3c082145ac56a` | **INVARIANTE (100% INTACTO)** |
| **[`sportpredict_models_v3.1.0.joblib`](file:///f:/Proyectos/Predicciones/backend/artifacts/sportpredict_models_v3.1.0.joblib)** | `19,083,886` | *(Nuevo en `v3.1.0`)* | `4d2c51db007f47c011b895c3c7e594907a58dc9b538e8ff992f6c00cf8837f47` | **CREADO Y ACTIVO (`v3.1.0`)** |
| [`sportpredict_local.db`](file:///f:/Proyectos/Predicciones/backend/data/sportpredict_local.db) | `1,630,208` | `54bd5ca6e647947ca44951c8a5bc7ed669235f5da3a0098e86fbb84640f13188` | `db0ee3b669bf137a11763cca8ed4a609a4ccb8617fb14e9084b18b32852c45d9` *(invariante tras `pytest`)* | **ACTUALIZADO CON `v3.1.0` E INMUNE A `pytest`** |

Asimismo, los proyectos hermanos `f:\Proyectos\EduNexus` y `f:\Proyectos\OdontoCloud` no fueron accedidos ni modificados en ningún instante.

---

## 8. Pruebas Automatizadas Ejecutadas y Resultados (`pytest`)

Se ejecutó la suite completa de pruebas automatizadas (`13` tests en `backend/tests/`) con aislamiento en [`conftest.py`](file:///f:/Proyectos/Predicciones/backend/tests/conftest.py):

| Archivo de Prueba | Nombre del Test | Propósito Verificado | Resultado |
| :--- | :--- | :--- | :---: |
| [`test_mvp_phase1.py`](file:///f:/Proyectos/Predicciones/backend/tests/test_mvp_phase1.py) | `test_odds_math_and_ev_formula` | Fórmulas matemáticas de probabilidad implícita, overround, valor esperado (EV) y Kelly fraccional. | **PASSED** |
| [`test_mvp_phase1.py`](file:///f:/Proyectos/Predicciones/backend/tests/test_mvp_phase1.py) | `test_zero_future_data_leakage_in_feature_builder` | Garantía Point-in-Time ante alteración de marcadores futuros. | **PASSED** |
| [`test_mvp_phase1.py`](file:///f:/Proyectos/Predicciones/backend/tests/test_mvp_phase1.py) | `test_end_to_end_api_and_ml_pipeline` | Pipeline completo de API y ML sobre base de datos temporal aislada sin tocar `sportpredict_local.db`. | **PASSED** |
| [`test_phase2_real_data.py`](file:///f:/Proyectos/Predicciones/backend/tests/test_phase2_real_data.py) | `test_real_team_and_datetime_normalization` | Normalización canónica de equipos, fechas UTC y validación de marcadores. | **PASSED** |
| [`test_phase2_real_data.py`](file:///f:/Proyectos/Predicciones/backend/tests/test_phase2_real_data.py) | `test_batch_chronological_features_exact_equivalence_and_no_leakage` | Equivalencia numérica exacta entre generador secuencial y por lotes sin fuga temporal. | **PASSED** |
| [`test_phase2_real_data.py`](file:///f:/Proyectos/Predicciones/backend/tests/test_phase2_real_data.py) | `test_simplex_ensemble_prunes_non_contributing_models` | Poda automática en el símplex de modelos que no mejoran la validación. | **PASSED** |
| [`test_phase3_scientific.py`](file:///f:/Proyectos/Predicciones/backend/tests/test_phase3_scientific.py) | `test_poisson_time_decay_and_competition_hfa` | Decaimiento temporal exponencial $\xi$ y ventaja de localía por competición en Dixon-Coles. | **PASSED** |
| [`test_phase3_scientific.py`](file:///f:/Proyectos/Predicciones/backend/tests/test_phase3_scientific.py) | `test_elo_competition_hfa_and_season_regression` | HFA por liga y regresión a la media inter-temporada en Elo dinámico. | **PASSED** |
| [`test_phase3_scientific.py`](file:///f:/Proyectos/Predicciones/backend/tests/test_phase3_scientific.py) | `test_strict_disjoint_temporal_boundaries_and_pre_match_standings` | Fronteras `Train / Val / Test` estrictamente disjuntas y tabla de posiciones pre-partido. | **PASSED** |
| [`test_phase3_scientific.py`](file:///f:/Proyectos/Predicciones/backend/tests/test_phase3_scientific.py) | `test_moving_block_bootstrap_significance_audit` | Moving Block Bootstrap para diferencias de Brier Score e intervalos de confianza al 95%. | **PASSED** |
| [`test_phase3_scientific.py`](file:///f:/Proyectos/Predicciones/backend/tests/test_phase3_scientific.py) | `test_goal_markets_models_and_evaluation` | Entrenamiento y evaluación de mercados de goles con stacking OOF temporal. | **PASSED** |
| [`test_phase3_scientific.py`](file:///f:/Proyectos/Predicciones/backend/tests/test_phase3_scientific.py) | **`test_temporal_oof_poisson_zero_leakage`** | **Verificación directa de `temporal_violations_count == 0` y `self_inclusion_violations_count == 0` en OOF.** | **PASSED** |
| [`test_phase3_scientific.py`](file:///f:/Proyectos/Predicciones/backend/tests/test_phase3_scientific.py) | **`test_version_tracking_preserves_previous_models`** | **Verificación de que `v3.1.0` es la única versión activa y que los `30` registros y `7` `.joblib` están intactos.** | **PASSED** |

- **Tiempo total de ejecución:** `13 passed in 2.28s`.
- **Invarianza de `sportpredict_local.db` tras `pytest`:** `SHA-256 = db0ee3b669bf137a11763cca8ed4a609a4ccb8617fb14e9084b18b32852c45d9` (antes y después).

---

## 9. Limitaciones Científicas y Operativas Pendientes

1. **Potencia estadística para diferencias sub-milimétricas (`N = 868` partidos de prueba):** Con `868` partidos de prueba retenida, el error estándar por bloques de las diferencias de Brier Score entre modelos competitivos es $\text{SE} \approx 0.0013 - 0.0022$. Esto permite demostrar con alta significancia estadística (`p < 0.001`, superando Holm-Bonferroni) la superioridad de los modelos `1X2` frente al Baseline (`-0.08123` Brier), pero hace que diferencias de orden `0.0003 - 0.0009` entre un ensamble y su mejor modelo individual estén dentro del ruido muestral.
2. **Ausencia de xG tiro-a-tiro en el dataset CC0 de marcador final:** Las variables `rolling_xg_proxy` son aproximaciones derivadas de goles históricos ponderados y eficiencia ofensiva/defensiva pre-partido, no expected goals ópticos de evento por tiro.
3. **Ausencia de cuotas históricas reales pre-partido en las Fases 1–3:** De acuerdo con las reglas del proyecto, no se han inventado ni simulado cuotas de casas de apuestas sobre los `4,338` partidos reales. La comparación contra probabilidades implícitas del mercado (`Market Brier Score`), cálculo de `Expected Value (EV)` sobre cuotas reales y simulación de bankroll con Kelly fraccional corresponden a la **Fase 4**.

---

## 10. Recomendación Formal sobre la Autorización de la Fase 4

> **DICTAMEN FINAL DE VALIDACIÓN `v3.1.0`: `APTO PARA AUTORIZAR EL INICIO DE LA FASE 4`**

### Justificación Técnica del Dictamen:
1. **Integridad Point-in-Time y Cero Fuga en Stacking (`100%` verificado):** Tanto las `27` variables pre-partido en los `868` partidos de prueba como las `4` señales `poisson_*` en los `2,605` partidos de entrenamiento (`T_train`) se generan utilizando exclusivamente partidos estrictamente anteriores (`r.kickoff_utc < m.kickoff_utc`), con `0` violaciones temporales y `0` autoinclusiones.
2. **Selección Científica No Forzada de Modelos por Mercado:** En `v3.1.0`, el mercado `1X2` utiliza el ensamble validado (`51.78% RF + 31.79% XGB + 16.43% ELO`, con `RANDOM_FOREST` co-óptimo), mientras que los 5 mercados de goles (`OVER_1_5`, `OVER_2_5`, `UNDER_2_5`, `OVER_3_5`, `BTTS`) conservan a **`Poisson / Dixon-Coles` (`POISSON`)** como modelo principal al haberse demostrado que las variantes de stacking tabular no lo superan significativamente una vez corregida la fuga in-sample.
3. **Gobernanza de Versiones y Aislamiento de Tests Sellados:** `v3.1.0` es la única versión activa en `ml_models` (`IDs 31–35`), todos los modelos históricos (`v1.0.0-mvp` a `v3.0.0-phase3-scientific`) se conservan intactos con sus hashes SHA-256 originales, y `pytest` corre en un entorno SQLite temporal aislado que jamás altera la base de datos de trabajo.

Quedo a la espera de tu revisión de este informe y de tu autorización explícita antes de iniciar cualquier tarea de la **Fase 4**.
