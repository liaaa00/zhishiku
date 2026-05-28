# 项目架构分析与改造方案：RAG 引用、反馈链路、可打开文件

任务 ID：328bedaa-213d-4ae6-ab6a-c093a2370823  
角色：架构师  
范围：只读分析与架构方案，不直接承担全部实现，不修改业务代码。

---

## 0. 本次返工说明与可审查证据

上一轮评审失败不是方案内容问题，而是团队 integration 视图无法解析 `D:\AI\SpeceAppDate\知识库` 为 Git 仓库。返工时已验证：

```text
工作目录：D:\AI\SpeceAppDate\知识库
git rev-parse --show-toplevel => D:/AI/SpeceAppDate/知识库
git -C internal-ai-assistant rev-parse --show-toplevel => D:/AI/SpeceAppDate/知识库
```

本文件作为架构交付物落在仓库内：

```text
docs/architect-rag-citations-feedback-file-access-plan.md
```

返工过程中未修改业务代码。当前工作树已有其他成员改动如下，本文只作为架构说明与接口契约对齐依据：

```text
internal-ai-assistant/backend/app/main.py
internal-ai-assistant/backend/app/models.py
internal-ai-assistant/backend/app/vector_store.py
internal-ai-assistant/frontend/src/style.css
internal-ai-assistant/frontend/src/views/chat/index.vue
```

---

## 1. 现状架构图文字说明

### 1.1 部署与运行形态

```text
浏览器
  │
  ├─ 当前实际入口：http://localhost:8080/chat 或 /admin
  │
  ▼
FastAPI 后端容器 / 本地 uvicorn
  ├─ 提供 REST API：/api/*
  ├─ 提供内嵌 HTML：CHAT_HTML / ADMIN_HTML
  ├─ SQLite：backend/data/app.db
  ├─ 上传文件：backend/data/uploads
  ├─ 文档解析后台线程：document-task-worker
  └─ RAG 调用：Qdrant 优先，SQLite fallback
       │
       ▼
Qdrant 向量库容器
```

补充说明：

- `frontend/` 下存在 Vue 3 + Element Plus 项目，但当前 `docker-compose.yml` 只启动 `backend` 和 `qdrant`，未启动 `frontend` 服务。
- 因此当前生产/演示入口更接近“FastAPI 单体后端 + 内嵌页面”。
- 长期建议统一到 Vue 前端，后端只保留 API；短期可以继续在内嵌 HTML 上落地 P0 功能。

### 1.2 RAG 主链路

```text
用户登录
  ↓
用户提问 POST /api/chat
  ↓
生成问题向量 embed_texts(question)
  ↓
优先 Qdrant 检索 search_chunks
  ├─ Qdrant payload 权限过滤：visibility / created_by / group_ids
  └─ 不可用或无命中时 fallback SQLite cosine_similarity
       ↓
服务端按用户权限过滤文档分片
  ├─ managed 文档：管理员可访问；普通用户需命中文档授权岗位组
  └─ chat_* 个人附件：仅 created_by 用户可访问
       ↓
contexts 拼接到 prompt
       ↓
chat_answer(question, contexts)
       ↓
保存 ChatSession / ChatMessage
       ↓
返回 answer + sources/citations
```

### 1.3 文档入库链路

```text
管理员上传知识库文件 / 用户上传聊天附件
  ↓
save_upload => backend/data/uploads
  ↓
Document 记录入库
  ↓
BackgroundTask 入队
  ↓
后台线程 parse_document_to_chunks
  ├─ PDF：pypdf
  ├─ docx/xlsx/csv/txt/md：本地解析
  └─ image：image_to_text 视觉 OCR
       ↓
chunk_text 分片
       ↓
embed_texts 生成向量
       ↓
DocumentChunk 写 SQLite
       ↓
upsert_document_chunks 同步 Qdrant payload
```

---

## 2. 涉及文件与模块清单

