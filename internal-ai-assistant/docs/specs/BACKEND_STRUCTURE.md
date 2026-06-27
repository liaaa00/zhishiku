# BACKEND_STRUCTURE.md — 后端与数据结构

> 最后更新：2026-05-29  
> 数据库引擎：SQLite（文件：`backend/data/app.db`）  
> ORM：SQLAlchemy 2.0.36（declarative_base）

---

## 1. 数据库表结构（13 张表）

### 1.1 `users` — 用户表

| 列名 | 类型 | 约束 | 说明 |
|------|------|------|------|
| `id` | String | PK | UUID，由 `uuid.uuid4()` 生成 |
| `username` | String(100) | UNIQUE, NOT NULL, INDEX | 登录用户名 |
| `password_hash` | String(255) | NOT NULL | SHA256(密码) 的十六进制（⚠️ 非 bcrypt） |
| `is_admin` | Boolean | NOT NULL, DEFAULT False | 管理员标记 |
| `is_active` | Boolean | NOT NULL, DEFAULT True | 账号启用/停用 |
| `created_at` | DateTime | NOT NULL, DEFAULT utcnow | 创建时间 |

**关系**：
- `groups` → M2M via `user_group_link` → `Group`

**重要规则**：
- 此表**不存储**姓名、部门名、工号、手机号、飞书 OpenID 等飞书已有的元数据。
- 人员身份仅以 `id`（UserID）与 `role_id`（GroupID）的映射关系存在。

---

### 1.2 `groups` — 岗位组表（角色组）

| 列名 | 类型 | 约束 | 说明 |
|------|------|------|------|
| `id` | String | PK | UUID |
| `name` | String(120) | UNIQUE, NOT NULL | 岗位组名称（如"HR"、"研发工程师"） |
| `created_at` | DateTime | NOT NULL, DEFAULT utcnow | 创建时间 |

**关系**：
- `users` → M2M via `user_group_link` → `User`
- `documents` → M2M via `document_group_link` → `Document`

---

### 1.3 `user_group_link` — 用户-岗位组关联表

| 列名 | 类型 | 约束 | 说明 |
|------|------|------|------|
| `user_id` | String | PK, FK → users.id ON DELETE CASCADE | 用户ID |
| `group_id` | String | PK, FK → groups.id ON DELETE CASCADE | 岗位组ID |

复合主键 `(user_id, group_id)`。

---

### 1.4 `documents` — 文档表

| 列名 | 类型 | 约束 | 说明 |
|------|------|------|------|
| `id` | String | PK | UUID |
| `title` | String(255) | NOT NULL | 文档标题（上传时取文件名 stem） |
| `filename` | String(255) | NOT NULL | 原始文件名 |
| `storage_path` | String(500) | NOT NULL | 服务器存储绝对路径 |
| `source_type` | String(20) | NOT NULL, DEFAULT "pdf" | `pdf` / `chat_pdf` / `chat_image` / `chat_txt` 等 |
| `created_by` | String | FK → users.id ON DELETE SET NULL, NULLABLE | 上传者ID |
| `created_at` | DateTime | NOT NULL, DEFAULT utcnow | 创建时间 |

**关系**：
- `groups` → M2M via `document_group_link` → `Group`
- `chunks` → 1:N → `DocumentChunk`（cascade delete）

---

### 1.5 `document_group_link` — 文档-岗位组权限关联表

| 列名 | 类型 | 约束 | 说明 |
|------|------|------|------|
| `document_id` | String | PK, FK → documents.id ON DELETE CASCADE | 文档ID |
| `group_id` | String | PK, FK → groups.id ON DELETE CASCADE | 岗位组ID |

---

### 1.6 `document_chunks` — 文档片段表

