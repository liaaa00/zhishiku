from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..admin_schemas import GroupCreate, GroupUpdate
from ..database import get_db
from ..models import Group, User
from .deps import audit, new_id, require_admin

router = APIRouter()


@router.get("/api/admin/groups")
def list_groups(db: Session = Depends(get_db), _: User = Depends(require_admin)):
    groups = db.execute(select(Group).order_by(Group.created_at.desc())).scalars().all()
    return [{"id": g.id, "name": g.name} for g in groups]


@router.post("/api/admin/groups")
def create_group(req: GroupCreate, db: Session = Depends(get_db), actor: User = Depends(require_admin)):
    name = req.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="请输入岗位组名称")
    if db.execute(select(Group).where(Group.name == name)).scalar_one_or_none():
        raise HTTPException(status_code=400, detail="岗位组已存在")
    group = Group(id=new_id(), name=name)
    db.add(group)
    db.flush()
    audit(db, actor, "group.create", "group", group.id, {"name": group.name})
    db.commit()
    return {"id": group.id, "name": group.name}


@router.put("/api/admin/groups/{group_id}")
def update_group(group_id: str, req: GroupUpdate, db: Session = Depends(get_db), actor: User = Depends(require_admin)):
    group = db.get(Group, group_id)
    if not group:
        raise HTTPException(status_code=404, detail="岗位组不存在")
    name = req.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="请输入岗位组名称")
    if db.execute(select(Group).where(Group.name == name, Group.id != group_id)).scalar_one_or_none():
        raise HTTPException(status_code=400, detail="岗位组已存在")
    group.name = name
    audit(db, actor, "group.update", "group", group.id, {"name": group.name})
    db.commit()
    return {"id": group.id, "name": group.name}


@router.delete("/api/admin/groups/{group_id}")
def delete_group(group_id: str, db: Session = Depends(get_db), actor: User = Depends(require_admin)):
    group = db.get(Group, group_id)
    if not group:
        raise HTTPException(status_code=404, detail="岗位组不存在")
    if group.users:
        raise HTTPException(status_code=400, detail="该岗位组仍有关联员工，不能直接删除")
    if group.documents:
        raise HTTPException(status_code=400, detail="该岗位组仍有关联文档，不能直接删除")
    name = group.name
    db.delete(group)
    audit(db, actor, "group.delete", "group", group_id, {"name": name})
    db.commit()
    return {"ok": True}
