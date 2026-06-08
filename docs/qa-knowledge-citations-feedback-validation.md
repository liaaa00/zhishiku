# QA 验收报告：知识库引用、反馈与 UI 回归

任务历史：5b3e665d-61fb-420c-b4bd-079fb3e7dd14；最终整体验收任务：c52c1175-db65-46d2-aa85-c5be1ff5bca9  
角色：测试工程师 / QA  
日期：2026-05-28  
最终验收基线：当前 integration worktree @ `f69103b fix: allow user feedback rating`，包含前端反馈 UI、管理员反馈页与 TypeScript 修复收尾改动。  
说明：本文件为知识库引用与反馈闭环 QA 汇总；最终权威细节见 `docs/qa-final-regression-2026-05-28.md`。

---

## 1. 最终验收结论

当前状态：**最终整体验收通过，可交付。**

此前记录的阻断已解除：

- **旧 BUG-001：前端反馈提交与后端 `rating=user_feedback` 枚举不兼容。**  
  已修复并通过 `python tests\qa_final_regression.py` 验证，`rating=user_feedback` 返回 200，不再因枚举校验返回 400。

- **旧 BUG-002：有权限但语义无关问题仍返回无关引用。**  
  已修复并通过严格回归验证，语义无关问题返回无命中拒答，`source_count=0`，无 `sources/citations`。

- **旧前端阻断：`npx tsc --noEmit` 缺少 `@types/node`。**  
  已修复，当前 `npx tsc --noEmit` exit code 0。

- **旧前端阻断：聊天页缺少每条 AI 回复下反馈 UI，管理员页缺少用户反馈管理页。**  
  已修复，当前聊天正式入口已具备每条 assistant message 的引用展示、预览/打开、反馈弹窗与 `/chat/feedback` 提交；管理员页已具备反馈列表、详情、问题/回答/引用快照与 `reviewed/resolved` 审核流转。

阻断项：**无**。

---

## 2. 可复现命令与结果

### 2.1 后端严格最终回归

目录：`internal-ai-assistant/backend`

```powershell
python tests\qa_final_regression.py
```

结果：通过。

```text
QA final regression passed.
```

覆盖：

- `rating=user_feedback` 反馈提交；
- 有权限但语义无关问题无命中拒答；
- `/api/chat` 的 `message_id`、`assistant_message_id`、`sources/citations`、`view_url/content_url` 契约；
- `/api/documents/{id}/content` 与 `/view` 鉴权、权限、chunk 读取和路径安全；
- `/api/chat/feedback` 保存 question/answer/sources 快照；
- `/api/admin/feedback` 列表、详情、`reviewed/resolved` 审核状态流转。

### 2.2 前端 TypeScript

目录：`internal-ai-assistant/frontend`

```powershell
npx tsc --noEmit
```

结果：通过，exit code 0。

### 2.3 前端构建

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

非阻塞警告：

- `node_modules/@vueuse/core/dist/index.js` 中部分 `/* #__PURE__ */` 注释位置 Rollup 无法解释，构建会移除相关注释。
- Vite 提示部分 chunk 压缩后大于 500 kB；当前主 JS chunk 约 1,099.79 kB，gzip 约 364.35 kB。

---

## 3. 前端静态覆盖结果

### 3.1 聊天正式入口

检查文件：`internal-ai-assistant/frontend/src/views/chat/index.vue`

通过点：

- `/chat` 返回后，前端使用：

```ts
id: data.message_id || data.assistant_message_id || messageId('assistant')
sources: normalizeSourceList(data.sources, data.citations)
```

将 assistant 消息 ID 和引用快照绑定到该条 AI 回复。

- 模板在 `message.role === 'assistant'` 时渲染该条消息下的 `source-section`。
- 引用列表使用 `message.sources`，因此是每条 AI 回复下的对应引用，而非页面级全局引用。
- 点击引用触发 `previewSource(source)`，通过 `content_url` 优先预览内容；“打开知识库文件”通过 `view_url` 打开原文。
- 每条 AI 回复下渲染 `feedback-section`，提供反馈按钮和弹窗。
- `submitFeedback()` 调用 `/chat/feedback`，提交 `session_id`、assistant `message_id`、`rating` 和用户反馈文本 `content`。

结论：通过。

### 3.2 引用工具

检查文件：`internal-ai-assistant/frontend/src/utils/source-utils.ts`

通过点：

- `normalizeSourceList()` 兼容 `sources` / `citations`。
- `sourcePreviewUrl()` 优先使用 `content_url`。
- `sourceOpenUrl()` 优先使用 `view_url`。
- `sourceSnippet()` 兼容 `content` / `snippet` / `excerpt`。

结论：通过。

### 3.3 管理员反馈页

检查文件：`internal-ai-assistant/frontend/src/views/admin/index.vue`

通过点：

- 存在“用户反馈”标签页。
- `loadFeedback()` 调用 `GET /admin/feedback` 并支持状态过滤。
- 列表展示反馈内容、问题快照、回答快照、引用快照概览和状态。
- `openFeedbackDialog()` 调用 `GET /admin/feedback/{id}` 展示详情。
- 详情弹窗展示反馈内容、管理员备注、问题、回答、完整 sources 引用快照。
- `updateFeedback()` 调用 `PUT /admin/feedback/{id}` 保存状态与备注。
- `quickUpdateFeedback()` / `saveFeedbackReview()` 支持 `reviewed`、`resolved` 等审核流转。

结论：通过。

---

## 4. 验收用例矩阵

| ID | 场景 | 当前结果 |
|---|---|---|
| TC-01 | 知识库命中回答返回引用 | 通过 |
| TC-02 | 每条 AI 回复下显示对应引用文件 | 通过 |
| TC-03 | 引用支持 `content_url` 预览与 `view_url` 打开 | 通过 |
| TC-04 | 历史会话 assistant 引用保留 | 通过 |
| TC-05 | 无权限访问引用/文档 | 通过 |
| TC-06 | 未登录访问 content/view | 通过 |
| TC-07 | 文件路径越权拦截 | 通过 |
| TC-08 | 反馈空内容/超长内容校验 | 通过 |
| TC-09 | `rating=user_feedback` 提交反馈 | 通过 |
| TC-10 | 反馈保存 question/answer/sources 快照 | 通过 |
| TC-11 | 管理员查看反馈列表/详情 | 通过 |
| TC-12 | 管理员审核 `reviewed/resolved` | 通过 |
| TC-13 | 有权限但语义无关问题无命中拒答 | 通过 |
| TC-14 | 前端 `npx tsc --noEmit` | 通过 |
| TC-15 | 前端 `npm run build` | 通过，存在非阻塞警告 |

---

## 5. 最终可交付结论

当前 integration worktree 已达到知识库引用、反馈闭环和管理员反馈审核的最终验收标准：

- 后端严格回归通过；
- 前端 TypeScript 与生产构建通过；
- 用户端聊天入口闭环通过；
- 管理员端反馈处理闭环通过；
- 剩余构建警告均为非阻塞优化项。

**结论：通过，可交付。**
