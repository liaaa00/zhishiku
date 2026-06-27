# IMPLEMENTATION_PLAN.md — 逐步构建序列

> 最后更新：2026-06-27  
> 本文档将未来开发和优化拆解成**原始人都能看懂的原子化步骤**。  
> 每一步只修改或创建一个小功能，杜绝 AI 跨步或乱序构建。  
> 执行过程中请勿跳过任何步骤，也不要合并多步一起做。

---

## 使用说明

1. 每步执行前：阅读该步的「依赖」和「涉及文件」。
2. 每步执行中：只修改该步列出的文件，不碰其他文件。
3. 每步执行后：运行「验证方式」确认通过，然后勾选 `[ ]` 为 `[x]`。
4. 如果某步失败：停止执行，记录错误原因，不要强行继续下一步。

---

## 阶段 1：安全补丁（P0 — 必须立即修复）

### 步骤 1.1 — 升级密码哈希为 bcrypt

- [x] **依赖**：无
- [x] **涉及文件**：`backend/app/security.py`、`backend/requirements.txt`
- [x] **做什么**：
  1. 打开 `backend/app/security.py`
  2. 删除新密码写入路径中的 SHA256 快速哈希实现
  3. 改用 `bcrypt.hashpw(..., bcrypt.gensalt())` 生成带盐密码哈希
  4. 修改 `verify_password` 函数，优先使用 `bcrypt.checkpw()` 验证
  5. 保持 `create_token`、`decode_token` 的 JWT 行为不变
- [x] **验证方式**：运行 `python tests/qa_security_regression.py`，确认 bcrypt 用户可登录。
- [x] **注意**：新建用户、默认管理员和重置密码均写入 bcrypt 哈希；旧 SHA256 哈希由步骤 1.2 兼容迁移。

---

### 步骤 1.2 — 迁移现有用户的密码哈希

- [x] **依赖**：步骤 1.1 完成
- [x] **涉及文件**：
  - `backend/app/security.py`（旧哈希识别与迁移 helper）
  - `backend/app/routers/auth.py`（登录时自动升级）
  - `backend/tests/qa_security_regression.py`（新增回归）
- [x] **做什么**：
  1. 在 `security.py` 追加函数 `is_legacy_hash(hash_str: str) -> bool`：检查哈希是否为 64 位十六进制（SHA256 特征）且不以 `$2b$` 开头（bcrypt 特征）。
  2. 在 `security.py` 追加函数 `migrate_password_if_needed(user, plain_password, db)`：调用 `hash_password` 重新生成 bcrypt 哈希，更新 `user.password_hash` 并 commit。
  3. 修改登录路由：在 `verify_password` 成功后，调用 `is_legacy_hash` 检查。如果是旧格式 → 自动升级为 bcrypt。
- [x] **验证方式**：
  1. `python tests/qa_security_regression.py` 会用旧 SHA256 用户登录 → 成功。
  2. 登录后检查数据库中该用户的 `password_hash` → 已变为 bcrypt 前缀。
  3. 新 bcrypt 用户再次登录 → 成功。
- [x] **注意**：自动升级是零停机迁移的最佳实践。不需要写离线迁移脚本。

---

## 阶段 2：前端安全加固（P1）

### 步骤 2.1 — 添加全局 401 拦截

- [x] **依赖**：无
- [x] **涉及文件**：仅 `frontend/src/api.ts`
- [x] **做什么**：
  1. 打开 `frontend/src/api.ts`
  2. 在 `http.interceptors.response` 中添加错误拦截器
  3. 拦截逻辑：
     - 如果 `error.response.status === 401` → 清除 `localStorage` 中的 `token` 和 `user` → 跳转到 `/login`
     - 其他错误 → 正常 reject
  4. 确保拦截器只在非登录页触发（避免登录失败时的无限重定向）
- [x] **验证方式**：
  1. 登录后，手动将 localStorage 中的 token 改成无效字符串
  2. 在聊天页发送一条消息
  3. 应自动跳转到 `/login` 页面
