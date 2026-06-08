# 前端聊天 UI 与流式状态审查返工报告

> 返工基准：`D:\AI\SpeceAppDate\知识库\.spectrai-worktrees\integrations\47875d61-a482-44a6-b96b-5eb26d06aa3c\internal-ai-assistant`。本轮修复以 integration worktree 实际代码为准。

## 修改与审查结果

### frontend/src/views/chat/index.vue
- 现象：原 integration 代码只用 axios `POST /chat`，没有 `/api/chat/stream` 流式读取、三阶段等待提示、delta 后隐藏 pending、取消/卸载清理，也没有流异常中断提示。
- 影响：慢检索/慢模型时用户只能看到静态等待；切换会话或离开页面后旧请求仍可能写回状态；流式契约无法验证。
- 优先级：P1。
- 已修复：
  - 实现 `sendWithStream()`：优先请求 `/api/chat/stream`，解析 `status/meta/delta/done` SSE。
  - 当前 integration 后端没有 `/api/chat/stream`，因此 404/405/无流式 body 会兼容回退到现有 `/api/chat`，不改变后端契约。
  - 初始提示为“正在连接知识库…”。
  - `status/retrieving` 或回退路径显示“正在检索知识库并组织回答（已等待 X 秒）”。
  - `meta` 或 `status/generating` 显示“已找到可用资料，正在调用模型组织回答…（已等待 X 秒）”。
  - `delta` 或回退 answer 正文开始输出时清空 `pendingText`，等待提示消失。
  - 新增 `AbortController`、`cancelActiveStream()`、`onUnmounted()`；新建对话、打开历史、退出、取消按钮、组件卸载都会中断当前请求。
  - 计时器在正文出现或 finally 中清理；流异常且已有正文时追加“发送中断：原因”。
  - 对 AI 文本做 `escapeHtml` 后再进行有限 markdown 替换，避免原 `v-html` 直接渲染后端内容。
  - 保留引用/摘要模式展示兼容字段：`sources/citations/references`、`citation_mode`、`summary_mode`、`document_count`。
- 验证状态：`npm run build` 通过。未做浏览器手测和真实后端联调；原因是本轮仅执行非破坏性命令，且 integration 后端当前无流式接口。

### frontend/src/api.ts
- 现象：原 integration 只有请求拦截器，没有 401 响应清理和跳转。
- 影响：token 失效时可能停留在聊天页并反复失败。
- 优先级：P1/P2。
- 已修复：增加响应拦截器，401 时清理 `token/user` 并跳转 `/login`。
- 验证状态：`npm run build` 通过。

### frontend/src/router.ts
- 现象：原 integration 路由无鉴权守卫，未登录可进入 `/chat` 和 `/admin`。
- 影响：前端权限体验不一致；后端虽会拦截接口，但页面可直接打开。
- 优先级：P2。
- 已修复：增加 `/chat`、`/admin` 的 `requiresAuth`；`/admin` 需要本地 admin 且通过 `/api/me` 校验；登录态访问 `/login` 会校验后跳 `/chat`。
- 验证状态：`npm run build` 通过。

### frontend/vite.config.ts
- 现象：原 integration 固定 5173 且没有 `/api` 代理。
- 影响：前端 dev server 直连时 API 请求无法稳定转发；与启动脚本目标不一致。
- 优先级：P2。
- 已修复：端口改为 5174，`strictPort: true`，`/api` 代理到 `http://localhost:8000`。
- 验证状态：`npm run build` 通过。

### scripts/start-latest.ps1
- 现象：integration 中 scripts 目录不存在，缺少一键启动脚本。
- 影响：用户无法通过脚本保证关闭旧窗口并用最新代码启动后端/前端。
- 优先级：P2。
- 已修复：新增脚本，停止 8000/5174 的 Listen 进程，启动后端 `uvicorn app.main:app --port 8000 --reload` 和前端 Vite 5174，并打开 `/chat`。
- 验证状态：未执行脚本，避免启动长期后台窗口；已做文本检查。

## 验证
- `npm install`：成功，added 87 packages，found 0 vulnerabilities。
- `npm run build`：成功，Vite 6.4.3，1669 modules transformed，built in 14.69s。
- 构建警告：`@vueuse/core` PURE 注释警告、单个 chunk > 500 kB。均不是本次功能阻断；大 chunk 属 P3 性能技术债。
- 未执行：浏览器 UI 手测、真实 `/api/chat/stream` 联调、慢模型超时；当前 integration 后端没有 `/api/chat/stream`，前端会回退 `/api/chat`。

## 手工验收步骤
1. 关闭旧后端和前端窗口。
2. 在项目根目录运行：`powershell -ExecutionPolicy Bypass -File scripts/start-latest.ps1`，或使用桌面快捷方式指向该脚本。
3. 打开 `http://localhost:5174/chat` 登录。
4. 发送普通问题：应先显示“正在连接知识库…”，随后显示“正在检索知识库并组织回答（已等待 X 秒）”；如果后端返回来源，则显示“已找到可用资料，正在调用模型组织回答…（已等待 X 秒）”；正文出现后等待提示消失。
5. 发送过程中点击“取消”、新对话、历史会话或退出：请求应中断，不应把旧回答写入新会话。
6. 若未来后端补齐 `/api/chat/stream`：验证 delta 逐步输出和 done 后引用/来源展示。
