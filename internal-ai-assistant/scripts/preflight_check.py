from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENV_PATH = ROOT / ".env"
ENV_EXAMPLE_PATH = ROOT / ".env.example"
COMPOSE_PATH = ROOT / "docker-compose.yml"
BACKEND_DATA = ROOT / "backend" / "data"
UPLOADS_DIR = BACKEND_DATA / "uploads"
PAGEINDEX_DIR = BACKEND_DATA / "pageindex"
DB_PATH = BACKEND_DATA / "app.db"
FRONTEND_DIST = ROOT / "frontend" / "dist"
REAL_CASES = ROOT / "backend" / "tests" / "retrieval_eval_real_cases.json"

SECRET_KEYS = {"JWT_SECRET", "DEFAULT_ADMIN_PASSWORD", "OPENAI_API_KEY", "EMBEDDING_API_KEY", "QDRANT_API_KEY"}
INSECURE_VALUES = {
    "JWT_SECRET": "please-change-this-secret",
    "DEFAULT_ADMIN_PASSWORD": "change-this-admin-password",
}
PRODUCTION_EMBEDDING_PROVIDERS = {"openai", "openai-compatible", "remote"}


def parse_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip().lstrip("\ufeff")
        value = value.strip().strip('"').strip("'")
        values[key] = value
    return values


def mask(key: str, value: str) -> str:
    if key in SECRET_KEYS and value:
        return "***已设置***"
    return value or "<空>"


def ok(message: str) -> None:
    print(f"[OK] {message}")


def warn(message: str) -> None:
    print(f"[WARN] {message}")


def fail(message: str) -> None:
    print(f"[FAIL] {message}")


