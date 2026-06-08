# AI 修改记录

> 用途：记录 AI 修改过什么、为什么改、验证过什么、有哪些遗留风险。新对话或长时间后继续时必须先读。

## 2026-06-08：建立项目修改安全机制

### 背景

用户要求把另一个项目中使用的“修改前必读 + 回归清单 + 修改记录 + 可按 commit 安全回退”机制迁移到本项目。

### 新增文档

- `docs/AI修改前必读.md`
- `docs/业务规则回归清单.md`
- `docs/AI修改记录.md`

### 写入的重要规则

- 用户最新明确指令优先；固定规则不是不可改规则。
- 本项目前端端口是 `5174`。
- `5173` 属于其他项目/程序，不允许操作。
- 后端端口是 `8000`。
- 目标 GitHub 仓库：`https://github.com/liaaa00/zhishiku.git`
- 修改前应读三份文档。
- 修改后根据范围跑回归测试。
- 提交/推送必须先经用户明确要求。
- 回退优先使用 `git revert`，不优先使用 `git reset --hard`。

### 验证

- 已确认当前项目此前没有这三份固定规则文档。
- 已通过 SpectrAI 文件工具创建，避免中文编码问题。

### 注意

当前工作区存在大量未提交改动。后续如需提交到 GitHub，应先整理：

1. 查看 `git status --short`
2. 确认 remote 是否配置到 `https://github.com/liaaa00/zhishiku.git`
3. 跑回归测试
4. 分批或整体 commit
5. 用户确认后 push

---

## 近期重要问题记录：端口与进程

### 现象

用户多次遇到：

- 前端窗口还在，但 `5174` 服务实际已停止
- 浏览器显示 `Failed to fetch`
- 后端曾有多个 uvicorn reload 父子进程残留，导致旧代码和新代码混跑

### 结论

- `Failed to fetch` 优先检查 `5174` 是否还在。
- 后端空闲不会自动停止。
- 多个旧 uvicorn 进程会导致调试混乱。
- 只允许清理能确认属于本项目的 `8000` / `5174` 进程。
- 不允许操作 `5173`。

---

## 近期重要问题记录：聊天路由

### 问题 1：助手身份问题误调用知识库

示例：

```text
你是谁？你可以做什么
```

曾被误判为知识库问题，返回“知识回答/来源片段”。

处理方向：

- 助手身份/能力问题优先走普通对话。

### 问题 2：无上下文编辑请求误检索知识库

示例：

```text
把内容整理成表格
```

曾因为“表格/整理”触发知识库检索，命中无关文档，甚至出现错误。

处理方向：

- 新窗口无上下文的整理/改写/翻译/总结类请求走普通模型。
- 模型应追问用户提供要整理的具体内容。
- 明确出现“文档/知识库/资料/附件/公司数据”等锚点时，才走知识库。

### 问题 3：PageIndex chunk_index 字符串导致异常

异常：

```text
ValueError: invalid literal for int() with base 10: 'pageindex:0000'
```

原因：

- PageIndex 来源的 `chunk_index` 可能是字符串。
- 结构化摘要排序时不能强制 `int()`。

处理方向：

- 对 `chunk_index` 使用安全排序函数。

---

## 近期重要问题记录：来源展示

### 现象

回答正文曾出现：

```text
[来源1][来源2]
```

用户认为突兀且不可点击。

处理方向：

- 正文不输出 `[来源1]`。
- 来源统一在独立来源面板展示。
- “当前分节”改为“相关来源”。
- “打开文档”应使用带鉴权的请求，Office 文件可下载。

---

## 近期重要问题记录：PageIndex/RAG

### 用户偏好

- 用户认为传统 RAG 偏落后，希望融合 PageIndex。
- 用户希望尽量全部文件都用 PageIndex。
- 回答优先来自 PageIndex 结构树，普通检索作为补充。
- 扫描版 PDF 走 OCR / 视觉解析。

### 注意

- PageIndex 可能增加解析成本和耗时。
- 问答速度受检索范围、模型速度、上下文长度、PageIndex 结构规模、向量库状态影响。

---

## 回退约定

用户可说：

```text
这次改错了，撤回刚才这次修改，用安全回退。
```

默认流程：

1. 查看最近 commit。
2. 使用 `git revert <commit>`。
3. 跑相关回归测试。
4. 更新本修改记录。
5. 用户确认后提交/推送。

除非用户明确要求，不执行 `git reset --hard`。

---

## 2026-06-08：发布整理阶段 A 草稿

### 背景

团队任务要求在其他架构、后端、前端、QA 成员完成前，先由 Git 发布整理角色检查当前工作区，识别可提交改动与本地/运行产物，并准备最终提交前的验证计划。本阶段不提交、不推送。

### 已执行检查

