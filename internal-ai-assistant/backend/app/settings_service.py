from sqlalchemy.orm import Session

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
