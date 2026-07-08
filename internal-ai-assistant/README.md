# 内部AI问答机器人

这是一个专用内部问答系统。

## 启动

1. 在 `.env` 中填写 `OPENAI_API_KEY`（DeepSeek Key）
2. 运行：

```bash
docker compose up -d --build
```

Docker Compose 使用三服务部署形态：`frontend`（Nginx + Vue SPA）对外暴露 `8080`，`backend` 在内部网络提供 `8000` API，`qdrant` 提供向量库。可通过环境变量 `FRONTEND_PORT` 调整前端入口端口；例如本机 `8080` 已被其他容器占用时，可先执行 PowerShell 命令 `$env:FRONTEND_PORT='8081'`，再运行 `docker compose up -d --build`。

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
- 文档检索本地试用可使用 local-hash；生产环境必须配置远程 embedding

## PageIndex 高级结构索引

系统默认会为 PDF / Markdown 生成内置轻量结构树，并在聊天检索时与原有 chunk / Qdrant 检索混合使用。

如需启用官方 VectifyAI/PageIndex：

```powershell
.\scripts\install-pageindex.ps1
```

然后在 `.env` 中配置：

```env
PAGEINDEX_ENABLED=1
PAGEINDEX_REPO_PATH=D:\path\to\internal-ai-assistant\third_party\PageIndex
# 可选：强制继续使用内置轻量结构树
# PAGEINDEX_FORCE_LIGHTWEIGHT=1
```

官方 PageIndex 不是标准 pip 包，因此项目将其作为可选源码路径加载；未安装依赖或未配置路径时，会自动回退到内置轻量结构树，不影响原知识库使用。

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
python -X utf8 tests/qa_retrieval_eval_runner.py --real-db --cases tests/retrieval_eval_real_cases.json
cd ..\frontend
npm run build
```

## 说明

如果你后面希望我继续把前端做得更像公司内部助手，我可以再简化 UI。