| 列名 | 类型 | 约束 | 说明 |
|------|------|------|------|
| `id` | String | PK | UUID |
| `document_id` | String | FK → documents.id ON DELETE CASCADE, INDEX, NOT NULL | 所属文档 |
| `page_number` | Integer | NULLABLE | 页码（PDF 有，TXT/MD 为 NULL） |
| `chunk_index` | Integer | NOT NULL | 片段序号（从 0 开始） |
| `content` | Text | NOT NULL | 片段文本内容 |
| `embedding_json` | Text | NOT NULL | JSON 序列化的向量（`List[float]`） |

---

### 1.7 `document_processing_status` — 文档处理状态表

| 列名 | 类型 | 约束 | 说明 |
|------|------|------|------|
| `document_id` | String | PK, FK → documents.id ON DELETE CASCADE | 文档ID |
| `user_id` | String | FK → users.id ON DELETE SET NULL, INDEX, NULLABLE | 上传者 |
| `status` | String(30) | NOT NULL, DEFAULT "pending" | `pending` / `processing` / `ready` / `failed` |
| `stage` | String(80) | NOT NULL, DEFAULT "uploaded" | 当前阶段描述 |
| `message` | Text | NOT NULL, DEFAULT "" | 状态消息 |
| `chunks` | Integer | NOT NULL, DEFAULT 0 | 已索引片段数 |
| `searchable` | Boolean | NOT NULL, DEFAULT False | 是否可检索 |
| `created_at` | DateTime | NOT NULL | 创建时间 |
| `updated_at` | DateTime | NOT NULL, ON UPDATE utcnow | 最后更新时间 |

---

### 1.8 `background_tasks` — 后台任务表

| 列名 | 类型 | 约束 | 说明 |
|------|------|------|------|
| `id` | String | PK | UUID |
| `task_type` | String(80) | NOT NULL, INDEX | `document_parse` / `document_reparse` / `chat_attachment_parse` |
| `document_id` | String | FK → documents.id ON DELETE CASCADE, INDEX, NULLABLE | 关联文档 |
| `status` | String(30) | NOT NULL, DEFAULT "pending", INDEX | `pending` / `running` / `success` / `failed` |
| `attempts` | Integer | NOT NULL, DEFAULT 0 | 重试次数 |
| `last_error` | Text | NOT NULL, DEFAULT "" | 最后一次错误信息 |
| `created_by` | String | FK → users.id ON DELETE SET NULL, NULLABLE | 创建者 |
| `created_at` | DateTime | NOT NULL | 创建时间 |
| `started_at` | DateTime | NULLABLE | 开始执行时间 |
| `finished_at` | DateTime | NULLABLE | 完成时间 |
| `updated_at` | DateTime | NOT NULL, ON UPDATE utcnow | 最后更新时间 |

---

### 1.9 `audit_logs` — 审计日志表

| 列名 | 类型 | 约束 | 说明 |
|------|------|------|------|
| `id` | String | PK | UUID |
| `actor_user_id` | String | FK → users.id ON DELETE SET NULL, INDEX, NULLABLE | 操作者ID |
| `actor_username` | String(100) | NOT NULL, DEFAULT "system" | 操作者用户名 |
| `action` | String(120) | NOT NULL, INDEX | 操作类型（如 `auth.login`、`user.create`） |
| `resource_type` | String(80) | NOT NULL, DEFAULT "" | 资源类型（`user`、`document`、`group` 等） |
| `resource_id` | String | NOT NULL, DEFAULT "" | 资源ID |
| `detail_json` | Text | NOT NULL, DEFAULT "{}" | JSON 格式的操作详情 |
| `created_at` | DateTime | NOT NULL | 操作时间 |

---

### 1.10 `chat_sessions` — 聊天会话表

| 列名 | 类型 | 约束 | 说明 |
|------|------|------|------|
| `id` | String | PK | UUID（前端可传入或自动生成） |
| `user_id` | String | FK → users.id ON DELETE SET NULL, NULLABLE | 所属用户 |
| `created_at` | DateTime | NOT NULL | 创建时间 |

---

### 1.11 `chat_messages` — 聊天消息表

