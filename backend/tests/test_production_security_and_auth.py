from datetime import datetime, timezone
import pytest
from fastapi import HTTPException

from app.api.routes_users import get_my_profile, list_users, update_user, UserUpdatePayload
from app.core.config import Settings
from app.core.security import (
    PLAN_CATALOG,
    RequestContext,
    decode_supabase_jwt,
    enforce_daily_analysis_quota,
    get_request_context,
    require_admin_role,
    require_authenticated_context,
)
from app.db.models import UserProfile
from app.db.session import SessionLocal
from app.main import health_check, readiness_check


def test_production_settings_validation():
    prod_bad = Settings(
        ENVIRONMENT="production",
        DATABASE_URL=None,
        SUPABASE_URL=None,
        CORS_ORIGINS="*",
        SEED_DEMO_DATA=True,
    )
    errors = prod_bad.validate_for_production()
    assert len(errors) >= 3
    assert any("PostgreSQL" in e for e in errors)
    assert any("SUPABASE_URL" in e for e in errors)
    assert any("CORS_ORIGINS" in e for e in errors)

    prod_good = Settings(
        ENVIRONMENT="production",
        DATABASE_URL="postgresql://user:pass@localhost:5432/sportpredict",
        SUPABASE_URL="https://example.supabase.co",
        CORS_ORIGINS="https://app.sportpredict.ai",
        SEED_DEMO_DATA=False,
    )
    assert prod_good.validate_for_production() == []


def test_dev_headers_rejected_in_production(monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "ENVIRONMENT", "production")
    monkeypatch.setattr(settings, "AUTH_ALLOW_DEV_HEADERS", True)

    ctx = get_request_context(x_user_role="ADMIN", x_user_plan="PRO")
    assert ctx.role == "ANONYMOUS"


def test_require_authenticated_and_admin_checks():
    ctx_anon = RequestContext(role="ANONYMOUS", plan_code="FREE", capabilities=PLAN_CATALOG["FREE"])
    ctx_user = RequestContext(role="USER", plan_code="PRO", capabilities=PLAN_CATALOG["PRO"])
    ctx_admin = RequestContext(role="ADMIN", plan_code="PRO", capabilities=PLAN_CATALOG["PRO"])

    with pytest.raises(HTTPException) as exc:
        require_authenticated_context(ctx_anon)
    assert exc.value.status_code == 401

    assert require_authenticated_context(ctx_user).role == "USER"

    with pytest.raises(HTTPException) as exc:
        require_admin_role(ctx_anon)
    assert exc.value.status_code == 401

    with pytest.raises(HTTPException) as exc:
        require_admin_role(ctx_user)
    assert exc.value.status_code == 403

    # Admin passes without error
    require_admin_role(ctx_admin)


def test_quota_enforcement_per_plan():
    db = SessionLocal()
    user_id = "test-quota-user-free-1"
    existing = db.get(UserProfile, user_id)
    if not existing:
        db.add(UserProfile(id=user_id, email="freeuser@test.com", role="USER", plan_code="FREE"))
        db.commit()

    ctx = RequestContext(
        role="USER",
        plan_code="FREE",
        capabilities=PLAN_CATALOG["FREE"],
        user_id=user_id,
        auth_method="jwt",
    )

    from app.db.models import UsageCounter
    today = datetime.now(timezone.utc).date()
    db.query(UsageCounter).filter(
        UsageCounter.user_id == user_id,
        UsageCounter.usage_date == today,
    ).delete()
    db.commit()
    db.close()

    r1 = enforce_daily_analysis_quota(ctx)
    assert r1["used"] == 1
    r2 = enforce_daily_analysis_quota(ctx)
    assert r2["used"] == 2
    r3 = enforce_daily_analysis_quota(ctx)
    assert r3["used"] == 3

    with pytest.raises(HTTPException) as exc_info:
        enforce_daily_analysis_quota(ctx)
    assert exc_info.value.status_code == 429
    assert "Límite diario" in exc_info.value.detail


def test_admin_user_routes():
    db = SessionLocal()
    admin_ctx = RequestContext(role="ADMIN", plan_code="PRO", capabilities=PLAN_CATALOG["PRO"], user_id="admin-1")
    user_ctx = RequestContext(role="USER", plan_code="FREE", capabilities=PLAN_CATALOG["FREE"], user_id="user-1", email="u1@test.com")

    # get_my_profile
    profile = get_my_profile(ctx=user_ctx)
    assert profile["email"] == "u1@test.com"
    assert profile["plan_code"] == "FREE"

    # list_users
    users_resp = list_users(search=None, limit=10, offset=0, db=db, _admin=admin_ctx)
    assert "items" in users_resp
    assert "total" in users_resp

    # update_user
    test_user_id = "test-updatable-user"
    if not db.get(UserProfile, test_user_id):
        db.add(UserProfile(id=test_user_id, email="test_up@test.com", role="USER", plan_code="FREE"))
        db.commit()

    updated = update_user(user_id=test_user_id, payload=UserUpdatePayload(plan_code="PREMIUM"), db=db, admin=admin_ctx)
    assert updated["plan_code"] == "PREMIUM"
    db.close()


def test_jwt_validation_invalid_token():
    with pytest.raises(Exception):
        decode_supabase_jwt("invalid.jwt.token")


def test_health_and_ready_endpoints():
    res_health = health_check()
    assert res_health["status"] == "ok"
    assert "version" in res_health

    res_ready = readiness_check()
    assert res_ready["status"] == "ready"
