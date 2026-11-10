"""Triggers de inmutabilidad del registro prospectivo (`prospective_predictions`).

Se instalan tanto en SQLite (desarrollo/pruebas) como en PostgreSQL (producción).
Reglas:
    - DELETE prohibido incondicionalmente.
    - UPDATE prohibido sobre los 13 campos pre-kickoff sellados por SHA-256 y sobre la metadata
      descriptiva pre-partido (recomendación de la auditoría 14, §6.1).
    - Solo se permiten actualizar: closing_odds, clv_odds_pct, clv_fair_prob_pct (CLV post-cierre)
      y los 6 campos de liquidación post-partido.
"""

from typing import List

from sqlalchemy import text
from sqlalchemy.engine import Connection

# Campos sellados (participan directa o indirectamente en el hash y en la valoración pre-kickoff).
SEALED_EXACT = [
    "match_id",
    "kickoff_utc",
    "model_version",
    "model_code",
    "market_code",
    "selection_code",
    "predicted_at_utc",
    "immutable_record_sha256",
]
SEALED_FLOAT_NOT_NULL = ["prob_model", "fair_model_odds"]
# Campos que pueden ser NULL: comparación null-safe.
SEALED_NULLABLE = [
    "observed_odds",
    "implied_prob_fair",
    "expected_value",
    # Metadata descriptiva pre-partido (congelada desde Fase 5)
    "competition_id",
    "competition_name",
    "fixture_label",
    "bookmaker_name",
    "opening_odds",
    "implied_prob_raw",
    "bookmaker_overround",
    "implied_prob_fair_power",
    "prob_edge",
    "edge_z_score",
    "edge_classification",
    "odds_captured_at_utc",
    "pre_kickoff_verified",
    "is_demo",
]

DELETE_MSG = "PROSPECTIVE_LEDGER_IMMUTABLE: No se permite eliminar predicciones prospectivas registradas."
UPDATE_MSG = (
    "PROSPECTIVE_LEDGER_IMMUTABLE: Prohibido modificar retroactivamente campos pre-partido "
    "de una predicción registrada."
)


def _sqlite_conditions() -> str:
    conds: List[str] = [f"OLD.{c} != NEW.{c}" for c in SEALED_EXACT]
    conds += [f"ABS(OLD.{c} - NEW.{c}) > 1e-9" for c in SEALED_FLOAT_NOT_NULL]
    conds += [f"OLD.{c} IS NOT NEW.{c}" for c in SEALED_NULLABLE]
    return "\n                    OR ".join(conds)


def _postgres_conditions() -> str:
    conds: List[str] = [f"OLD.{c} IS DISTINCT FROM NEW.{c}" for c in SEALED_EXACT]
    conds += [f"ABS(OLD.{c} - NEW.{c}) > 1e-9" for c in SEALED_FLOAT_NOT_NULL]
    conds += [f"OLD.{c} IS DISTINCT FROM NEW.{c}" for c in SEALED_NULLABLE]
    return "\n           OR ".join(conds)


def install_prospective_ledger_triggers(conn: Connection) -> None:
    """Instala (o actualiza) los triggers de inmutabilidad según el dialecto de la conexión."""
    dialect = conn.dialect.name
    if dialect == "sqlite":
        conn.execute(
            text(
                f"""
                CREATE TRIGGER IF NOT EXISTS trg_prospective_predictions_no_delete
                BEFORE DELETE ON prospective_predictions
                BEGIN
                    SELECT RAISE(ABORT, '{DELETE_MSG}');
                END;
                """
            )
        )
        # Versión v1 (13 campos) reemplazada por v2 (13 campos + metadata descriptiva).
        conn.execute(text("DROP TRIGGER IF EXISTS trg_prospective_predictions_immutable_update"))
        conn.execute(
            text(
                f"""
                CREATE TRIGGER IF NOT EXISTS trg_prospective_predictions_immutable_update_v2
                BEFORE UPDATE ON prospective_predictions
                WHEN (
                    {_sqlite_conditions()}
                )
                BEGIN
                    SELECT RAISE(ABORT, '{UPDATE_MSG}');
                END;
                """
            )
        )
    elif dialect == "postgresql":
        conn.execute(
            text(
                f"""
                CREATE OR REPLACE FUNCTION fn_prospective_predictions_guard() RETURNS trigger AS $$
                BEGIN
                    IF TG_OP = 'DELETE' THEN
                        RAISE EXCEPTION '{DELETE_MSG}';
                    END IF;
                    IF {_postgres_conditions()} THEN
                        RAISE EXCEPTION '{UPDATE_MSG}';
                    END IF;
                    RETURN NEW;
                END;
                $$ LANGUAGE plpgsql;
                """
            )
        )
        conn.execute(text("DROP TRIGGER IF EXISTS trg_prospective_predictions_guard ON prospective_predictions"))
        conn.execute(
            text(
                """
                CREATE TRIGGER trg_prospective_predictions_guard
                BEFORE UPDATE OR DELETE ON prospective_predictions
                FOR EACH ROW EXECUTE FUNCTION fn_prospective_predictions_guard();
                """
            )
        )
        # TRUNCATE no dispara triggers de fila: se bloquea con un trigger de sentencia.
        conn.execute(
            text(
                f"""
                CREATE OR REPLACE FUNCTION fn_prospective_predictions_no_truncate() RETURNS trigger AS $$
                BEGIN
                    RAISE EXCEPTION '{DELETE_MSG}';
                END;
                $$ LANGUAGE plpgsql;
                """
            )
        )
        conn.execute(text("DROP TRIGGER IF EXISTS trg_prospective_predictions_no_truncate ON prospective_predictions"))
        conn.execute(
            text(
                """
                CREATE TRIGGER trg_prospective_predictions_no_truncate
                BEFORE TRUNCATE ON prospective_predictions
                FOR EACH STATEMENT EXECUTE FUNCTION fn_prospective_predictions_no_truncate();
                """
            )
        )
    else:
        raise RuntimeError(f"Dialecto no soportado para triggers de inmutabilidad: {dialect}")
