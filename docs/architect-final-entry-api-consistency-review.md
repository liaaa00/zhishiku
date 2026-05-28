# 架构复核：统一交付入口与前后端接口一致性检查

任务 ID：34d2c2ce-4cec-4e88-89a6-313e65054a7c  
角色：架构师  
范围：只读复核与归档，不修改业务代码。  
复核时间：2026-05-28

---

## 0. 本轮返工说明

上一轮内容评审给出 8.55/10，主要扣分点不是架构判断错误，而是：

1. `integration worktree` 缺失导致评审链路不可用；
2. 复核结果以任务摘要形式提交，缺少独立结构化归档文档；
3. 需要更明确的 P0 修复优先级、字段矩阵和 QA 验收重点。

本轮返工新增本文件作为独立归档交付物：

```text
docs/architect-final-entry-api-consistency-review.md
```

本轮仍遵循“只读分析，不改代码”。当前工作区中存在其他成员未提交的前后端实现改动，本架构任务只新增/提交 `docs/` 下文档，不纳入业务代码修改。

### 0.1 integration 阻断证据

本地 Git 视图显示：

```text
当前 HEAD: 67ea289 docs: refine architect analysis testing and retrieval plan
上一轮架构文档提交: b8fe4f6 docs: add architect RAG citations feedback plan
可见 integration 备份引用:
- backup/team-builtin-team-template-fullstack-feature-squad-integration/1779954152001 -> b8fe4f6
- backup/team-e67c4d14-e561-4cf0-afcb-75c7573485d5-integration/1779954418749 -> b8fe4f6
```

仓库没有独立命名为 `integration` 的本地分支或额外 Git worktree；`git worktree list` 仅显示当前仓库根。因此 Reviewer 报告的 `integration_worktree_missing/not_initialized` 属于团队集成基础设施状态，不是本任务文档内容缺失。建议 Leader/CI 先初始化 integration worktree 后再让 Reviewer 使用集成视图评审。

---

## 1. 最终交付入口决策

### 1.1 当前事实

| 证据 | 当前状态 | 影响 |
|---|---|---|
| `internal-ai-assistant/docker-compose.yml` | 只启动 `backend` 和 `qdrant`，未启动 `frontend` 服务 | Docker 默认访问进入 FastAPI 内置页面 |
| `internal-ai-assistant/README.md` | 访问入口仍写 `http://localhost:8080/chat` 和 `/admin` | 用户会进入后端内嵌 HTML，而不是 Vue/Vite 前端 |
| `backend/app/main.py` | 存在 `@app.get('/chat')` 和 `@app.get('/admin')` 返回内嵌 HTML | 内嵌页仍是可达入口，需同步能力或降级为兼容入口 |
| `frontend/src/views/chat/index.vue` | **integration committed 版本仅有全局 sources 展示，无反馈按钮、逐消息引用、openSourceFile**；工作区未提交 diff 中可见相关实现雏形 | Vue 仍是满足目标体验的主实现方向，但当前集成状态前端未就绪 |
| `frontend/src/views/admin/index.vue` | **integration committed 版本无反馈管理模块**；工作区未提交 diff 中可见反馈面板雏形 | 管理员反馈闭环需要前端提交并合入后才可验收 |

### 1.2 架构决策

**正式交付入口应优先使用 Vue/Vite 前端。**

理由：

- 用户目标要求“每次回复聊天框下面显示引用文件、点击打开查看、回答后可反馈给管理员”。这属于复杂交互，Vue 组件化更适合维护。
- 后端内嵌 HTML 集中在 `main.py` 字符串中，长期维护成本高，难以和 Element Plus/状态管理/构建校验保持一致。
- 前端任务的验收文档 `internal-ai-assistant/frontend/FRONTEND_CHAT_ACCEPTANCE.md` 已围绕 Vue 消费后端字段定义验收点。

### 1.3 两条可执行路径