- [x] **注意**：当前实现直接使用 `window.location.href = '/login'`，避免 axios 与 router 循环依赖。

---

### 步骤 2.2 — 添加路由守卫

- [x] **依赖**：步骤 2.1 完成（可选，但建议同时做）
- [x] **涉及文件**：仅 `frontend/src/router.ts`
- [x] **做什么**：
  1. 打开 `frontend/src/router.ts`
  2. 为每个路由添加 `meta.requiresAuth` 字段：
     - `/login` → `requiresAuth: false`
     - `/chat` → `requiresAuth: true`
     - `/admin` → `requiresAuth: true, requiresAdmin: true`
  3. 添加 `router.beforeEach` 全局守卫：
     - 未登录访问需登录页面 → 跳转 `/login`
     - 已登录访问 `/login` → 跳转 `/chat`
     - 非管理员访问 `/admin` → 跳转 `/chat`
- [x] **验证方式**：
  1. 清除 localStorage token → 手动输入 `/chat` URL → 应跳转到 `/login`
  2. 手动输入 `/admin` URL → 应跳转到 `/login`
  3. 用普通用户登录 → 手动输入 `/admin` URL → 应跳转到 `/chat`
- [x] **注意**：管理员判断使用 localStorage 中缓存的 user.is_admin。

---

## 阶段 3：飞书原生组件集成（P0 — 架构核心）

### 步骤 3.1 — 安装飞书 JS-SDK

- [x] **依赖**：无
- [x] **涉及文件**：
  - `frontend/package.json`
  - `frontend/package-lock.json`
- [x] **做什么**：
  1. 进入 `frontend/` 目录
  2. 运行 `npm install @lark-base-open/js-sdk`（或其他确定的飞书官方 npm 包）
  3. 确认安装后版本写入 `package.json` 的 `dependencies`
  4. 更新 `vite.config.ts` 的手动分包策略，将飞书 SDK 单独拆成 `vendor-feishu` chunk
  5. 更新 `docs/specs/TECH_STACK.md` — 在"前端依赖"表中追加新条目
- [x] **验证方式**：
  1. 运行 `npm audit --audit-level=high` → 0 vulnerabilities。
  2. 运行 `npm run build` → 产物中有 `vendor-feishu` chunk。
- [x] **注意**：已采用 npm 包 `@lark-base-open/js-sdk@1.0.2`，缺少真实飞书应用配置时走 mock 选择器框架。

---

### 步骤 3.2 — 改造管理员页面的"员工"Tab

- [x] **依赖**：步骤 3.1 完成
- [x] **涉及文件**：`frontend/src/views/admin/index.vue`、`frontend/src/feishuNative.ts`、`frontend/src/style.css`
- [x] **做什么**：
  1. 在"员工"Tab 的新增员工表单中：
     - 添加"从飞书选人"按钮，通过适配器取回人员 ID 并填入 username
     - 添加"从飞书选部门"按钮，通过适配器取回部门名称并匹配/创建本地岗位组
     - 保留密码输入框、岗位组多选下拉和管理员复选框
  2. `UserSelect` 选择的人员 → 取其 `open_id` 或 `user_id` 作为系统用户的 `username`
  3. `DepartmentSelect` 选择的部门 → 自动在系统中创建/匹配对应的岗位组（Group）
  4. **不将**飞书返回的姓名、部门全名、头像 URL 写入后端数据库
  5. 在没有真实飞书应用上下文时，使用 mock prompt 选择器验证端到端交互
- [x] **验证方式**：
  1. 点击"新增员工" → 可触发飞书选择框架或 mock 输入框
  2. 选择/输入一个飞书用户 → 其 open_id/user_id 自动填入用户名框
  3. 提交后 → 数据库中 users 表仅新增用户核心字段，无冗余元数据字段
- [x] **注意**：
  - 飞书 JS-SDK 通过动态 import 按需初始化，并单独拆入 `vendor-feishu` chunk
  - 当前真实原生选择器保留在适配器扩展点，未配置真实飞书应用时使用 mock 数据验证

---

### 步骤 3.3 — 确认无元数据泄露

