# AI 修改前必读

> 本仓库当前项目主体位于 `internal-ai-assistant/`。本文件是根目录可追溯入口，实际维护内容见：`internal-ai-assistant/docs/AI修改前必读.md`。

## 发布整理要求

- 开始任何修改前，必须先阅读：
  - `internal-ai-assistant/docs/AI修改前必读.md`
  - `internal-ai-assistant/docs/业务规则回归清单.md`
  - `internal-ai-assistant/docs/AI修改记录.md`
- 目标远程仓库：`https://github.com/liaaa00/zhishiku.git`。
- 阶段 B 放行后若 remote 为空，配置 `origin=https://github.com/liaaa00/zhishiku.git` 并推送 `master`。
- 本项目前端端口为 `5174`，后端端口为 `8000`，不得操作其他项目端口 `5173`。
- 提交前必须说明提交范围和已通过验证；默认使用安全 Git 操作，不使用 `git reset --hard`。
- 临时文件、运行日志、本地缓存、真实 `.env`、敏感配置、外部源码下载目录不得进入最终提交。
