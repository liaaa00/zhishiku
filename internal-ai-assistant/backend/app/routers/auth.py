from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Response
from fastapi.security import HTTPAuthorizationCredentials
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import User
from ..security import create_token, decode_token, hash_password, is_legacy_hash, should_refresh_token, token_expires_at, verify_password
from .deps import audit, require_user, row_to_user, security

router = APIRouter()


class LoginRequest(BaseModel):
    username: str
    password: str


def auth_payload(user: User) -> dict:
    token = create_token({"sub": user.id})
    decoded = decode_token(token)
    expires_at = token_expires_at(decoded)
    return {
        "token": token,
        "expires_at": expires_at.isoformat() if expires_at else None,
        "user": row_to_user(user),
    }


@router.post("/api/auth/login")
def login(req: LoginRequest, db: Session = Depends(get_db)):
    user = db.execute(select(User).where(User.username == req.username)).scalar_one_or_none()
    if not user or not verify_password(req.password, user.password_hash):
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    if not getattr(user, "is_active", True):
        raise HTTPException(status_code=403, detail="账号已被停用，请联系管理员")
    # 自动升级旧 SHA256 哈希到 bcrypt
    if is_legacy_hash(user.password_hash):
        user.password_hash = hash_password(req.password)
    audit(db, user, "auth.login", "user", user.id)
    db.commit()
    return auth_payload(user)


@router.post("/api/auth/refresh")
def refresh_token(
    db: Session = Depends(get_db),
    cred: Optional[HTTPAuthorizationCredentials] = Depends(security),
):
    if not cred:
        raise HTTPException(status_code=401, detail="请先登录")
    try:
        payload = decode_token(cred.credentials)
    except Exception as exc:
        raise HTTPException(status_code=401, detail="登录已失效，请重新登录") from exc
    user = db.get(User, payload.get("sub"))
    if not user:
        raise HTTPException(status_code=401, detail="用户不存在")
    if not getattr(user, "is_active", True):
        raise HTTPException(status_code=403, detail="账号已被停用，请联系管理员")
    audit(db, user, "auth.refresh", "user", user.id)
    db.commit()
    return auth_payload(user)


@router.get("/api/me")
def me(
    response: Response,
    user: User = Depends(require_user),
    cred: Optional[HTTPAuthorizationCredentials] = Depends(security),
):
    if cred:
        try:
            payload = decode_token(cred.credentials)
            if should_refresh_token(payload):
                response.headers["X-Refresh-Token"] = create_token({"sub": user.id})
        except Exception:
            pass
    return row_to_user(user)
