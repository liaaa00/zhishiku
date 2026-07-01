import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
REPO_DIR = BASE_DIR.parent
FRONTEND_DIST_DIR = Path(os.getenv("FRONTEND_DIST_DIR") or (REPO_DIR / "frontend" / "dist"))
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)
UPLOAD_DIR = DATA_DIR / "uploads"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
PAGEINDEX_DIR = DATA_DIR / "pageindex"
PAGEINDEX_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = DATA_DIR / "app.db"
DATABASE_URL = os.getenv("DATABASE_URL", f"sqlite:///{DB_PATH.as_posix()}")
INSECURE_JWT_SECRET = "please-change-this-secret"
JWT_SECRET = os.getenv("JWT_SECRET", INSECURE_JWT_SECRET)
JWT_ALGORITHM = "HS256"

# CORS 允许的来源列表，逗号分隔。生产部署时通过环境变量传入实际域名。
# 示例：CORS_ORIGINS=http://your-domain.com,https://your-domain.com
CORS_ORIGINS = [
    origin.strip()
    for origin in os.getenv("CORS_ORIGINS", "http://localhost:8080,http://localhost:5174").split(",")
    if origin.strip()
]

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL", "") or None
CHAT_MODEL = os.getenv("CHAT_MODEL", "deepseek-chat")

PAGEINDEX_ENABLED = os.getenv("PAGEINDEX_ENABLED", "1").lower() not in {"0", "false", "no", "off"}
PAGEINDEX_MIN_CHARS = int(os.getenv("PAGEINDEX_MIN_CHARS", "1"))
PAGEINDEX_REPO_PATH = os.getenv("PAGEINDEX_REPO_PATH", "").strip()

GRAPH_EXTRACTION_ENABLED = os.getenv("GRAPH_EXTRACTION_ENABLED", "1").lower() not in {"0", "false", "no", "off"}
GRAPH_AUTO_CONFIRM_THRESHOLD = float(os.getenv("GRAPH_AUTO_CONFIRM_THRESHOLD", "0.85"))
GRAPH_PENDING_THRESHOLD = float(os.getenv("GRAPH_PENDING_THRESHOLD", "0.60"))
GRAPH_MAX_CHUNKS_PER_DOCUMENT = int(os.getenv("GRAPH_MAX_CHUNKS_PER_DOCUMENT", "80"))
GRAPH_MAX_CHARS_PER_CHUNK = int(os.getenv("GRAPH_MAX_CHARS_PER_CHUNK", "3000"))

PDF_OCR_MAX_PAGES = int(os.getenv("PDF_OCR_MAX_PAGES", "20"))
PDF_OCR_MIN_TEXT_CHARS = int(os.getenv("PDF_OCR_MIN_TEXT_CHARS", "80"))
PDF_OCR_ZOOM = float(os.getenv("PDF_OCR_ZOOM", "2.0"))

# 文档上传限制：默认 200MB，可通过 MAX_UPLOAD_MB 调整。
MAX_UPLOAD_MB = int(os.getenv("MAX_UPLOAD_MB", "200"))
MAX_UPLOAD_BYTES = MAX_UPLOAD_MB * 1024 * 1024

# 向量库后端：local 使用 SQLite 内本地向量；qdrant 使用独立向量数据库。
VECTOR_BACKEND = os.getenv("VECTOR_BACKEND", "qdrant").lower()

# Embedding 生成方式：默认 local-hash；生产可改为 openai/openai-compatible。
EMBEDDING_PROVIDER = os.getenv("EMBEDDING_PROVIDER", "local").strip().lower()
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "local-hash").strip()
EMBEDDING_DIM = int(os.getenv("EMBEDDING_DIM", "512"))
EMBEDDING_API_KEY = os.getenv("EMBEDDING_API_KEY", OPENAI_API_KEY).strip()
EMBEDDING_BASE_URL = (os.getenv("EMBEDDING_BASE_URL", "") or OPENAI_BASE_URL or "").strip()
QDRANT_URL = os.getenv("QDRANT_URL", "http://localhost:6333")
QDRANT_API_KEY = os.getenv("QDRANT_API_KEY", "")
QDRANT_COLLECTION = os.getenv("QDRANT_COLLECTION", "internal_ai_chunks")

DEFAULT_ADMIN_USERNAME = os.getenv("DEFAULT_ADMIN_USERNAME", "admin")
INSECURE_ADMIN_PASSWORD = "change-this-admin-password"
DEFAULT_ADMIN_PASSWORD = os.getenv("DEFAULT_ADMIN_PASSWORD", INSECURE_ADMIN_PASSWORD)

APP_ENV = os.getenv("APP_ENV", "development").strip().lower()
IS_PRODUCTION = APP_ENV in {"production", "prod"}
REMOTE_EMBEDDING_PROVIDERS = {"openai", "openai-compatible", "remote"}
LOCAL_EMBEDDING_PROVIDERS = {"", "local", "local-hash"}


def validate_production_embedding() -> list[str]:
    """Return production embedding configuration problems."""
    if not IS_PRODUCTION:
        return []
    problems: list[str] = []
    if EMBEDDING_PROVIDER in LOCAL_EMBEDDING_PROVIDERS or EMBEDDING_MODEL.lower() == "local-hash":
        problems.append(
            "APP_ENV=production must use OpenAI-compatible embedding; set EMBEDDING_PROVIDER=openai-compatible and a real EMBEDDING_MODEL"
        )
    elif EMBEDDING_PROVIDER not in REMOTE_EMBEDDING_PROVIDERS:
        problems.append(
            "EMBEDDING_PROVIDER must be one of openai/openai-compatible/remote in production"
        )
    if not EMBEDDING_API_KEY:
        problems.append("EMBEDDING_API_KEY is required in production")
    if not EMBEDDING_MODEL or EMBEDDING_MODEL.lower() == "local-hash":
        problems.append("EMBEDDING_MODEL must be a remote embedding model in production")
    return problems


def validate_security() -> None:
    """生产环境（APP_ENV=production）下拒绝使用默认密钥/口令启动。"""
    if not IS_PRODUCTION:
        return
    problems = []
    if JWT_SECRET == INSECURE_JWT_SECRET:
        problems.append("JWT_SECRET 仍为默认值，请改为高强度随机密钥")
    if DEFAULT_ADMIN_PASSWORD == INSECURE_ADMIN_PASSWORD:
        problems.append("DEFAULT_ADMIN_PASSWORD 仍为默认值，请改为强口令")
    problems.extend(validate_production_embedding())
    if problems:
        raise RuntimeError("生产环境安全检查未通过：\n- " + "\n- ".join(problems))


def warn_insecure_defaults() -> list[str]:
    """非生产环境下，对仍在使用的默认密钥/口令发出告警（不阻断启动）。

    返回告警文案列表，调用方负责记录日志。生产环境由 validate_security() 直接拦截，
    此处对生产返回空列表以避免重复处理。
    """
    if IS_PRODUCTION:
        return []
    warnings: list[str] = []
    if JWT_SECRET == INSECURE_JWT_SECRET:
        warnings.append(
            "JWT_SECRET 仍为默认值 'please-change-this-secret'：该密钥公开可知，"
            "任何人可伪造任意用户（含管理员）的登录令牌。请设置环境变量 JWT_SECRET。"
        )
    if DEFAULT_ADMIN_PASSWORD == INSECURE_ADMIN_PASSWORD:
        warnings.append(
            "DEFAULT_ADMIN_PASSWORD 仍为默认值：管理员口令极易被猜中，请设置环境变量 DEFAULT_ADMIN_PASSWORD。"
        )
    return warnings