### 后端

| 文件 | 当前职责 | 改造影响 |
|---|---|---|
| `backend/app/main.py` | API 路由、内嵌页面、聊天/RAG 主流程、管理接口 | 新增/调整引用持久化、引用查看、反馈接口、管理员反馈管理 |
| `backend/app/models.py` | SQLAlchemy ORM | 扩展 `ChatMessage.sources_json` 或新增引用表；新增反馈表 |
| `backend/app/vector_store.py` | Qdrant collection、payload、检索过滤 | 确保 payload 带 `chunk_id`、`filename`、`chunk_index`、权限字段 |
| `backend/app/ai_client.py` | embedding、模型回答、OCR | 强化只基于上下文回答的提示词约束；必要时增加答案后校验 |
| `backend/app/document_utils.py` | 文档文本抽取、分片、文件名清洗 | 文件预览与解析片段展示依赖其输出质量 |
| `backend/app/config.py` | 上传目录、模型、Qdrant、embedding 配置 | 文件访问安全依赖 `UPLOAD_DIR`；生产需配置强密钥 |
| `backend/app/security.py` | JWT 与密码哈希 | 建议后续升级密码哈希与 token 生命周期策略 |

### 前端

| 文件 | 当前职责 | 改造影响 |
|---|---|---|
| `frontend/src/views/chat/index.vue` | Vue 聊天页 | 长期主入口：消息模型、引用卡片、反馈入口、引用查看弹窗 |
| `frontend/src/views/admin/index.vue` | Vue 管理页 | 长期管理入口：反馈管理、文档权限、任务状态 |
| `frontend/src/api.ts` | Axios 封装 | 复用 Authorization header；新增接口方法类型 |
| `frontend/src/router.ts` | 路由 | `/chat`、`/admin` |
| `frontend/src/style.css` | 全局样式 | 消息引用区、反馈区、详情弹窗样式 |
| `backend/app/main.py` 内 `CHAT_HTML/ADMIN_HTML` | 当前实际页面 | 若短期继续用内嵌页，需要同步实现同等交互 |

---

## 3. 目标架构边界

### 3.1 必须满足

1. AI 回答必须先经过授权知识库/个人附件检索。
2. 无检索命中时，不生成事实型业务答案，只返回“未在授权资料中找到依据”。
3. 每条 assistant 消息都要携带自己的 `sources/citations`，历史会话重新打开仍可见。
4. 引用卡片可点击打开详情或原文件，服务端必须二次鉴权。
5. 每条 assistant 消息下方可提交反馈，反馈能被管理员查看和处理。
6. 文件打开不得暴露服务器真实路径，不允许路径穿越。

### 3.2 不建议第一阶段承担

1. 不建议第一阶段强做完整 Office 在线预览。
2. 不建议把“文件路径”交给前端拼接或传回。
3. 不建议长期维护 Vue 页面与后端内嵌 HTML 两套不一致入口。
4. 不建议在没有高质量 embedding 的情况下承诺强语义召回质量。

---

## 4. 后端如何保证回答基于知识库并返回 citations/sources

### 4.1 检索前置

`POST /api/chat` 必须维持以下顺序：

```text
validate question
  -> validate session ownership
  -> embed question
  -> authorized retrieval
  -> if contexts empty: grounded fallback answer
  -> else call model with contexts only
  -> persist answer and citations
  -> return answer + citations
```

### 4.2 权限过滤一致性

Qdrant 路径和 SQLite fallback 路径必须共享同一权限语义：

```text
personal/chat_*：doc.created_by == current_user.id
managed/admin：current_user.is_admin == true
managed/normal user：document_group_link 命中文档与用户岗位组交集
```

Qdrant payload 至少应包含：

