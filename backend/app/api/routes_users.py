from datetime import datetime, timezone
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.security import (
    PLAN_CATALOG,
    RequestContext,
    current_admin,
    current_user,
    usage_today,
)
from app.db.models import UsageCounter, UserProfile
from app.db.session import get_db

router = APIRouter(prefix="/api/v1", tags=["Users & Subscriptions"])


@router.get("/me")
def get_my_profile(ctx: RequestContext = Depends(current_user)):
    """Perfil del usuario autenticado, plan vigente y consumo diario."""
    return {
        "user_id": ctx.user_id,
        "email": ctx.email,
        "role": ctx.role,
        "plan_code": ctx.plan_code,
        "auth_method": ctx.auth_method,
        "capabilities": vars(ctx.capabilities),
        "usage_today": {
            "match_analysis": usage_today(ctx.user_id),
            "limit": ctx.capabilities.daily_analysis_limit,
        },
    }


class UserUpdatePayload(BaseModel):
    role: Optional[Literal["USER", "ANALYST", "ADMIN"]] = None
    plan_code: Optional[Literal["FREE", "PREMIUM", "PRO"]] = None
    is_active: Optional[bool] = None


def _serialize(u: UserProfile) -> dict:
    return {
        "id": u.id,
        "email": u.email,
        "role": u.role,
        "plan_code": u.plan_code,
        "is_active": u.is_active,
        "created_at": u.created_at.isoformat() if u.created_at else None,
        "last_seen_at": u.last_seen_at.isoformat() if u.last_seen_at else None,
    }


@router.get("/admin/users")
def list_users(
    search: Optional[str] = Query(default=None, max_length=120),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    _admin: RequestContext = Depends(current_admin),
):
    """Lista usuarios registrados (solo ADMIN)."""
    q = db.query(UserProfile)
    if search:
        q = q.filter(UserProfile.email.ilike(f"%{search.strip().lower()}%"))
    total = q.count()
    items = q.order_by(UserProfile.created_at.desc()).offset(offset).limit(limit).all()
    return {"total": total, "items": [_serialize(u) for u in items], "plans": list(PLAN_CATALOG.keys())}


@router.patch("/admin/users/{user_id}")
def update_user(
    user_id: str,
    payload: UserUpdatePayload,
    db: Session = Depends(get_db),
    admin: RequestContext = Depends(current_admin),
):
    """Asigna rol, plan o estado de un usuario (solo ADMIN). Los cobros no están activos:
    la asignación de planes PREMIUM/PRO es manual."""
    user = db.get(UserProfile, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="Usuario no encontrado.")
    if admin.user_id == user_id and (payload.role not in (None, "ADMIN") or payload.is_active is False):
        raise HTTPException(status_code=400, detail="No puedes quitarte el rol ADMIN ni desactivar tu propia cuenta.")
    if payload.role is not None:
        user.role = payload.role
    if payload.plan_code is not None:
        user.plan_code = payload.plan_code
    if payload.is_active is not None:
        user.is_active = payload.is_active
    db.commit()
    return _serialize(user)


@router.get("/admin/usage")
def usage_summary(
    db: Session = Depends(get_db),
    _admin: RequestContext = Depends(current_admin),
):
    """Resumen de consumo del día (UTC) por usuario (solo ADMIN)."""
    today = datetime.now(timezone.utc).date()
    rows = db.query(UsageCounter).filter(UsageCounter.usage_date == today).order_by(UsageCounter.count.desc()).limit(200).all()
    return {
        "date": today.isoformat(),
        "items": [{"user_id": r.user_id, "metric": r.metric, "count": r.count} for r in rows],
    }
