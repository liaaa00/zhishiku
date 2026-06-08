# CLAUDE.md — AI 操作手册（最高宪法）

> 最后更新：2026-05-29  
> 适用范围：所有 AI 助手（Claude、Codex、Gemini 等）在为本项目编写或修改代码时必须遵守。  
> **本文档优先级高于任何模型的默认行为或训练数据中的"最佳实践"。**

---

## 0. 学习循环（Meta-Rule）

**每次被纠正错误后，必须执行以下流程：**

1. 分析错误根因（是逻辑错误、遗漏边界、架构违规还是风格不一致？）
2. 将**错误模式**和**预防规则**追加到本文档对应章节
3. 在本次会话和未来所有会话中强制执行新增的规则
4. 如果错误源于对项目现状的误解 → 先更新对应的 `specs/*.md` 文档，再更新本文档

记录格式：
```markdown
### 错误记录 #N — YYYY-MM-DD
- **错误**：[具体做了什么]
- **根因**：[为什么会犯错]
- **纠正**：[正确的做法是什么]
- **预防规则**：[今后如何避免]
```

---

## 1. 文件命名规范

| 类型 | 规范 | 示例 |
|------|------|------|
| Vue 页面 | `views/<功能>/index.vue` | `views/chat/index.vue` |
| Vue 子组件 | `PascalCase.vue` | `SourcePreviewDrawer.vue` |
| TypeScript 工具 | `kebab-case.ts` | `source-utils.ts` |
| Python 模块 | `snake_case.py` | `ai_client.py` |
| 规范文档 | `UPPER_SNAKE.md` | `TECH_STACK.md` |
| 测试文件 | `qa_<描述>.py` 或 `test_<模块>.py` | `qa_final_regression.py` |

---

## 2. 目录结构约束（不可变）

```
internal-ai-assistant/
├── .env                          # 环境变量（不入 Git）
├── .env.example                  # 环境变量模板
├── docker-compose.yml
├── README.md
│
├── docs/
│   └── specs/                    # 📌 所有规范文档在此
│       ├── TECH_STACK.md
│       ├── BACKEND_STRUCTURE.md
│       ├── APP_FLOW.md
│       ├── FRONTEND_GUIDELINES.md
│       ├── CLAUDE.md             # 本文件
│       ├── progress.txt
│       └── IMPLEMENTATION_PLAN.md
│
├── backend/
│   ├── Dockerfile
│   ├── requirements.txt
│   ├── data/                     # SQLite + 上传文件（不入 Git）
│   │   ├── app.db
│   │   └── uploads/
│   ├── tests/                    # 测试脚本
│   └── app/
│       ├── __init__.py
│       ├── main.py               # ⚠️ 单文件巨石，1576 行
│       ├── config.py
│       ├── database.py
│       ├── models.py
│       ├── schemas.py
│       ├── security.py
│       ├── ai_client.py
│       ├── vector_store.py
│       └── document_utils.py
│
└── frontend/
    ├── Dockerfile
    ├── nginx.conf
    ├── package.json
    ├── package-lock.json
    ├── tsconfig.json
    ├── vite.config.ts
    ├── index.html
    └── src/
        ├── main.ts
        ├── App.vue
        ├── style.css
        ├── router.ts
        ├── api.ts
        ├── vite-env.d.ts
        ├── utils/
        │   └── source-utils.ts
        └── views/
            ├── login/index.vue
            ├── chat/
            │   ├── index.vue
            │   └── components/
            │       └── SourcePreviewDrawer.vue
            └── admin/index.vue
```

**约束**：
- 新增 Python 模块放在 `backend/app/`，不得新建根目录模块。
- 新增 Vue 页面放在 `frontend/src/views/<功能>/index.vue`。
- 新增 Vue 子组件放在对应页面的 `components/` 子目录。
- 文件移动/重命名必须同步更新所有 import 引用。
- `backend/data/` 目录不得提交到 Git（已在 `.gitignore`）。

---

## 3. 核心禁止事项（宪法级）

### 🔴 3.1 严禁自建本地组织架构同步逻辑

**规则**：禁止在 Python 后端编写任何以下功能：
- 调用飞书 Open API 获取部门列表/用户列表
- 在数据库存储员工姓名、部门名、工号、手机号等飞书已有的元数据
- 定时同步、增量同步、全量同步组织架构的后台任务
- 在 user 表添加 `name`、`department`、`avatar`、`email`、`phone`、`employee_id` 等冗余字段
- 任何形式的本地组织架构树构建和缓存

**正确做法**：
- 人员权限仅存储 `User.id ↔ Group.id` 的纯映射关系
- 所有部门/人员的选择和展示，由飞书原生前端组件 `DepartmentSelect` / `UserSelect` 在 UI 层实时处理
- 这些组件返回的飞书元数据（姓名、部门名等）仅在 UI 层使用，**不写入后端数据库**

**当前状态**：`users` 表仅有 `id`, `username`, `password_hash`, `is_admin`, `is_active`, `created_at` 六个字段。保持这个纯度不变。

### 🔴 3.2 严禁恢复已删除的功能

以下功能已确认删除，**不得以任何形式恢复**：

| 功能 | 删除原因 |
|------|----------|
| 自建组织架构同步（飞书 API 拉取部门/人员） | 架构决策：改由飞书原生组件实时获取 |
| 周报提交页 | 功能已移除 |
| 周报关闭按钮 | 随周报提交页一起移除 |
| 用户自助注册页 | 安全决策：仅管理员可创建账号 |

### 🟡 3.3 后端模块约束

