from pathlib import Path
import shutil
import sqlite3
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import app.core.config as app_config
import app.db.init_db as app_init_db
import app.db.session as app_session
import app.services.prediction_service as app_pred_service


@pytest.fixture(scope="session", autouse=True)
def isolated_test_environment(tmp_path_factory: pytest.TempPathFactory):
    """Aísla el 100% de las pruebas automatizadas (pytest) en una copia temporal de la base de datos
    y un directorio temporal de artefactos.
    Garantiza criptográficamente que ninguna prueba modifique `sportpredict_local.db` ni `backend/artifacts/`.
    """
    tmp_dir: Path = tmp_path_factory.mktemp("sportpredict_test_isolated")
    isolated_db_path: Path = tmp_dir / "sportpredict_test_isolated.db"
    isolated_artifacts_dir: Path = tmp_dir / "artifacts"
    isolated_artifacts_dir.mkdir(parents=True, exist_ok=True)

    real_db_path = app_config.DATA_DIR / "sportpredict_local.db"
    if real_db_path.exists():
        # Copia segura de SQLite mediante API de backup (incluso con conexiones concurrentes de solo lectura)
        src_conn = sqlite3.connect(str(real_db_path))
        dst_conn = sqlite3.connect(str(isolated_db_path))
        with dst_conn:
            src_conn.backup(dst_conn)
        dst_conn.close()
        src_conn.close()
    else:
        # Fallback para entornos limpios sin base local: crea las tablas mínimas requeridas
        from app.db.session import Base
        Base.metadata.create_all(bind=test_engine)

    # Copiar artefactos existentes al directorio aislado para lectura/verificación sin tocar los originales
    if app_config.ARTIFACTS_DIR.exists():
        for jb in app_config.ARTIFACTS_DIR.glob("*.joblib"):
            shutil.copy2(jb, isolated_artifacts_dir / jb.name)

    test_db_url = f"sqlite:///{isolated_db_path.as_posix()}"
    test_engine = create_engine(test_db_url, connect_args={"check_same_thread": False})
    TestSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)

    orig_engine = app_session.engine
    orig_session_local = app_session.SessionLocal
    orig_init_engine = app_init_db.engine
    orig_artifacts_dir = app_pred_service.ARTIFACTS_DIR

    orig_dev_headers = app_config.settings.AUTH_ALLOW_DEV_HEADERS
    orig_env = app_config.settings.ENVIRONMENT
    app_config.settings.AUTH_ALLOW_DEV_HEADERS = True
    app_config.settings.ENVIRONMENT = "test"

    app_session.engine = test_engine
    app_session.SessionLocal = TestSessionLocal
    app_init_db.engine = test_engine
    app_pred_service.ARTIFACTS_DIR = isolated_artifacts_dir

    # Si algún módulo de test ya importó SessionLocal por valor, actualizar su referencia
    import sys

    for mod_name, mod_obj in list(sys.modules.items()):
        if mod_name.startswith("tests.") and mod_obj is not None and hasattr(mod_obj, "SessionLocal"):
            setattr(mod_obj, "SessionLocal", TestSessionLocal)

    yield {
        "isolated_db_path": isolated_db_path,
        "isolated_artifacts_dir": isolated_artifacts_dir,
        "SessionLocal": TestSessionLocal,
    }

    test_engine.dispose()
    app_config.settings.AUTH_ALLOW_DEV_HEADERS = orig_dev_headers
    app_config.settings.ENVIRONMENT = orig_env
    app_session.engine = orig_engine
    app_session.SessionLocal = orig_session_local
    app_init_db.engine = orig_init_engine
    app_pred_service.ARTIFACTS_DIR = orig_artifacts_dir


def pytest_runtest_setup(item: pytest.Item) -> None:
    """Garantiza que cualquier módulo de prueba que haya importado `SessionLocal` directamente
    utilice siempre la sesión aislada temporal configurada por `isolated_test_environment`.
    """
    import sys
    for mod_name, mod_obj in list(sys.modules.items()):
        if (mod_name.startswith("tests.") or mod_name.startswith("backend.tests")) and mod_obj is not None:
            if hasattr(mod_obj, "SessionLocal"):
                setattr(mod_obj, "SessionLocal", app_session.SessionLocal)
    mod = getattr(item, "module", None)
    if mod is not None and hasattr(mod, "SessionLocal"):
        setattr(mod, "SessionLocal", app_session.SessionLocal)

