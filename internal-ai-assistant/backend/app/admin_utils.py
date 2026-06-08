from typing import List

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .models import Group, User


def ensure_password_strength(password: str, field_name: str = "密码"):
    if len(password or "") < 8:
        raise HTTPException(status_code=400, detail=f"{field_name}至少 8 位")


def active_admin_count(db: Session) -> int:
    return db.execute(select(func.count()).select_from(User).where(User.is_admin == True, User.is_active == True)).scalar_one()


def ensure_not_last_active_admin(db: Session, user: User, detail: str):
    if user.is_admin and getattr(user, "is_active", True) and active_admin_count(db) <= 1:
        raise HTTPException(status_code=400, detail=detail)


def load_groups_by_ids(db: Session, group_ids: List[str]) -> list[Group]:
    unique_ids = list(dict.fromkeys(group_ids or []))
    if not unique_ids:
        return []
    groups = db.execute(select(Group).where(Group.id.in_(unique_ids))).scalars().all()
    found_ids = {g.id for g in groups}
    missing_ids = [gid for gid in unique_ids if gid not in found_ids]
    if missing_ids:
        raise HTTPException(status_code=400, detail="岗位组不存在或已被删除")
    return groups
