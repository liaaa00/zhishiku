# IMPLEMENTATION_PLAN.md — 逐步构建序列

> 最后更新：2026-05-29  
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

- [ ] **依赖**：无
- [ ] **涉及文件**：仅 `backend/app/security.py`
- [ ] **做什么**：
  1. 打开 `backend/app/security.py`
  2. 删除 `hash_password` 函数中的 `hashlib.sha256` 实现
  3. 改用 `passlib.hash.bcrypt` 的 `hash()` 方法
  4. 修改 `verify_password` 函数，使用 `passlib.hash.bcrypt` 的 `verify()` 方法
  5. 不要修改文件中的其他任何函数（`create_token`, `decode_token`）
- [ ] **验证方式**：启动后端，用管理员账号登录。如果能正常登录 → 通过。
- [ ] **注意**：此步只替换加密方法。已存在的 SHA256 密码哈希将在步骤 1.2 处理。

---

### 步骤 1.2 — 迁移现有用户的密码哈希

- [ ] **依赖**：步骤 1.1 完成
- [ ] **涉及文件**：
  - `backend/app/security.py`（追加函数）
  - `backend/app/main.py`（修改 `login` 函数）
- [ ] **做什么**：
  1. 在 `security.py` 追加函数 `is_legacy_hash(hash_str: str) -> bool`：检查哈希是否为 64 位十六进制（SHA256 特征）且不以 `$2b$` 开头（bcrypt 特征）。
  2. 在 `security.py` 追加函数 `migrate_password(user, plain_password, db)`：调用 `hash_password` 重新生成 bcrypt 哈希，更新 `user.password_hash` 并 commit。
  3. 修改 `login` 路由：在 `verify_password` 成功后，调用 `is_legacy_hash` 检查。如果是旧格式 → 调用 `migrate_password` 自动升级。
- [ ] **验证方式**：
  1. 用旧管理员账号（SHA256 哈希）登录 → 应成功。
  2. 检查数据库中该用户的 `password_hash` → 应已变为 `$2b$` 开头。
  3. 用新密码再次登录 → 应成功。
- [ ] **注意**：自动升级是零停机迁移的最佳实践。不需要写离线迁移脚本。

---

## 阶段 2：前端安全加固（P1）

### 步骤 2.1 — 添加全局 401 拦截

- [ ] **依赖**：无
- [ ] **涉及文件**：仅 `frontend/src/api.ts`
- [ ] **做什么**：
  1. 打开 `frontend/src/api.ts`
  2. 在 `http.interceptors.response` 中添加错误拦截器
  3. 拦截逻辑：
     - 如果 `error.response.status === 401` → 清除 `localStorage` 中的 `token` → 跳转到 `/login`
     - 其他错误 → 正常 reject
  4. 确保拦截器只在非登录页触发（避免登录失败时的无限重定向）
- [ ] **验证方式**：
  1. 登录后，手动将 localStorage 中的 token 改成无效字符串
  2. 在聊天页发送一条消息
  3. 应自动跳转到 `/login` 页面
- [ ] **注意**：需要引入 `vue-router` 的 router 实例。参考当前 `api.ts` 和 `router.ts` 的导入方式。

---

### 步骤 2.2 — 添加路由守卫

- [ ] **依赖**：步骤 2.1 完成（可选，但建议同时做）
- [ ] **涉及文件**：仅 `frontend/src/router.ts`
- [ ] **做什么**：
  1. 打开 `frontend/src/router.ts`
  2. 为每个路由添加 `meta.requiresAuth` 字段：
     - `/login` → `requiresAuth: false`
     - `/chat` → `requiresAuth: true`
     - `/admin` → `requiresAuth: true, requiresAdmin: true`
  3. 添加 `router.beforeEach` 全局守卫：
     - 未登录访问需登录页面 → 跳转 `/login`
     - 已登录访问 `/login` → 跳转 `/chat`
     - 非管理员访问 `/admin` → 跳转 `/chat` 或显示提示
- [ ] **验证方式**：
  1. 清除 localStorage token → 手动输入 `/chat` URL → 应跳转到 `/login`
  2. 手动输入 `/admin` URL → 应跳转到 `/login`
  3. 用普通用户登录 → 手动输入 `/admin` URL → 应跳转或提示
- [ ] **注意**：管理员的判断需要调用 `/api/me` 或从 localStorage 读取缓存。

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

- [ ] **依赖**：无
- [ ] **涉及文件**：
  - 新建 `backend/app/routers/__init__.py`
  - 新建 `backend/app/routers/auth.py`
  - 修改 `backend/app/main.py`
- [ ] **做什么**：
  1. 创建 `backend/app/routers/` 目录和 `__init__.py`
  2. 创建 `routers/auth.py`，移动以下内容：
     - `LoginRequest` 模型
     - `POST /api/auth/login` 路由
     - `GET /api/me` 路由
     - `require_user` 依赖函数
     - `require_admin` 依赖函数
  3. 在 `main.py` 中导入并注册 `auth_router`
  4. 确保所有 import 路径正确（原有 `from .security import` 等）
- [ ] **验证方式**：
  1. 运行后端 → 登录 API 仍正常工作
  2. 用 curl 测试 `POST /api/auth/login` 和 `GET /api/me`