def main() -> int:
    failures: list[str] = []
    warnings: list[str] = []

    print("内部 AI 问答助手生产化预检（只读，不修改文件/数据库）")
    print(f"项目目录：{ROOT}")
    print("")

    if COMPOSE_PATH.exists():
        ok("docker-compose.yml 存在")
    else:
        failures.append("缺少 docker-compose.yml")
        fail("缺少 docker-compose.yml")

    example_env = parse_env(ENV_EXAMPLE_PATH)
    runtime_env = parse_env(ENV_PATH)
    if ENV_EXAMPLE_PATH.exists():
        ok(".env.example 存在")
    else:
        warnings.append("缺少 .env.example，后续部署交接困难")
        warn("缺少 .env.example，后续部署交接困难")

    if ENV_PATH.exists():
        ok(".env 存在")
    else:
        failures.append("缺少 .env，服务无法读取生产配置")
        fail("缺少 .env，服务无法读取生产配置")

    required_keys = [
        "APP_ENV",
        "DEFAULT_ADMIN_USERNAME",
        "DEFAULT_ADMIN_PASSWORD",
        "JWT_SECRET",
        "OPENAI_API_KEY",
        "OPENAI_BASE_URL",
        "CHAT_MODEL",
        "VECTOR_BACKEND",
        "QDRANT_URL",
        "QDRANT_COLLECTION",
        "EMBEDDING_PROVIDER",
        "EMBEDDING_MODEL",
        "CORS_ORIGINS",
        "MAX_UPLOAD_MB",
    ]
    print("\n环境变量检查：")
    for key in required_keys:
        value = runtime_env.get(key, "")
        if key not in runtime_env:
            if key in example_env:
                warnings.append(f".env 未显式设置 {key}，将依赖代码或 .env.example 约定")
                warn(f"{key}: 未显式设置")
            else:
                warnings.append(f".env.example 也未声明 {key}")
                warn(f"{key}: 未声明")
            continue
        if not value and key == "OPENAI_API_KEY":
            warnings.append("OPENAI_API_KEY 为空；聊天生成将无法调用大模型，除非已在管理后台另行配置模型 Key")
            warn("OPENAI_API_KEY: <空>，需要配置 LLM Key")
        elif not value and key in {"OPENAI_BASE_URL", "CHAT_MODEL"}:
            warnings.append(f"{key} 为空；请确认模型配置来源")
            warn(f"{key}: <空>")
        elif key in SECRET_KEYS:
            ok(f"{key}: {mask(key, value)}")
        else:
            ok(f"{key}: {mask(key, value)}")

    app_env = runtime_env.get("APP_ENV", "development").strip().lower()
    if app_env in {"production", "prod"}:
        ok("APP_ENV=production，将启用后端生产安全校验")
        for key, insecure in INSECURE_VALUES.items():
            if runtime_env.get(key) == insecure:
                failures.append(f"生产环境不能使用默认 {key}")
                fail(f"生产环境不能使用默认 {key}")
        if not runtime_env.get("OPENAI_API_KEY"):
            failures.append("生产环境缺少 OPENAI_API_KEY，聊天生成不可用")
            fail("生产环境缺少 OPENAI_API_KEY，聊天生成不可用")
        provider = runtime_env.get("EMBEDDING_PROVIDER", "local").strip().lower()
        model = runtime_env.get("EMBEDDING_MODEL", "local-hash").strip().lower()
        if provider not in PRODUCTION_EMBEDDING_PROVIDERS or model == "local-hash":
            failures.append("生产环境必须使用远程 embedding，不能使用 local-hash")
            fail("生产环境必须使用远程 embedding，不能使用 local-hash")
        if not runtime_env.get("EMBEDDING_API_KEY"):
            failures.append("生产环境缺少 EMBEDDING_API_KEY")
            fail("生产环境缺少 EMBEDDING_API_KEY")
    else:
        warnings.append("APP_ENV 不是 production；真实上线前应改为 production 并通过后端安全校验")
        warn("APP_ENV 不是 production；真实上线前应改为 production 并通过后端安全校验")

    cors = runtime_env.get("CORS_ORIGINS", "")
    if app_env in {"production", "prod"} and re.search(r"localhost|127\.0\.0\.1", cors):
        warnings.append("生产 CORS_ORIGINS 仍包含 localhost/127.0.0.1")
        warn("生产 CORS_ORIGINS 仍包含 localhost/127.0.0.1")

    print("\n持久化数据路径检查：")
    for label, path in [
        ("后端数据目录", BACKEND_DATA),
        ("上传文件目录", UPLOADS_DIR),
        ("PageIndex目录", PAGEINDEX_DIR),
    ]:
        if path.exists():
            ok(f"{label}: {path}")
        else:
            warnings.append(f"{label} 不存在，首次启动会创建：{path}")
            warn(f"{label} 不存在，首次启动会创建：{path}")
    if DB_PATH.exists():
        ok(f"SQLite 数据库存在：{DB_PATH}")
    else:
        warnings.append("SQLite app.db 不存在；全新环境首次启动会初始化")
        warn("SQLite app.db 不存在；全新环境首次启动会初始化")

    print("\n构建/评测资产检查：")
    if FRONTEND_DIST.exists():
        ok("frontend/dist 存在，可作为前端构建产物参考")
    else:
        warnings.append("frontend/dist 不存在；部署前需运行 npm run build 或使用 Docker 构建")
        warn("frontend/dist 不存在；部署前需运行 npm run build 或使用 Docker 构建")
    if REAL_CASES.exists():
        ok("真实检索评测集存在：backend/tests/retrieval_eval_real_cases.json")
    else:
        warnings.append("缺少真实检索评测集，无法执行 24/24 回归门禁")
        warn("缺少真实检索评测集，无法执行 24/24 回归门禁")

    print("\n建议上线前执行：")
    print("1. docker compose up -d --build")
    print("2. 访问 /api/health、/chat、/admin")
    print("3. 后台上传真实样本文档并确认状态 ready/searchable")
    print("4. cd backend && python -X utf8 -m pytest tests/unit -q")
    print("5. cd backend && python -X utf8 tests/qa_retrieval_eval_runner.py --real-db --cases tests/retrieval_eval_real_cases.json")

    print("\n汇总：")
    print(f"失败项：{len(failures)}，警告项：{len(warnings)}")
    if failures:
        print("必须修复：")
        for item in failures:
            print(f"- {item}")
        return 1
    if warnings:
        print("需确认/补齐：")
        for item in warnings:
            print(f"- {item}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
