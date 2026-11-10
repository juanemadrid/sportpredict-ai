# SPORTPREDICT AI — INFORME DE AUDITORÍA CIENTÍFICA Y PROFUNDIZACIÓN ML (FASE 3)

**Fecha de ejecución:** `2026-11-09T16:56:02Z`  
**Versión registrada:** `v3.0.0-phase3-scientific`  
**Dataset utilizado:** `OPENFOOTBALL_CC0_REAL` (`4,338` partidos históricos reales de `Premier League`, `LaLiga EA Sports`, `Serie A` y `Bundesliga`, temporadas `2021-22`, `2022-23`, `2023-24`, licencia `CC0-1.0 Universal`).  
**Reporte JSON auditable:** `backend/data/real_historical/phase3_scientific_report.json`  
**Artefacto serializado:** `backend/artifacts/sportpredict_models_v3.0.0-phase3-scientific.joblib`

---

## 1. MODELOS MEJORADOS (IMPLEMENTACIÓN TÉCNICA)

### 1.1. Modelo A: Poisson / Dixon-Coles (`backend/app/ml/models/poisson_model.py`)
- **Decaimiento temporal exponencial configurable:** cada partido histórico a distancia $\Delta t$ días respecto al cierre de la ventana de entrenamiento recibe ponderación $w(\Delta t) = \exp(-\xi \cdot \Delta t)$, otorgando mayor peso a la forma reciente.
- **Ventaja de localía (HFA) por competición:** estimación ponderada independiente de medias goleadoras locales y visitantes ($\bar{\lambda}_{H,c}, \bar{\lambda}_{A,c}$) para cada liga (`Premier League`, `LaLiga`, `Serie A`, `Bundesliga`).
- **Optimización iterativa de parámetros de ataque y defensa:** resolución iterativa (`n_iterations = 5`) de las ecuaciones de máxima verosimilitud ponderada con encogimiento Bayesiano (`shrinkage = 4.0`) y corrección de correlación de marcadores bajos de Dixon-Coles ($\rho = -0.05$).
- **Auditoría de calibración de goles esperados (`evaluate_expected_goals_calibration`):**
  - En validación temporal ($T_{\text{val}} = 865$ partidos), la búsqueda en rejilla sobre $\xi \in \{0.0, 0.0008, 0.0015, 0.0022, 0.0030, 0.0045\}$ y `use_competition_hfa` $\in \{\text{False}, \text{True}\}$ seleccionó $\xi = 0.0015$ (`vida media` $\approx 462$ días) con `use_competition_hfa = True`, reduciendo el Brier Score en validación de `0.58354` ($\xi=0$, sin HFA por liga) a **`0.58259`**.
  - En el conjunto de prueba retenido ($T_{\text{test}} = 868$ partidos), el error de calibración de goles totales mejoró frente a la Fase 2: el **RMSE de goles totales** bajó de `1.6882` a **`1.6646`** y el **MAE de goles totales** bajó de `1.3510` a **`1.3346`** (media predicha `2.8292` vs media real `2.9101` goles/partido).

### 1.2. Modelo B: Sistema Elo Dinámico (`backend/app/ml/models/elo_model.py`)
- **Ventaja de localía y parámetro de empate independientes por competición (`calibrate_competition_parameters`):** calibrados exclusivamente sobre $T_{\text{train}}$ sin fuga futura:
  - `Premier League` (`id=1`): $\text{HFA} = 52.62$ pts Elo, $\nu_{\text{draw}} = 0.7485$
  - `LaLiga EA Sports` (`id=2`): $\text{HFA} = 43.40$ pts Elo, $\nu_{\text{draw}} = 0.6113$
  - `Serie A` (`id=3`): $\text{HFA} = 25.00$ pts Elo, $\nu_{\text{draw}} = 0.7063$
  - `Bundesliga` (`id=4`): $\text{HFA} = 60.90$ pts Elo, $\nu_{\text{draw}} = 0.6556$
