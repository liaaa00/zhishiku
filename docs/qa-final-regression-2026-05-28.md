# QA 最终整体验收：前端闭环合入后复测知识库引用、反馈 UI、管理员反馈页与类型构建

任务 ID：c52c1175-db65-46d2-aa85-c5be1ff5bca9  
执行角色：QA  
日期：2026-05-28  
验收基线：当前 integration worktree，HEAD `f69103b fix: allow user feedback rating`。本轮基于该 worktree 中已合入的前端反馈 UI、管理员反馈页、`@types/node`/tsc 收尾改动执行验收。  
约束：仅执行 QA 验证与文档更新，未修改后端/前端业务实现。

---

## 1. 最终结论

**最终整体验收通过，当前 integration worktree 可交付。**

此前 QA 报告中的前端阻断项已解除：

1. `npx tsc --noEmit` 已通过，`@types/node` 相关类型阻断解除。
2. `npm run build` 已通过。
3. Vue 聊天正式入口已在每条 AI 回复下展示该回复自己的知识库引用文件，并支持 `content_url` 预览与 `view_url` 打开。
4. 每条 AI 回复下已具备反馈按钮/弹窗，可向 `/api/chat/feedback` 提交反馈。前端提交 `message_id`、`rating`、用户反馈文本 `content`；其中 `message_id` 使用 `/api/chat` 返回的 assistant 消息 ID（`message_id` / `assistant_message_id`）。引用快照由后端按该 assistant 消息 ID 从消息 `sources_json` 保存，并已由严格回归脚本验证。
5. 管理员反馈页已具备列表、详情、问题/回答/引用快照展示，并可审核流转 `reviewed`、`resolved`。
6. 后端严格回归脚本仍通过，覆盖 `rating=user_feedback`、无关问题无命中拒答、`sources/citations`、`content/view` 鉴权与路径安全、反馈快照和管理员审核流转。

阻断项：**无**。

非阻塞警告：仅保留 Vite/Rollup 构建警告，详见第 6 节。

---

## 2. 本轮执行命令与结果

### 2.1 integration 基线确认

```powershell
git status --short
git branch --show-current
git rev-parse --short HEAD
git log -1 --oneline
```

结果摘要：

- 当前分支：`master`
- 当前 HEAD：`f69103b`
- 最新提交：`f69103b fix: allow user feedback rating`
- worktree 包含前端收尾与 QA 文档/脚本改动，符合本任务“基于当前 integration worktree”验收范围。

### 2.2 后端严格最终回归

目录：`internal-ai-assistant/backend`

```powershell
python tests\qa_final_regression.py
```

结果：通过。

```text
QA final regression passed.
```

覆盖并通过：

- `/api/chat/feedback` 接受 `rating=user_feedback`，不再返回枚举不兼容 400。
- 用户有权限但问题与知识库内容无关时，返回无命中拒答，`source_count=0`，不返回无关 `sources/citations`。
- `/api/chat` 返回 `message_id`、`assistant_message_id`、`user_message_id`、`sources`、`citations`、`view_url`、`content_url`。
- 历史会话 assistant 消息保留 `sources/citations`。
- `/api/documents/{id}/content` 未登录 401、授权 200、错误 chunk 404、无权限 404。
- `/api/documents/{id}/view` 授权 200、无权限 404，并对 upload 根目录外 `storage_path` 返回 403。
- `/api/chat/feedback` 校验空内容/超长内容/错用户 message_id，并保存问题、回答、sources 快照。
- `/api/admin/feedback` 列表、`/api/admin/feedback/{id}` 详情、`reviewed` 与 `resolved` 审核状态流转通过。

### 2.3 前端 TypeScript

目录：`internal-ai-assistant/frontend`

```powershell
npx tsc --noEmit
```

结果：通过，exit code 0。

### 2.4 前端生产构建

目录：`internal-ai-assistant/frontend`

```powershell
npm run build
```

结果：通过，exit code 0。

输出摘要：

```text
vite v6.4.2 building for production...
✓ 1667 modules transformed.
✓ built in 7.78s
```