- 已阅读 `internal-ai-assistant/docs/AI修改前必读.md`、`internal-ai-assistant/docs/业务规则回归清单.md`、`internal-ai-assistant/docs/AI修改记录.md`。
- 已执行 `git status --short`、`git log --oneline -5`、`git remote -v`、`git diff --stat`。
- 当前 `remote` 尚未配置；阶段 B 若无阻断，将按规则配置 `origin` 到 `https://github.com/liaaa00/zhishiku.git`。

### 初步提交候选范围

- 后端：RAG/PageIndex、上传与文档解析、聊天路由、鉴权与后台管理拆分相关源码。
- 前端：聊天页、后台页、登录页、路由守卫、Vite 5174 端口与代理、样式与 favicon。
- 文档：项目规则文档、规格文档、QA/架构阶段报告、发布整理记录。
- 测试/脚本：后端 QA 回归脚本、启动脚本、PageIndex 可选安装脚本。
- 配置：`.env.example`、`.gitignore`、README 中与 200MB 上传限制、PageIndex、生产安全检查相关说明。

### 明确排除/忽略项

已将以下本地或外部产物加入 `.gitignore`，后续不纳入暂存：

- `.claude/`：本地助手配置，包含本机命令与示例密钥字样。
- `internal-ai-assistant/.runlogs/`：运行日志。
- `internal-ai-assistant/.runtime/`：本地启动/集成临时文件。
- `internal-ai-assistant/third_party/`：外部 PageIndex 源码下载目录，内部含嵌套 `.git` 与示例文档；项目仅保留可选安装脚本和依赖说明。
- 既有忽略项继续排除：`.env`、`backend/data/`、`node_modules/`、`dist/`、`__pycache__/`、`*.pyc`、`*.zip`、`MaxKB-src/`、`.spectrai-worktrees/`。

### 阶段 B 前验证计划

待架构、后端、前端、QA 均反馈无发布阻断后，最终提交前至少执行：

1. `python -m compileall app`（工作目录：`internal-ai-assistant/backend`）。
2. `npm run build`（工作目录：`internal-ai-assistant/frontend`）。
3. 结合 QA 结论补充接口/页面回归结果；如服务可用，检查 `8000/api/health`、`5174/chat`、`5174/admin` 以及业务规则清单中的聊天/知识库/PageIndex 最小用例。
4. 复查 `git status --short` 和暂存清单，确认不包含日志、缓存、本地配置、敏感配置或外部源码下载目录。

### 当前风险/待确认

- 当前工作区改动规模较大，需等待各成员确认各自范围无阻断后再提交。
- 远程未配置，阶段 B 推送前需配置 `origin`。
- `.env.example` 仅含占位值，未发现真实 API Key；真实 `.env` 已被忽略。
- 架构统筹补充：remote 当前为空；阶段 B 放行后需配置 `origin=https://github.com/liaaa00/zhishiku.git` 并推送 `master`。
- 架构统筹补充：排除项必须覆盖 `internal-ai-assistant/.env`、`.claude/settings.local.json`、`internal-ai-assistant/.runtime/`、`internal-ai-assistant/.runlogs/`、`internal-ai-assistant/backend/data/`、`internal-ai-assistant/third_party/PageIndex/`、`__pycache__/`、`*.pyc`、`node_modules/`、`dist/`、`MaxKB-src/`、`*.zip`、`.spectrai-worktrees/`、`bad-frontend-ui-status.txt`、`bad-frontend-ui.diff`。

---

## 2026-06-08：发布整理阶段 A 评审返工

### 返工原因

评审反馈 integration 视图未看到阶段 A 发布整理证据，且当前 HEAD 中存在 `bad-frontend-ui-status.txt`、`bad-frontend-ui.diff` 临时诊断文件风险。为提高可追溯性，本次在当前工作区补齐根目录 `docs/` 入口文档，并清理临时诊断文件。

### 本次返工动作

- 确认三份详细规则文档实际位于 `internal-ai-assistant/docs/`。
- 新增根目录入口文档：
  - `docs/AI修改前必读.md`
  - `docs/业务规则回归清单.md`
  - `docs/AI修改记录.md`
- 删除临时诊断文件：
  - `bad-frontend-ui-status.txt`
  - `bad-frontend-ui.diff`
- `.gitignore` 补充同类临时诊断文件忽略规则，避免再次进入最终发布提交。

### 合规/排除清单更新

- 可纳入候选：项目源码、规则文档、QA/架构报告、后端测试脚本、启动/安装脚本、README、`.env.example`、`.gitignore`。
- 明确排除：`.claude/`、`internal-ai-assistant/.runlogs/`、`internal-ai-assistant/.runtime/`、`internal-ai-assistant/third_party/`、真实 `.env`、`internal-ai-assistant/backend/data/`、`node_modules/`、`dist/`、`__pycache__/`、`*.pyc`、`.spectrai-worktrees/`、`*.zip`、`MaxKB-src/`、`bad-frontend-ui-status.txt`、`bad-frontend-ui.diff`。