- **Evaluación de variantes ($K \in \{16, 20, 24, 28, 32\}$ y regresión a la media entre temporadas $\theta \in \{0.0, 0.15, 0.25, 0.33\}$):**
  - En un horizonte de 3 temporadas consecutivas, aplicar regresión hacia `1500` entre temporadas ($\theta > 0$) diluye la separación legítima entre clubes dominantes y clubes recién ascendidos o de media tabla; por ello $\theta = 0.0$ superó consistentemente a $\theta \in \{0.15, 0.25, 0.33\}$.
  - La mejor configuración en validación fue **`K = 32.0, θ = 0.0, use_competition_hfa = True`**, mejorando el Brier Score en validación de `0.58232` (Elo estándar $K=24$, HFA global) a **`0.57670`**, y en prueba ($T_{\text{test}}$) de `0.58479` a **`0.58332`** (con reducción del error de calibración ECE de `0.02853` a **`0.01540`**).

### 1.3. Modelos C y D: Random Forest y XGBoost (`rf_model.py`, `xgb_model.py`)
- **Ampliación de variables pre-partido (`29` variables para 1X2):** se incorporaron tasas móviles estrictamente pre-partido (`kickoff_utc < T`) en ventana de 10 encuentros (`home_over25_rate10`, `away_over25_rate10`, `home_btts_rate10`, `away_btts_rate10`, `home_clean_sheet_rate10`, `away_clean_sheet_rate10`, `combined_goal_env10`).
- **Control de sobreajuste y calibración (`sigmoid` vs `isotonic`):**
  - **Random Forest (`selected_rf_config`):** `n_estimators = 240`, `max_depth = 6`, `min_samples_leaf = 10`, `calibration_method = "isotonic"`. Brier en entrenamiento: `0.54297`, Brier en validación: **`0.56769`** (`overfit_gap = +0.02472`).
  - **XGBoost (`selected_xgb_config`):** `n_estimators = 100`, `max_depth = 2`, `learning_rate = 0.03`, `min_child_weight = 15.0`, `reg_lambda = 3.0`, `calibration_method = "isotonic"`. Gracias a la poda superficial (`max_depth = 2`) y el peso mínimo por hoja (`min_child_weight = 15.0`), se eliminó por completo el sobreajuste: Brier en entrenamiento `0.57883`, Brier en validación **`0.56584`** (`overfit_gap = -0.01299`, ECE en validación `0.01204`).

---

## 2. MÉTRICAS ANTERIORES (FASE 2) VS. NUEVAS (FASE 3)

