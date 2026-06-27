# TECH_STACK.md — 技术栈规范

> 最后更新：2026-05-29  
> 合规承诺：本文件锁定当前项目实际使用的所有框架、运行时和核心依赖包的确切版本。  
> 任何 AI 或开发者不得在未更新本文档的情况下变更技术栈。新增依赖必须同步追加到此文件。

---

## 1. 运行时环境

| 层级 | 运行时 | 版本 | 备注 |
|------|--------|------|------|
| 后端语言 | Python | 3.12 | Dockerfile 固定 `python:3.12-slim` |
| 前端语言 | TypeScript | 5.9.3（锁定） | tsconfig `target: ES2020`, `module: ESNext` |
| 前端运行时 | Node.js | 22-alpine | Dockerfile 固定 `node:22-alpine` |
| Web 服务器 | Nginx | 1.27-alpine | 前端反向代理，静态资源缓存策略已配置 |
| 容器编排 | Docker Compose | v3 | 三服务：backend + frontend（隐式）+ qdrant |

---

## 2. 后端依赖（Python）

锁定版本来源：`backend/requirements.txt`。**所有版本均为精确锁定（==），无浮动范围。**

| 包名 | 锁定版本 | 用途 |
|------|----------|------|
| `fastapi` | 0.115.6 | Web 框架，API 路由 + 依赖注入 |
| `uvicorn[standard]` | 0.32.1 | ASGI 服务器 |
| `sqlalchemy` | 2.0.36 | ORM，数据库抽象层 |
| `pypdf` | 5.1.0 | PDF 文档文本提取 |
| `openai` | 1.58.1 | DeepSeek API 客户端（OpenAI-compatible） |
| `python-dotenv` | 1.0.1 | .env 环境变量加载 |
| `bcrypt` / `passlib[bcrypt]` | bcrypt 4.3.0 / passlib 1.7.4 | 密码哈希与旧 SHA256 哈希兼容迁移 |
| `PyJWT` | 2.10.1 | JWT 令牌签发与验证 |
| `python-multipart` | 0.0.19 | 文件上传解析（UploadFile） |

---

## 3. 前端依赖（TypeScript/Vue）

锁定版本来源：`frontend/package-lock.json`（lockfileVersion 3）。  
以下为 `node_modules` 中实际安装的精确版本：

| 包名 | 锁定版本 | 用途 |
|------|----------|------|
| `vue` | 3.5.35 | 前端框架（Composition API + `<script setup>`） |
| `vue-router` | 4.6.4 | SPA 路由 |
| `pinia` | 2.3.1 | 状态管理（已挂载但业务逻辑尚未使用 Store） |
| `element-plus` | 2.14.0 | UI 组件库（按需导入，无全量注册） |
| `axios` | 1.16.1 | HTTP 客户端（拦截器注入 JWT Bearer Token） |
| `@lark-base-open/js-sdk` | 1.0.2 | 飞书/多维表格 Base JS SDK，用于原生人员/部门选择组件框架 |
| `@element-plus/icons-vue` | 2.3.2 | Element Plus 图标（间接依赖） |

**开发依赖：**

| 包名 | 锁定版本 | 用途 |
|------|----------|------|
| `vite` | 6.4.3 | 构建工具 |
| `@vitejs/plugin-vue` | 5.2.4 | Vite Vue 插件 |
| `typescript` | 5.9.3 | TypeScript 编译器 |
| `@types/node` | 20.17.10 | Node.js 类型声明 |

---

## 4. 基础设施与外部服务

| 组件 | 版本/配置 | 用途 |
|------|-----------|------|
| Qdrant | `qdrant/qdrant:latest` | 向量数据库，存储文档片段向量索引 |
| SQLite | 内嵌（`app.db`） | 主业务数据库，文件位于 `backend/data/app.db` |
| DeepSeek | `deepseek-v4-flash`（`.env` 配置） | LLM 对话模型 + Vision OCR（图片识别） |
| 本地 Embedding | `local-hash`（默认） | 基于 MD5+Sparse 的轻量向量生成，无需外部 API |

---

## 5. 构建与部署

| 环节 | 方式 | 说明 |
|------|------|------|
| 前端构建 | `npm run build` → `vite build` | 输出到 `frontend/dist`，手动分包策略已配置 |
| 前端部署 | Nginx 静态文件 + 反向代理 | `/api/` → `backend:8000`，静态资源强缓存 |
| 后端构建 | `pip install -r requirements.txt` | Dockerfile `python:3.12-slim` |
| 后端部署 | `uvicorn app.main:app --host 0.0.0.0 --port 8000` | Docker 内端口映射 8080:8000 |
| 全栈启动 | `docker compose up -d --build` | 自动启动 backend + qdrant |

---

## 6. 禁止引入的依赖

以下依赖在当前架构中**明确禁止**，除非经过架构评审并更新本文档：

- ❌ 任何自建的组织架构同步库（如飞书 SDK 的 contact/v1 等）— 人员/部门选择必须走飞书原生前端组件
- ❌ 重型 ORM 替代品（如 Django ORM、Prisma）— 保持 SQLAlchemy
- ❌ 额外的状态管理库（如 Vuex）— 保持 Pinia
- ❌ CSS 框架（如 Tailwind CSS、Bootstrap）— 保持 Element Plus 内置样式 + scoped CSS
- ❌ 图表库（如 ECharts）— 当前无需数据可视化，评估后再决定

---

## 7. 版本歧义消除规则

1. **后端版本**：所有依赖以 `requirements.txt` 中的 `==` 为准。CI/CD 必须使用 `--no-deps` 以外的精确安装。
2. **前端版本**：以 `package-lock.json` 中实际 `node_modules` 的 `version` 字段为准。`package.json` 中的 `^` 范围仅为开发时的"可接受范围"提示。
3. **基础设施版本**：Qdrant 使用 `latest` 标签。首次部署后应固定到实际拉取的镜像 digest。
4. **Python 内置模块**：`hashlib`, `json`, `re`, `uuid`, `pathlib`, `threading`, `csv`, `xml`, `zipfile`, `mimetypes`, `urllib` 均使用 Python 3.12 标准库。