| 列名 | 类型 | 约束 | 说明 |
|------|------|------|------|
| `id` | String | PK | UUID |
| `session_id` | String | FK → chat_sessions.id ON DELETE CASCADE, INDEX, NOT NULL | 所属会话 |
| `role` | String(20) | NOT NULL | `user` / `assistant` |
| `content` | Text | NOT NULL | 消息正文 |
| `sources_json` | Text | NOT NULL, DEFAULT "[]" | JSON 序列化的引用来源列表 |
| `created_at` | DateTime | NOT NULL | 发送时间 |

---

### 1.12 `feedback` — 用户反馈表

| 列名 | 类型 | 约束 | 说明 |
|------|------|------|------|
| `id` | String | PK | UUID |
| `user_id` | String | FK → users.id ON DELETE SET NULL, INDEX, NULLABLE | 反馈者ID |
| `username` | String(100) | NOT NULL, DEFAULT "" | 反馈者用户名 |
| `session_id` | String | FK → chat_sessions.id ON DELETE SET NULL, INDEX, NULLABLE | 关联会话 |
| `message_id` | String | FK → chat_messages.id ON DELETE SET NULL, INDEX, NULLABLE | 关联消息 |
| `rating` | String(30) | NOT NULL, DEFAULT "" | `helpful` / `unhelpful` |
| `category` | String(50) | NOT NULL, DEFAULT "other", INDEX | `incorrect` / `missing_source` / `not_helpful` / `other` |
| `content` | Text | NOT NULL | 反馈正文 |
| `question_snapshot` | Text | NOT NULL, DEFAULT "" | 提问快照 |
| `answer_snapshot` | Text | NOT NULL, DEFAULT "" | 回答快照 |
| `sources_json` | Text | NOT NULL, DEFAULT "[]" | 引用来源快照 |
| `status` | String(30) | NOT NULL, DEFAULT "new", INDEX | `new` / `reviewed` / `resolved` / `ignored` |
| `created_at` | DateTime | NOT NULL | 提交时间 |
| `reviewed_at` | DateTime | NULLABLE | 审核时间 |
| `review_note` | Text | NOT NULL, DEFAULT "" | 审核备注 |
| `admin_note` | Text | NOT NULL, DEFAULT "" | 管理员处理备注 |
| `handled_by_user_id` | String | FK → users.id ON DELETE SET NULL, INDEX, NULLABLE | 处理人ID |
| `handled_by_username` | String(100) | NOT NULL, DEFAULT "" | 处理人用户名 |
| `handled_at` | DateTime | NULLABLE | 处理时间 |

---

### 1.13 `settings` — 系统设置表（Key-Value）

| 列名 | 类型 | 约束 | 说明 |
|------|------|------|------|
| `key` | String(120) | PK | 设置键（如 `deepseek_api_key`） |
| `value` | Text | NOT NULL, DEFAULT "" | 设置值 |

**已知设置键**：
- `deepseek_api_key` — 模型 API Key
- `deepseek_base_url` — 模型接口地址
- `deepseek_model` — 对话模型名称

---

## 2. 核心数据流与权限模型

### 2.1 人员权限模型（角色管理）

```
User ──M2M── Group（岗位组）
```

- **不存储**：姓名、部门名、工号、手机号、邮箱、飞书 OpenID。
- **仅存储**：UserID ↔ GroupID 的映射。
- 用户的飞书元数据（姓名、部门）由**飞书原生前端组件** `DepartmentSelect` / `UserSelect` 在 UI 层实时获取和展示。
- **严禁后端自建组织架构同步逻辑**。

### 2.2 文档权限模型

```
Document ──M2M── Group（岗位组）
```

- 文档上传后可分配一个或多个岗位组。
- 用户只能检索到自己所在岗位组有权访问的文档。
- 管理员（`is_admin=True`）可查看所有托管文档。
- 个人附件（`source_type` 以 `chat_` 开头）仅上传者自己可见。