### 2.1. Verificación de Fronteras Temporales Sin Solapamiento
En la Fase 2, el corte porcentual directo (`60% / 20% / 20%`) caía dentro de una misma jornada con partidos simultáneos (`2023-04-22` y `2023-12-10`). En la Fase 3, [`PointInTimeFeatureBuilder.split_chronologically_no_overlap`](file:///f:/Proyectos/Predicciones/backend/app/ml/features.py#L74-L96) desplazó el índice de corte hasta el siguiente cambio estricto de timestamp:
- **Train ($N = 2,605$):** hasta `2023-04-22T15:00:00+00:00`
- **Validation ($N = 865$):** desde `2023-04-22T15:30:00+00:00` hasta `2023-12-10T12:30:00+00:00` (`max(Train) < min(Val)` verificado = `True`)
- **Test ($N = 868$):** desde `2023-12-10T14:00:00+00:00` (`max(Val) < min(Test)` verificado = `True`)
- **Auditoría de clasificación pre-partido (`standings_integrity_verified`):** `40` partidos auditados a lo largo de las 3 particiones; **`0` discrepancias** (`standings_pre_match_mismatches = 0`).

### 2.2. Tabla Comparativa en el Conjunto de Prueba Retenido ($T_{\text{test}} = 868$ partidos reales)

| Modelo | Brier Fase 2 (`v2.0.0` original) | Brier Fase 2 (mismo split exacto) | Brier Fase 3 (`v3.0.0` nuevo) | $\Delta$ Brier (Fase 3 vs Fase 2 mismo split) | Log Loss Fase 3 | ECE Fase 3 | Accuracy Fase 3 | IC 95% Brier Fase 3 |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **Baseline Empírico** | `0.65334` | `0.65331` | **`0.65331`** | `0.00000` | `1.06941` | — | `45.39%` | — |
| **Modelo A: Poisson / DC** | `0.58981` | `0.59406` | **`0.59239`** | **`-0.00167`** | `0.99028` | **`0.00486`** | `52.30%` | `[0.57239, 0.61239]` |
| **Modelo B: Elo Dinámico** | `0.58467` | `0.58479` | **`0.58332`** | **`-0.00148`** | `0.97939` | `0.01540` | **`53.57%`** | `[0.56303, 0.60360]` |
| **Modelo C: Random Forest** | `0.58168` | `0.58206` | **`0.57943`** | **`-0.00263`** | **`0.96989`** | `0.02300` | `52.65%` | `[0.55693, 0.60192]` |
| **Modelo D: XGBoost** | `0.58336` | `0.58278` | **`0.58162`** | **`-0.00116`** | `0.97254` | `0.03524` | `52.53%` | `[0.55870, 0.60454]` |
| **Modelo E: Ensamble** | `0.58131` | `0.58170` | **`0.58036`** | **`-0.00134`** | `0.97093` | `0.03121` | `52.53%` | `[0.55796, 0.60275]` |

> [!NOTE]
> En el mismo corte exacto sin solapamiento ($T_{\text{test}} = 868$), **los 5 modelos mejoraron su Brier Score en Fase 3 respecto a su versión de Fase 2**, destacando **Random Forest (`0.57943`, $\Delta = -0.00263$)** como el mejor modelo individual en $T_{\text{test}}$ y el **Ensamble (`0.58036`)** como el segundo mejor global (tras haber sido el mejor en validación $T_{\text{val}}$ con `0.56556`).

---

## 3. COMPARACIONES ESTADÍSTICAS Y AUDITORÍA DEL ENSAMBLE (`Moving Block Bootstrap`)

Se aplicó `paired_moving_block_bootstrap_test` (`block_size = 20` partidos contiguos, `n_boot = 1,000` réplicas) sobre las diferencias pareadas por partido $d_t = \text{BS}_t(A) - \text{BS}_t(B)$:

1. **¿La combinación de Fase 2 (`94.62% RF + 5.38% Poisson`) mejoraba de forma estadísticamente significativa a Random Forest individual?**
   - **Resultado experimental:** En $T_{\text{test}}$, $\Delta \text{Brier} = -0.00036$ (`0.58170` vs `0.58206`), **IC 95% `[-0.00094, +0.00018]`**, $Z = -1.2661$, **$p = 0.2140$**.
   - **Conclusión científica:** Aunque la mezcla reduce levemente la varianza puntual en 3.6 diezmilésimas, **el cero está dentro del intervalo de confianza al 95%**, por lo que **NO existe evidencia de superioridad estadísticamente significativa** sobre Random Forest individual.
2. **¿El Ensamble optimizado de Fase 3 (`75.69% XGBoost + 15.89% RF + 8.42% Poisson`, `0% Elo`) supera significativamente a Random Forest en Fase 3?**
   - En $T_{\text{val}}$, el Ensamble logró el menor Brier (`0.56556` vs `0.56769` de RF, $\Delta = -0.00213$, IC 95% `[-0.00636, +0.00155]`, $p = 0.2980$, no significativo).
   - En $T_{\text{test}}$, Random Forest obtuvo `0.57943` y el Ensamble `0.58036` ($\Delta = +0.00093$, **IC 95% `[-0.00271, +0.00410]`**, **$p = 0.5720$**, diferencia **NO significativa**).
   - En cambio, el Ensamble de Fase 3 **sí supera de forma estadísticamente significativa al 95%** a:
     - **Poisson mejorado** en $T_{\text{test}}$: $\Delta \text{Brier} = -0.01203$, **IC 95% `[-0.02077, -0.00313]`**, **$p = 0.0060$** (significativo).
     - **XGBoost individual** en $T_{\text{test}}$: $\Delta \text{Brier} = -0.00126$, **IC 95% `[-0.00228, -0.00012]`**, **$p = 0.0190$** (significativo).
3. **Comparación de todos los modelos frente al Baseline en $T_{\text{test}}$ ($N = 868$):**
   - **Random Forest vs Baseline:** $\Delta \text{Brier} = -0.07388$, IC 95% `[-0.09195, -0.05740]`, $Z = -8.71$, **$p < 0.0001$** (**Altamente significativo**).
   - **Ensamble vs Baseline:** $\Delta \text{Brier} = -0.07296$, IC 95% `[-0.09107, -0.05768]`, $Z = -8.89$, **$p < 0.0001$** (**Altamente significativo**).
   - **XGBoost vs Baseline:** $\Delta \text{Brier} = -0.07169$, IC 95% `[-0.09035, -0.05618]`, $Z = -8.44$, **$p < 0.0001$** (**Altamente significativo**).
   - **Elo vs Baseline:** $\Delta \text{Brier} = -0.07000$, IC 95% `[-0.08516, -0.05593]`, $Z = -9.73$, **$p < 0.0001$** (**Altamente significativo**).
   - **Poisson vs Baseline:** $\Delta \text{Brier} = -0.06092$, IC 95% `[-0.07573, -0.04889]`, $Z = -9.18$, **$p < 0.0001$** (**Altamente significativo**).

---

## 4. MERCADOS DE GOLES (VALIDACIÓN INDEPENDIENTE EN $T_{\text{test}} = 868$)

Se desarrollaron y validaron independientemente modelos específicos (`POISSON`, `RF_GOALS`, `XGB_GOALS`, `ENSEMBLE_GOALS`) para los 5 mercados solicitados:

| Mercado | Frec. Real ($T_{\text{test}}$) | Baseline Brier | Poisson Brier | RF Específico Brier | XGB Específico Brier | Ensamble Goles Brier | Mejor Modelo en $T_{\text{test}}$ | $\Delta$ Brier vs Baseline (IC 95%, $p$-valor) | ¿ML supera significativamente a Poisson? |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **`OVER_2_5`** | `54.26%` | `0.24890` | `0.23396` | `0.23362` | `0.23469` | **`0.23352`** | **Ensamble** (`55.2% Pois + 44.8% RF`) | **`-0.01538`** (`[-0.0226, -0.0086]`, $p < 0.0001$) | No ($\Delta = -0.00045$, $p = 0.298$) |
| **`UNDER_2_5`** | `45.74%` | `0.24890` | `0.23396` | `0.23375` | `0.23465` | **`0.23359`** | **Ensamble** (`57.8% Pois + 42.2% RF`) | **`-0.01530`** (`[-0.0225, -0.0085]`, $p < 0.0001$) | No ($\Delta = -0.00037$, $p = 0.378$) |
| **`OVER_3_5`** | `34.10%` | `0.22630` | **`0.21648`** | `0.21812` | `0.21916` | **`0.21648`** | **Poisson Puro** (`100% Pois`) | **`-0.00982`** (`[-0.0153, -0.0046]`, $p = 0.0020$) | No (Poisson puro es óptimo) |
| **`OVER_1_5`** | `79.03%` | `0.16663` | **`0.15973`** | `0.16056` | `0.16124` | **`0.15973`** | **Poisson Puro** (`100% Pois`) | **`-0.00690`** (`[-0.0120, -0.0019]`, $p = 0.0100$) | No (Poisson puro es óptimo) |
| **`BTTS`** | `55.53%` | `0.24776` | `0.24283` | **`0.24219`** | `0.24266` | `0.24220` | **RF Específico / Ensamble** | **`-0.00557`** (`[-0.0106, -0.0010]`, $p = 0.0210$) | No ($\Delta = -0.00064$, $p = 0.547$) |

### ¿Qué mercados funcionan mejor?
1. **`OVER_2_5` y `UNDER_2_5` (Mayor ventaja estadística sobre el Baseline):** logran la mayor reducción absoluta de Brier Score ($\Delta = -0.01538$, $Z = -4.34$, $p < 0.0001$) y una precisión de clasificación del **`61.06%`** (`F1 = 0.6530`), donde la combinación de Poisson (`55%`) + Random Forest Específico (`45%`) logra el mejor resultado en prueba.
2. **Resultado ganador `1X2` en `Premier League` y `LaLiga`:** en `Premier League` ($N=224$), el Brier Score en prueba desciende hasta **`0.55502`** (Elo mejorado) y **`0.55884`** (Random Forest), frente a `0.65331` del Baseline.
3. **`BTTS` (Ambos Marcan):** mientras que Poisson individual queda al borde de la significancia ($p = 0.0550$), **`RF_GOALS`** y **`ENSEMBLE_GOALS`** incorporan las tasas de portería imbatida (`clean_sheet_rate10`) y alcanzan significancia estadística al 95% frente al Baseline ($\Delta = -0.00557$, $p = 0.0210$, ECE = `0.02051`).

---

## 5. VARIABLES MÁS IMPORTANTES (IMPORTANCIA AUDITADA)

### 5.1. Mercado `1X2` (Random Forest y XGBoost)
1. **`elo_diff`** (`15.82%` en RF, `16.45%` en XGB): diferencia de calificación Elo pre-partido ajustada por competición.
2. **`league_pos_diff`** (`11.63%` en RF, `7.71%` en XGB): diferencia de posición en la tabla de liga calculada estrictamente antes del encuentro (`kickoff_utc < T`).
3. **`away_elo_pre` y `home_elo_pre`** (`16.78%` combinado en RF, `9.54%` en XGB): nivel absoluto de fuerza de ambos clubes.
4. **Rendimiento ofensivo móvil de 10 partidos (`away_gf_last10`, `home_gf_last10`, `away_pts_last10`, `home_pts_last10`)**: aportan más estabilidad y menor ruido que la ventana corta de 5 partidos (`last5`).
5. **Desempeño específico en condición de local/visitante (`away_away_gf_avg`, `home_home_gf_avg`, `combined_goal_env10`)**.

### 5.2. Mercados de Goles (`Over/Under` y `BTTS`)
1. **`poisson_market_prob` y `poisson_lambda_total`** (`43.2%–47.0%` de importancia en RF, `16.0%–21.8%` en XGB): las esperanzas matemáticas $\lambda_H, \lambda_A$ del modelo Poisson/Dixon-Coles con decaimiento temporal constituyen el predictor base más fuerte.
2. **`combined_goal_env10` y `home_home_gf_avg` / `away_away_gf_avg`**: capturan la tendencia reciente de partidos abiertos o cerrados de ambos equipos.
3. **`home_btts_rate10`, `away_btts_rate10`, `home_clean_sheet_rate10`, `away_clean_sheet_rate10`**: variables clave en el mercado `BTTS` y `Over 3.5`.

---

## 6. MODELOS Y VARIANTES DESCARTADOS (DECISIONES CIENTÍFICAS)

1. **Variantes Elo con regresión inter-temporada $\theta \in \{0.15, 0.25, 0.33\}$:** descartadas experimentalmente porque en un horizonte de 3 temporadas degradan el Brier Score en validación (de `0.57670` con $\theta=0.0$ hasta `0.58345` con $\theta=0.33$).
2. **Árboles XGBoost profundos (`max_depth >= 4`) sin restricción de peso por hoja:** descartados por mostrar brecha de sobreajuste (`overfit_gap = +0.02509`); se adoptó `max_depth = 2, min_child_weight = 15.0` (`overfit_gap = -0.01299`).
3. **Participación de Elo dentro del Ensamble 1X2 (`peso = 0.0000`):** dado que `elo_diff`, `home_elo_pre` y `away_elo_pre` ya son las 3 variables principales dentro de Random Forest y XGBoost, añadir Elo linealmente al Ensamble es redundante y el optimizador SLSQP lo poda legítimamente a `0.0`.
4. **Clasificadores de árboles (`RF_GOALS`, `XGB_GOALS`) en mercados extremos `OVER_1_5` y `OVER_3_5` (`peso = 0.0000` en el Ensamble de Goles):** en umbrales de cola (`1.5` y `3.5` goles), la distribución analítica de Poisson/Dixon-Coles con decaimiento temporal ($\xi = 0.0015$) no es superada por los clasificadores tabulares en validación ni en prueba (`0.15973` y `0.21648`), por lo que se descarta añadir complejidad innecesaria en esos dos mercados.

---

## 7. LIMITACIONES PENDIENTES

1. **Ausencia de cuotas históricas reales en el dataset `CC0-1.0` (`has_historical_odds = False`):** cumpliendo estrictamente la regla 8 de la Fase 3, **no se han inventado cuotas históricas ni se ha simulado ROI ficticio** (`simulated_bets_count = 0`, `simulated_roi_pct = 0.0`). Para auditar rentabilidad real frente al mercado (`Closing Line Value` y `Yield` real) es necesario incorporar un archivo histórico autorizado que incluya cuotas de cierre reales.
2. **Ausencia de `xG`, tiros a puerta (`SOT`), córners y bajas por lesión a nivel de partido en `openfootball/football.json`:** las variables avanzadas existen en el esquema pero toman valores neutros en este dataset abierto de marcadores.
3. **Diferencia no significativa entre los mejores modelos top (`RF`, `XGB`, `Ensamble`):** aunque todos superan al Baseline con $p < 0.0001$ ($Z < -8.4$), la diferencia entre `Random Forest` (`0.57943`) y `Ensamble` (`0.58036`) en $T_{\text{test}}$ está dentro del margen de ruido muestral ($\Delta = 0.00093$, $p = 0.5720$).

---

## 8. RECOMENDACIÓN PARA LA SIGUIENTE FASE (FASE 4)

1. **En Producción para `1X2`:** utilizar el **Ensamble (`v3.0.0-phase3-scientific`)** y **`Random Forest Calibrado Isotonic`** en paralelo, mostrando el acuerdo/dispersión entre los 4 motores (`Poisson`, `Elo`, `RF`, `XGBoost`) como métrica objetiva de incertidumbre.
2. **En Producción para Mercados de Goles:** utilizar el **Ensamble Híbrido (`Poisson + RF_GOALS`)** para `OVER_2_5`, `UNDER_2_5` y `BTTS`, y **Poisson/Dixon-Coles con decaimiento ($\xi=0.0015$)** para `OVER_1_5` y `OVER_3_5`.
3. **Siguiente Paso Recomendado (FASE 4 — Calibración contra Mercado y Detección de Valor Real con Cuotas Autorizadas):**
   - Incorporar un dataset histórico autorizado que posea cuotas reales de apertura/cierre (`1X2` y `Over/Under 2.5`) o activar la captura prospectiva pre-partido (`Prediction` inmutable antes del `kickoff_utc`) para medir el **Market Brier Score**, el **Closing Line Value (CLV)** y verificar científicamente si las probabilidades de `v3.0.0-phase3-scientific` generan Valor Esperado positivo ($EV > 0$) frente a cuotas reales.
