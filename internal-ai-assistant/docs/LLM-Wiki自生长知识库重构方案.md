# LLM Wiki 自生长知识库重构方案

## 背景

当前系统的主要问题不是单个检索参数不好，而是架构范式偏向传统 RAG：

```text
问题 -> 临时检索 chunk -> LLM 拼接答案
```

这种方式容易出现：

- 知识不沉淀，每次回答都重新消费碎片；
- 跨文档推理弱，系统看见的是片段而不是体系；
- 答案不稳定，同一问题可能因为召回变化产生不同结果；
- 工程复杂度持续上升，容易不断叠加向量、关键词、重排、图谱和特殊规则。

新的方向是 Wiki-first：

```text
原始素材 -> Wiki 编译层 -> 结构化 Markdown 知识库 -> 查询优先使用 Wiki -> 必要时回原文核验
```

核心原则：**编译而非临时检索，积累而非一次性消耗。**

## 新三层架构

### 1. 原始素材层

保留现有上传、解析、OCR、表格抽取、原始 chunk、PageIndex、图谱和权限能力。

这一层负责：

- 原文可追溯；
- 审计引用；
- 新资料编译输入；
- Wiki 缺失时兜底。

### 2. Wiki 知识库层

新增 Wiki 数据模型：

- `wiki_pages`：Markdown 页面，包含标题、类型、状态、摘要、正文、作用域；
- `wiki_page_sources`：Wiki 页面到原始文档/chunk 的来源关系；
- `wiki_page_links`：页面之间的双向链接基础；
- `wiki_compile_status`：每个文档的 Wiki 编译状态。

当前第一阶段先实现确定性编译：

```text
Document + DocumentChunk -> source 类型 Markdown Wiki 页
```

后续再升级为 LLM 编译：

```text
原始文档 -> source/entity/concept/rule/overview 多类型页面 + 双向链接
```

### 3. 查询与规则层

新的查询顺序：

```text
表格精确查询 / 规则层
  ↓
Wiki-first 搜索
  ↓
Wiki 强命中则直接回答
  ↓
Wiki 未命中或弱命中时，才 fallback 到旧 RAG
```

说明：表格查询保留优先级，因为它是确定性统计，不属于用户不满意的碎片 RAG。

## 已落地的第一阶段

### 后端模块

```text
backend/app/wiki/
  compiler.py   # 文档 -> Markdown Wiki 页
  search.py     # Wiki-first 搜索与权限过滤
```

### 管理 API

```text
GET  /api/admin/wiki/status
GET  /api/admin/wiki/pages
GET  /api/admin/wiki/pages/{page_id}
GET  /api/admin/wiki/search-test?q=...
POST /api/admin/wiki/documents/{document_id}/compile
POST /api/admin/wiki/compile-all
```

### 自动编译

文档后台解析成功后会自动执行 Wiki 编译：

```text
上传/重解析 -> chunk 入库 -> Wiki 编译 -> 图谱抽取
```

Wiki 编译失败不会让文档解析失败，只会写审计记录。

### 查询接入

`rag.pipeline.retrieve_contexts()` 现在会先尝试 Wiki-first：

- 非表格问题先查已发布 Wiki 页；
- 强命中时返回 `backend=wiki`；
- 元数据中 `retrieval_route.name=wiki`；
- 旧 RAG 只作为 fallback；
- fallback 时会保留 `wiki_first.reason` 便于诊断。

## 验证标准

第一阶段必须满足：

1. 已编译 Wiki 页的问题直接返回 `backend=wiki`；
2. 表格查询仍不被 Wiki/图谱覆盖；
3. 原有 title guard、graph guard 不回退；
4. 新表可通过 `Base.metadata.create_all` 和运行时 schema 自动创建；
5. Wiki 页面保留原始文档/chunk 来源，满足追溯和权限过滤。

## 后续阶段

### Phase 2：LLM 编译器

从单文档 source 页升级为多类型页面：

- `source`：原始文档页；
- `entity`：公司、部门、人员、系统、客户等实体；
- `concept`：业务概念；
- `rule`：统计口径、流程规则、例外规则；
- `overview`：专题总览页。

### Phase 3：Review / Lint / Eval

加入知识库体检：

- 缺来源页面；
- 孤立页面；
- 重复页面；
- 冲突规则；
- 过期页面；
- 高频问题未沉淀。

### Phase 4：弱化旧 RAG

当 Wiki 覆盖率足够后：

- 默认关闭 LLM reranker；
- Qdrant/向量检索降级为原文定位与编译输入；
- 日常问答以 Wiki/规则层为主；
- 旧 chunk RAG 仅处理未编译资料和证据核验。
