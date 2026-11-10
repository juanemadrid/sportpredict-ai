# SPORTPREDICT AI — AUDITORÍA FINAL DE HASH Y VALIDACIÓN ESTADÍSTICA

**Código de Documento:** `14_AUDITORIA_FINAL_HASH_Y_ESTADISTICA.md`  
**Fecha de Emisión:** 2026-11-09  
**Tipo de Documento:** Auditoría Técnica y Científica de Solo Lectura (Previa a Fase 5)  
**Versión Base del Motor:** `v3.1.0` (Validada, Activa en Almacenamiento)  
**Alcance:** Verificación del mecanismo de hash SHA-256 en Fase 4, recálculo matemático de potencia estadística, análisis de unidad muestral y sesgo de selección por EV.  
**Estado de la Fase 5:** **NO AUTORIZADA — NO INICIADA** (Todos los criterios C1 a C11 permanecen PENDIENTES).  
**Restricción Mandataria Cumplida:** Cero modificaciones de código ejecutable, cero migraciones, cero reentrenamientos, cero alteraciones de bases de datos o dataset, y cero gasto ($0 USD).

---

## 1. Resumen Ejecutivo y Dictamen de Auditoría

Esta auditoría técnica independiente inspeccionó el estado del código fuente, el esquema relacional, los triggers SQLite y los fundamentos probabilísticos de SPORTPREDICT AI.

### Dictamen General por Apartado