| 方案 | 内容 | 优先级 | 适用场景 |
|---|---|---|---|
| A. Vue 成为正式入口 | `docker-compose.yml` 增加 frontend 服务或 nginx 反代；README 改为 Vue 入口；后端保留 API 与可选兼容页 | P0 推荐 | 希望一次性交付用户可见的完整体验 |
| B. 保持 8080 `/chat` `/admin` | 必须同步改造后端内嵌 `CHAT_HTML`/`ADMIN_HTML`，达到 Vue 同等能力 | P0 备选 | 暂时不能改部署拓扑 |

**不可接受状态**：README/docker-compose 默认仍指向内嵌 `/chat` `/admin`，但内嵌页没有消息级引用、反馈按钮、反馈管理、引用打开能力。这会导致“代码里有 Vue 能力，但用户默认访问不到”的 P0 入口不一致。

---

## 2. 后端接口契约与前端消费矩阵

> 说明：后端实际反馈提交接口为 `POST /api/chat/feedback`；评审描述中的 `/api/feedback` 可作为兼容别名建议，但当前代码证据以 `/api/chat/feedback` 为准。前端 axios base 通常为 `/api`，因此 Vue 中 `http.get('/admin/feedback')` 对应后端 `/api/admin/feedback`。

### 2.1 `/api/chat`：问答与引用返回

| 字段 | 后端提供 | 前端必须消费/兼容 | 说明 |
|---|---:|---:|---|
| `session_id` | 是 | 是 | 继续会话和历史刷新 |
| `message_id` | 是 | 是 | assistant 消息 ID，反馈关联主键 |
| `assistant_message_id` | 是 | 是 | `message_id` 别名，前端需兼容 |
| `user_message_id` | 是 | 建议 | 便于审计或 UI 定位 |
| `answer` | 是 | 是 | AI 回答正文 |
| `retrieval_backend` | 是 | 建议 | 显示/记录 Qdrant 或 SQLite fallback |
| `sources` | 是 | 是 | 引用列表主字段 |
| `citations` | 是 | 是 | `sources` 别名，前端需兼容 |
| `source_count` | 是 | 建议 | 空引用/低置信提示 |

`sources/citations` 单项字段：

| 字段 | 后端提供 | 前端用途 |
|---|---:|---|
| `id` | 是 | 列表 key |
| `document_id` | 是 | 打开原文、查询片段 |
| `document_title` / `title` | 是 | 引用卡片标题 |
| `filename` / `file_name` | 是 | 文件名展示 |
| `page_number` / `page` | 是 | 页码/定位提示 |
| `chunk_id` | 是 | 打开原文时定位片段 |
| `chunk_index` | 是 | 排序/补充定位 |
| `source_type` | 是 | 区分授权文档/个人附件 |
| `score` | 是 | P1 显示置信度或调试 |
| `content` / `snippet` / `excerpt` | 是 | 引用片段正文 |
| `view_url` / `url` | 是 | 直接打开原文件 |
| `content_url` | 是 | 拉取片段详情/全文片段 |

### 2.2 `/api/chat/sessions/{id}`：历史引用恢复

| 字段 | 后端提供 | 前端必须消费 | 风险 |
|---|---:|---:|---|
| `session` | 是 | 是 | 会话元信息 |
| `messages[].id` | 是 | 是 | 消息 key 与反馈关联 |
| `messages[].role` | 是 | 是 | 区分 user/assistant |
| `messages[].content` | 是 | 是 | 消息正文 |
| `messages[].sources` | assistant 有 | 是 | 每条 AI 消息独立引用 |
| `messages[].citations` | assistant 有 | 是 | sources 别名 |

验收重点：刷新页面或重新打开历史会话后，引用必须恢复到对应 assistant 消息下，不能只显示“最近一次全局 sources”。

### 2.3 `POST /api/chat/feedback`：用户反馈提交