- **不得继续扩大 `main.py`**：当前 1576 行，新增 API 应拆分到独立模块。目标：逐步将 main.py 拆分为 routers/ 子模块。
- **不得绕过 ORM 写原始 SQL**：使用 SQLAlchemy ORM，特殊查询经评审后允许 `select()` 表达式。
- **不得修改 `config.py` 的默认值语义**：环境变量默认值为安全基线。

### 🟡 3.4 前端约束

- **不得使用 Element Plus 全量注册**：必须按需导入。
- **不得引入新的 UI 框架**（如 Ant Design Vue、Naive UI）：保持 Element Plus 唯一。
- **不得引入 Tailwind CSS 或其他原子化 CSS 框架**：使用 Element Plus 内置 + scoped CSS。
- **不得修改 `vite.config.ts` 中的手动分包策略**：除非新增大体积依赖。

---

## 4. 代码编写规范

### 4.1 Python（后端）

```python
# ✅ 类型标注（已有模式） + 函数文档字符串
def chat_answer(
    question: str,
    contexts: List[dict],
    api_key: Optional[str] = None,
    base_url: Optional[str] = None,
    model: Optional[str] = None,
) -> str:
    """使用 DeepSeek 生成基于上下文的回答。"""

# ✅ 使用 FastAPI 依赖注入获取数据库会话和当前用户
def list_users(db: Session = Depends(get_db), _: User = Depends(require_admin)):
    ...

# ✅ 所有写操作记录审计日志
audit(db, actor, "action.name", "resource_type", resource_id, detail_dict)
db.commit()
```

**禁止**：
- ❌ `except Exception: pass` 吞掉所有异常（至少记录日志）
- ❌ `print()` 用于生产日志（使用 `logging` 模块或 structured 输出）
- ❌ 在 `config.py` 外硬编码敏感值

### 4.2 TypeScript/Vue（前端）

参考 `FRONTEND_GUIDELINES.md` 第 7 节。

### 4.3 API 设计规范

- 管理端 API 前缀：`/api/admin/`
- 用户端 API 前缀：`/api/`（非 admin）
- 请求体使用 Pydantic `BaseModel`
- 响应体使用 `dict` 字面量（当前模式），未来可迁移至 Pydantic `response_model`
- 错误返回：`raise HTTPException(status_code=4xx/5xx, detail="中文描述")`

---

## 5. 安全性基线

| 要求 | 状态 |
|------|------|
| 密码哈希使用 bcrypt（而非 SHA256） | ⚠️ **未实现** — `passlib[bcrypt]` 已安装但未使用 |
| JWT Token 24 小时过期 | ✅ 已实现 |
| API Key 不在 API 响应中泄露 | ✅ 已实现（`api_key_set: bool`） |
| CORS 限制 | ⚠️ 当前 `allow_origins=["*"]`，生产需收紧 |
| 输入清理 | ⚠️ HTML escape 用于 SSR 页面，API 响应未统一转义 |
| 文件上传类型白名单 | ✅ 已实现（`CHAT_FILE_EXTENSIONS` + `KNOWLEDGE_FILE_EXTENSIONS`） |
| 文件大小限制 | ✅ 已实现（默认 30MB） |
| SQL 注入防护 | ✅ SQLAlchemy ORM 参数化查询 |
| 自删除/自停用防护 | ✅ 已实现（不能删除/停用自己的账号） |

---

## 6. 技术债跟踪（从代码中识别的已知问题）

| 编号 | 问题 | 位置 | 优先级 |
|------|------|------|--------|
| TD-01 | SHA256 替代 bcrypt 做密码哈希 | `backend/app/security.py` | 🔴 高 |
| TD-02 | main.py 单文件 1576 行巨石架构 | `backend/app/main.py` | 🟡 中 |
| TD-03 | CORS 全开 `allow_origins=["*"]` | `backend/app/main.py:48` | 🟡 中 |
| TD-04 | Token 无 refresh 机制 | `backend/app/security.py` | 🟡 中 |
| TD-05 | 无数据库迁移工具（Alembic） | — | 🟢 低 |
| TD-06 | 无前端路由守卫 | `frontend/src/router.ts` | 🟡 中 |
| TD-07 | 无全局 401 拦截与自动跳转登录 | `frontend/src/api.ts` | 🟡 中 |
| TD-08 | Pinia 已挂载但无 Store 使用 | `frontend/src/main.ts` | 🟢 低 |
| TD-09 | 飞书原生组件尚未集成 | — | 🔴 高（计划中） |
| TD-10 | SSR 管理页面（ADMIN_HTML）与 Vue SPA 功能重复 | `backend/app/main.py` | 🟢 低 |
| TD-11 | embedding 默认使用 local-hash（仅适小型部署） | `backend/app/ai_client.py` | 🟢 低 |

---

## 7. 必须阅读的相关文件

修改任何代码前，必须先阅读以下文件以确保上下文一致：

1. `docs/specs/TECH_STACK.md` — 确认可用的依赖和版本
2. `docs/specs/BACKEND_STRUCTURE.md` — 确认数据库表和 API 接口
3. `docs/specs/APP_FLOW.md` — 确认用户流程不受影响
4. `docs/specs/FRONTEND_GUIDELINES.md` — 确认 UI 风格一致性
5. `docs/specs/progress.txt` — 确认当前进度和待解决问题
6. `docs/specs/IMPLEMENTATION_PLAN.md` — 确认计划中的后续步骤

---

## 8. 错误记录

> 以下为被纠正后追加的规则。每次被纠正时在此追加。

### 错误记录 #1 — 2026-05-29（初始化）
- **错误**：项目是用 AI 氛围编程（Vibe Coding）写的，缺乏规范文档
- **根因**：缺乏系统性架构文档和约束规则
- **纠正**：生成本套 7 份规范文档
- **预防规则**：所有 AI 必须在修改代码前先阅读本文件和相关 specs/*.md