产物体积摘要：

- CSS：`dist/assets/index-rTgdWx5d.css`，约 367.80 kB，gzip 49.97 kB。
- JS：`dist/assets/index-BN_NWMeY.js`，约 1,099.79 kB，gzip 364.35 kB。

---

## 3. 后端契约验收结果

严格脚本 `internal-ai-assistant/backend/tests/qa_final_regression.py` 已作为后端最终契约验收依据。脚本验证点包括：

| 验收点 | 结果 |
|---|---|
| `rating=user_feedback` 提交反馈 | 通过 |
| 有权限但语义无关问题无命中拒答 | 通过 |
| `/api/chat` 返回 `message_id` / `assistant_message_id` | 通过 |
| `/api/chat` 返回 `sources` / `citations` | 通过 |
| 引用包含 `view_url` / `content_url` | 通过 |
| `/api/documents/{id}/content` 鉴权、权限、chunk 读取 | 通过 |
| `/api/documents/{id}/view` 鉴权、权限、文件响应 | 通过 |
| upload 根目录外路径安全拦截 | 通过 |
| `/api/chat/feedback` 保存 question/answer/sources 快照 | 通过 |
| `/api/admin/feedback` 列表/详情 | 通过 |
| 管理员审核 `reviewed` / `resolved` | 通过 |

后端契约结论：**通过，可交付**。

---

## 4. 前端聊天入口验收结果

检查文件：`internal-ai-assistant/frontend/src/views/chat/index.vue`  
公共引用工具：`internal-ai-assistant/frontend/src/utils/source-utils.ts`

### 4.1 每条 AI 回复下展示对应引用

已通过源码与构建验证：

- 聊天页在 `message.role === 'assistant'` 时渲染 `assistant-tools`。
- 每条 assistant message 内部渲染 `source-section` 和 `source-list`。
- 发送 `/chat` 后，前端将 `normalizeSourceList(data.sources, data.citations)` 写入该 assistant message 的 `sources` 字段，而不是页面级全局 sources。
- 因此 UI 展示的是每条 AI 回复自己的引用列表。

结论：**通过**。

### 4.2 `content_url` 预览与 `view_url` 打开

已通过源码与构建验证：

- 点击引用触发 `previewSource(source)`。
- `loadSourcePreview(source)` 调用 `sourcePreviewUrl(source)`。
- `sourcePreviewUrl()` 优先使用 `content_url`，其次使用 `view_url` / `url`。
- 预览接口返回 `content`、`snippet`、`excerpt` 或 `chunks` 时，前端在抽屉中展示片段内容。
- “打开知识库文件”触发 `openSourceFile(source)`。
- `sourceOpenUrl()` 优先使用 `view_url`，其次使用 `url` / `content_url`，并通过 `window.open()` 打开。

结论：**通过**。

### 4.3 每条 AI 回复下反馈按钮/弹窗与提交

已通过源码、TypeScript 和后端脚本验证：

- 每条 assistant message 下渲染 `feedback-section`。
- 提供“有帮助 / 不够好 / 输入反馈”等按钮。
- `openFeedback(message, rating)` 打开反馈弹窗，并绑定当前 assistant message。
- `submitFeedback()` 调用：

```ts
http.post('/chat/feedback', {
  session_id: sessionId.value || null,
  message_id: feedbackTarget.value.id,
  rating: feedbackForm.rating || 'user_feedback',
  content,
})
```

说明：前端提交体包含 `message_id`、`rating` 和用户反馈文本 `content`。其中 `message_id` 的值来自 `/api/chat` 返回的 assistant 消息 ID：

```ts
id: data.message_id || data.assistant_message_id || messageId('assistant')
```

后端以该 assistant message id 定位消息并保存 question/answer/sources 快照；严格回归脚本已验证管理员列表与详情中存在问题、回答和 sources 快照。

结论：**通过**。

---

## 5. 管理员反馈页验收结果

检查文件：`internal-ai-assistant/frontend/src/views/admin/index.vue`