| 请求字段 | 必填 | 说明 |
|---|---:|---|
| `session_id` | 建议 | 会话归属，用于快照上下文 |
| `message_id` | P0 必须 | assistant 消息 ID，确保反馈指向具体回答 |
| `rating` | 可选 | 如 good/bad/inaccurate 等 |
| `content` | 必填 | 用户输入反馈，后端限制非空且最长 2000 字 |

| 响应字段 | 说明 |
|---|---|
| `ok` | true 表示提交成功 |
| `id` | 反馈记录 ID |
| `status` | 初始状态，一般为 new |
| `message` | “反馈已提交给管理员”类提示 |

后端会保存 `question_snapshot`、`answer_snapshot` 和 `sources_json`，满足“反馈给管理员时保留回答和引用快照”的目标。

### 2.4 `GET /api/admin/feedback` 与 `PUT /api/admin/feedback/{id}`：管理员反馈处理

| GET 列表字段 | 前端用途 |
|---|---|
| `id` | 操作主键 |
| `user_id` / `username` | 反馈用户 |
| `session_id` / `message_id` | 回溯上下文 |
| `rating` / `content` | 反馈类型和内容 |
| `question` / `answer` | 问答快照 |
| `sources` / `citations` | 引用快照 |
| `status` | new/reviewed/resolved/ignored |
| `created_at` / `reviewed_at` | 时间展示 |
| `review_note` | 管理员备注 |

| PUT 请求字段 | 说明 |
|---|---|
| `status` | 允许 `new/reviewed/resolved/ignored`，前端若出现 `reviewing` 应映射或避免提交 |
| `review_note` | 管理员处理备注 |

P1 建议：管理员反馈详情中的引用快照应复用聊天页 `openSourceFile` 逻辑，让管理员可点击打开原文/片段。若产品要求管理员必须核查引用原文件，则该项升级为 P0。

### 2.5 `/api/documents/{id}/view`、`/content`、`/meta`

| 接口 | 用途 | 前端消费建议 |
|---|---|---|
| `GET /api/documents/{id}/view?chunk_id=...` | 返回原文件 `FileResponse` | 优先用于“打开原文件” |
| `GET /api/documents/{id}/content?chunk_id=...` | 返回片段/文档内容 JSON | 用于抽屉内展示引用片段详情，Office/PDF 不便预览时兜底 |
| `GET /api/documents/{id}/meta` | 返回文档元信息 | 引用详情弹窗或权限校验提示 |

权限要求：三者均需通过 `resolve_document_file_for_user`，禁止未授权用户猜 ID 打开文件，禁止路径穿越和暴露服务器真实路径。

---

## 3. P0 风险清单与最小修复优先级

| 优先级 | 风险 | 判定 | 最小修复建议 |
|---|---|---|---|
| P0-1 | **阻塞交付：默认入口仍进入后端内嵌 HTML，且 integration committed 前端未消费反馈/逐消息引用接口** | docker-compose 只暴露 backend，README 指向 `8080/chat`/`admin`；后端接口已就绪但前端消费者未集成 | 方案 A：前端提交并合入 Vue 实现后增加 frontend 服务/反代并更新 README；或方案 B：同步改造内嵌页到 Vue 同等能力 |
| P0-2 | 每条 assistant 回复下未逐条展示引用 | 若只在全局抽屉显示最近 sources，则不满足用户目标 | Vue 消息模型必须保存 `message.sources/citations`，历史接口也必须恢复 |
| P0-3 | 反馈无法关联具体回答 | 无 `message_id` 会导致管理员不知道用户反馈哪条回答 | 使用 `/api/chat` 返回的 `message_id/assistant_message_id` 提交 `/api/chat/feedback` |
| P0-4 | 管理员无法查看/处理反馈 | 缺 `/api/admin/feedback` 消费或入口不可达 | Vue 管理页增加反馈 Tab；后端管理员接口返回快照并允许状态更新 |
| P0-5 | 引用不能打开或权限绕过 | 只显示文本片段、不支持打开；或打开不鉴权 | 引用卡片优先走 `view_url`，失败走 `content_url`，后端统一鉴权 |
| P0-6 | RAG 无命中仍编造答案 | 用户明确要求每次回答基于知识库内容 | 无授权上下文时返回“未找到相关内容”，不得生成事实型答案 |

