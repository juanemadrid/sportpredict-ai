from typing import Any, Dict, List
import numpy as np
from sklearn.base import clone
from sklearn.calibration import CalibratedClassifierCV
from xgboost import XGBClassifier

from app.ml.features import FEATURE_COLUMNS


class CalibratedXGBoostModel:
    """MODELO D: XGBOOST CON CALIBRACIÓN DE PROBABILIDADES FUERA DE MUESTRA.
    - Predicción de resultados multiclase (0=HOME, 1=DRAW, 2=AWAY).
    - Regularización estricta (max_depth=3, reg_lambda=3.0, subsample=0.8) para evitar sobreajuste.
    - Calibración mediante validación cruzada interna (cv=3) sobre el conjunto de entrenamiento (T_train),
      manteniendo T_val 100% fuera de muestra.
    """

    def __init__(
        self,
        n_estimators: int = 120,
        max_depth: int = 3,
        learning_rate: float = 0.04,
        min_child_weight: float = 5.0,
        reg_lambda: float = 3.0,
        subsample: float = 0.80,
        colsample_bytree: float = 0.80,
        calibration_method: str = "sigmoid",
        random_state: int = 42,
    ):
        self.n_estimators = n_estimators
        self.max_depth = max_depth
        self.learning_rate = learning_rate
        self.min_child_weight = min_child_weight
        self.reg_lambda = reg_lambda
        self.subsample = subsample
        self.colsample_bytree = colsample_bytree
        self.calibration_method = calibration_method
        self.random_state = random_state

        self.base_xgb = XGBClassifier(
            n_estimators=n_estimators,
            max_depth=max_depth,
            learning_rate=learning_rate,
            min_child_weight=min_child_weight,
            subsample=subsample,
            colsample_bytree=colsample_bytree,
            reg_alpha=0.8,
            reg_lambda=reg_lambda,
            objective="multi:softprob",
            num_class=3,
            eval_metric="mlogloss",
            n_jobs=1,
            random_state=random_state,
            verbosity=0,
        )
        self.calibrated_model: Any = None
        self.feature_importances: Dict[str, float] = {}
        self.is_fitted: bool = False

    @staticmethod
    def _dict_to_vector(feature_dict: Dict[str, Any]) -> np.ndarray:
        return np.array([float(feature_dict.get(col, 0.0) or 0.0) for col in FEATURE_COLUMNS], dtype=np.float64)

    def fit(
        self,
        X_train: List[Dict[str, Any]],
        y_train: List[int],
        X_val: List[Dict[str, Any]] | None = None,
        y_val: List[int] | None = None,
    ) -> "CalibratedXGBoostModel":
        X_tr = np.vstack([self._dict_to_vector(d) for d in X_train])
        y_tr = np.array(y_train, dtype=int)

        self.base_xgb.fit(X_tr, y_tr)
        importances = self.base_xgb.feature_importances_
        self.feature_importances = {
            col: round(float(imp), 4)
            for col, imp in sorted(zip(FEATURE_COLUMNS, importances), key=lambda x: x[1], reverse=True)
        }

        if len(X_train) >= 45 and len(set(y_train)) == 3:
            method = self.calibration_method if len(X_train) >= 200 else "sigmoid"
            try:
                cal = CalibratedClassifierCV(estimator=clone(self.base_xgb), method=method, cv=3)
                cal.fit(X_tr, y_tr)
                self.calibrated_model = cal
            except Exception:
                self.calibrated_model = self.base_xgb
        else:
            self.calibrated_model = self.base_xgb

        self.is_fitted = True
        return self

    def predict_proba_matrix(self, X_list: List[Dict[str, Any]]) -> np.ndarray:
        if not X_list:
            return np.zeros((0, 3), dtype=np.float64)
        if not self.is_fitted or self.calibrated_model is None:
            return np.tile(np.array([0.44, 0.27, 0.29], dtype=np.float64), (len(X_list), 1))
        mat = np.vstack([self._dict_to_vector(d) for d in X_list])
        probs = self.calibrated_model.predict_proba(mat)
        probs = np.clip(probs, 0.01, 0.98)
        probs = probs / probs.sum(axis=1, keepdims=True)
        return probs

    def predict_1x2(self, feature_dict: Dict[str, Any]) -> Dict[str, float]:
        if not self.is_fitted or self.calibrated_model is None:
            return {"HOME": 0.44, "DRAW": 0.27, "AWAY": 0.29}

        vec = self._dict_to_vector(feature_dict).reshape(1, -1)
        probs = self.calibrated_model.predict_proba(vec)[0]
        probs = np.clip(probs, 0.01, 0.98)
        probs = probs / probs.sum()
        return {
            "HOME": round(float(probs[0]), 5),
            "DRAW": round(float(probs[1]), 5),
            "AWAY": round(float(probs[2]), 5),
        }
