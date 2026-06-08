# QA 验收计划：优先级 2-4 与风险收敛

任务 ID：0c8bfc76-e9bf-4091-bac1-9ed680b06107  
角色：测试工程师  
日期：2026-05-29  
验证基线：integration worktree `D:\AI\SpeceAppDate\知识库\.spectrai-worktrees\integrations\e67c4d14-e561-4cf0-afcb-75c7573485d5`  
说明：本文件先定义可复用验收清单；最终结果以 integration worktree 的复测命令与报告为准。

## 1. 目标

按以下顺序收敛风险并完成验收：
1. 先覆盖上一轮遗留风险：页面覆盖范围限制、`check:performance` 纳入验收、性能不退化。
2. 验证优先级 2：`/api/chat` sources/citations 的高亮片段、定位、相关度/命中原因字段，以及前端引用高亮/点击预览定位。
3. 验证优先级 3：无知识库依据时明确提示且不编造，前端也有依据不足提示。
4. 验证优先级 4：用户反馈分类提交、管理员按分类/状态筛选、更新状态和处理备注。
5. 最终在 integration worktree 上跑完后端、前端、性能相关验收命令，输出可交付 QA 报告。

## 2. 固定验收环境

- 后端目录：`internal-ai-assistant/backend`
- 前端目录：`internal-ai-assistant/frontend`
- integration HEAD：`f69103b`
- 后端服务：`http://localhost:8080`
- 前端预览：`http://127.0.0.1:4173`

## 3. 可复用验收清单

### 3.1 优先级 2：引用与高亮闭环
- `/api/chat` 返回 `message_id` / `assistant_message_id`。
- `/api/chat` 返回 `sources` 与 `citations`。
- 引用对象包含高亮片段或可等价定位信息：`content` / `snippet` / `excerpt` / `highlighted_text` / `match_text`。
- 引用对象包含相关度或命中原因字段：`score` / `relevance_score` / `similarity` / `confidence`，以及 `match_reason` / `reason` / `hit_reason`。
- 前端聊天页每条 assistant 回答都展示对应来源列表。
- 点击来源可打开预览抽屉，并能定位到对应内容。
- “打开知识库文件”动作优先使用 `view_url`。

### 3.2 优先级 3：无依据不编造
- 无命中时返回明确的无命中/拒答语义。
- 不返回伪造 `sources` / `citations`。
- 前端显示“依据不足/未命中”类提示，不误导为有证据回答。

### 3.3 优先级 4：反馈闭环
- 用户可提交反馈，包含分类/评分与内容。
- 管理员可按状态筛选反馈。
- 管理员可按关键词筛选反馈。
- 管理员可查看反馈详情、问题快照、回答快照和来源快照。
- 管理员可更新状态为 `reviewed` / `resolved` 并保存备注。

### 3.4 风险收敛项
- 页面覆盖范围仍需确认：`/login`、`/chat`、`/admin` 均可启动且不白屏。
- `check:performance` 必须纳入最终验收，不接受仅 build 通过。
- 构建产物不得出现新的 >500 KiB 关键 JS chunk 回退。

## 4. 最终执行命令

### 4.1 后端
```powershell
cd internal-ai-assistant/backend
python tests\qa_final_regression.py
```

### 4.2 前端
```powershell
cd internal-ai-assistant/frontend
npx tsc --noEmit
npm run build
npm run check:performance
```

### 4.3 页面 smoke
```powershell
cd internal-ai-assistant/frontend
npm run preview -- --host 0.0.0.0 --port 4173
```
然后手工检查：`/login`、`/chat`、`/admin`、引用预览、反馈弹窗、管理员筛选/处理。

## 5. 通过标准

- 后端回归脚本全部通过。
- `npx tsc --noEmit`、`npm run build`、`npm run check:performance` 全部通过。
- 页面 smoke 无白屏、无运行时错误、关键交互可完成。
- P2/P3/P4 对应场景均有证据链，不以“未验证”为“通过”。

## 6. 待验证项记录模板

| ID | 场景 | 状态 | 证据 |
|---|---|---|---|
| TC-P2-01 | `/api/chat` 返回 sources/citations/message_id | 待验证 |  |
| TC-P2-02 | 引用高亮/定位/预览 | 待验证 |  |
| TC-P3-01 | 无命中时不编造 | 待验证 |  |
| TC-P3-02 | 前端依据不足提示 | 待验证 |  |
| TC-P4-01 | 反馈分类提交 | 待验证 |  |
| TC-P4-02 | 管理员状态/关键词筛选 | 待验证 |  |
| TC-P4-03 | 状态更新与备注保存 | 待验证 |  |
| TC-RISK-01 | `check:performance` 纳入验收 | 待验证 |  |
| TC-RISK-02 | 页面覆盖与无白屏 smoke | 待验证 |  |

## 7. 当前结论

当前仅完成测试计划与清单定义；最终是否通过，必须以 integration worktree 上的后端、前端和性能复测结果为准。