from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.security import HTTPAuthorizationCredentials
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..admin_schemas import AuthResponse, UserPayload
from ..admin_utils import ensure_password_strength
from ..database import get_db
from ..models import User
from ..rate_limit import login_limiter
from ..security import create_token, decode_token, hash_password, is_legacy_hash, should_refresh_token, token_expires_at, verify_password
from .deps import audit, new_id, require_user, row_to_user, security

router = APIRouter()


class LoginRequest(BaseModel):
    username: str
    password: str


class RegisterRequest(BaseModel):
    username: str
    password: str


class RegisterResponse(BaseModel):
    ok: bool = True
    message: str
    username: str
    status: str = "pending_review"


def auth_payload(user: User) -> dict:
    token = create_token({"sub": user.id})
    decoded = decode_token(token)
    expires_at = token_expires_at(decoded)
    return {
        "token": token,
        "expires_at": expires_at.isoformat() if expires_at else None,
        "user": row_to_user(user),
    }


@router.post("/api/auth/register", response_model=RegisterResponse)
def register(req: RegisterRequest, request: Request, db: Session = Depends(get_db)):
    username = (req.username or "").strip()
    if not username or not req.password:
        raise HTTPException(status_code=400, detail="请输入账号和密码")
    if len(username) < 3 or len(username) > 100:
        raise HTTPException(status_code=400, detail="账号长度需为 3-100 位")
    ensure_password_strength(req.password)
    if db.execute(select(User).where(User.username.ilike(username))).scalar_one_or_none():
        raise HTTPException(status_code=400, detail="账号已存在，请直接登录或联系管理员")
    user = User(
        id=new_id(),
        username=username,
        password_hash=hash_password(req.password),
        is_admin=False,
        is_active=False,
        approval_status="pending",
        approval_note="",
    )
    db.add(user)
    db.flush()
    client_ip = request.client.host if request.client else "unknown"
    audit(db, None, "auth.register", "user", user.id, {"username": user.username, "client_ip": client_ip, "status": "pending_review"})
    db.commit()
    return {"ok": True, "message": "注册已提交，请等待管理员启用账号并分配权限", "username": user.username, "status": "pending_review"}


@router.post("/api/auth/login", response_model=AuthResponse)
def login(req: LoginRequest, request: Request, db: Session = Depends(get_db)):
    client_ip = request.client.host if request.client else "unknown"
    rate_key = f"{client_ip}:{req.username}"
    retry_after = login_limiter.retry_after(rate_key)
    if retry_after > 0:
        raise HTTPException(
            status_code=429,
            detail="登录尝试过于频繁，请稍后再试",
            headers={"Retry-After": str(retry_after)},
        )
    user = db.execute(select(User).where(User.username == req.username)).scalar_one_or_none()
    if not user or not verify_password(req.password, user.password_hash):
        login_limiter.register_failure(rate_key)
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    if not getattr(user, "is_active", True):
        login_limiter.register_failure(rate_key)
        raise HTTPException(status_code=403, detail="账号已被停用，请联系管理员")
    # 登录成功，清除失败计数
    login_limiter.reset(rate_key)
    # 自动升级旧 SHA256 哈希到 bcrypt
    if is_legacy_hash(user.password_hash):
        user.password_hash = hash_password(req.password)
    audit(db, user, "auth.login", "user", user.id)
    db.commit()
    return auth_payload(user)


@router.post("/api/auth/refresh", response_model=AuthResponse)
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


@router.get("/api/me", response_model=UserPayload)
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
