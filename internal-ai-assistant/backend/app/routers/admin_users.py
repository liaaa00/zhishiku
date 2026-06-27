from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..admin_schemas import OkResponse, UserCreate, UserGroupsUpdate, UserPasswordReset, UserStatusUpdate, UserUpdate, UserPayload
from ..admin_utils import ensure_not_last_active_admin, ensure_password_strength, load_groups_by_ids
from ..database import get_db
from ..models import User
from ..security import hash_password
from .deps import audit, new_id, require_admin, row_to_user

router = APIRouter()


@router.get("/api/admin/users", response_model=list[UserPayload])
def list_users(db: Session = Depends(get_db), _: User = Depends(require_admin)):
    users = db.execute(select(User).order_by(User.created_at.desc())).scalars().all()
    return [row_to_user(u) for u in users]


@router.post("/api/admin/users", response_model=UserPayload)
def create_user(req: UserCreate, db: Session = Depends(get_db), actor: User = Depends(require_admin)):
    username = req.username.strip()
    if not username or not req.password:
        raise HTTPException(status_code=400, detail="请输入账号和密码")
    ensure_password_strength(req.password)
    if db.execute(select(User).where(func.lower(User.username) == username.lower())).scalar_one_or_none():
        raise HTTPException(status_code=400, detail="员工账号已存在")
    user = User(id=new_id(), username=username, password_hash=hash_password(req.password), is_admin=req.is_admin)
    user.groups = load_groups_by_ids(db, req.group_ids)
    db.add(user)
    db.flush()
    audit(db, actor, "user.create", "user", user.id, {"username": user.username, "is_admin": user.is_admin})
    db.commit()
    return row_to_user(user)


@router.put("/api/admin/users/{user_id}", response_model=UserPayload)
def update_user(user_id: str, req: UserUpdate, db: Session = Depends(get_db), actor: User = Depends(require_admin)):
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="员工不存在")
    username = req.username.strip()
    if not username:
        raise HTTPException(status_code=400, detail="请输入账号")
    if db.execute(select(User).where(func.lower(User.username) == username.lower(), User.id != user_id)).scalar_one_or_none():
        raise HTTPException(status_code=400, detail="员工账号已存在")
    if user.id == actor.id and not req.is_admin:
        raise HTTPException(status_code=400, detail="不能取消自己的管理员权限")
    if user.is_admin and not req.is_admin:
        ensure_not_last_active_admin(db, user, "不能取消最后一个可用管理员的权限")
    user.username = username
    user.is_admin = bool(req.is_admin)
    user.is_active = bool(req.is_active)
    user.groups = load_groups_by_ids(db, req.group_ids)
    audit(db, actor, "user.update", "user", user.id, {"username": user.username, "is_admin": user.is_admin, "is_active": user.is_active, "group_ids": req.group_ids})
    db.commit()
    return row_to_user(user)


@router.put("/api/admin/users/{user_id}/groups", response_model=UserPayload)
def update_user_groups(user_id: str, req: UserGroupsUpdate, db: Session = Depends(get_db), actor: User = Depends(require_admin)):
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="员工不存在")
    user.groups = load_groups_by_ids(db, req.group_ids)
    if req.is_admin is not None:
        if user.id == actor.id and not req.is_admin:
            raise HTTPException(status_code=400, detail="不能取消自己的管理员权限")
        if user.is_admin and not req.is_admin:
            ensure_not_last_active_admin(db, user, "不能取消最后一个可用管理员的权限")
        user.is_admin = req.is_admin
    audit(db, actor, "user.update_groups", "user", user.id, {"group_ids": req.group_ids, "is_admin": user.is_admin})
    db.commit()
    return row_to_user(user)


@router.post("/api/admin/users/{user_id}/reset-password", response_model=OkResponse)
def reset_user_password(user_id: str, req: UserPasswordReset, db: Session = Depends(get_db), actor: User = Depends(require_admin)):
    ensure_password_strength(req.password, "新密码")
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="员工不存在")
    user.password_hash = hash_password(req.password)
    audit(db, actor, "user.reset_password", "user", user.id, {"username": user.username})
    db.commit()
    return {"ok": True}


@router.put("/api/admin/users/{user_id}/status", response_model=UserPayload)
def update_user_status(user_id: str, req: UserStatusUpdate, db: Session = Depends(get_db), actor: User = Depends(require_admin)):
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="员工不存在")
    if user.id == actor.id and not req.is_active:
        raise HTTPException(status_code=400, detail="不能停用自己的账号")
    if not req.is_active:
        ensure_not_last_active_admin(db, user, "不能停用最后一个可用管理员")
    user.is_active = req.is_active
    audit(db, actor, "user.update_status", "user", user.id, {"is_active": user.is_active})
    db.commit()
    return row_to_user(user)


@router.delete("/api/admin/users/{user_id}", response_model=OkResponse)
def delete_user(user_id: str, db: Session = Depends(get_db), actor: User = Depends(require_admin)):
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="员工不存在")
    if user.id == actor.id:
        raise HTTPException(status_code=400, detail="不能删除自己的账号")
    ensure_not_last_active_admin(db, user, "不能删除最后一个可用管理员")
    username = user.username
    user.groups = []
    audit(db, actor, "user.delete", "user", user.id, {"username": username})
    db.delete(user)
    db.commit()
    return {"ok": True}
