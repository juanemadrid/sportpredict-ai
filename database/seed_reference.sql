-- =============================================================================
-- SPORTPREDICT AI - CATÁLOGOS DE REFERENCIA INICIALES (SIN CLAVES FICTICIAS)
-- =============================================================================

INSERT INTO subscription_plans (plan_code, display_name, daily_analysis_limit, allowed_market_tiers, includes_odds_comparator, includes_full_history, includes_model_benchmarks, billing_active)
VALUES
    ('FREE', 'Plan Gratuito', 3, 1, FALSE, FALSE, FALSE, FALSE),
    ('PREMIUM', 'Plan Premium', 50, 2, TRUE, TRUE, FALSE, FALSE),
    ('PRO', 'Plan Profesional', 9999, 3, TRUE, TRUE, TRUE, FALSE)
ON CONFLICT (plan_code) DO NOTHING;

-- Mercados Progresivos (Sección 5):
-- Nivel 1 habilitado inicialmente tras validación del motor base.
-- Niveles 2 y 3 controlados según cobertura y evaluación del mercado.
INSERT INTO market_catalog (market_code, display_name, tier_level, min_samples_required, is_enabled, status_reason)
VALUES
    ('1X2', 'Resultado Final (Local / Empate / Visitante)', 1, 50, TRUE, 'Habilitado - Nivel 1 evaluado con Poisson, Elo, RF, XGBoost y Ensamble'),
    ('OVER_UNDER_1_5', 'Más / Menos de 1.5 Goles', 1, 50, TRUE, 'Habilitado - Nivel 1 evaluado mediante distribución de Poisson calibrada'),
    ('OVER_UNDER_2_5', 'Más / Menos de 2.5 Goles', 1, 50, TRUE, 'Habilitado - Nivel 1 evaluado mediante distribución de Poisson calibrada'),
    ('BTTS', 'Ambos Equipos Marcan (Sí / No)', 1, 50, TRUE, 'Habilitado - Nivel 1 evaluado mediante matriz conjunta de goles'),
    ('OVER_UNDER_3_5', 'Más / Menos de 3.5 Goles', 2, 120, TRUE, 'Habilitado - Nivel 2 evaluado en cola de distribución de goles'),
    ('DOUBLE_CHANCE', 'Doble Oportunidad (1X / 12 / X2)', 2, 50, TRUE, 'Habilitado - Nivel 2 derivado por aditividad de sucesos disjuntos 1X2'),
    ('EXACT_SCORE', 'Marcador Exacto Probable', 2, 150, TRUE, 'Habilitado - Nivel 2 matriz bivariada de goles (0-0 a 5-5)'),
    ('HALF_TIME_RESULT', 'Resultado al Descanso (HT 1X2)', 2, 300, FALSE, 'Pendiente de cobertura histórica suficiente de goles al descanso'),
    ('CORNERS_OU', 'Total de Córners Más / Menos', 3, 500, FALSE, 'Bloqueado (Nivel 3): requiere >500 partidos con serie histórica validada de córners'),
    ('CARDS_OU', 'Total de Tarjetas Más / Menos', 3, 500, FALSE, 'Bloqueado (Nivel 3): requiere >500 partidos con serie histórica de tarjetas y árbitros'),
    ('SHOTS_ON_TARGET', 'Tiros a Puerta Más / Menos', 3, 500, FALSE, 'Bloqueado (Nivel 3): requiere cobertura completa de tiros a puerta por partido')
ON CONFLICT (market_code) DO NOTHING;

INSERT INTO data_sources (provider_code, display_name, license_type, daily_quota_limit, requests_used_today, status, is_demo)
VALUES
    ('DEMO_SEED', 'Dataset Histórico Semilla Verificable (DEMO)', 'Open Benchmark / Uso Demostrativo Interno', 99999, 0, 'ACTIVE', TRUE),
    ('AUTHORIZED_CSV', 'Importador de Archivos CSV Autorizados', 'Licencia Verificada por el Usuario / Kaggle Open License', 99999, 0, 'ACTIVE', FALSE),
    ('STATSBOMB_OPEN', 'StatsBomb Open Data Adapter', 'CC BY-NC-SA 4.0 (Investigación y Evaluación)', 5000, 0, 'ACTIVE', FALSE),
    ('API_FOOTBALL', 'API-Football v3 (api-sports.io)', 'Plan Gratuito (100 req/día) / Comercial según suscripción', 100, 0, 'NOT_CONFIGURED', FALSE)
ON CONFLICT (provider_code) DO NOTHING;