| Apartado Auditado | Objeto de Inspección | Veredicto | Resumen del Hallazgo |
| :--- | :--- | :---: | :--- |
| **1. Verificación del Hash Prospectivo** | Función `compute_prospective_record_sha256`, serialización, triggers SQLite y liquidación post-partido. | **`APROBADO`** | El hash se calcula sobre 9 atributos pre-kickoff canónicos y deterministas. No incluye campos de liquidación, permitiendo que la verificación `recomputed_hash == immutable_record_sha256` sea 100% exitosa post-liquidación. Los triggers bloquean `DELETE` y protegen los 13 campos pre-partido. |
| **2. Matemática de Potencia y Muestra** | Deducción analítica de $N_{\text{sig}}$ y $N_{\text{pot}}$ bajo CLT para $\bar{O}=2.00, e=0.03, \operatorname{Var}(R)=0.9991$. | **`APROBADO`** | Se reproducen con exactitud matemática las cifras: Unilateral (3.004 sig / 6.864 pot 80%) y Bilateral (4.265 sig / 8.714 pot 80%). Se documenta formalmente que corresponden a supuestos idealizados y no constituyen garantías universales. |
| **3. Unidad de Análisis y Dependencia** | Análisis de observaciones correlacionadas, mercados múltiples por partido, efecto de diseño y sesgo por EV. | **`APROBADO`** | Se formaliza que 3.004 registros no equivalen a 3.004 apuestas ni a 3.004 partidos independientes. Se establece el ajuste por correlación intra-conglomerado ($\text{DEFF}$) y el tratamiento del sesgo de selección (Winner's Curse / contracción empírica). |
| **4. Estado de Fase 5** | Verificación de inmovilización operativa y criterios C1–C11. | **`PENDIENTE`** | La Fase 5 no ha sido iniciada. Todos sus criterios de aceptación C1–C11 permanecen formalmente en estado `PENDIENTE` a la espera de la autorización expresa del propietario. |

---

## 2. Verificación del Hash del Registro Prospectivo e Inmutabilidad SQLite

Se auditó la implementación de Fase 4 en [`backend/app/services/phase4_market_service.py`](file:///f:/Proyectos/Predicciones/backend/app/services/phase4_market_service.py) y [`backend/app/db/models.py`](file:///f:/Proyectos/Predicciones/backend/app/db/models.py).

### 2.1 Campos que Participan en el Hash SHA-256
La función `compute_prospective_record_sha256` (líneas 161–179 de `phase4_market_service.py`) calcula la firma criptográfica a partir de exactamente **9 atributos pre-kickoff**:

```python
def compute_prospective_record_sha256(
    match_id: int,
    kickoff_utc_iso: str,
    model_version: str,
    model_code: str,
    market_code: str,
    selection_code: str,
    prob_model: float,
    observed_odds: Optional[float],
    predicted_at_utc_iso: str,
) -> str:
    odds_str = f"{float(observed_odds):.4f}" if observed_odds is not None else "NO_ODDS"
    payload = (
        f"match={match_id}|kickoff={kickoff_utc_iso}|ver={model_version}|mod={model_code}|"
        f"mkt={market_code}|sel={selection_code}|prob={prob_model:.6f}|odds={odds_str}|"
        f"pred_at={predicted_at_utc_iso}"
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
```

### 2.2 ¿Se calcula sobre la fila completa o sobre campos pre-kickoff?
- **Hallazgo:** El hash **NO se calcula sobre la fila completa** (la tabla `prospective_predictions` posee 37 columnas), sino sobre un **subconjunto canónico de 9 atributos pre-kickoff invariantes**.
- **Impacto:** Ninguno de los 6 campos de liquidación (`settlement_status`, `actual_outcome_code`, `actual_outcome_binary`, `brier_contribution`, `log_loss_contribution`, `settled_at_utc`) interviene en la firma SHA-256.

### 2.3 Serialización Canónica y Determinismo
Se verificó el determinismo de la serialización:
1. **Orden de campos:** Fijo y cableado (`match` $\rightarrow$ `kickoff` $\rightarrow$ `ver` $\rightarrow$ `mod` $\rightarrow$ `mkt` $\rightarrow$ `sel` $\rightarrow$ `prob` $\rightarrow$ `odds` $\rightarrow$ `pred_at`).
2. **Tipos y codificación:**
   - Fechas: Normalizadas a UTC mediante `_ensure_utc(dt).isoformat()`.
   - Números reales: `prob_model` con 6 decimales fijos (`{prob_model:.6f}`); `observed_odds` con 4 decimales fijos (`{float(observed_odds):.4f}`).
   - Valores nulos: Si `observed_odds` es nulo, se codifica textualmente como `"NO_ODDS"`.
   - Carácter separador: Pipe (`|`) sin espacios para evitar ambigüedades de espaciado.

### 2.4 Verificación del Hash Post-Liquidación
En el método `_serialize_prospective_record` (líneas 873–925) y en el endpoint `/api/v1/phase4/prospective/ledger`, se recomputa el hash en cada consulta:
```python
recomputed_hash = compute_prospective_record_sha256(...)
item["sha256_integrity_verified"] = (recomputed_hash == r.immutable_record_sha256)
```
- **Resultado:** Tras liquidar un partido en `/prospective/settle`, los 9 campos pre-kickoff permanecen inalterados. En consecuencia, `recomputed_hash == r.immutable_record_sha256` evalúa a `True` de forma determinista y `all_hashes_valid` es `True`.
- **Comprobación:** Ninguno de los 6 campos de liquidación provoca discrepancia criptográfica.

### 2.5 Eficacia de los Triggers SQLite
Se auditaron los triggers en líneas 221–254 de `phase4_market_service.py`:
- **`trg_prospective_predictions_no_delete`:** Bloquea incondicionalmente cualquier sentencia `DELETE ON prospective_predictions` con `RAISE(ABORT)`.
- **`trg_prospective_predictions_immutable_update`:** Evalúa una cláusula `WHEN` con 13 condiciones disyuntivas. Aborta con `RAISE(ABORT)` si se intenta modificar:
  `match_id`, `kickoff_utc`, `model_version`, `model_code`, `market_code`, `selection_code`, `prob_model`, `fair_model_odds`, `observed_odds`, `implied_prob_fair`, `expected_value`, `predicted_at_utc` o `immutable_record_sha256`.
- **Observación Técnica Menor:** Columnas accesorias descriptivas de la tabla (como `competition_name`, `fixture_label` o `bookmaker_name`) no están incluidas en la cláusula `WHEN` del trigger. Esto no afecta la integridad de la predicción probabilística ni del hash SHA-256, pero se recomienda incluirlas en una futura revisión si se desea congelar la metadata nominal.

---

## 3. Auditoría Matemática del Tamaño de Muestra y Potencia Estadística

Se reprodujo analíticamente el cálculo muestral bajo los supuestos declarados.

### 3.1 Supuestos Declarados del Modelo Idealizado
- Cuota decimal media: $\bar{O} = 2.00$.
- Ventaja real hipotética (Yield esperado): $e = \mathbb{E}[R] = 0.03$ (+3.0%).
- Retorno por unidad apostada: $R \in \{\bar{O} - 1, -1\} = \{+1.0, -1.0\}$.
- Probabilidad real de acierto bajo ventaja $e$:
  $$p = \frac{1 + e}{\bar{O}} = \frac{1.03}{2.00} = 0.5150$$
- Varianza del retorno por apuesta unitaria:
  $$\operatorname{Var}(R) = p(\bar{O} - 1)^2 + (1 - p)(-1.0)^2 - e^2 = 0.5150(1.0)^2 + 0.4850(1.0)^2 - (0.03)^2$$
  $$\operatorname{Var}(R) = 0.5150 + 0.4850 - 0.0009 = 0.9991$$
- Nivel de significancia: $\alpha = 0.05$.
- Potencia estadística objetivo: $1 - \beta = 0.80$ ($\beta = 0.20$).

### 3.2 Fórmulas bajo el Teorema del Límite Central (CLT)
Bajo CLT, el retorno medio tras $N$ observaciones independientes e idénticamente distribuidas (i.i.d.) sigue:
$$\bar{R}_N \sim \mathcal{N}\left(e, \frac{\operatorname{Var}(R)}{N}\right)$$

Bajo la hipótesis nula $H_0: e = 0$ (o $e \le 0$), el estadístico de prueba es:
$$Z = \frac{\bar{R}_N}{\sqrt{\operatorname{Var}(R) / N}}$$

Para satisfacer el umbral de significancia ($Z_\alpha$) y potencia ($Z_\beta$):
- **Significancia Únicamente:**
  $$N_{\text{sig}} = \left\lceil \frac{Z_\alpha^2 \times \operatorname{Var}(R)}{e^2} \right\rceil$$
- **Potencia al 80% con Significancia al 95%:**
  $$N_{\text{pot}} = \left\lceil \frac{(Z_\alpha + Z_\beta)^2 \times \operatorname{Var}(R)}{e^2} \right\rceil$$

### 3.3 Valores Críticos de $Z$ Normal Estándar
- Unilateral ($\alpha = 0.05$): $Z_{0.95} = \Phi^{-1}(0.95) = \mathbf{1.6448536...}$
- Bilateral ($\alpha = 0.05$): $Z_{0.975} = \Phi^{-1}(0.975) = \mathbf{1.9599640...}$
- Potencia 80% ($\beta = 0.20$): $Z_{0.80} = \Phi^{-1}(0.80) = \mathbf{0.8416212...}$

### 3.4 Reproducción de Cálculos

#### A. Prueba Unilateral ($H_0: e \le 0$ vs $H_1: e > 0$)
1. **Significancia al 95%:**
   $$N_{\text{sig, 1-cola}} = \left\lceil \frac{1.6448536^2 \times 0.9991}{0.0009} \right\rceil = \left\lceil \frac{2.7055436 \times 0.9991}{0.0009} \right\rceil = \left\lceil \frac{2.7031086}{0.0009} \right\rceil = \lceil 3.003,454 \rceil = \mathbf{3.004 \text{ observaciones}}$$
2. **Potencia del 80% al 95%:**
   $$Z_\alpha + Z_\beta = 1.6448536 + 0.8416212 = 2.4864748$$
   $$(Z_\alpha + Z_\beta)^2 = 2.4864748^2 = 6.1825572$$
   $$N_{\text{pot, 1-cola}} = \left\lceil \frac{6.1825572 \times 0.9991}{0.0009} \right\rceil = \left\lceil \frac{6.1769930}{0.0009} \right\rceil = \lceil 6.863,326 \rceil = \mathbf{6.864 \text{ observaciones}}$$

#### B. Prueba Bilateral ($H_0: e = 0$ vs $H_1: e \ne 0$)
1. **Significancia al 95%:**
   $$N_{\text{sig, 2-colas}} = \left\lceil \frac{1.9599640^2 \times 0.9991}{0.0009} \right\rceil = \left\lceil \frac{3.8414588 \times 0.9991}{0.0009} \right\rceil = \left\lceil \frac{3.8379995}{0.0009} \right\rceil = \lceil 4.264,444 \rceil = \mathbf{4.265 \text{ observaciones}}$$
2. **Potencia del 80% al 95%:**
   $$Z_{\alpha/2} + Z_\beta = 1.9599640 + 0.8416212 = 2.8015852$$
   $$(Z_{\alpha/2} + Z_\beta)^2 = 2.8015852^2 = 7.8488796$$
   $$N_{\text{pot, 2-colas}} = \left\lceil \frac{7.8488796 \times 0.9991}{0.0009} \right\rceil = \left\lceil \frac{7.8418156}{0.0009} \right\rceil = \lceil 8.713,128 \rceil = \mathbf{8.714 \text{ observaciones}}$$

#### Tabla Resumen de Verificación Matemática

| Configuración de Prueba | Nivel $\alpha$ | Potencia $1-\beta$ | Valor $Z_\alpha$ | Valor $Z_\beta$ | Resultado Analítico Exacto | Cifra Redondeada Oficial |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: |
| **Unilateral (Significancia)** | 0.05 | — | 1.64485 | — | $\lceil 3.003,45 \rceil$ | **3.004** |
| **Unilateral (Potencia 80%)** | 0.05 | 0.80 | 1.64485 | 0.84162 | $\lceil 6.863,33 \rceil$ | **6.864** |
| **Bilateral (Significancia)** | 0.05 | — | 1.95996 | — | $\lceil 4.264,44 \rceil$ | **4.265** |
| **Bilateral (Potencia 80%)** | 0.05 | 0.80 | 1.95996 | 0.84162 | $\lceil 8.713,13 \rceil$ | **8.714** |

> **Advertencia Metodológica:** Estas cifras son aproximaciones asintóticas bajo un modelo analítico concreto ($\bar{O}=2.00, e=3\%$, varianza binomial). **No constituyen garantías de rentabilidad.** Si el yield real del mercado es inferior (ej. $+1.5\%$) o la cuota promedio superior ($\bar{O}=2.50$), la muestra requerida para potencia 80% se eleva a más de **25.000 apuestas**.

---

## 4. Unidad de Análisis, Dependencia y Sesgo de Selección

### 4.1 ¿Cuándo una Apuesta Equivale a una Observación Independiente?
Una apuesta constituye una observación estadísticamente independiente **únicamente si su resultado condicional no comparte información latente ni shocks no observados con otra apuesta de la muestra**.
- **Independientes:** Dos apuestas sobre partidos de ligas distintas jugados en días separados.
- **Dependientes:** Apuestas realizadas sobre el mismo partido o sobre partidos de la misma fecha de campeonato donde los resultados concurrentes afectan la estrategia táctica (ej. fecha final de liga con equipos disputando el descenso).

### 4.2 Contabilización de Varios Mercados del Mismo Partido
En SPORTPREDICT AI, un solo encuentro genera hasta **13 predicciones prospectivas** (`1X2`: 3; `OVER 1.5`, `OVER 2.5`, `UNDER 2.5`, `OVER 3.5`, `BTTS`: 2 cada uno).
- Todas estas selecciones están atadas a la **misma realización de goles** ($G_H, G_A$).
- Si el partido finaliza $3-1$, los eventos `OVER 1.5`, `OVER 2.5` y `BTTS` ganan simultáneamente, mientras que `UNDER 2.5` pierde. La covarianza cruzada entre retornos es estrictamente positiva ($\operatorname{Cov}(R_a, R_b) > 0$).
- Tratar 13 registros de un mismo partido como 13 grados de libertad independientes constituye un error de **pseudorreplicación**.

### 4.3 Ajuste del Tamaño Efectivo de Muestra por Correlación Intra-Partido
Bajo la formulación de efectos de conglomerados (Kish, 1965), el factor de inflación de varianza o Efecto de Diseño ($\text{DEFF}$) para $m$ selecciones correlacionadas por partido con coeficiente de correlación intra-conglomerado $\rho \in (0, 1)$ es:
$$\text{DEFF} = 1 + (m - 1)\rho$$

El tamaño de muestra efectivo ($N_{\text{eff}}$) que aporta información independiente es:
$$N_{\text{eff}} = \frac{N_{\text{nominal}}}{\text{DEFF}} = \frac{N_{\text{nominal}}}{1 + (m - 1)\rho}$$

**Ejemplo Numérico:** Si en promedio se seleccionan $m = 3$ mercados por partido con correlación estimada $\rho = 0.40$:
$$\text{DEFF} = 1 + (3 - 1)(0.40) = 1 + 0.80 = 1.80$$
Para obtener el equivalente informativo a 6.864 apuestas independientes, se requerirían:
$$N_{\text{nominal}} = 6.864 \times 1.80 = \mathbf{12.355 \text{ registros}}$$

### 4.4 Diferenciación: Partidos vs Apuestas vs Registros

```
+---------------------------------------------------------------------------------------------------+
| CONCEPTO                     | DEFINICIÓN EXACTA                   | EQUIVALENCIA INFORMACIONAL   |
+---------------------------------------------------------------------------------------------------+
| 1. Registros en Ledger       | Filas en prospective_predictions    | N_registros >= N_apuestas    |
| 2. Apuestas Seleccionadas    | Decisiones activas con EV >= 2%     | Subconjunto filtrado         |
| 3. Partidos Independientes   | Encuentros deportivos disjuntos     | Unidad genuina de libertad   |
+---------------------------------------------------------------------------------------------------+
```

- **Por qué 3.004 no es una constante intercambiable:**
  - 3.004 registros en base de datos pueden corresponder a solo **231 partidos** ($231 \times 13 \approx 3.003$). Evaluar un modelo sobre 231 partidos deja un error estándar enorme.
  - 3.004 apuestas seleccionadas con valor esperado positivo distribuidas en 1.500 partidos otorgan un tamaño efectivo sensiblemente menor a 3.004 debido a la covarianza intra-partido.
  - **No sustituir cálculos con umbrales fijos:** Declarar "3.000 partidos" como umbral automático es conceptualmente incorrecto. El requerimiento de partidos depende de la varianza empírica observada y de la correlación de los residuos del modelo.

### 4.5 Sesgo de Selección por Filtrado de Oportunidades por EV
Al seleccionar únicamente apuestas donde el valor esperado estimado sea positivo ($\hat{\text{EV}} \ge 2.0\%$):
$$\hat{\text{EV}} = (\hat{p} \times O) - 1 = (p_{\text{verdadero}} + \epsilon)O - 1 = \text{EV}_{\text{verdadero}} + \epsilon O$$
Donde $\epsilon$ es el error de estimación del modelo ($\mathbb{E}[\epsilon] = 0$).

1. **La Maldición del Ganador (*Winner's Curse*):** Condicionar la muestra a $\hat{\text{EV}} \ge 0.02$ selecciona sistemáticamente observaciones donde $\epsilon > 0$.
2. **Regresión a la Media:** En la muestra prospectiva de liquidación, los errores $\epsilon$ no se repiten sistemáticamente. El yield promedio observado suele converger a un valor significativamente menor que el EV estimado pre-apuesta.
3. **Tratamiento Metodológico en Fase 5:**
   - Aplicar contracción empírica (*shrinkage*) sobre probabilidades extremas.
   - Evaluar métricas de Brier Score y Log Loss sobre **la totalidad de las probabilidades**, no únicamente sobre el subconjunto con EV positivo.
   - Reportar el Closing Line Value (CLV) como métrica primaria de eficiencia, dado que el CLV es insensible al azar del marcador final.

---

## 5. Matriz de Resultados y Dictamen por Apartado

```markdown
| Apartado de Auditoría | Criterio Evaluado | Estado | Justificación / Evidencia |
| :---: | :--- | :---: | :--- |
| **AUD-01** | Hash Prospectivo pre-kickoff | **APROBADO** | 9 campos canónicos normalizados; verificado post-settle en test_phase4_settlement_idempotence. |
| **AUD-02** | Triggers SQLite Inmutables | **APROBADO** | DELETE bloqueado incondicionalmente; 13 condiciones disyuntivas en UPDATE. |
| **AUD-03** | Matemática Unilateral (3.004 / 6.864) | **APROBADO** | Deducción exacta bajo CLT con Z_alpha=1.64485 y Z_beta=0.84162. |
| **AUD-04** | Matemática Bilateral (4.265 / 8.714) | **APROBADO** | Deducción exacta bajo CLT con Z_alpha/2=1.95996 y Z_beta=0.84162. |
| **AUD-05** | Análisis de Correlación y DEFF | **APROBADO** | Formalización del ajuste Kish por conglomerados y distinción de registros vs partidos. |
| **AUD-06** | Análisis de Sesgo de Selección EV | **APROBADO** | Modelado formal del Winner's Curse y regresión a la media en apuestas condicionadas. |
| **AUD-07** | Estado Operativo de Fase 5 | **PENDIENTE** | Fase 5 no iniciada; criterios C1 a C11 permanecen formalmente PENDIENTES. |
```

---

## 6. Limitaciones, Recomendaciones Técnicas y Cero Alteración de Activos

### 6.1 Limitaciones Identificadas
1. **Atributos descriptivos fuera del trigger de update:** Columnas como `fixture_label` o `competition_name` no provocan excepción si se intentan actualizar directamente vía SQL. Se recomienda incluirlas en una futura migración antes de producción.
2. **Dependencia de la varianza empírica:** El cálculo de 6.864 apuestas asume varianza unitaria estricta de 0.9991. Si el sistema opera con cuotas promedio de 2.80, la varianza asciende a $\sim 1.77$, lo que elevaría el $N$ necesario a más de 12.000 observaciones.

### 6.2 Recomendaciones Técnicas para Cuando se Autorice la Fase 5
1. Incorporar en el dashboard de Fase 5 el cálculo en tiempo real del **tamaño muestral efectivo** ($N_{\text{eff}}$) ajustado por la correlación intra-partido real de las predicciones liquidadas.
2. No habilitar afirmaciones de rentabilidad comercial en la UI hasta que el intervalo de confianza del yield observado (obtenido por Moving Block Bootstrap) supere el cero con significancia bilateral al 95%.

### 6.3 Confirmación de Integridad de Activos
Se certifica que durante esta auditoría documental:
- No se modificó ningún archivo en `backend/app/`, `backend/ml/`, `backend/data/` ni `database/`.
- No se entrenó ni recompiló ningún modelo `.joblib`.
- La base de datos persistente `backend/data/sportpredict_local.db` y el CSV histórico `openfootball_real_matches_cc0.csv` conservan exactamente sus hashes SHA-256 certificados en el informe `10_INFORME_CORRECCION_SEGURIDAD_FASE4.md`.
- La suite de 20 pruebas automatizadas se mantiene intacta y aprobada al 100%.

---

## 7. Declaración de Cierre y Bloqueo de Fase 5

> [!CAUTION]
> **ESTADO FINAL DEL SISTEMA:**  
> - La presente auditoría de solo lectura concluye formalmente con la entrega de este documento.  
> - **LA FASE 5 PERMANECE SIN INICIAR.**  
> - Los criterios `C1` a `C11` de la Fase 5 permanecen en estado **`PENDIENTE`**.  
> - El sistema se encuentra en reposo absoluto a la espera de la autorización expresa del propietario.