### 2.3 检索权限过滤

**Qdrant 路径**（`vector_store.py → permission_filter`）：
```
must: [
  { visibility == "personal" AND created_by == current_user_id }
  OR { visibility == "managed" AND group_ids 匹配 }
]
管理员额外：{ visibility == "managed" }（无条件）
```

**SQLite 回退路径**（`main.py → chat()`）：
- 相同逻辑，通过 SQL JOIN `document_group_link` 实现。

---

## 3. 完整 API 接口合约（40 个端点）

### 3.1 健康检查

| 方法 | 路径 | 认证 | 说明 |
|------|------|------|------|
| GET | `/api/health` | 无 | 返回 `{"ok": true, "version": "0.9.0"}` |

### 3.2 认证

| 方法 | 路径 | 认证 | 请求体 | 响应 |
|------|------|------|--------|------|
| POST | `/api/auth/login` | 无 | `LoginRequest { username, password }` | `{ token, user }` |
| GET | `/api/me` | JWT | — | `{ id, username, is_admin, is_active, groups }` |

### 3.3 聊天

| 方法 | 路径 | 认证 | 请求体/参数 | 说明 |
|------|------|------|-------------|------|
| GET | `/api/chat/sessions` | JWT | — | 列出当前用户的会话列表 |
| GET | `/api/chat/sessions/{session_id}` | JWT | — | 获取会话详情 + 消息列表 |
| DELETE | `/api/chat/sessions/{session_id}` | JWT | — | 删除会话及其消息 |
| POST | `/api/chat/attachments` | JWT | `multipart/form-data: file` | 上传聊天附件（PDF/DOCX/XLSX/CSV/TXT/MD/图片） |
| POST | `/api/chat` | JWT | `ChatRequest { question, session_id?, top_k }` | 发送问题，返回 `{ answer, session_id, message_id, sources, confidence, grounding_warning }` |
| POST | `/api/chat/feedback` | JWT | `FeedbackCreate { session_id?, message_id?, rating?, category?, feedback_category?, content }` | 提交用户反馈 |

### 3.4 文档访问（通用）

| 方法 | 路径 | 认证 | 说明 |
|------|------|------|------|
| GET | `/api/documents/{document_id}/view` | JWT | 下载/预览文档原文件（权限检查） |
| GET | `/api/documents/{document_id}/content` | JWT | 获取文档片段内容（支持 chunk_id, limit, include_content 参数） |
| GET | `/api/documents/{document_id}/meta` | JWT | 获取文档元数据 |
| GET | `/api/documents/status` | JWT | 列出文档处理状态（scope: all/chat/admin） |

### 3.5 管理端 — 岗位组

| 方法 | 路径 | 认证 | 说明 |
|------|------|------|------|
| GET | `/api/admin/groups` | Admin | 列出所有岗位组 |
| POST | `/api/admin/groups` | Admin | `GroupCreate { name }` 创建岗位组 |

### 3.6 管理端 — 用户

| 方法 | 路径 | 认证 | 说明 |
|------|------|------|------|
| GET | `/api/admin/users` | Admin | 列出所有用户 |
| POST | `/api/admin/users` | Admin | `UserCreate { username, password, is_admin, group_ids }` 创建用户 |
| PUT | `/api/admin/users/{user_id}/groups` | Admin | `UserGroupsUpdate { group_ids, is_admin? }` 更新用户岗位组和角色 |
| POST | `/api/admin/users/{user_id}/reset-password` | Admin | `UserPasswordReset { password }` 重置密码 |
| PUT | `/api/admin/users/{user_id}/status` | Admin | `UserStatusUpdate { is_active }` 启用/停用 |
| DELETE | `/api/admin/users/{user_id}` | Admin | 删除用户 |

### 3.7 管理端 — 文档