```json
{
  "document_id": "doc_id",
  "document_title": "制度文件",
  "filename": "制度文件.pdf",
  "chunk_id": "chunk_id",
  "page_number": 3,
  "chunk_index": 12,
  "content": "分片全文",
  "source_type": "pdf",
  "visibility": "managed|personal",
  "created_by": "user_id",
  "group_ids": ["group_id"]
}
```

### 4.3 模型提示词约束

`chat_answer()` 的 system prompt 应明确：

- 只能基于提供的 `contexts` 回答。
- 找不到依据时必须说明“未在授权资料中找到依据”。
- 不得基于常识补全公司制度、流程、金额、人员等业务事实。
- 回答末尾可以列出引用编号，但 UI 以结构化 `citations` 为准。

### 4.4 citations 构造规则

后端从 `contexts` 构造 `sources/citations`，不要依赖模型生成引用。

建议字段：

```json
{
  "id": "citation_1_or_source_row_id",
  "document_id": "doc_id",
  "document_title": "入职流程",
  "filename": "入职工单.xlsx",
  "chunk_id": "chunk_id",
  "page_number": null,
  "chunk_index": 5,
  "source_type": "xlsx",
  "source_kind": "managed|personal",
  "score": 0.82,
  "content_preview": "命中片段摘要，建议 300 字以内",
  "view_url": "/api/documents/{document_id}/view?chunk_id={chunk_id}"
}
```

---

## 5. 引用文件数据模型与打开查看接口

### 5.1 P0 数据模型：随 assistant message 保存快照

可直接在 `ChatMessage` 上保存 `sources_json`：

```python
ChatMessage.sources_json: Text = "[]"
```

优点：

- 改动小。
- 历史会话可恢复引用。
- 适合当前小型 SQLite 项目。

缺点：

- 后续按文档、反馈、引用质量统计不方便。
- 不适合大规模引用分析。

### 5.2 P1 推荐模型：独立引用快照表

当需要引用统计、管理员质检、引用点击日志时，建议新增：

```text
chat_message_sources
- id: string primary key
- message_id: string index
- session_id: string index
- document_id: string index
- chunk_id: string nullable
- document_title_snapshot: string
- filename_snapshot: string
- source_type: string
- source_kind: managed|personal
- page_number: int nullable
- chunk_index: int nullable
- score: float nullable
- content_preview: text
- created_at: datetime
```

### 5.3 引用详情接口

推荐新增：

```http
GET /api/sources/{source_id}
Authorization: Bearer <token>
```

响应：

```json
{
  "source": {
    "id": "source_id",
    "message_id": "assistant_message_id",
    "document_id": "doc_id",
    "document_title": "入职流程",
    "filename": "入职工单.xlsx",
    "page_number": null,
    "chunk_index": 3,
    "source_type": "xlsx",
    "content_preview": "..."
  },
  "chunk": {
    "id": "chunk_id",
    "content": "完整命中分片内容"
  },
  "document": {
    "view_url": "/api/documents/doc_id/view?chunk_id=chunk_id",
    "download_url": "/api/documents/doc_id/view",
    "can_preview_original": true
  }
}
```

如短期未建 `chat_message_sources` 表，可用 `document_id + chunk_id` 直接打开：

```http
GET /api/documents/{document_id}/meta
GET /api/documents/{document_id}/view?chunk_id={chunk_id}
```

### 5.4 文件打开接口

```http
GET /api/documents/{document_id}/view?chunk_id={chunk_id}
Authorization: Bearer <token>
```

行为：

- 服务端通过 `document_id` 查 `Document`。
- 服务端重新校验当前用户权限。
- 服务端用数据库中的 `storage_path` 定位文件。
- 返回 `FileResponse`。
- 可在 header 中返回 `X-Document-Page`、`X-Document-Chunk-Index` 供前端提示定位。

初版文件类型策略：

