from sqlalchemy.orm import Session

from .config import EMBEDDING_API_KEY, EMBEDDING_BASE_URL, EMBEDDING_MODEL, EMBEDDING_PROVIDER
from .models import Setting


def get_setting(db: Session, key: str, default: str = "") -> str:
    item = db.get(Setting, key)
    return item.value if item else default


def set_setting(db: Session, key: str, value: str):
    item = db.get(Setting, key)
    if item:
        item.value = value
    else:
        db.add(Setting(key=key, value=value))


def get_model_config(db: Session) -> dict:
    return {
        "api_key": get_setting(db, "deepseek_api_key", ""),
        "base_url": get_setting(db, "deepseek_base_url", "https://api.deepseek.com"),
        "model": get_setting(db, "deepseek_model", "deepseek-chat"),
    }


def get_embedding_config(db: Session | None = None) -> dict:
    provider_default = EMBEDDING_PROVIDER or "local"
    base_url_default = EMBEDDING_BASE_URL or ""
    model_default = EMBEDDING_MODEL or "local-hash"
    api_key_default = EMBEDDING_API_KEY or ""
    if db is None:
        return {
            "provider": provider_default,
            "base_url": base_url_default,
            "model": model_default,
            "api_key": api_key_default,
        }
    return {
        "provider": get_setting(db, "embedding_provider", provider_default),
        "base_url": get_setting(db, "embedding_base_url", base_url_default),
        "model": get_setting(db, "embedding_model", model_default),
        "api_key": get_setting(db, "embedding_api_key", api_key_default),
    }


def get_reranker_config(db: Session) -> dict:
    enabled_raw = get_setting(db, "reranker_enabled", "0").strip().lower()
    max_candidates_raw = get_setting(db, "reranker_max_candidates", "24")
    try:
        max_candidates = max(4, min(int(max_candidates_raw), 60))
    except ValueError:
        max_candidates = 24
    return {
        "enabled": enabled_raw in {"1", "true", "yes", "on"},
        "model": get_setting(db, "reranker_model", ""),
        "max_candidates": max_candidates,
    }