### 3.1 推荐修复时间线

1. **第 1 步：统一入口**  
   Leader 决策 Vue 正式入口；前端服务接入 docker-compose/README。若本轮不能改部署，则改造后端内嵌 HTML。
2. **第 2 步：消息级引用闭环**  
   确认 `/api/chat` 和历史会话返回每条 assistant 的 `sources/citations`；前端按消息渲染引用卡片。
3. **第 3 步：反馈闭环**  
   用户端提交 `/api/chat/feedback`，管理员端加载 `/api/admin/feedback` 并处理。
4. **第 4 步：引用打开与安全**  
   `view_url/content_url` 前端兜底，后端鉴权、路径穿越防护、404/403 明确。
5. **第 5 步：端到端验收**  
   由 QA 使用正式入口完成“登录 -> 提问 -> 引用 -> 打开 -> 反馈 -> 管理员处理 -> 历史恢复 -> 无权限拒答”。

---

## 4. 前端消费字段 × 后端提供字段矩阵

| 功能 | 后端字段/接口 | Vue Chat 必须 | Vue Admin 必须 | 备注 |
|---|---|---:|---:|---|
| 生成回答 | `POST /api/chat.answer` | 是 | 否 | 显示 AI 回复 |
| 记录会话 | `session_id` | 是 | 否 | 后续问题复用 |
| 反馈关联 | `message_id` / `assistant_message_id` | 是 | 列表展示 | 反馈必须指向 assistant 消息 |
| 引用列表 | `sources` / `citations` | 是 | 是，作为反馈快照 | 两端均需兼容别名 |
| 引用标题 | `document_title/title/filename/file_name` | 是 | 是 | 卡片标题 |
| 引用片段 | `content/snippet/excerpt` | 是 | 是 | 片段预览 |
| 打开原文 | `view_url/url` | 是 | P1，必要时 P0 | 管理端核查引用时复用 |
| 片段详情 | `content_url` | 是 | P1，必要时 P0 | 原文件打不开时兜底 |
| 历史恢复 | `GET /api/chat/sessions/{id}` | 是 | 否 | sources 挂在每条 message 下 |
| 提交反馈 | `POST /api/chat/feedback` | 是 | 否 | content 非空，message_id 优先 |
| 反馈列表 | `GET /api/admin/feedback` | 否 | 是 | 管理员权限 |
| 处理反馈 | `PUT /api/admin/feedback/{id}` | 否 | 是 | 状态值需与后端枚举一致 |
| 文件鉴权 | `/api/documents/{id}/view/content/meta` | 是 | 建议 | 统一 401/403/404 行为 |

---

## 5. 对前后端提交摘要的复核结论

### 5.1 后端方向

已满足的方向：

- `/api/chat` 已执行检索，返回 `answer + sources/citations + message_id`。
- assistant 消息持久化 `sources_json`，历史会话通过 `message_to_dict` 返回 sources/citations。
- `/api/chat/feedback` 保存用户反馈、问答快照和引用快照。
- `/api/admin/feedback` 与 `PUT /api/admin/feedback/{id}` 提供管理员查看/处理能力。
- `/api/documents/{id}/view` 与 `/content` 均通过 `resolve_document_file_for_user` 做权限和路径校验。

仍需关注：

- `/api/feedback` 不是实际路由；若产品/前端文档坚持该路径，应增加兼容别名或统一文档为 `/api/chat/feedback`。
- `reviewing` 不是后端允许状态，前端类型若包含该值，应避免提交到 PUT 接口或由后端扩展枚举。
- 无命中拒答已存在，但仍需 QA 用真实空知识库/无授权用户验证不生成事实型答案。

### 5.2 前端方向

