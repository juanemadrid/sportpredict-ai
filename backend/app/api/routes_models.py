import json
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.security import RequestContext, get_request_context, require_admin_role
from app.db.models import BacktestRun, MLModel
from app.db.session import get_db
from app.services.prediction_service import prediction_service

router = APIRouter(prefix="/api/v1/models", tags=["ML Models, Training & Scientific Validation"])


class TrainRequest(BaseModel):
    calibration_method: str = "sigmoid"
    version_tag: Optional[str] = None
    real_only: Optional[bool] = None


@router.get("/comparison")
def get_models_scientific_comparison(
    version: Optional[str] = Query(default=None, description="Versión específica a consultar (por defecto la versión activa)"),
    db: Session = Depends(get_db),
):
    """Compara científicamente los 5 modelos (Poisson, Elo, Random Forest, XGBoost y Ensamble)
    frente al modelo de referencia (Baseline) y frente a las probabilidades del mercado (Sección 9).
    Conserva intactas todas las versiones anteriores para auditoría histórica.
    """
    all_models = db.query(MLModel).order_by(MLModel.id.asc()).all()
    available_versions = list(dict.fromkeys(m.version for m in all_models))
    active_versions = list(dict.fromkeys(m.version for m in all_models if m.is_active))

    explicit_version = version if isinstance(version, str) and version else None
    default_version = (
        active_versions[-1]
        if active_versions
        else (available_versions[-1] if available_versions else prediction_service.active_version)
    )
    target_version = explicit_version or default_version
    models = [m for m in all_models if m.version == target_version]

    backtests = db.query(BacktestRun).order_by(BacktestRun.executed_at.desc()).all()
    latest_bt_by_model_id = {}
    for bt in backtests:
        if bt.model_id not in latest_bt_by_model_id:
            latest_bt_by_model_id[bt.model_id] = bt

    items = []
    for m in models:
        bt = latest_bt_by_model_id.get(m.id)
        feat_imp = json.loads(m.feature_importance_json) if m.feature_importance_json else {}
        hyper = json.loads(m.hyperparameters_json) if m.hyperparameters_json else {}
        cal_curve = json.loads(bt.calibration_curve_json) if bt and bt.calibration_curve_json else []
        by_comp = json.loads(bt.by_competition_json) if bt and bt.by_competition_json else {}

        items.append(
            {
                "id": m.id,
                "model_code": m.model_code,
                "display_name": m.display_name,
                "version": m.version,
                "calibration_method": m.calibration_method,
                "artifact_path": m.artifact_path,
                "train_matches_count": m.train_matches_count,
                "ensemble_weight": round(m.ensemble_weight, 4),
                "val_brier_score": m.val_brier_score,
                "val_log_loss": m.val_log_loss,
                "test_brier_score": m.test_brier_score,
                "test_log_loss": m.test_log_loss,
                "trained_at": m.trained_at.isoformat(),
                "feature_importance": feat_imp,
                "excluded_notes": hyper.get("excluded_notes", {}),
                "backtest": {
                    "run_uid": bt.run_uid,
                    "train_period": bt.train_period,
                    "val_period": bt.val_period,
                    "test_period": bt.test_period,
                    "total_predictions": bt.total_predictions,
                    "accuracy": bt.accuracy,
                    "precision_macro": bt.precision_macro,
                    "recall_macro": bt.recall_macro,
                    "f1_macro": bt.f1_macro,
                    "brier_score": bt.brier_score,
                    "log_loss": bt.log_loss,
                    "ece_calibration": bt.ece_calibration,
                    "baseline_brier_score": bt.baseline_brier_score,
                    "market_brier_score": bt.market_brier_score,
                    "simulated_bets_count": bt.simulated_bets_count,
                    "simulated_roi_pct": bt.simulated_roi_pct,
                    "simulated_yield_pct": bt.simulated_yield_pct,
                    "confidence_intervals_95": hyper.get("confidence_intervals_95", {}),
                    "calibration_curve": cal_curve,
                    "by_competition": by_comp,
                    "is_demo": bt.is_demo,
                }
                if bt
                else None,
            }
        )

    return {
        "active_version": target_version,
        "available_versions": available_versions,
        "validation_protocol": "Partición estrictamente cronológica (Train 60% -> Validación Temporal 20% -> Prueba Final Retenida 20%). Cero fuga de información futura.",
        "models": items,
    }


@router.post("/train")
def trigger_model_training(
    payload: TrainRequest,
    db: Session = Depends(get_db),
    ctx: RequestContext = Depends(get_request_context),
):
    """Módulo administrativo para entrenar, calibrar y evaluar modelos guardando una nueva versión (Sección 8)."""
    require_admin_role(ctx)
    method = payload.calibration_method.lower()
    if method not in ("sigmoid", "isotonic"):
        raise HTTPException(status_code=400, detail="calibration_method debe ser 'sigmoid' o 'isotonic'")
    try:
        report = prediction_service.train_and_validate_all_models(
            db=db,
            version_tag=payload.version_tag,
            calibration_method=method,
            real_only=payload.real_only,
        )
        return report
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