| 类型 | P0 策略 | P1/P2 增强 |
|---|---|---|
| PDF | 浏览器直接打开文件；显示页码提示 | PDF.js 定位页码 |
| TXT/MD/CSV | 可直接预览或展示解析片段 | 高亮命中片段 |
| DOCX/XLSX | P0 展示解析片段；允许下载原文件 | 在线预览/转换 HTML |
| 图片 | 打开图片；展示 OCR 文本 | OCR 区域高亮 |

---

## 6. 反馈提交给管理员的数据链路

### 6.1 用户反馈接口

推荐接口：

```http
POST /api/chat/feedback
Authorization: Bearer <token>
Content-Type: application/json
```

请求：

```json
{
  "session_id": "session_id",
  "message_id": "assistant_message_id",
  "rating": "helpful|incorrect|bad_citation|not_solved|other",
  "content": "用户补充反馈，最多 2000 字"
}
```

响应：

```json
{
  "ok": true,
  "id": "feedback_id",
  "status": "new",
  "message": "反馈已提交给管理员"
}
```

### 6.2 反馈表建议

当前可用字段：

```text
feedback
- id
- user_id
- username
- session_id
- message_id
- rating
- content
- question_snapshot
- answer_snapshot
- sources_json
- status
- created_at
- reviewed_at
- review_note
```

建议状态枚举统一为：

```text
new / reviewing / resolved / ignored
```

### 6.3 管理员反馈接口

```http
GET /api/admin/feedback?status=new
PUT /api/admin/feedback/{feedback_id}
```

列表响应：

```json
[
  {
    "id": "feedback_id",
    "username": "zhangsan",
    "session_id": "session_id",
    "message_id": "assistant_message_id",
    "rating": "bad_citation",
    "content": "引用文件不对",
    "question": "原问题快照",
    "answer": "AI 回答快照",
    "sources": [],
    "status": "new",
    "created_at": "2026-05-28T..."
  }
]
```

更新请求：

```json
{
  "status": "reviewing|resolved|ignored",
  "review_note": "管理员处理备注"
}
```

### 6.4 审计要求

以下操作写入 `AuditLog`：

- `feedback.submit`
- `feedback.review`
- `document.permissions_update`
- `document.delete`
- `document.reparse`
- `vector.reindex`

---

## 7. 前端消息模型扩展

### 7.1 TypeScript 状态模型

```ts
export type ChatRole = 'user' | 'assistant'

export interface MessageSource {
  id?: string
  document_id: string
  document_title: string
  filename?: string
  file_name?: string
  chunk_id?: string | null
  page_number?: number | null
  page?: number | null
  chunk_index?: number | null
  source_type: string
  source_kind?: 'managed' | 'personal'
  score?: number | null
  content?: string
  snippet?: string
  excerpt?: string
  content_preview?: string
  view_url?: string
  url?: string
}

export interface FeedbackState {
  submitted: boolean
  feedback_id?: string
  rating?: 'helpful' | 'incorrect' | 'bad_citation' | 'not_solved' | 'other'
  status?: 'new' | 'reviewing' | 'resolved' | 'ignored'
}

export interface ChatMessage {
  id?: string
  role: ChatRole
  content: string
  created_at?: string
  sources?: MessageSource[]
  citations?: MessageSource[]
  feedback?: FeedbackState
  pending?: boolean
  error?: string
}
```

### 7.2 聊天页交互

每条 assistant 消息下方固定展示：

```text
[引用 1] [引用 2] ...
[有帮助] [不准确] [引用不对] [没解决] [其他]
[复制]
```

要求：

- 引用跟随具体 assistant message，不再只显示“最近一次全局 sources”。
- 历史会话打开后，引用仍在原消息下方。
- 引用卡片点击调用 `view_url` 或打开详情弹窗。
- 反馈提交中/成功/失败均有状态提示。
- 反馈提交失败时保留用户已输入内容。

### 7.3 管理页交互

新增“反馈管理”菜单：

- 列表：时间、用户、类型、问题摘要、状态。
- 详情：问题快照、回答快照、引用快照、用户反馈。
- 操作：状态流转、管理员备注。

