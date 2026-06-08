from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import User
from ..security import create_token, hash_password, is_legacy_hash, verify_password
from .deps import audit, require_user, row_to_user

router = APIRouter()


class LoginRequest(BaseModel):
    username: str
    password: str


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
    return {"token": create_token({"sub": user.id}), "user": row_to_user(user)}


@router.get("/api/me")
def me(user: User = Depends(require_user)):
    return row_to_user(user)
