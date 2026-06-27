import hashlib
from datetime import datetime, timedelta, timezone
from typing import Any

import bcrypt
import jwt

from .config import JWT_ALGORITHM, JWT_SECRET

TOKEN_EXPIRE_MINUTES = 24 * 60
TOKEN_REFRESH_WINDOW_MINUTES = 60


def hash_password(password: str) -> str:
    """使用 bcrypt 生成密码哈希。"""
    return bcrypt.hashpw(
        password.encode("utf-8"),
        bcrypt.gensalt(),
    ).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    """验证密码。先尝试 bcrypt，失败则回退到旧 SHA256 格式。"""
    try:
        return bcrypt.checkpw(
            password.encode("utf-8"),
            password_hash.encode("utf-8"),
        )
    except ValueError:
        pass  # 不是有效的 bcrypt 哈希，尝试旧 SHA256 格式
    if is_legacy_hash(password_hash):
        return (
            hashlib.sha256(password.encode("utf-8")).hexdigest()
            == password_hash
        )
    return False


def is_legacy_hash(hash_str: str) -> bool:
    """检测是否为旧版 SHA256 哈希（64 位十六进制，非 bcrypt $2b$ 前缀）。"""
    return (
        len(hash_str) == 64
        and not hash_str.startswith("$2b$")
        and all(c in "0123456789abcdef" for c in hash_str.lower())
    )


def migrate_password_if_needed(user, plain_password: str, db) -> bool:
    """如果密码仍是旧 SHA256 格式，自动升级为 bcrypt。返回是否已迁移。"""
    if not is_legacy_hash(user.password_hash):
        return False
    user.password_hash = hash_password(plain_password)
    db.commit()
    return True


def create_token(payload: dict, expires_minutes: int = TOKEN_EXPIRE_MINUTES) -> str:
    data = payload.copy()
    data["exp"] = datetime.now(timezone.utc) + timedelta(minutes=expires_minutes)
    return jwt.encode(data, JWT_SECRET, algorithm=JWT_ALGORITHM)


def decode_token(token: str) -> dict:
    return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])


def token_expires_at(payload: dict[str, Any]) -> datetime | None:
    exp = payload.get("exp")
    if exp is None:
        return None
    try:
        return datetime.fromtimestamp(float(exp), timezone.utc)
    except (TypeError, ValueError, OSError):
        return None


def should_refresh_token(payload: dict[str, Any], window_minutes: int = TOKEN_REFRESH_WINDOW_MINUTES) -> bool:
    expires_at = token_expires_at(payload)
    if expires_at is None:
        return True
    return expires_at - datetime.now(timezone.utc) <= timedelta(minutes=window_minutes)
