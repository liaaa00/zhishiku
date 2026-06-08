# 前端性能优化方案与构建基线（P1）

日期：2026-05-28  
角色：架构师  
范围：`internal-ai-assistant/frontend` 的 Vite/Rollup 分包、路由懒加载、管理后台与文件预览入口拆分方案。本文档只定义方案、边界与验收标准，不变更业务接口。

## 1. 当前基线

执行命令：

```bash
cd internal-ai-assistant/frontend
npm run build
```

当前输出：

| 产物 | 大小 | gzip | 结论 |
|---|---:|---:|---|
| `dist/assets/index-BN_NWMeY.js` | 1,099.79 kB | 364.35 kB | 超过 Rollup/Vite 默认 500 kB warning 阈值 |
| `dist/assets/index-rTgdWx5d.css` | 367.80 kB | 49.97 kB | 主要来自全量 Element Plus 样式 |
| `dist/index.html` | 0.41 kB | 0.31 kB | 正常 |

构建 warning：

- `(!) Some chunks are larger than 500 kB after minification.`
- 同时出现 `node_modules/@vueuse/core/dist/index.js` PURE 注释提示；该提示来自 Element Plus 依赖链，不是本次 500 kB 大 chunk 的直接根因，可作为低优先级噪声记录。

## 2. 超大 chunk 来源分析

### 2.1 同步路由导致所有页面进入首屏主包

当前 `src/router.ts` 同步导入全部页面：

```ts
import LoginView from './views/login/index.vue'
import ChatView from './views/chat/index.vue'
import AdminView from './views/admin/index.vue'
```

结果：访问 `/login` 或 `/chat` 时，`/admin` 管理后台代码也随主包下载；访问 `/login` 时聊天页的引用预览抽屉、反馈提交逻辑等也随主包下载。

页面规模：

| 页面 | 源文件 | 行数 | 字节 | 性能判断 |
|---|---|---:|---:|---|
| 管理后台 | `src/views/admin/index.vue` | 696 | 24,223 | tabs、table、upload、dialog、反馈处理都较重，应独立 chunk |
| 聊天页 | `src/views/chat/index.vue` | 701 | 20,040 | 聊天主流程 + 引用预览 drawer + 反馈 dialog，可先路由级拆分，后续再组件级拆 |
| 登录页 | `src/views/login/index.vue` | 27 | 1,067 | 轻量，但仍建议懒加载以形成清晰路由边界 |

### 2.2 全量 Element Plus 注册与全量 CSS 导入

当前 `src/main.ts`：

```ts
import ElementPlus from 'element-plus'
import 'element-plus/dist/index.css'
createApp(App).use(createPinia()).use(router).use(ElementPlus).mount('#app')
```

影响：

- Element Plus 全组件库和样式被放入首屏主包/主 CSS。
- 本地依赖证据：`node_modules/element-plus/dist/index.full.mjs` 约 2.11 MB，`node_modules/element-plus/dist/index.css` 约 357 KB；构建后 CSS 约 367.80 kB，基本对应全量样式。
- 当前 admin/chat/login 都大量使用 `el-*`，短期可先把 Element Plus JS 拆成 vendor chunk，避免塞入业务主包；中期再做按需组件与样式导入。

### 2.3 聊天页文件预览和管理后台天然是延迟入口

- 聊天页引用文件预览入口：`src/views/chat/index.vue` 中 `el-drawer`、`previewSource`、`loadSourcePreview`、`openSourceFile`。这些能力只有用户点击引用来源后才需要。
- 管理后台入口：`/admin`，且 `onMounted(loadAll)` 会请求 `/admin/groups`、`/admin/users`、`/admin/documents`、`/admin/feedback`。它不应影响普通聊天首屏。

## 3. 分包策略

### 3.1 第一阶段（必须先完成）：路由级懒加载 + vendor manualChunks

目标：不改接口、不拆复杂组件，先让 `npm run build` 不再出现 500 kB chunk warning，并让首屏入口只加载必要代码。

