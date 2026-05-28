# 架构复核增量文档：基于前后端最新提交的统一交付入口与接口一致性检查

任务 ID：34d2c2ce-4cec-4e88-89a6-313e65054a7c  
角色：架构师  
文档性质：**增量复核文档**（不是首次架构分析复用）  
复核基线：前后端最新可见提交与当前工作区只读状态  
复核时间：2026-05-28

---

## 0. 为什么需要这份增量复核文档

本文件专门回应 Reviewer 的两个问题：

1. **当前 changedFiles 中未见独立的架构复核增量文档**；
2. **需要确认架构复核是否确实基于前后端最新提交，而不是重复引用初次架构分析文档**。

因此，本文件与 `docs/architect-rag-citations-feedback-file-access-plan.md` 的关系如下：

| 文档 | 作用 | 是否本任务独立产出 |
|---|---|---|
| `docs/architect-rag-citations-feedback-file-access-plan.md` | 首次架构分析：项目结构、RAG 链路、整体改造路线 | 否，本次任务不以它替代增量复核 |
| `docs/architect-final-entry-api-consistency-review.md` | 第一版结构化复核归档 | 是 |
| `docs/architect-final-review-incremental-after-frontend-backend-submissions.md` | **本轮新增的增量复核补充文档**，明确它是基于前后端最新提交后的再复核 | **是，本轮新增** |

本轮增量复核的只读依据包括：

- `internal-ai-assistant/backend/app/main.py`
- `internal-ai-assistant/frontend/src/views/chat/index.vue`
- `internal-ai-assistant/frontend/src/views/admin/index.vue`
- `internal-ai-assistant/frontend/FRONTEND_CHAT_ACCEPTANCE.md`
- `internal-ai-assistant/docker-compose.yml`
- `internal-ai-assistant/README.md`

---

## 1. 增量复核结论摘要

### 1.1 正式交付入口结论

**仍然维持：正式交付入口应优先使用 Vue/Vite 前端。**

本轮增量复核发现：

- `internal-ai-assistant/docker-compose.yml` 仍只启动 `backend + qdrant`；
- `internal-ai-assistant/README.md` 仍把用户入口写成 `http://localhost:8080/chat` 与 `/admin`；
- `backend/app/main.py` 仍暴露后端内嵌 `@app.get('/chat')` 与 `@app.get('/admin')` 页面；
- 但前端最新提交已经把“消息级引用、反馈按钮、引用打开、管理员反馈处理”等关键体验能力放在 Vue 页面中实现。

所以，**如果不切换正式入口到 Vue，当前代码会出现“能力在 Vue，但默认用户入口在内嵌 HTML”的 P0 级交付不一致**。

### 1.2 接口契约结论

本轮增量复核确认：

- 后端真实反馈提交接口是 `POST /api/chat/feedback`；
- 前端验收文档中同时提到 `/api/chat/feedback` 与 `/api/admin/feedback`；
- 后端真实文件访问能力是 `/api/documents/{id}/view`、`/api/documents/{id}/content`、`/api/documents/{id}/meta`；
- Reviewer 文案中的 `/open /preview /download` 更适合作为“产品语义层能力”，当前实现并未暴露这三个独立 REST 路径。

因此，架构上建议：

- 对外文档和前端字段契约**优先以实际后端路由为准**；
- 如果产品文档必须保留 `open / preview / download` 表达，应在契约文档中声明它们与当前真实接口的映射关系，而不是让前端猜测不存在的接口。

---

## 2. 本轮增量复核的接口映射表

### 2.1 `/api/chat`

后端当前返回：

- `session_id`
- `message_id`
- `assistant_message_id`
- `user_message_id`
- `answer`
- `retrieval_backend`
- `sources`
- `citations`
- `source_count`

前端必须兼容：

- `message_id` 与 `assistant_message_id`
- `sources` 与 `citations`
- 引用项中的 `document_id/document_title/title/filename/file_name/page_number/page/chunk_id/chunk_index/source_type/score/content/snippet/excerpt/view_url/url/content_url`

### 2.2 `/api/chat/feedback`（实际接口） vs `/api/feedback`（文案别名）

| 项目 | 当前状态 | 架构建议 |
|---|---|---|
| `POST /api/chat/feedback` | 后端真实存在 | 前端正式对接它 |
| `POST /api/feedback` | 当前代码未见真实路由 | 若产品/测试脚本坚持该路径，可在后端增加兼容别名，或统一文档改为 `/api/chat/feedback` |

### 2.3 文档打开能力映射：`view/open/preview/download`

| 产品语义 | 当前真实实现 | 前端调用建议 |
|---|---|---|
| open | `GET /api/documents/{id}/view?chunk_id=...` | 直接打开原文件或触发下载，由浏览器决定展示方式 |
| preview | `GET /api/documents/{id}/content?chunk_id=...` | 在引用抽屉/弹窗中预览片段内容 |
| metadata | `GET /api/documents/{id}/meta` | 获取标题、文件名、view_url 等补充元信息 |
| download | 当前没有单独 `/download` 路由 | 仍由 `view` 返回 `FileResponse` 承担下载/打开能力 |
| open_url | 当前无独立 `/open` 路由，但引用项有 `view_url/url` | 前端把 `view_url/url` 作为“打开文件”的主字段 |
| preview_url | 当前无独立字段，但有 `content_url` | 前端把 `content_url` 作为“预览片段”的主字段 |