- [ ] **注意**：只移动代码不修改逻辑。每个提取的模块保持与原代码完全相同。

---

### 步骤 4.2 — 拆分 main.py（提取聊天路由）

- [ ] **依赖**：步骤 4.1 完成
- [ ] **涉及文件**：
  - 新建 `backend/app/routers/chat.py`
  - 修改 `backend/app/main.py`
- [ ] **做什么**：
  1. 创建 `routers/chat.py`，移动以下内容：
     - `ChatRequest` 模型
     - `POST /api/chat` 路由
     - `GET /api/chat/sessions` 路由
     - `GET /api/chat/sessions/{session_id}` 路由
     - `DELETE /api/chat/sessions/{session_id}` 路由
     - `POST /api/chat/attachments` 路由
     - `POST /api/chat/feedback` 路由
     - 相关的辅助函数（`session_payload`, `message_to_dict`, `serialize_sources` 等）
  2. 在 `main.py` 中注册 `chat_router`
- [ ] **验证方式**：
  1. 发送聊天消息 → 正常返回
  2. 上传附件 → 正常处理
  3. 提交反馈 → 正常保存
- [ ] **注意**：粒度要小，每次只移动一个逻辑分组。

---

### 步骤 4.3 — 拆分 main.py（提取管理端路由）

- [ ] **依赖**：步骤 4.2 完成
- [ ] **涉及文件**：
  - 新建 `backend/app/routers/admin_users.py`
  - 新建 `backend/app/routers/admin_documents.py`
  - 新建 `backend/app/routers/admin_feedback.py`
  - 新建 `backend/app/routers/admin_config.py`
  - 修改 `backend/app/main.py`
- [ ] **做什么**：按功能域拆分管理端路由到 4 个文件。
- [ ] **验证方式**：管理端所有 Tab 功能正常。
- [ ] **注意**：这是最复杂的一步，可分多次完成。

---

## 阶段 5：数据库工程化（P2）

### 步骤 5.1 — 引入 Alembic 并生成初始迁移

- [ ] **依赖**：无
- [ ] **涉及文件**：
  - `backend/requirements.txt`（追加 `alembic`）
  - 新建 `backend/alembic/` 目录
  - 新建 `backend/alembic.ini`
- [ ] **做什么**：
  1. 安装 `alembic` 并添加到 `requirements.txt`
  2. 运行 `alembic init alembic`
  3. 配置 `alembic.ini` 中的 `sqlalchemy.url` 指向 SQLite
  4. 配置 `alembic/env.py` 导入 `Base.metadata`
  5. 运行 `alembic revision --autogenerate -m "initial"` 生成初始迁移
  6. 运行 `alembic upgrade head` 确认迁移执行成功
- [ ] **验证方式**：
  1. 删除 `app.db`，运行 `alembic upgrade head` → 重新创建所有表
  2. 启动后端 → 所有功能正常
- [ ] **注意**：不要修改现有表结构，只生成当前结构的迁移快照。

---

## 阶段 6：生产配置（P1）

### 步骤 6.1 — 收紧 CORS 配置

- [ ] **依赖**：无
- [ ] **涉及文件**：
  - `backend/app/main.py`（行 48）
  - `.env` 和 `.env.example`（追加配置项）
- [ ] **做什么**：
  1. 在 `.env` 中追加 `CORS_ORIGINS=http://localhost:8080,http://localhost:5173`
  2. 在 `config.py` 中读取 `CORS_ORIGINS` 环境变量，解析为列表
  3. 修改 `main.py` 的 `CORSMiddleware` 配置，使用 `config.CORS_ORIGINS` 替代 `["*"]`
  4. 开发环境默认值保持宽松（`http://localhost:8080,http://localhost:5173`）
- [ ] **验证方式**：
  1. 从 `http://localhost:8080` 访问 → 正常
  2. 从 `http://evil.com`（用 curl 模拟 Origin header）→ 被 CORS 拒绝
- [ ] **注意**：生产部署时通过环境变量传入实际域名。

---

## 进度追踪

| 阶段 | 步骤 | 状态 | 完成日期 |
|------|------|------|----------|
| 1 | 1.1 升级密码哈希为 bcrypt | 待执行 | — |
| 1 | 1.2 迁移现有用户密码哈希 | 待执行 | — |
| 2 | 2.1 添加全局 401 拦截 | 已完成 | 2026-06-16 |
| 2 | 2.2 添加路由守卫 | 已完成 | 2026-06-16 |
| 3 | 3.1 安装飞书 JS-SDK | 已完成 | 2026-06-27 |
| 3 | 3.2 改造管理员"员工"Tab | 已完成 | 2026-06-27 |
| 3 | 3.3 确认无元数据泄露 | 已完成 | 2026-06-27 |
| 4 | 4.1 拆分认证路由 | 待执行 | — |
| 4 | 4.2 拆分聊天路由 | 待执行 | — |
| 4 | 4.3 拆分管端路由 | 待执行 | — |
| 5 | 5.1 引入 Alembic 迁移 | 待执行 | — |
| 6 | 6.1 收紧 CORS 配置 | 待执行 | — |