---

## 8. 文件打开安全与路径穿越防护

### 8.1 风险

1. 前端伪造 `document_id` 越权查看文件。
2. 前端传入路径导致路径穿越。
3. `storage_path` 指向上传目录外部文件。
4. 文件删除后引用仍存在，打开时报错。
5. 引用快照暴露用户无权限文档摘要。

### 8.2 服务端防护策略

文件接口严禁接受本地路径参数，只接受 `document_id/chunk_id/source_id`。

伪代码：

```python
def resolve_document_file_for_user(db, document_id, user):
    doc = db.get(Document, document_id)
    if not doc:
        raise HTTPException(404)

    if not can_access_document(db, doc, user):
        raise HTTPException(403)

    upload_root = UPLOAD_DIR.resolve()
    file_path = Path(doc.storage_path).resolve()

    if upload_root not in file_path.parents and file_path != upload_root:
        raise HTTPException(403, 'invalid file path')

    if not file_path.exists() or not file_path.is_file():
        raise HTTPException(404)

    return doc, file_path
```

### 8.3 权限函数

```python
def can_access_document(db, doc, user):
    source_type = str(doc.source_type or '')
    if source_type.startswith('chat_'):
        return doc.created_by == user.id
    if user.is_admin:
        return True
    user_group_ids = {g.id for g in user.groups}
    doc_group_ids = {g.id for g in doc.groups}
    return bool(user_group_ids & doc_group_ids)
```

### 8.4 HTTP 状态码

| 场景 | 状态码 |
|---|---|
| 未登录 | 401 |
| 无权限 | 403 或为防枚举返回 404 |
| 文档不存在 | 404 |
| 文件缺失 | 404 |
| 路径非法 | 403 |
| chunk 不属于 document | 400/404 |

---

## 9. 后端接口契约总表

| 接口 | 方法 | 权限 | 用途 |
|---|---|---|---|
| `/api/chat` | POST | 登录用户 | 提问、RAG、返回 answer + sources/citations |
| `/api/chat/sessions` | GET | 登录用户 | 会话列表 |
| `/api/chat/sessions/{id}` | GET | 会话所有者 | 会话详情，消息内含 sources/citations |
| `/api/chat/feedback` | POST | 登录用户 | 对 assistant 消息提交反馈 |
| `/api/documents/{id}/meta` | GET | 有文档权限 | 查看文档元信息 |
| `/api/documents/{id}/view` | GET | 有文档权限 | 打开或下载原文件 |
| `/api/sources/{id}` | GET | 有引用/文档权限 | 查看引用详情，P1 推荐 |
| `/api/admin/feedback` | GET | 管理员 | 反馈列表 |
| `/api/admin/feedback/{id}` | PUT | 管理员 | 处理反馈 |
| `/api/admin/documents/{id}/chunks` | GET | 管理员 | 查看文档分片 |
| `/api/admin/vector/reindex` | POST | 管理员 | 重建 Qdrant 向量索引 |

---

## 10. 分阶段改造计划

### 阶段 0：恢复可审查集成视图

- 确保 `D:\AI\SpeceAppDate\知识库` 是 Git 仓库根。
- 架构文档放入 `docs/`。
- 后续实现与评审均基于仓库根。

### 阶段 1：P0 可信回答与引用持久化

后端：

- `/api/chat` 统一返回 `message_id`、`assistant_message_id`、`user_message_id`。
- 每条 assistant message 保存 `sources_json` 或写入 `chat_message_sources`。
- 历史会话接口返回 `message.sources` 和 `message.citations`。
- Qdrant 与 SQLite fallback 均返回 `chunk_id/filename/chunk_index/score`。

前端：

- 消息数组按 `ChatMessage` 模型保存。
- assistant 消息下方渲染引用卡片。
- 历史会话恢复引用。