已满足的方向：

- **integration committed Chat Vue 视图尚不存在** `submitFeedback`、`/api/chat/feedback`、`openSourceFile`、消息级 `sources/citations` 消费逻辑；当前仅能看到全局 `sources` 展示。
- **integration committed Admin Vue 视图尚不存在** `loadFeedback`、`http.get('/admin/feedback')`、`updateFeedback`、`http.put('/admin/feedback/{id}')` 等反馈管理消费者。
- `FRONTEND_CHAT_ACCEPTANCE.md` 与工作区未提交 diff 中可见前端对接方向，但必须由前端同事提交并合入 integration 后才能视为已实现。

仍需关注：

- 正式入口未接入 Vue 时，这些能力不会被默认用户访问到。
- 管理员反馈详情展示引用快照，但当前未确认已复用聊天页打开原文逻辑；建议列为 P1，若管理员必须核查原文则列 P0。
- 前端字段兼容应覆盖 snake_case 与 camelCase，例如 `assistant_message_id/assistantMessageId`、`document_id/documentId`。

---

## 6. QA 最终验收重点

QA 应在 integration worktree 初始化且正式入口确定后，按以下顺序验收：

1. **正式入口**：README/docker-compose 暴露地址进入 Vue/Vite；若仍进入内嵌 `/chat`，则确认内嵌页已具备同等能力，否则 P0 不通过。
2. **RAG 强约束**：无授权文档/无命中问题返回拒答提示；有命中问题必须带 `sources/citations`。
3. **逐条引用**：连续提问两轮，每条 assistant 回复下显示各自引用，不串到全局最近引用。
4. **历史恢复**：刷新页面或打开历史会话后，之前每条 assistant 的引用仍显示。
5. **打开引用**：点击引用可打开原文或片段详情；无权限、非法 ID、路径穿越返回 403/404。
6. **反馈提交**：用户对具体 assistant 消息提交反馈，成功后 UI 显示已提交/已反馈。
7. **管理员闭环**：管理员看到反馈列表、问答快照、引用快照，并能更新状态和备注。
8. **字段兼容**：前端同时兼容 `sources/citations`、`message_id/assistant_message_id`、`view_url/url/content_url`。
9. **回归风险**：移动端、长引用列表、上传附件解析中/失败状态、登录过期 401 跳转。

---

## 7. 本轮评审失败点响应

| 失败点/建议 | 本轮响应 |
|---|---|
| integration worktree missing | 在 0.1 节明确本地 Git 证据和阻断性质；该问题需 Leader/CI 初始化，不是业务文档可单独解决 |
| 交付形式缺少结构化文档 | 新增本独立归档文档，包含入口决策、接口矩阵、P0 优先级、QA 清单 |
| P0 修复优先级不足 | 第 3 节按 P0-1 到 P0-6 排序，并给出 5 步时间线 |
| 管理端引用打开闭环 | 第 2.4、4、5.2 节明确列为 P1/条件 P0 |
| QA 验收重点散落 | 第 6 节集中列出 9 条验收重点 |
| 契约对照表缺失 | 第 4 节提供“前端消费字段 × 后端提供字段”矩阵 |
| 路径拼写疑似 `nternal-ai-assistant` | 本文统一使用实际路径 `internal-ai-assistant/...` |

---

## 8. 结论

架构结论保持不变：**Vue/Vite 应作为正式交付入口；若短期仍交付 FastAPI 内嵌 `/chat` `/admin`，必须同步补齐与 Vue 等价的消息级引用、引用打开、反馈提交和管理员反馈处理能力。**

后端接口字段总体已经具备支撑能力，但 **integration committed 前端尚未对齐**：反馈按钮、逐消息引用、引用打开和管理员反馈面板仍需前端提交并合入 integration。当前最大阻塞是“后端接口已就绪但前端消费者未集成 + 正式入口仍指向后端内嵌页”。在前端实现合入后，建议优先按第 6 节执行端到端验收。