### 阶段 B 状态

截至返工时，架构、后端、前端、QA 依赖任务仍未全部完成并明确无阻断，因此不运行最终验证、不暂存、不提交、不推送。阶段 B 放行后再补写验证结果与提交哈希。

### 编码与集成状态说明

- 六份中文规则/记录文档均可用 Python `Path.read_text(encoding="utf-8")` 正常读取，文件内容按 UTF-8 保存；PowerShell 默认控制台可能显示乱码，不代表文件编码异常。
- 若 `master..HEAD` 或 integration git log 暂无提交差异，阶段 A 证据当前体现为工作树可核验文件：根目录 `docs/` 三份入口、`internal-ai-assistant/docs/` 三份详细文档、`.gitignore` 排除规则、`bad-frontend-ui-status.txt` 与 `bad-frontend-ui.diff` 删除状态。
- 阶段 B 放行前必须重新核验这些工作树证据是否仍存在；若集成状态未保留，应先恢复阶段 A 整理记录，再执行最终验证和发布。

### 阶段 B 最终清单模板（待放行后执行）

- 合规提交候选：项目源码、规则文档、AI 修改记录、QA/架构报告、后端测试脚本、启动/安装脚本、README、`.env.example`、`.gitignore`。
- 排除项：`internal-ai-assistant/.env`、`.claude/settings.local.json`、`internal-ai-assistant/.runtime/`、`internal-ai-assistant/.runlogs/`、`internal-ai-assistant/backend/data/`、`internal-ai-assistant/third_party/PageIndex/`、`__pycache__/`、`*.pyc`、`node_modules/`、`dist/`、`MaxKB-src/`、`*.zip`、`.spectrai-worktrees/`、`bad-frontend-ui-status.txt`、`bad-frontend-ui.diff`。
- 验证命令：`python -m compileall app`（`internal-ai-assistant/backend`）和 `npm run build`（`internal-ai-assistant/frontend`），并结合 QA/范围门禁结论补充可用接口/页面验证。
- 远程与发布：若 remote 为空，配置 `origin=https://github.com/liaaa00/zhishiku.git`；只暂存合规文件；创建规范 commit；推送 `master`；记录提交哈希、推送结果、验证结果、提交/排除清单。

---

## 2026-06-08：实际阶段 B 最终验证与发布记录

### 发布前状态

- 当前分支：`master`。
- 当前 HEAD：`756d1ab`（发布前）。
- `git remote -v` 为空；提交前需配置 `origin=https://github.com/liaaa00/zhishiku.git`。
- 阶段 A 记录和 `.gitignore` 已明确排除真实 `.env`、运行日志、本地配置、第三方源码、构建产物、缓存与临时诊断文件。

### 最终验证结果

- `python -m compileall app`（`internal-ai-assistant/backend`）：通过。
- `python tests/qa_api_validation.py`：通过，输出 `QA API validation passed`。
- `python tests/qa_final_regression.py`：通过，输出 `QA final regression passed`。
- `python tests/qa_priority_2_4_regression.py`：通过，输出 `Priority 2-4 regression passed`。
- `python tests/qa_performance_api.py`：通过，输出 `QA performance API checks passed`。
- `python tests/qa_final_regression_other_rating.py`：通过，输出 `QA final regression passed`。
- `npm run build`（`internal-ai-assistant/frontend`）：通过；Vite 构建完成，存在 chunk size warning 和 VueUse 注释 warning，不阻断发布。
- Smoke：`http://127.0.0.1:8000/api/health` 返回 200。
- Smoke：`127.0.0.1:5174` 未监听，因此 `5174/api/health`、`5174/chat`、`5174/admin` 无法连接；未启动或操作 5173。由于 5174 服务未运行且无有效浏览器登录态，本轮未覆盖登录态页面深度 smoke；风险纳入发布摘要。

### 提交范围计划

- 纳入：已 accepted/merged 的后端源码与测试、前端源码、README、docs、scripts、`.gitignore`、`.env.example`、`requirements-pageindex.txt`、`bad-frontend-ui-status.txt` 与 `bad-frontend-ui.diff` 的删除状态。
- 排除：`internal-ai-assistant/.env`、真实密钥、`.claude/`、`.runtime/`、`.runlogs/`、`backend/data/`、`third_party/PageIndex/`、`node_modules/`、`dist/`、`__pycache__/`、`*.pyc`、`.pytest_cache/`、`MaxKB-src/`、`*.zip`、`.spectrai-worktrees/`、Vite smoke 日志/截图和其他临时调试文件。