建议改动：

1. `src/router.ts` 改成动态导入：

```ts
import { createRouter, createWebHistory, type RouteRecordRaw } from 'vue-router'

const routes: RouteRecordRaw[] = [
  { path: '/', redirect: '/chat' },
  { path: '/login', component: () => import('./views/login/index.vue') },
  { path: '/chat', component: () => import('./views/chat/index.vue') },
  { path: '/admin', component: () => import('./views/admin/index.vue') },
]

export default createRouter({ history: createWebHistory(), routes })
```

2. `vite.config.ts` 增加 `manualChunks`，建议边界：

```ts
build: {
  outDir: 'dist',
  rollupOptions: {
    output: {
      manualChunks(id) {
        if (id.includes('node_modules')) {
          if (id.includes('element-plus') || id.includes('@element-plus') || id.includes('@vueuse')) return 'vendor-element-plus'
          if (id.includes('/vue') || id.includes('vue-router') || id.includes('pinia')) return 'vendor-vue'
          if (id.includes('axios')) return 'vendor-http'
          return 'vendor-misc'
        }
        if (id.includes('/src/views/admin/')) return 'view-admin'
        if (id.includes('/src/views/chat/')) return 'view-chat'
      },
    },
  },
}
```

说明：

- `vendor-vue`：Vue 运行时、Router、Pinia，所有页面共享，首屏必需但相对稳定。
- `vendor-element-plus`：Element Plus 与 `@vueuse/*` 等 UI 依赖，缓存稳定；短期仍可能较大，但不再与业务主包混在一起。若它仍超过 500 kB，进入第二阶段按需导入。
- `vendor-http`：axios 单独拆出，便于缓存和排查。
- `view-admin`、`view-chat`：业务路由块；若 `manualChunks` 对动态 import 的页面命名已足够清晰，也可只保留 vendor 拆分。

### 3.2 第二阶段（若 Element Plus vendor 仍 >500 kB）：Element Plus 按需导入

如果第一阶段后 `vendor-element-plus` 仍超过 500 kB warning，则不应简单提高 `chunkSizeWarningLimit`，而应执行按需导入：

- 移除 `main.ts` 的 `import ElementPlus from 'element-plus'` 与 `app.use(ElementPlus)`。
- 只全局注册实际用到的组件，或采用 `unplugin-vue-components` + `unplugin-auto-import` 自动按需导入。
- 样式从 `element-plus/dist/index.css` 改为组件级样式或 `element-plus/theme-chalk/base.css` + 组件样式。
- 由于当前项目未安装自动导入插件，若要引入新依赖，需要由 frontend 明确变更 `package.json/package-lock.json`，QA 重新执行 `npm install`/`npm run build`。

当前页面实际使用的组件类别包括：

- Login：`ElForm`、`ElFormItem`、`ElInput`、`ElButton`、`ElMessage`
- Chat：`ElButton`、`ElAlert`、`ElEmpty`、`ElDialog`、`ElForm`、`ElFormItem`、`ElRadioGroup`、`ElRadioButton`、`ElInput`、`ElDrawer`、`ElMessage`
- Admin：`ElButton`、`ElAlert`、`ElTabs`、`ElTabPane`、`ElInput`、`ElSelect`、`ElOption`、`ElCheckbox`、`ElTable`、`ElTableColumn`、`ElTag`、`ElUpload`、`ElEmpty`、`ElDialog`、`ElForm`、`ElFormItem`、`ElMessage`

### 3.3 第三阶段（可选优化）：文件预览与管理后台内部组件级拆分

在路由级懒加载和 UI 按需导入稳定后，再考虑：

- 把聊天页引用预览抽屉拆成 `src/views/chat/components/SourcePreviewDrawer.vue`，使用 `defineAsyncComponent` 或条件渲染延迟加载。边界：只接收 `SourceItem` 与 `load/open` 回调，不改变后端接口。
- 把聊天反馈 dialog 拆成 `FeedbackDialog.vue`。
- 把管理后台 tabs 拆成 `GroupAdminTab.vue`、`UserAdminTab.vue`、`DocumentPermissionTab.vue`、`FeedbackAdminTab.vue`。第一步至少可让反馈处理明细 dialog 独立，以降低 `/admin` 初次渲染成本。

