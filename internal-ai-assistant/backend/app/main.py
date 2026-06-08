import logging

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from .config import CORS_ORIGINS, validate_security
from .database import Base, engine
from .ai_client import chat_answer, embed_texts
from .html_pages import ADMIN_HTML, CHAT_HTML
from .routers.admin_documents import router as admin_documents_router
from .routers.admin_feedback import router as admin_feedback_router
from .routers.admin_groups import router as admin_groups_router
from .routers.admin_model import router as admin_model_router
from .routers.admin_tasks import router as admin_tasks_router
from .routers.admin_users import router as admin_users_router
from .routers.admin_vector import router as admin_vector_router
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
app.include_router(auth_router)
app.include_router(chat_router)
app.include_router(chat_api_router)
app.include_router(documents_router)
app.include_router(admin_model_router)
app.include_router(admin_vector_router)
app.include_router(admin_tasks_router)
app.include_router(admin_feedback_router)
app.include_router(admin_groups_router)
app.include_router(admin_users_router)
app.include_router(admin_documents_router)

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
    Base.metadata.create_all(bind=engine)
    initialize_runtime_schema()
    bootstrap_default_admin()
    start_task_worker()


@app.get("/", include_in_schema=False)
def root():
    return RedirectResponse("/chat")


@app.get("/chat", response_class=HTMLResponse, include_in_schema=False)
def chat_page():
    return HTMLResponse(CHAT_HTML)


@app.get("/admin", response_class=HTMLResponse, include_in_schema=False)
def admin_page():
    return HTMLResponse(ADMIN_HTML)


@app.get("/api/health")
def health():
    return {"ok": True, "version": "0.9.0"}


