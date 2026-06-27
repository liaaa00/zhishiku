# FRONTEND_GUIDELINES.md — 前端视觉与组件规范

> 最后更新：2026-05-29  
> 基于当前代码逆向提取的 UI 风格、组件模式和视觉标准。

---

## 1. 组件库与导入策略

### 1.1 使用的组件库

| 库 | 版本 | 说明 |
|----|------|------|
| Element Plus | 2.14.0（锁定） | 唯一 UI 组件库 |
| @element-plus/icons-vue | 2.3.2（间接依赖） | 图标集 |

### 1.2 导入策略（强制性）

**必须使用按需导入**，禁止全量注册：

```typescript
// ✅ 正确：按需导入
import { ElButton } from 'element-plus/es/components/button/index'
import 'element-plus/es/components/button/style/css'

// ❌ 禁止：全量注册
import ElementPlus from 'element-plus'
app.use(ElementPlus)
```

**原因**：当前前端代码 100% 使用按需导入，`vite.config.ts` 中手动分包策略依赖此约定。全量注册会破坏 Tree Shaking 和构建分包。

### 1.3 已使用的 Element Plus 组件清单

| 组件 | 使用位置 |
|------|----------|
| `el-button` | 登录页、聊天页、管理页、来源预览抽屉 |
| `el-card` | 登录页 |
| `el-input` | 登录页、管理页（用户名/密码/岗位组名称） |
| `el-form` / `el-form-item` | 登录页 |
| `el-table` / `el-table-column` | 管理页（用户列表、文档列表） |
| `el-tag` | 聊天页（相关度标签）、管理页（管理员标签、状态标签） |
| `el-tabs` / `el-tab-pane` | 管理页（5 个页签） |
| `el-select` / `el-option` | 管理页（岗位组多选、状态过滤） |
| `el-checkbox` | 管理页（管理员复选框） |
| `el-upload` | 管理页（文档上传） |
| `el-alert` | 聊天页（错误提示、合规警告）、管理页（错误提示） |
| `el-empty` | 聊天页（无引用来源）、管理页（无数据） |
| `el-dialog` | 聊天页（反馈对话框） |
| `el-drawer` | 聊天页（来源预览抽屉） |
| `el-message` | 全局（操作反馈 toast） |
| `el-textarea` | 聊天页（问题输入框） |

---

## 2. 视觉风格：简洁企业内网风（Enterprise Minimal）

### 2.1 核心设计语言

当前代码呈现的风格特征：
- **背景色系统**：浅灰蓝基调（`#f5f7fb` / `#f6f8fc` / `#f8fafc`）
- **卡片设计**：白底 + 浅灰边框 + 大圆角（12-22px）
- **排版**：无衬线 Arial/Helvetica，信息层级通过字号和字重区分
- **交互**：悬停微交互（hover 变色/上浮）、按钮禁用态

### 2.2 字体系统

```css
/* 全局默认 */
font-family: Arial, Helvetica, sans-serif;

/* 实际使用中的字号层级（从代码中提取） */
.eyebrow: 12px   /* 小标签/辅助文字 */
small: 12px      /* 时间戳/次要信息 */
p, .tip: 12px    /* 提示文字 #888 */
body: 14px       /* 正文（Element Plus 默认） */
.message-content: 15px  /* 聊天消息 */
h3: 15px          /* 区块标题 #303133 */
h2: ~20px        /* 页面标题 */
h1: ~24px        /* 聊天页主标题 */
```

### 2.3 间距系统

| 层级 | 值 | 使用场景 |
|------|-----|----------|
| xs | 4px | 高亮 padding |
| sm | 8px | 元素内间距、gap |
| md | 12px | 卡片内间距、表单项间距 |
| lg | 16px | 区块间距、页面 padding（小屏） |
| xl | 24px | 页面 padding（桌面端）、header 底部间距 |
| 2xl | 32px | 大区块分隔 |

---

## 3. 调色板（从实际代码中提取）

### 3.1 主色板