| 方法 | 路径 | 认证 | 说明 |
|------|------|------|------|
| GET | `/api/admin/documents` | Admin | 列出所有文档（含岗位组权限） |
| POST | `/api/admin/documents` | Admin | `multipart/form-data: file` 上传知识库文档 |
| GET | `/api/admin/documents/{document_id}/chunks` | Admin | 查看文档片段列表 |
| POST | `/api/admin/documents/{document_id}/reparse` | Admin | 重新解析文档（入后台队列） |
| DELETE | `/api/admin/documents/{document_id}` | Admin | 删除文档及其片段、权限 |
| PUT | `/api/admin/documents/{document_id}/permissions` | Admin | `DocumentPermissionUpdate { group_ids }` 更新文档岗位组权限 |

### 3.8 管理端 — 反馈

| 方法 | 路径 | 认证 | 说明 |
|------|------|------|------|
| GET | `/api/admin/feedback` | Admin | 列出所有反馈（支持 status/category 过滤） |
| GET | `/api/admin/feedback/{feedback_id}` | Admin | 获取单条反馈详情 |
| PUT | `/api/admin/feedback/{feedback_id}` | Admin | `FeedbackReview { status, review_note, admin_note }` 审核反馈 |

### 3.9 管理端 — 模型配置

| 方法 | 路径 | 认证 | 说明 |
|------|------|------|------|
| GET | `/api/admin/model` | Admin | 获取模型配置（api_key 仅返回是否已设置） |
| PUT | `/api/admin/model` | Admin | `ModelConfig { api_key, base_url, model }` 更新模型配置 |

### 3.10 管理端 — 向量库

| 方法 | 路径 | 认证 | 说明 |
|------|------|------|------|
| GET | `/api/admin/vector/status` | Admin | 获取向量库状态 |
| POST | `/api/admin/vector/reindex` | Admin | 全量重建 Qdrant 索引 |

### 3.11 管理端 — 后台任务

| 方法 | 路径 | 认证 | 说明 |
|------|------|------|------|
| GET | `/api/admin/tasks` | Admin | 列出后台任务（支持 limit） |
| POST | `/api/admin/tasks/{task_id}/retry` | Admin | 重试单个失败任务 |

### 3.12 管理端 — 审计日志

| 方法 | 路径 | 认证 | 说明 |
|------|------|------|------|
| GET | `/api/admin/audit-logs` | Admin | 列出审计日志（支持 limit） |

### 3.13 静态页面（SSR）

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/` | 重定向到 `/chat` |
| GET | `/chat` | 返回预渲染的聊天页面 HTML（内联 CSS/JS 的独立页面） |
| GET | `/admin` | 返回预渲染的管理端 HTML（内联 CSS/JS 的独立页面） |

---

## 4. 认证与授权机制

### 4.1 JWT Token

- **签发**：登录成功后签发，有效期 24 小时。
- **算法**：HS256，密钥来自 `JWT_SECRET` 环境变量。
- **Payload**：`{ sub: user.id, exp: timestamp }`
- **传递**：前端 Axios 拦截器自动注入 `Authorization: Bearer <token>`。

### 4.2 权限依赖注入

| 依赖函数 | 作用 |
|----------|------|
| `require_user` | 验证 JWT Token，返回 `User` 对象。Token 无效 → 401。 |
| `require_admin` | 在 `require_user` 基础上检查 `is_admin`。非管理员 → 403。 |

### 4.3 ⚠️ 已知安全隐患 / 后续优化

| 问题 | 严重程度 | 说明 |
|------|----------|------|
| Token 无刷新机制 | 🟡 中 | 24 小时到期后需重新登录，无 refresh token。 |
| 响应模型未统一 | 🟢 低 | 多数路由仍直接返回 `dict` / `list`，后续可补充 Pydantic `response_model` 稳定 API 契约。 |
| Qdrant 回退缺少显式告警 | 🟢 低 | Qdrant 不可用时可回退 SQLite 向量检索，但管理员侧缺少明确健康告警。 |