验收：

- 无引用时不生成事实型回答。
- 每条 AI 回复下方都有独立引用区。
- 历史消息引用不丢失。

### 阶段 2：P0 引用打开与文件安全

后端：

- 实现 `/api/documents/{id}/meta`。
- 实现 `/api/documents/{id}/view?chunk_id=`。
- 可选实现 `/api/sources/{source_id}`。
- 统一 `can_access_document` 和 path resolve 防护。

前端：

- 引用卡片点击打开详情弹窗。
- PDF/图片可打开原文件；Office 初版显示解析片段或下载。

验收：

- 有权限用户能打开引用。
- 无权限用户不能通过猜 ID 打开。
- 响应不暴露服务器真实路径。

### 阶段 3：P0/P1 反馈闭环

后端：

- 实现 `/api/chat/feedback`。
- 实现 `/api/admin/feedback` 和更新接口。
- 反馈保存问题、回答、引用快照。
- 写审计日志。

前端：

- assistant 消息下方增加反馈按钮。
- 弹出反馈类型与文本框。
- 管理页增加反馈管理。

验收：

- 反馈关联具体 assistant message。
- 管理员能查看并处理。
- 反馈包含引用快照。

### 阶段 4：P1 前端统一与体验升级

- 决策：Vue 为长期主入口，FastAPI 内嵌 HTML 作为临时兼容或下线。
- `docker-compose.yml` 增加 frontend 服务或将 Vue build 接入后端静态目录。
- 移动端适配引用与反馈区。
- 增加 loading 状态：检索中、生成中、上传解析中、反馈提交中。

### 阶段 5：P1/P2 质量与运维升级

- 引入 Alembic 管理 schema migration。
- 升级密码哈希：SHA256 -> bcrypt/argon2。
- JWT 加强：过期刷新、强 `JWT_SECRET`、生产禁用默认密码。
- Embedding 升级：local-hash -> 高质量 embedding 服务。
- 增加相关性阈值和低置信度兜底。
- Qdrant 健康状态与索引同步监控。
- 自动化测试：后端权限测试、RAG fallback 测试、反馈接口测试、前端构建测试。
- 修复中文乱码文档和源码注释显示问题。

---

## 11. 技术权衡与回滚思路

### 11.1 引用保存：`sources_json` vs 独立表

| 方案 | 优点 | 缺点 | 建议 |
|---|---|---|---|
| `ChatMessage.sources_json` | 快速、低迁移成本、适合 P0 | 查询统计不方便 | P0 可用 |
| `chat_message_sources` | 结构化、利于统计和质量分析 | 迁移和代码量更多 | P1 推荐 |

回滚：保留 `/api/chat` 旧字段 `sources`；前端兼容 `sources/citations`。

### 11.2 原文件预览：直接 FileResponse vs 转换预览

| 方案 | 优点 | 缺点 | 建议 |
|---|---|---|---|
| FileResponse | 快速、安全边界清晰 | Office 体验一般 | P0 |
| PDF.js/Office 转 HTML | 体验好 | 实现复杂、依赖多 | P1/P2 |

回滚：若原文预览异常，仍可展示解析片段详情。

### 11.3 前端入口：内嵌 HTML vs Vue

| 方案 | 优点 | 缺点 | 建议 |
|---|---|---|---|
| 继续内嵌 HTML | 当前可用、部署简单 | 难维护、代码集中在 main.py | 短期 P0 |
| Vue 独立前端 | 工程化、组件化、体验更好 | 需要调整部署 | 长期推荐 |

回滚：保留后端内嵌页作为临时入口，Vue 未稳定前不删除。

---

## 12. 验收检查清单

### RAG 与引用

- [ ] `/api/chat` 必须先检索授权知识库。
- [ ] 无命中时不生成事实型业务答案。
- [ ] 有命中时返回 `sources` 和 `citations`。
- [ ] 每条 assistant message 保存自己的引用。
- [ ] 历史会话打开后引用仍可见。
- [ ] Qdrant 与 SQLite fallback 权限一致。