| CSS 变量/色值 | 用途 | 来源 |
|---------------|------|------|
| `#f5f7fb` | 页面全局背景 | `.page-center` background |
| `#f6f8fc` | 聊天区底部渐变背景 | `.chat-footer` gradient |
| `#fff` | 卡片/气泡背景 | `.message-bubble`, `.composer-card` |
| `#e8f3ff` | 用户消息气泡（浅蓝） | `.msg.user` background |
| `#303133` | 主文字色 | Element Plus `--el-text-color-primary` |
| `#606266` | 次要文字色 | Element Plus `--el-text-color-regular` |
| `#909399` | 辅助文字色 | Element Plus `--el-text-color-secondary` |
| `#64748b` | 灰色辅助文字 | 来源元数据、composer-footer |
| `#888` | 提示文字 | `.tip` color |
| `#cbd5e1` | 边框色（浅灰） | `.composer-card` border |
| `#e2e8f0` | 预览框边框 | `.preview-box` border |
| `#eef2f7` | 分割线 | `.composer-footer` border-top |
| `#243044` | 预览框正文色 | `.preview-box` color |

### 3.2 高亮与语义色

| 色值 | 用途 |
|------|------|
| `#fef08a`（黄底） + `#854d0e`（棕字） | 关键词命中高亮 `.hit-mark` |
| Element Plus 默认：`--el-color-primary` | 主按钮/链接色（蓝色系） |
| Element Plus `type="success"` | 管理员标签/成功状态 |
| Element Plus `type="warning"` | 合规警告提示 |
| Element Plus `type="error"` | 错误提示 |
| Element Plus `type="info"` | 非管理员标签 |

### 3.3 阴影

```css
/* 输入卡片阴影 */
box-shadow: 0 18px 46px rgba(15, 23, 42, 0.1);

/* 一般无大面积阴影使用 — 保持扁平为主 */
```

---

## 4. 组件模式

### 4.1 页面布局模板

```
┌─────────────────────────────────────────────────┐
│ .chat-shell / .admin-page                       │
│ max-width: 960px; margin: 0 auto; padding: 24px │
│ ┌─────────────────────────────────────────────┐ │
│ │ .chat-header / .page-header                 │ │
│ │ display: flex; justify-content: space-      │ │
│ │ between; align-items: flex-start            │ │
│ └─────────────────────────────────────────────┘ │
│ ┌─────────────────────────────────────────────┐ │
│ │ 内容区（flex column / grid）                │ │
│ └─────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────┘
```

### 4.2 聊天消息气泡

```css
.message-row       /* display: flex; gap: 12px */
.message-row.user  /* justify-content: flex-end */
.message-avatar    /* 40x40 圆形，渐变蓝色背景，白色文字 */
.message-bubble    /* padding: 14px 18px; border-radius: 18px */
.user .message-bubble  /* background: #e8f3ff（浅蓝） */
.assistant .message-bubble  /* background: #fff（白色） */
```

### 4.3 来源卡片网格

```css
.source-list {
  display: grid;
  gap: 12px;
  /* 自适应列，最小 280px */
}
.source-item {
  display: grid;
  grid-template-columns: auto 1fr auto;
  /* border: 1px solid; border-radius: 14px; padding: 14px */
}
```

### 4.4 管理端标签页

```css
.admin-tabs {
  /* 使用 Element Plus el-tabs 默认样式 */
}
.toolbar {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
  margin-bottom: 16px;
}
```

---

## 5. 响应式断点

从实际 CSS 媒体查询中提取：

| 断点 | 触发条件 | 变化 |
|------|----------|------|
| 桌面端 | 默认 (>720px) | `max-width: 960px`，双列/多列布局 |
| 移动端 | `@media (max-width: 720px)` | 页面 padding 缩小到 16px，列布局变单列，输入区竖向堆叠 |
| 管理端 | `@media (max-width: 960px)` | toolbar 变竖向，表格横向滚动，详情卡片单列 |

### 5.1 移动端具体调整

