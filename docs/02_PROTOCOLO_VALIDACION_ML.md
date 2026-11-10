# SPORTPREDICT AI — Protocolo de Validación Científica y Cuotas

## 1. Partición Temporal Estricta (Prohibición de `train_test_split` aleatorio)

En series temporales deportivas, dividir partidos al azar provoca fuga de información (por ejemplo, conocer el rendimiento de un equipo en la jornada 30 para predecir la jornada 12).

Todo entrenamiento y evaluación en **SPORTPREDICT AI** aplica partición cronológica ordenada por `kickoff_utc`:

1. **Conjunto de Entrenamiento ($T_{train}$):** Primer bloque histórico (ej. primeras temporadas o 65% inicial cronológico). Se utiliza para estimar parámetros de ataque/defensa (Poisson), historia Elo y ajuste de árboles (RF, XGBoost).
2. **Conjunto de Validación Temporal ($T_{val}$):** Bloque intermedio subsecuente (ej. siguiente 15% cronológico). Se utiliza para:
   - Calibración de probabilidades (`CalibratedClassifierCV` con método `sigmoid` o `isotonic`).
   - Cálculo de pesos del **Modelo E (Ensamble)**.
   - Selección de hiperparámetros sin tocar el conjunto de prueba final.
3. **Conjunto de Prueba Final Retenido ($T_{test}$):** Bloque más reciente (ej. último 20% cronológico). Nunca interviene en el ajuste ni en la optimización de umbrales. Todas las métricas reportadas como rendimiento fuera de muestra provienen exclusivamente de $T_{test}$.

---

## 2. Métricas de Evaluación Obligatorias

Para cada modelo y mercado se calculan y registran:

- **Brier Score Multiclase / Binario:**
  $$\text{BS} = \frac{1}{N} \sum_{i=1}^{N} \sum_{k=1}^{K} (p_{i,k} - y_{i,k})^2$$
  Mide simultáneamente calibración y resolución. Menor es mejor.
- **Log Loss (Entropía Cruzada):**
  $$\text{LogLoss} = -\frac{1}{N} \sum_{i=1}^{N} \sum_{k=1}^{K} y_{i,k} \ln(\max(p_{i,k}, \epsilon))$$
  Penaliza severamente predicciones excesivamente confiadas e incorrectas.
- **Expected Calibration Error (ECE) y Curvas de Calibración:** Agrupación en intervalos de probabilidad para medir la desviación entre probabilidad estimada y frecuencia empírica real.
- **Métricas de Clasificación:** Accuracy, Precision (macro/ponderada), Recall y F1-Score.
- **Métricas Económicas Simuladas (Backtesting con información pre-partido):**
  - Número total de predicciones evaluadas ($N$).
  - Número de oportunidades con Valor Esperado positivo ($EV > \text{umbral}$ definido en validación).
  - **ROI Simulado** y **Yield** (beneficio neto sobre unidades totales arriesgadas bajo stake plano unitario).

---

## 3. Modelos de Referencia (Benchmarks Obligatorios)

Ningún modelo se presenta de forma aislada. Siempre se compara frente a:
1. **Modelo Base Ingenuo (*Naive Baseline*):** Frecuencia histórica empírica de victoria local, empate y victoria visitante en el conjunto de entrenamiento.
2. **Probabilidad Implícita del Mercado (cuando existen cuotas reales):** Probabilidad derivada de las cuotas disponibles tras remover el margen de la casa de apuestas (*overround*).
3. **Versiones Anteriores del Motor:** Registro histórico en la tabla `backtest_runs`.

---

## 4. Sistema de Probabilidades, Margen y Valor Esperado (EV)

Sea $p_k \in (0, 1)$ la probabilidad calibrada estimada por el modelo para la selección $k$, y $O_k > 1$ la cuota decimal disponible en el mercado:

1. **Cuota Decimal Justa (*Fair Odds*):**
   $$O_{\text{justa}, k} = \frac{1}{p_k}$$

2. **Margen de la Casa de Apuestas (*Overround*):**
   Para un mercado mutuamente excluyente con $K$ resultados posibles:
   $$\text{Overround} = \left(\sum_{j=1}^{K} \frac{1}{O_j}\right) - 1$$

3. **Probabilidad Implícita Ajustada del Mercado (sin margen):**
   $$q_{\text{mercado}, k} = \frac{1 / O_k}{\sum_{j=1}^{K} (1 / O_j)}$$

4. **Diferencia o Ventaja Estadística (*Edge*):**
   $$\text{Edge}_k = p_k - q_{\text{mercado}, k}$$

5. **Valor Esperado Estimado ($EV$):**
   $$EV_k = (p_k \times O_k) - 1$$

6. **Nivel de Incertidumbre ($\sigma_{\text{modelo}}$):**
   Calculado a partir de la dispersión (desviación estándar) entre las probabilidades emitidas por los modelos independientes (Poisson, Elo, Random Forest, XGBoost) más una penalización por tamaño de muestra histórico de los equipos involucrados. Nunca se confunde baja incertidumbre con "apuesta segura".
