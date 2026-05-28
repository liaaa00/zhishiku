import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)
UPLOAD_DIR = DATA_DIR / "uploads"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = DATA_DIR / "app.db"
DATABASE_URL = os.getenv("DATABASE_URL", f"sqlite:///{DB_PATH.as_posix()}")
JWT_SECRET = os.getenv("JWT_SECRET", "please-change-this-secret")
JWT_ALGORITHM = "HS256"

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL", "") or None
CHAT_MODEL = os.getenv("CHAT_MODEL", "deepseek-chat")

# 文档上传限制：默认 30MB，可通过 MAX_UPLOAD_MB 调整。
MAX_UPLOAD_MB = int(os.getenv("MAX_UPLOAD_MB", "30"))
MAX_UPLOAD_BYTES = MAX_UPLOAD_MB * 1024 * 1024

# 向量库后端：local 使用 SQLite 内本地向量；qdrant 使用独立向量数据库。
VECTOR_BACKEND = os.getenv("VECTOR_BACKEND", "qdrant").lower()

# Embedding 生成方式：默认 local-hash；生产可改为 openai/openai-compatible。
EMBEDDING_PROVIDER = os.getenv("EMBEDDING_PROVIDER", "local").lower()
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "local-hash")
EMBEDDING_DIM = int(os.getenv("EMBEDDING_DIM", "512"))
EMBEDDING_API_KEY = os.getenv("EMBEDDING_API_KEY", OPENAI_API_KEY)
EMBEDDING_BASE_URL = os.getenv("EMBEDDING_BASE_URL", "") or OPENAI_BASE_URL
QDRANT_URL = os.getenv("QDRANT_URL", "http://localhost:6333")
QDRANT_API_KEY = os.getenv("QDRANT_API_KEY", "")
QDRANT_COLLECTION = os.getenv("QDRANT_COLLECTION", "internal_ai_chunks")

DEFAULT_ADMIN_USERNAME = os.getenv("DEFAULT_ADMIN_USERNAME", "admin")
DEFAULT_ADMIN_PASSWORD = os.getenv("DEFAULT_ADMIN_PASSWORD", "change-this-admin-password")