## 4. 实施边界

### frontend

- 可以修改：`internal-ai-assistant/frontend/src/router.ts`、`internal-ai-assistant/frontend/vite.config.ts`。
- 第二阶段如需要按需导入，可以修改：`src/main.ts`、新增 `src/plugins/element-plus.ts` 或 `src/components/*`，以及 `package.json/package-lock.json`。
- 不改后端 API 契约，不改知识库检索、反馈业务字段。

### backend

- 第 1 步无需改动。
- 只需在前端回归发现 `/api/...` 预览或文件打开路径异常时协助确认接口行为。

### qa

- 以构建产物和路由/关键交互为主验收。
- 不需要重新做知识库引用质量、反馈系统业务升级的深度验证；只覆盖因分包可能影响的页面加载和基础交互。

## 5. 验收命令与目标

### 必跑命令

```bash
cd internal-ai-assistant/frontend
npm run build
```

目标：

- 不再出现 `Some chunks are larger than 500 kB after minification` warning。
- 产物中应至少出现独立的路由/供应商 chunk，例如：`vendor-vue-*`、`vendor-element-plus-*`、`vendor-http-*`、`view-chat-*`、`view-admin-*` 或 Vite 自动命名的等价 chunk。
- 单个 JS chunk 建议目标：首轮所有 JS chunk 均 `<500 kB`；若 `vendor-element-plus` 仍超过 500 kB，必须进入 Element Plus 按需导入，而不是只调高 warning 阈值。

### 建议回归路径

```bash
cd internal-ai-assistant/frontend
npm run build
npm run preview -- --host 0.0.0.0 --port 4173
```

手工检查：

1. `/login`：页面可加载，登录按钮和错误提示正常。
2. `/chat`：页面可加载；发送问题失败时有错误提示；已有引用来源时点击“预览”能打开 drawer，重新加载预览和打开文件按钮不报前端运行时错误。
3. `/admin`：页面可加载；岗位组、员工、文档权限、反馈 tab 可切换；刷新全部按钮不因懒加载报错；上传控件可打开文件选择；反馈处理 dialog 可打开。

### 可选产物分析

如需要更精确归因，可临时使用 `rollup-plugin-visualizer` 或 `vite-bundle-visualizer` 生成分析报告；但不要把临时报告或插件作为第一阶段强依赖，除非团队同意引入依赖。

## 6. 风险与注意事项

1. 当前工作区已有其他成员改动（如 `frontend/package.json`、`frontend/src/views/admin/index.vue`、`frontend/src/views/chat/index.vue`、`frontend/src/utils/` 等）。实施分包时不要回滚或覆盖这些业务改动。
2. 文档读取时 PowerShell 控制台曾显示中文乱码，但源文件内容可被工具按 UTF-8 读取；编辑必须使用 SpectrAI 文件工具或确保 UTF-8 no BOM，避免破坏中文。
3. 不建议通过 `build.chunkSizeWarningLimit` 掩盖问题。只有在明确所有大 chunk 都是可接受且不可再拆的稳定 vendor 后，才可作为最后手段调整阈值，并需在架构评审中说明原因。
4. 若采用自动按需导入插件，会新增依赖和构建配置复杂度；应先完成路由懒加载与 manualChunks 基线验证，再决定是否引入。

## 7. 推荐执行顺序

1. frontend：改 `router.ts` 动态 import。
2. frontend：改 `vite.config.ts` manualChunks。
3. frontend：执行 `npm run build` 并记录 chunk 列表；若仍有 >500 kB warning，继续 Element Plus 按需导入。
4. qa：按第 5 节验收构建与路由基础交互。
5. architect：评审 chunk 列表与是否需要第二阶段按需导入。