- [x] **依赖**：步骤 3.2 完成
- [x] **涉及文件**：
  - `backend/app/models.py`（检查）
  - `backend/tests/qa_user_metadata_regression.py`（新增回归）
- [x] **做什么**：
  1. 检查 `User` 模型 → 确认仅有核心身份与状态字段
  2. 检查用户创建/更新 API → 确认请求体和响应体不包含姓名、部门等飞书元数据字段
  3. 检查 `/api/admin/users` 响应 → 确认仅返回 id, username, is_admin, is_active, groups
  4. 如果发现任何新增的元数据字段 → 删除
- [x] **验证方式**：
  1. 运行 `python tests/qa_user_metadata_regression.py` → 通过
  2. 回归断言 `/api/admin/users` 每个用户对象仅含允许字段
- [x] **注意**：此步是合规检查，确保"纯角色管理"模型不变。

---

## 阶段 4：后端架构优化（P1）

### 步骤 4.1 — 拆分 main.py（提取认证路由）

- [x] **依赖**：无
- [x] **涉及文件**：
  - `backend/app/routers/__init__.py`
  - `backend/app/routers/auth.py`
  - `backend/app/routers/deps.py`
  - `backend/app/main.py`
- [x] **做什么**：
  1. 创建 `backend/app/routers/` 目录和 `__init__.py`
  2. 创建 `routers/auth.py`，移动以下内容：
     - `LoginRequest` 模型
     - `POST /api/auth/login` 路由
     - `GET /api/me` 路由
  3. 创建 `routers/deps.py`，集中 `require_user`、`require_admin`、`audit`、`row_to_user` 等共享依赖
  4. 在 `main.py` 中导入并注册 `auth_router`
- [x] **验证方式**：运行 `python tests/qa_security_regression.py`，确认登录 API 与 `/api/me` 依赖链可用。
- [x] **注意**：路由拆分后 `main.py` 仅保留应用初始化、router 注册、HTML fallback 和 health check。

---

### 步骤 4.2 — 拆分 main.py（提取聊天路由）

- [x] **依赖**：步骤 4.1 完成
- [x] **涉及文件**：
  - `backend/app/routers/chat.py`
  - `backend/app/routers/chat_api.py`
  - `backend/app/main.py`
- [x] **做什么**：
  1. 创建 `routers/chat.py`，承载会话列表、会话详情、删除会话等历史会话 API
  2. 创建 `routers/chat_api.py`，承载 `POST /api/chat`、流式聊天、附件上传、反馈提交和后台检索测试 API
  3. 在 `main.py` 中注册 `chat_router` 和 `chat_api_router`
- [x] **验证方式**：运行现有 QA 回归（如 `qa_final_regression.py`、`qa_api_validation.py`）确认聊天、附件、反馈和引用链路正常。
- [x] **注意**：聊天主流程较大，已按会话管理与聊天执行拆成两个 router，降低 `main.py` 复杂度。

---

### 步骤 4.3 — 拆分 main.py（提取管理端路由）

- [x] **依赖**：步骤 4.2 完成
- [x] **涉及文件**：
  - `backend/app/routers/admin_users.py`
  - `backend/app/routers/admin_groups.py`
  - `backend/app/routers/admin_documents.py`
  - `backend/app/routers/admin_feedback.py`
  - `backend/app/routers/admin_model.py`
  - `backend/app/routers/admin_vector.py`
  - `backend/app/routers/admin_tasks.py`
  - `backend/app/routers/admin_table_schema.py`
  - `backend/app/main.py`
- [x] **做什么**：按功能域拆分管理端路由到用户、岗位组、文档、反馈、模型配置、向量库、后台任务和表格 schema 管理等文件。
- [x] **验证方式**：管理端 API 已被 `qa_user_metadata_regression.py`、`qa_table_schema_aliases_regression.py`、`qa_api_validation.py` 等回归覆盖。
- [x] **注意**：这是最复杂的一步，当前已完成多 router 拆分；`response_model` 统一化仍可作为后续低优先级 API 契约优化。

---

## 阶段 5：数据库工程化（P2）

