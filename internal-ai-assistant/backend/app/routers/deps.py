import json
import uuid
from typing import Optional

from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import AuditLog, User
from ..security import decode_token

security = HTTPBearer(auto_error=False)


def new_id() -> str:
    return str(uuid.uuid4())


def row_to_user(user: User) -> dict:
    approved_at = getattr(user, "approved_at", None)
    return {
        "id": user.id,
        "username": user.username,
        "is_admin": user.is_admin,
        "is_active": getattr(user, "is_active", True),
        "approval_status": getattr(user, "approval_status", "approved") or "approved",
        "approval_note": getattr(user, "approval_note", "") or "",
        "approved_by_username": getattr(user, "approved_by_username", "") or "",
        "approved_at": approved_at.isoformat() if approved_at else None,
        "groups": [{"id": g.id, "name": g.name} for g in user.groups],
    }


def parse_json_list(value: str) -> list:
    try:
        parsed = json.loads(value or "[]")
        return parsed if isinstance(parsed, list) else []
    except Exception:
        return []


LOW_CONFIDENCE_THRESHOLD = 0.35


def normalized_score(value) -> float | None:
    try:
        if value is None or value == "":
            return None
        score = float(value)
    except (TypeError, ValueError):
        return None
    if score > 1:
        score = score / 100.0 if score <= 100 else 1.0
    return max(0.0, min(score, 1.0))


def require_user(db: Session = Depends(get_db), cred: Optional[HTTPAuthorizationCredentials] = Depends(security)) -> User:
    if not cred:
        raise HTTPException(status_code=401, detail="请先登录")
    try:
        payload = decode_token(cred.credentials)
        user = db.get(User, payload.get("sub"))
    except Exception as exc:
        raise HTTPException(status_code=401, detail="登录已失效，请重新登录") from exc
    if not user:
        raise HTTPException(status_code=401, detail="用户不存在")
    if not getattr(user, "is_active", True):
        raise HTTPException(status_code=403, detail="账号已被停用，请联系管理员")
    return user


def require_admin(user: User = Depends(require_user)) -> User:
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="需要管理员权限")
    return user


def audit(db: Session, actor: Optional[User], action: str, resource_type: str = "", resource_id: str = "", detail: Optional[dict] = None):
    db.add(
        AuditLog(
            id=new_id(),
            actor_user_id=actor.id if actor else None,
            actor_username=actor.username if actor else "system",
            action=action,
            resource_type=resource_type,
            resource_id=resource_id or "",
            detail_json=json.dumps(detail or {}, ensure_ascii=False),
        )
    )