已通过源码、TypeScript、构建与后端脚本验证：

- 管理员页存在“用户反馈”标签页。
- `loadFeedback()` 调用 `GET /admin/feedback`，支持按状态过滤。
- 列表展示反馈用户、rating、反馈内容、问题快照、回答快照、引用快照概览和状态。
- `openFeedbackDialog(item)` 调用 `GET /admin/feedback/{id}` 加载详情。
- 详情弹窗展示：反馈内容、管理员备注、问题快照、回答快照、完整引用 sources 快照。
- `updateFeedback()` 调用 `PUT /admin/feedback/{id}` 更新审核状态和备注。
- `quickUpdateFeedback()` 可快速将 `new` 更新为 `reviewed`。
- `saveFeedbackReview()` 可保存 `reviewed`、`resolved` 等处理结果。
- 后端严格回归脚本已验证 `reviewed` 与 `resolved` 两个状态流转均返回 200 且状态正确。

结论：**通过**。

---

## 6. 非阻塞警告记录

`npm run build` 仍存在以下非阻塞警告，不影响本次验收通过：

1. `node_modules/@vueuse/core/dist/index.js` 中部分 `/* #__PURE__ */` 注释位置 Rollup 无法解释，构建会移除相关注释以避免问题。
2. Vite 提示部分 chunk 压缩后大于 500 kB：当前主 JS chunk 约 1,099.79 kB，gzip 约 364.35 kB。

建议后续性能优化时考虑动态导入或 `build.rollupOptions.output.manualChunks`，但这不是当前知识库引用/反馈闭环的交付阻断项。

---

## 7. 最终验收矩阵

| ID | 场景 | 结果 | 证据 |
|---|---|---|---|
| TC-01 | 后端严格最终回归脚本 | 通过 | `python tests\qa_final_regression.py` 输出 `QA final regression passed.` |
| TC-02 | `rating=user_feedback` | 通过 | 严格脚本覆盖，返回 200 |
| TC-03 | 语义无关但有权限问题无命中拒答 | 通过 | 严格脚本覆盖，`source_count=0` 且无 `sources/citations` |
| TC-04 | `/api/chat` 返回 message 与引用契约 | 通过 | 严格脚本覆盖 `message_id`、`assistant_message_id`、`sources/citations`、`view_url/content_url` |
| TC-05 | content/view 鉴权、权限、路径安全 | 通过 | 严格脚本覆盖 401/200/404/403 |
| TC-06 | 反馈快照保存 | 通过 | 严格脚本覆盖管理员列表/详情含 question/answer/sources |
| TC-07 | 管理员审核流转 | 通过 | 严格脚本覆盖 `reviewed`、`resolved` |
| TC-08 | 前端 TypeScript | 通过 | `npx tsc --noEmit` exit code 0 |
| TC-09 | 前端生产构建 | 通过 | `npm run build` exit code 0 |
| TC-10 | 每条 AI 回复下引用展示 | 通过 | `chat/index.vue` 按 assistant message 渲染 `message.sources` |
| TC-11 | 引用 `content_url` 预览与 `view_url` 打开 | 通过 | `source-utils.ts` + `chat/index.vue` 预览/打开逻辑 |
| TC-12 | 每条 AI 回复下反馈按钮/弹窗 | 通过 | `chat/index.vue` 的 `feedback-section`、`openFeedback()`、`submitFeedback()` |
| TC-13 | 管理员反馈列表/详情/审核页 | 通过 | `admin/index.vue` 的 `loadFeedback()`、`openFeedbackDialog()`、`updateFeedback()` |

---

## 8. 可交付结论

当前 integration worktree 已满足本次最终整体验收条件：

- 后端知识库引用、无命中拒答、文件查看、反馈保存、管理员审核闭环通过严格回归。
- 前端类型检查与生产构建通过。
- 用户端聊天入口具备每条 AI 回复的引用展示、预览/打开、反馈提交闭环。
- 管理员端具备反馈列表、详情、快照查看与审核状态流转。

**结论：通过，可交付。**