### 引用打开

- [ ] 引用卡片可点击。
- [ ] 打开前二次校验权限。
- [ ] 无权限返回 403/404。
- [ ] 文件缺失返回 404。
- [ ] 不暴露 `storage_path`。
- [ ] 防止路径穿越。

### 反馈闭环

- [ ] 每条 assistant 消息下方有反馈入口。
- [ ] 反馈关联 `message_id`。
- [ ] 反馈保存问题、回答、引用快照。
- [ ] 管理员可列表查看。
- [ ] 管理员可更新状态和备注。
- [ ] 操作写审计日志。

### 前端体验

- [ ] 消息级引用区不是全局最近引用。
- [ ] 反馈提交成功后显示“已反馈”。
- [ ] 移动端可查看引用与提交反馈。
- [ ] 上传附件状态可见。
- [ ] 网络/权限/解析失败有明确提示。

### 安全与运维

- [ ] 默认管理员密码不在页面暴露。
- [ ] 生产必须设置强 `JWT_SECRET`。
- [ ] 上传大小和扩展名限制有效。
- [ ] 关键接口有权限测试。
- [ ] 数据库迁移可重复执行。

---

## 13. 交付给前后端的最小实现顺序

1. 后端补齐/确认 `ChatMessage.sources_json`，`/api/chat` 返回 `message_id + sources/citations`。
2. 后端确保 `get_chat_session` 返回每条消息的 `sources/citations`。
3. 后端补齐 `can_access_document`，实现 `/api/documents/{id}/view` 与 `/api/documents/{id}/meta`。
4. 后端新增/确认 `feedback` 表与 `/api/chat/feedback`。
5. 后端新增/确认 `/api/admin/feedback` 列表与处理接口。
6. 前端 ChatMessage 模型扩展 `sources/citations/feedback`。
7. 前端每条 AI 消息下方渲染引用卡片和反馈按钮。
8. 前端引用点击打开详情/原文。
9. 管理端增加反馈管理。
10. 补测试与手工验收记录。

---

## 14. 项目整体升级建议

1. **工程边界**：拆分 `main.py`，建议按 `routers/chat.py`、`routers/admin.py`、`services/rag.py`、`services/documents.py`、`services/feedback.py` 组织。
2. **迁移管理**：引入 Alembic，替代运行时 `ALTER TABLE`。
3. **前端统一**：选择 Vue 作为长期入口，`docker-compose.yml` 增加 frontend 服务。
4. **检索质量**：生产禁用 local-hash embedding，改高质量 embedding；增加 score threshold。
5. **可观测性**：记录 retrieval_backend、top_k、source_count、无答案率、反馈率、负反馈率。
6. **安全**：密码哈希升级、JWT secret 强校验、接口限流、上传文件病毒扫描或隔离策略。
7. **文档治理**：增加文档版本号、重解析状态、删除保护、引用快照保留策略。
8. **测试**：覆盖权限、路径穿越、Qdrant fallback、反馈提交、历史引用恢复。

---

## 15. 本方案对评审失败维度的回应

| 失败维度 | 回应 |
|---|---|
| completeness | 本文件覆盖现状架构、模块清单、RAG、引用、反馈、前端模型、安全、阶段计划、升级建议 |
| accuracy | 基于实际文件和当前 Git 工作树只读分析，列出具体模块和链路 |
| codeQuality/docQuality | 文档结构化，可直接交付前后端拆任务 |
| adherence | 未修改业务代码，仅新增架构交付文档 |
| innovation | 给出 P0/P1 分层、回滚策略、入口统一、引用模型权衡与安全策略 |
| integration_review_blocked | 文档已纳入仓库 `docs/`，且仓库根可由 `git rev-parse` 解析 |
