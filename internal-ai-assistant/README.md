# 内部AI问答机器人

这是一个专用内部问答系统。

## 启动

1. 在 `.env` 中填写 `OPENAI_API_KEY`（DeepSeek Key）
2. 运行：

```bash
docker compose up -d --build
```

Docker Compose 默认使用 `frontend`、`backend`、`postgres` 和 `qdrant`；可选的 `ollama` profile 仅绑定本机 `127.0.0.1:11434`。可通过环境变量 `FRONTEND_PORT` 调整前端入口端口；例如本机 `8080` 已被其他容器占用时，可先执行 PowerShell 命令 `$env:FRONTEND_PORT='8081'`，再运行 `docker compose up -d --build`。

如果你不想用 Docker，也可以直接：

```bash
cd backend
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

## 访问

- 聊天端：http://localhost:8080/chat
- 管理端：http://localhost:8080/admin

## 管理员初始化

首次启动会根据环境变量初始化管理员账号。请在生产环境设置 `DEFAULT_ADMIN_USERNAME` 和 `DEFAULT_ADMIN_PASSWORD`，不要在页面或文档中暴露默认密码。

## DeepSeek

- 对话模型：`.env` 中的 `CHAT_MODEL`
- 接口地址：`https://api.deepseek.com`
- 文档检索可用 local-hash 做基线；正式使用应配置真实语义 embedding（本地 Ollama 或外部 OpenAI-compatible 服务）

## 本地语义向量（Ollama）

Ollama 只替换 embedding 引擎，不新增索引体系；检索仍使用 Qdrant、Wiki-first 和知识图谱。首次使用先拉取模型：

```powershell
docker compose --profile ollama up -d ollama
docker compose exec ollama ollama pull bge-m3
```

在后台模型配置中填写 `openai-compatible`、`http://ollama:11434/v1`、`bge-m3` 和占位 API Key `ollama`。先执行 Embedding 连接测试，再执行“重建向量”；`bge-m3` 会把 Qdrant 集合安全重建为 1024 维。若连接或重建失败，保留原配置和集合，不要混用两种向量。

## 运行健康检查

`GET /api/health` 只检查应用进程存活，不访问外部依赖；`GET /api/ready` 会实际检查 PostgreSQL、Qdrant、当前 embedding 服务，并校验 embedding 与 Qdrant 的向量维度一致。任一依赖失败时，`/api/ready` 返回 HTTP 503。

监控系统建议每 5 分钟调用一次 `/api/ready`，请求超时设为 30 秒，连续两次非 200 后告警。不要把深度检查作为高频 Docker liveness probe，以免反复触发 embedding 推理。

```powershell
curl.exe --fail --max-time 30 http://localhost:8080/api/ready
```

Docker Compose 已为 PostgreSQL、Qdrant 和可选 Ollama 服务配置容器健康检查。Ollama 默认检查 `bge-m3`，如使用其他模型，可设置 `OLLAMA_EMBEDDING_MODEL`。

## 可选 PageIndex 兼容索引

默认检索链路使用 Wiki-first、Qdrant 和知识图谱，PageIndex 默认关闭，不参与文档解析或检索。只有超长 PDF / Markdown 的专项评测证明结构索引有稳定收益时，才建议安装并在 `.env` 中设置 `PAGEINDEX_ENABLED=1`。

```powershell
.\scripts\install-pageindex.ps1
```

官方 PageIndex 不是标准 pip 包；启用时通过 `PAGEINDEX_REPO_PATH` 指向其源码目录。

## 生产化/实际运行

真实上线或内部试运行前，先按以下文档执行：

- [生产化上线检查清单](docs/生产化上线检查清单.md)
- [部署运行手册](docs/部署运行手册.md)
- [真实知识库导入与验收流程](docs/真实知识库导入与验收流程.md)
- [业务评测集建设方案](docs/业务评测集建设方案.md)

只读预检命令：

```powershell
python -X utf8 scripts\preflight_check.py
```

上线前建议至少跑：

```powershell
cd backend
python -X utf8 -m pytest tests/unit -q
python -X utf8 tests/qa_retrieval_eval_runner.py --real-db --pipeline --cases tests/retrieval_eval_real_cases.json
python -X utf8 tests/qa_answer_eval_runner.py --real-db --pipeline
python -X utf8 tests/qa_answer_eval_runner.py --real-db --pipeline --llm
cd ..\frontend
npm run build
```

切换 OpenAI-compatible embedding 前，先在模型配置中通过 Embedding 连接测试。随后执行后台“重建向量”；该操作会用当前模型重新生成全部 chunk embedding、校验统一维度，再重建 Qdrant 集合，而不是重传旧向量。

## 说明

如果你后面希望我继续把前端做得更像公司内部助手，我可以再简化 UI。

## PostgreSQL migration

Docker Compose now uses PostgreSQL as the primary application database. Configure these variables in `.env` before first startup:

```env
POSTGRES_DB=internal_ai_assistant
POSTGRES_USER=internal_ai
POSTGRES_PASSWORD=replace-with-strong-postgres-password
DATABASE_URL=postgresql+psycopg://internal_ai:replace-with-strong-postgres-password@postgres:5432/internal_ai_assistant
```

To copy the existing SQLite `backend/data/app.db` into PostgreSQL, run after backing up the SQLite database:

```bash
docker compose --profile migration run --rm --build migrate-sqlite-to-postgres
```

The migration service mounts `backend/data/app.db` read-only, drops/recreates the PostgreSQL schema, and imports rows using the current SQLAlchemy models. After migration, use PostgreSQL as the source of truth; keep the SQLite backup only for rollback.
