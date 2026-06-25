from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..admin_schemas import ModelConfig
from ..database import get_db
from ..models import User
from ..settings_service import get_embedding_config, get_model_config, get_reranker_config, set_setting
from .deps import audit, require_admin

router = APIRouter()


@router.get("/api/admin/model")
def get_model(db: Session = Depends(get_db), _: User = Depends(require_admin)):
    cfg = get_model_config(db)
    embedding = get_embedding_config(db)
    reranker = get_reranker_config(db)
    provider = (embedding.get("provider") or "local").lower()
    embedding_ready = provider in {"openai", "openai-compatible", "remote"} and bool(embedding.get("api_key")) and bool(embedding.get("model"))
    return {
        "base_url": cfg["base_url"],
        "model": cfg["model"],
        "api_key_set": bool(cfg["api_key"]),
        "embedding": {
            "provider": provider,
            "base_url": embedding.get("base_url") or "",
            "model": embedding.get("model") or "local-hash",
            "api_key_set": bool(embedding.get("api_key")),
            "ready": embedding_ready,
            "using_local_hash": not embedding_ready,
            "warning": "当前使用 local-hash，本地可用但语义检索准确率有限。" if not embedding_ready else "已配置远程 embedding，建议重建向量库。",
        },
        "reranker": {
            "enabled": bool(reranker.get("enabled")),
            "model": reranker.get("model") or cfg["model"],
            "max_candidates": reranker.get("max_candidates") or 24,
            "ready": bool(reranker.get("enabled") and cfg["api_key"]),
            "warning": "Reranker 未启用，当前使用规则精排。" if not reranker.get("enabled") else "Reranker 已启用，将消耗额外模型调用。",
        },
    }


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


@router.post("/api/admin/model/embedding-test")
def test_embedding_model(db: Session = Depends(get_db), _: User = Depends(require_admin)):
    cfg = get_embedding_config(db)
    provider = (cfg.get("provider") or "local").lower()
    if provider not in {"openai", "openai-compatible", "remote"}:
        return {"ok": False, "message": "当前仍在使用 local-hash，请先配置远程 embedding。"}
    if not cfg.get("api_key"):
        return {"ok": False, "message": "未配置 embedding API Key。"}
    if not cfg.get("model"):
        return {"ok": False, "message": "未配置 embedding 模型名称。"}
    try:
        from openai import OpenAI

        client = OpenAI(api_key=cfg["api_key"], base_url=cfg.get("base_url") or None, timeout=30.0, max_retries=1)
        response = client.embeddings.create(model=cfg["model"], input=["embedding health check"])
        dim = len(response.data[0].embedding) if response.data else 0
        return {"ok": True, "message": f"Embedding 连接成功，向量维度：{dim}"}
    except Exception as exc:
        return {"ok": False, "message": f"Embedding 连接失败：{str(exc)[:200]}"}


@router.put("/api/admin/model")
def save_model(req: ModelConfig, db: Session = Depends(get_db), actor: User = Depends(require_admin)):
    if req.api_key:
        set_setting(db, "deepseek_api_key", req.api_key.strip())
    set_setting(db, "deepseek_base_url", req.base_url.strip() or "https://api.deepseek.com")
    set_setting(db, "deepseek_model", req.model.strip() or "deepseek-chat")
    if req.embedding_provider:
        set_setting(db, "embedding_provider", req.embedding_provider.strip().lower())
    if req.embedding_base_url:
        set_setting(db, "embedding_base_url", req.embedding_base_url.strip())
    if req.embedding_model:
        set_setting(db, "embedding_model", req.embedding_model.strip())
    if req.embedding_api_key:
        set_setting(db, "embedding_api_key", req.embedding_api_key.strip())
    set_setting(db, "reranker_enabled", "1" if req.reranker_enabled else "0")
    set_setting(db, "reranker_model", req.reranker_model.strip())
    set_setting(db, "reranker_max_candidates", str(max(4, min(int(req.reranker_max_candidates or 24), 60))))
    audit(db, actor, "model.update", "setting", "deepseek_model", {
        "base_url": req.base_url,
        "model": req.model,
        "api_key_set": bool(req.api_key),
        "embedding_provider": req.embedding_provider,
        "embedding_model": req.embedding_model,
        "embedding_api_key_set": bool(req.embedding_api_key),
        "reranker_enabled": bool(req.reranker_enabled),
        "reranker_model": req.reranker_model,
        "reranker_max_candidates": req.reranker_max_candidates,
    })
    db.commit()
    return {"ok": True}
