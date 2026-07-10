import logging
import math

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from sqlalchemy import text

from .config import CORS_ORIGINS, FRONTEND_DIST_DIR, validate_security, warn_insecure_defaults
from .database import Base, SessionLocal, engine
from .ai_client import chat_answer, embed_texts
from .settings_service import get_embedding_config
from .vector_store import qdrant_health
from .html_pages import ADMIN_HTML, CHAT_HTML
from .routers.admin_documents import router as admin_documents_router
from .routers.admin_evaluation import router as admin_evaluation_router
from .routers.admin_feedback import router as admin_feedback_router
from .routers.admin_graph import router as admin_graph_router
from .routers.admin_groups import router as admin_groups_router
from .routers.admin_model import router as admin_model_router
from .routers.admin_operations import router as admin_operations_router
from .routers.admin_quality import router as admin_quality_router
from .routers.admin_routing_rules import router as admin_routing_rules_router
from .routers.admin_table_schema import router as admin_table_schema_router
from .routers.admin_tasks import router as admin_tasks_router
from .routers.admin_users import router as admin_users_router
from .routers.admin_vector import router as admin_vector_router
from .routers.admin_wiki import router as admin_wiki_router
from .routers.auth import router as auth_router
from .routers.chat import router as chat_router
from .routers.chat_api import router as chat_api_router
from .routers.documents import router as documents_router
from .task_service import bootstrap_default_admin, initialize_runtime_schema, start_task_worker

app = FastAPI(title="内部 AI 问答助手", version="0.9.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    """添加安全响应头，防御常见 Web 攻击。"""
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    # CSP：允许同源和 data: URI（Markdown 图片内联），阻止其他外部资源
    response.headers["Content-Security-Policy"] = "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; script-src 'self'"
    return response
app.include_router(auth_router)
app.include_router(chat_router)
app.include_router(chat_api_router)
app.include_router(documents_router)
app.include_router(admin_model_router)
app.include_router(admin_operations_router)
app.include_router(admin_routing_rules_router)
app.include_router(admin_vector_router)
app.include_router(admin_wiki_router)
app.include_router(admin_table_schema_router)
app.include_router(admin_quality_router)
app.include_router(admin_tasks_router)
app.include_router(admin_evaluation_router)
app.include_router(admin_feedback_router)
app.include_router(admin_graph_router)
app.include_router(admin_groups_router)
app.include_router(admin_users_router)
app.include_router(admin_documents_router)

def frontend_index_response():
    """Serve the built Vue SPA when available; otherwise keep backend HTML as fallback."""
    index_path = FRONTEND_DIST_DIR / "index.html"
    if index_path.is_file():
        return FileResponse(index_path)
    return None


@app.get("/assets/{asset_path:path}", include_in_schema=False)
def frontend_asset(asset_path: str):
    asset_file = (FRONTEND_DIST_DIR / "assets" / asset_path).resolve()
    assets_root = (FRONTEND_DIST_DIR / "assets").resolve()
    if not asset_file.is_relative_to(assets_root) or not asset_file.is_file():
        raise HTTPException(status_code=404, detail="Frontend asset not found")
    return FileResponse(asset_file)

# 日志：输出到 stdout，由 Docker / systemd 统一收集
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
logger = logging.getLogger("ai-assistant")


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """全局未处理异常兜底：记录日志并返回 500，避免敏感信息泄露。"""
    logger.error(
        "未处理异常 | path=%s method=%s client=%s",
        request.url.path,
        request.method,
        request.client.host if request.client else "unknown",
        exc_info=exc,
    )
    return JSONResponse(
        status_code=500,
        content={"detail": "服务器内部错误，已记录日志"},
    )


def ensure_runtime_schema() -> None:
    """Backward-compatible alias for existing QA/maintenance scripts."""
    initialize_runtime_schema()


@app.on_event("startup")
def startup():
    validate_security()
    for warning in warn_insecure_defaults():
        logger.warning("安全告警 | %s", warning)
    Base.metadata.create_all(bind=engine)
    initialize_runtime_schema()
    bootstrap_default_admin()
    start_task_worker()


@app.get("/", include_in_schema=False)
def root():
    return RedirectResponse("/chat")


@app.get("/login", include_in_schema=False)
def login_page():
    spa_response = frontend_index_response()
    if spa_response is not None:
        return spa_response
    return RedirectResponse("/chat")


@app.get("/chat", include_in_schema=False)
def chat_page():
    spa_response = frontend_index_response()
    if spa_response is not None:
        return spa_response
    return HTMLResponse(CHAT_HTML)


@app.get("/admin", include_in_schema=False)
def admin_page():
    spa_response = frontend_index_response()
    if spa_response is not None:
        return spa_response
    return HTMLResponse(ADMIN_HTML)


@app.get("/api/health")
def health():
    return {"ok": True, "version": "0.9.0"}


@app.get("/api/ready")
def readiness():
    components: dict[str, dict] = {}
    embedding_config: dict = {}
    db = None
    try:
        db = SessionLocal()
        db.execute(text("SELECT 1"))
        embedding_config = get_embedding_config(db)
        components["database"] = {"ok": True}
    except Exception:
        logger.warning("就绪检查失败 | component=database", exc_info=True)
        components["database"] = {"ok": False}
    finally:
        if db is not None:
            db.close()

    try:
        qdrant = qdrant_health()
        qdrant_required = bool(qdrant.get("qdrant_enabled"))
        qdrant_ready = bool(qdrant.get("qdrant_ready")) if qdrant_required else True
        components["qdrant"] = {
            "ok": qdrant_ready,
            "required": qdrant_required,
            "points_count": qdrant.get("points_count"),
            "dimension": qdrant.get("vector_size"),
        }
    except Exception:
        logger.warning("就绪检查失败 | component=qdrant", exc_info=True)
        components["qdrant"] = {"ok": False, "required": True, "points_count": None, "dimension": None}

    provider = str(embedding_config.get("provider") or "local").lower()
    model = str(embedding_config.get("model") or "local-hash")
    embedding_dimension = None
    try:
        if provider in {"openai", "openai-compatible", "remote"}:
            if not embedding_config.get("api_key") or not model:
                raise RuntimeError("remote embedding configuration is incomplete")
        vectors = embed_texts(["readiness probe"], strict=True, timeout=15.0)
        if len(vectors) != 1 or not vectors[0]:
            raise RuntimeError("embedding probe returned no vector")
        if any(not isinstance(value, (int, float)) or not math.isfinite(value) for value in vectors[0]):
            raise RuntimeError("embedding probe returned invalid values")
        embedding_dimension = len(vectors[0])
        qdrant_dimension = components["qdrant"].get("dimension")
        if components["qdrant"].get("ok") and qdrant_dimension and embedding_dimension != qdrant_dimension:
            raise RuntimeError("embedding and Qdrant dimensions do not match")
        components["embedding"] = {
            "ok": True,
            "provider": provider,
            "model": model,
            "dimension": embedding_dimension,
        }
    except Exception:
        logger.warning("就绪检查失败 | component=embedding provider=%s model=%s", provider, model, exc_info=True)
        components["embedding"] = {
            "ok": False,
            "provider": provider,
            "model": model,
            "dimension": embedding_dimension,
        }

    ready = all(component.get("ok") for component in components.values())
    return JSONResponse(
        status_code=200 if ready else 503,
        content={"ok": ready, "status": "ready" if ready else "degraded", "version": "0.9.0", "components": components},
    )