```css
@media (max-width: 720px) {
  .chat-shell { padding: 14px 12px; gap: 12px; }
  .chat-header { flex-direction: column; border-radius: 18px; }
  .chat-body { max-height: calc(100dvh - 280px); }
  .prompt-grid { grid-template-columns: 1fr; }
  .message-row { gap: 8px; margin-bottom: 16px; }
  .message-avatar { width: 30px; height: 30px; }
  .message-row.user .message-stack,
  .message-stack { max-width: 100%; }
  .source-item { grid-template-columns: auto minmax(0, 1fr); }
}
```

---

## 6. 飞书原生组件使用约束（宪法级）

### 6.1 强制使用规则

| 场景 | 必须使用的组件 | 禁止做法 |
|------|---------------|----------|
| 部门/组织选择 | `DepartmentSelect`（飞书原生） | ❌ 自建部门树/下拉框 |
| 人员选择 | `UserSelect`（飞书原生） | ❌ 自建人员搜索/列表 |
| 获取用户姓名/部门 | 飞书组件返回的实时数据 | ❌ 存储在后端数据库中冗余 |
| 组织架构展示 | 飞书组件内置渲染 | ❌ 后端返回部门 JSON 前端渲染 |

### 6.2 当前集成状态

⚠️ **当前代码中尚未集成飞书 SDK 或任何飞书原生组件**。这是一个已决策但尚未执行的重构方向。  
- `package.json` 中无飞书相关依赖（无 `@lark-base-open/js-sdk`、`@feishu/feishu-ui` 等）
- 后端无飞书 API 调用（无 contact、im 等 open API 请求）
- 人员管理目前完全手动创建用户名/密码 + 岗位组

详见 `CLAUDE.md` 关于此事的强制约束。

---

## 7. 前端代码组织规范

### 7.1 目录结构（已确立）

```
frontend/src/
├── main.ts                 # 入口，createApp + Pinia + Router
├── App.vue                 # 根组件 <router-view />
├── style.css               # 全局基础样式（仅 body/布局类）
├── router.ts               # 路由定义
├── api.ts                  # Axios 实例 + JWT 拦截器
├── vite-env.d.ts           # Vite 类型声明
├── stores/
│   └── auth.ts             # Pinia 认证状态：token/user/isAdmin/logout
├── utils/
│   └── source-utils.ts     # 引用来源处理工具函数
└── views/
    ├── login/
    │   └── index.vue       # 登录页
    ├── chat/
    │   ├── index.vue       # 聊天页（~834 行）
    │   └── components/
    │       └── SourcePreviewDrawer.vue  # 来源预览抽屉
    └── admin/
        └── index.vue       # 管理页（~867 行）
```

### 7.2 文件命名规范

| 类型 | 命名 | 示例 |
|------|------|------|
| Vue 页面组件 | 视图名 + `index.vue` | `views/login/index.vue` |
| Vue 子组件 | PascalCase + `.vue` | `SourcePreviewDrawer.vue` |
| TypeScript 工具 | kebab-case + `.ts` | `source-utils.ts` |
| 样式 | `style.css`（全局）+ scoped（组件内） | — |
| API 实例 | `api.ts` | — |

### 7.3 组件编写规范

```vue
<!-- ✅ 使用 Composition API + <script setup> + TypeScript -->
<script setup lang="ts">
import { ref, computed, watch, reactive, nextTick } from 'vue'
// Element Plus 按需导入
import { ElButton } from 'element-plus/es/components/button/index'
import 'element-plus/es/components/button/style/css'

// props with defineModel
const visible = defineModel<boolean>('visible', { default: false })

// 逻辑...
</script>

<template>
  <!-- 使用 scoped 样式 + Element Plus 组件 + 语义化 HTML -->
</template>

<style scoped>
/* 组件样式 */
</style>
```

### 7.4 样式约定

- **组件样式**：使用 `<style scoped>`，禁止全局样式污染
- **CSS 变量**：优先使用 Element Plus 的 CSS 变量（如 `var(--el-border-color-light)`）
- **颜色**：直接使用十六进制值，不使用 Element Plus 色彩函数
- **禁止**：Tailwind CSS、CSS-in-JS（styled-components 等）、Sass/SCSS
