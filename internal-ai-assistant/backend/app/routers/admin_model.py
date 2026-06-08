from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..admin_schemas import ModelConfig
from ..database import get_db
from ..models import User
from ..settings_service import get_model_config, set_setting
from .deps import audit, require_admin

router = APIRouter()


@router.get("/api/admin/model")
def get_model(db: Session = Depends(get_db), _: User = Depends(require_admin)):
    cfg = get_model_config(db)
    return {"base_url": cfg["base_url"], "model": cfg["model"], "api_key_set": bool(cfg["api_key"])}


@router.post("/api/admin/model/test")
def test_model(db: Session = Depends(get_db), _: User = Depends(require_admin)):
    cfg = get_model_config(db)
    if not cfg["api_key"]:
        return {"ok": False, "message": "未配置 API Key"}
    try:
        from openai import OpenAI

        client = OpenAI(api_key=cfg["api_key"], base_url=cfg["base_url"] or "https://api.deepseek.com", timeout=120.0, max_retries=1)
        response = client.chat.completions.create(
            model=cfg["model"] or "deepseek-chat",
            messages=[{"role": "user", "content": "hi"}],
            max_tokens=5,
            temperature=0.0,
        )
        content = response.choices[0].message.content or ""
        return {"ok": True, "message": f"连接成功，模型返回：{content[:50]}"}
    except Exception as exc:
        return {"ok": False, "message": f"连接失败：{str(exc)[:200]}"}


@router.put("/api/admin/model")
def save_model(req: ModelConfig, db: Session = Depends(get_db), actor: User = Depends(require_admin)):
    if req.api_key:
        set_setting(db, "deepseek_api_key", req.api_key.strip())
    set_setting(db, "deepseek_base_url", req.base_url.strip() or "https://api.deepseek.com")
    set_setting(db, "deepseek_model", req.model.strip() or "deepseek-chat")
    audit(db, actor, "model.update", "setting", "deepseek_model", {"base_url": req.base_url, "model": req.model, "api_key_set": bool(req.api_key)})
    db.commit()
    return {"ok": True}