### 步骤 5.1 — 引入 Alembic 并生成初始迁移

- [x] **依赖**：无
- [x] **涉及文件**：
  - `backend/requirements.txt`（追加 `alembic`）
  - `backend/alembic/` 目录
  - `backend/alembic.ini`
  - `backend/tests/qa_alembic_regression.py`（新增回归）
- [x] **做什么**：
  1. 安装 `alembic` 并添加到 `requirements.txt`
  2. 创建 `alembic.ini`、`alembic/env.py` 和迁移脚本模板
  3. 配置 `alembic.ini` 默认指向 SQLite，并在 `env.py` 中用 `app.config.DATABASE_URL` 覆盖运行时数据库 URL
  4. 配置 `alembic/env.py` 导入 `Base.metadata` 和 `app.models`
  5. 生成初始迁移 `20260627_0001_initial_schema.py`，快照当前 SQLAlchemy 模型表结构
  6. 运行 `alembic upgrade head` 与 `alembic check` 确认迁移执行成功且 schema 与 metadata 对齐
- [x] **验证方式**：
  1. `python tests/qa_alembic_regression.py` → 从空 SQLite 库执行 `alembic upgrade head`
  2. 校验所有核心表和 `alembic_version` 已创建
  3. 执行 `alembic check` → `No new upgrade operations detected`
- [x] **注意**：未修改现有业务表结构；`Base.metadata.create_all` 与运行时兼容补表逻辑暂保留，便于旧部署平滑过渡。

---

## 阶段 6：生产配置（P1）

### 步骤 6.1 — 收紧 CORS 配置

- [x] **依赖**：无
- [x] **涉及文件**：
  - `backend/app/config.py`
  - `backend/app/main.py`
  - `.env.example`
  - `backend/tests/qa_security_regression.py`（新增回归）
- [x] **做什么**：
  1. 在 `.env.example` 中追加 `CORS_ORIGINS=http://localhost:8080,http://localhost:5174`
  2. 在 `config.py` 中读取 `CORS_ORIGINS` 环境变量，解析为列表
  3. 修改 `main.py` 的 `CORSMiddleware` 配置，使用 `config.CORS_ORIGINS` 替代 `["*"]`
  4. 开发环境默认值保持允许内嵌后端页面 `http://localhost:8080` 与本项目前端 Vite 端口 `http://localhost:5174`
- [x] **验证方式**：
  1. `python tests/qa_security_regression.py` → `http://localhost:5174` 预检通过
  2. `python tests/qa_security_regression.py` → `http://evil.com` 预检返回 400 且无 `access-control-allow-origin`
- [x] **注意**：生产部署时通过环境变量传入实际域名。

---

## 进度追踪

| 阶段 | 步骤 | 状态 | 完成日期 |
|------|------|------|----------|
| 1 | 1.1 升级密码哈希为 bcrypt | 已完成 | 2026-06-27 |
| 1 | 1.2 迁移现有用户密码哈希 | 已完成 | 2026-06-27 |
| 2 | 2.1 添加全局 401 拦截 | 已完成 | 2026-06-16 |
| 2 | 2.2 添加路由守卫 | 已完成 | 2026-06-16 |
| 3 | 3.1 安装飞书 JS-SDK | 已完成 | 2026-06-27 |
| 3 | 3.2 改造管理员"员工"Tab | 已完成 | 2026-06-27 |
| 3 | 3.3 确认无元数据泄露 | 已完成 | 2026-06-27 |
| 4 | 4.1 拆分认证路由 | 已完成 | 2026-06-27 |
| 4 | 4.2 拆分聊天路由 | 已完成 | 2026-06-27 |
| 4 | 4.3 拆分管端路由 | 已完成 | 2026-06-27 |
| 5 | 5.1 引入 Alembic 迁移 | 已完成 | 2026-06-27 |
| 6 | 6.1 收紧 CORS 配置 | 已完成 | 2026-06-27 |
| 7 | 7.4 生产环境切换 OpenAI-compatible embedding 并补充检索质量评估 | 已完成 | 2026-06-27 |