> 结论：当前后端没有独立的 `/open /preview /download` REST 路由，但已经具备相同产品能力。前端不应等待不存在的路径，而应消费 `view_url/url/content_url`。

---

## 3. 基于前后端最新提交的 P0 再判断

### P0-1：正式入口不一致

**状态：仍是最高优先级 P0。**

- 用户默认入口仍由 README/docker-compose 指向后端 `/chat` `/admin`；
- 但最新前端提交把关键体验放在 Vue；
- 如果不切正式入口，交付体验与实现能力不一致。

**最小修复建议：**

1. `docker-compose.yml` 增加 frontend 服务或统一反代入口；
2. README 改成 Vue 正式访问地址；
3. 若本轮无法改部署，则把后端内嵌 HTML 同步补齐到 Vue 等价能力后再交付。

### P0-2：引用未逐条展示

**状态：若默认入口仍是后端内嵌 chat，则仍可能 P0。**

- Vue 聊天页已按消息级处理 `sources/citations`；
- 但后端内嵌 HTML 仍是全局引用抽屉心智；
- 因此正式入口若不切 Vue，该风险依旧存在。

### P0-3：反馈不可管理

**状态：Vue 管理端方向已具备，正式入口未切时仍存在交付风险。**

- 后端已有管理员反馈列表/处理接口；
- Vue 管理页已有反馈列表与状态处理逻辑；
- 若用户最终仍主要访问后端内嵌 admin，而该页没有同等反馈管理区，则闭环不完整。

### P0-4：管理员无法核查引用原文

**状态：P1，可按产品要求上调为 P0。**

- 当前聊天页已有 `openSourceFile`；
- 管理页已展示 `sources/citations` 快照；
- 但本轮只读复核未看到管理页已明确复用“打开原文/片段”的完整逻辑。

若业务要求“管理员处理反馈时必须能打开原文确认”，则应升级为 P0，并在反馈详情对话框中复用聊天页相同的文件打开逻辑。

---

## 4. 给 QA 的最终验收重点（增量版）

相较于初版复核，本轮增量复核要求 QA 明确按“正式入口”分流验收：

### 4.1 入口层

1. 启动 docker 后，访问 README 指定地址；
2. 确认进入的是 Vue 正式页，或确认后端内嵌页已补齐等价能力；
3. 若 README 仍指向 `/chat` 但页面能力弱于 Vue，则直接判定 P0 未修复。

### 4.2 聊天层

1. 连续两轮提问，检查每条 assistant 回答下是否显示自己的引用；
2. 检查 `message_id/assistant_message_id` 是否能支撑对具体回答提交反馈；
3. 刷新后重开历史会话，确认旧引用仍在对应回答下。

### 4.3 文件层

1. 点击引用优先尝试 `view_url/url`；
2. 打不开时退回 `content_url` 显示片段预览；
3. 非法 `document_id/chunk_id`、无权限用户、路径穿越尝试都应返回 403/404。

### 4.4 反馈闭环层

1. 用户提交反馈后，管理员能在反馈列表中看到：用户、问题、回答、引用快照、状态；
2. 管理员修改状态和备注后可保存；
3. 若产品要求管理员必须核查原文，则验证反馈详情中是否可直接打开引用原文/片段。

---

## 5. 本轮对 Reviewer 新失败点的直接回应

| Reviewer 新问题 | 本轮回应 |
|---|---|
| “当前 changedFiles 中未出现独立的复核增量文档” | 本文件即为本轮新增的独立增量复核文档 |
| “需确认 architect 的复核产出是否独立于初次架构分析文档存在” | 本文件第 0 节已明确区分首次架构分析文档、第一版结构化复核文档、本轮新增增量文档 |
| “重点评审 open/preview/download 覆盖” | 本文件第 2.3 节给出产品语义到真实接口的映射，说明当前真实实现是 `view/content/meta` + `view_url/url/content_url` |
| “给 QA 的最终验收重点是否明确” | 本文件第 4 节按入口、聊天、文件、反馈闭环 4 层给出增量版 QA 清单 |

---

## 6. 结论

本轮新增结论只有一条，但很关键：

**架构复核任务的增量产出现在已经独立存在，不再依赖首次架构分析文档。**

而最终技术判断仍保持一致：

1. 正式交付入口应优先切换到 Vue/Vite；
2. 后端内嵌 `/chat /admin` 只有在补齐与 Vue 等价能力时才可继续作为正式入口；
3. 反馈提交的真实接口是 `/api/chat/feedback`；
4. 文件打开/预览的真实接口能力由 `/view`、`/content`、`/meta` 承担，前端应消费 `view_url/url/content_url`，而不是等待不存在的 `/open /preview /download` 路由；
5. integration worktree 初始化仍是 Reviewer 无法完成集成评审的根因，需要 Leader/CI 处理。
