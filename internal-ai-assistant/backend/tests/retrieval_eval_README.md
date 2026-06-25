# 检索评测集使用说明

这个目录里现在有两类评测：

- `retrieval_eval_cases.json`：fixture 评测。脚本会创建临时 SQLite 和模拟文档，用于稳定回归。
- `retrieval_eval_real_cases.json`：真实库评测模板。直接读取当前 `backend/data/app.db`，用于检查真实知识库效果。
- `qa_retrieval_eval_runner.py`：评测 runner。

## 一、什么样的问题适合放进真实测评？

真实测评的问题不是“标准考试题”，而是用户真的可能会问、并且你能判断证据对不对的问题。

优先收集这 6 类：

1. 高频标准问法
   - 例：`员工怎么签署电子劳动合同？`
   - 目的：核心业务必须答准。

2. 口语化问法
   - 例：`我收到签劳动合同的通知了，从哪里进去处理？`
   - 目的：用户不会总是说“电子签”“流程”这种标准词。

3. 角色冲突问题
   - 例：`合同组在工单系统里怎么处理电子劳动合同盖章和归档？`
   - 目的：防止员工指南和内部工单材料互相干扰。

4. 表格精确查询
   - 例：`2026年3月北仑派单截止时间是什么时候？`
   - 目的：检查 Excel/CSV 行级证据是否找对。

5. 缺条件问题
   - 例：`社保截止时间是什么时候？`
   - 目的：如果城市、月份、业务类型不完整，系统不应乱答。

6. 无资料/防幻觉问题
   - 例：`深圳2027年医保缴费规则是什么？`
   - 目的：库里没有资料时，不应强行命中无关文档。

## 二、真实测评先测什么？

第一阶段不要要求最终答案文字完全一致，先测“证据是否正确”：

- 应该命中哪些文档标题/文件名
- 不应该命中哪些文档标题/文件名
- 检索上下文里应该出现哪些证据词
- 是否应该走表格后端 `table`

等证据稳定后，再做最终回答质量评测。

## 三、运行 fixture 评测

在 `internal-ai-assistant/backend` 目录执行：

```bash
python tests/qa_retrieval_eval_runner.py
```

输出详细 JSON：

```bash
python tests/qa_retrieval_eval_runner.py --json
```

保留临时数据库用于调试：

```bash
python tests/qa_retrieval_eval_runner.py --keep-db
```

## 四、运行真实知识库评测

```bash
python tests/qa_retrieval_eval_runner.py --real-db
```

指定真实评测文件：

```bash
python tests/qa_retrieval_eval_runner.py --real-db --cases tests/retrieval_eval_real_cases.json
```

查看检索解释报告：

```bash
python tests/qa_retrieval_eval_runner.py --real-db --cases tests/retrieval_eval_real_cases.json --explain
```

解释报告会显示：

- 每个问题命中的 Top 文档
- 检索后端：`table` / `hybrid` / `sqlite+keyword` 等
- query_profile
- score / rerank_score / llm_rerank_score
- positive_signals / negative_signals
- 命中片段摘要

## 五、真实评测 case 写法

示例：

```json
{
  "id": "real_employee_esign_colloquial_001",
  "category": "口语化问法",
  "question": "我收到签劳动合同的通知了，从哪里进去处理？",
  "why": "真实用户不一定会说电子签，但语义仍是员工签署入口。",
  "expected": {
    "top_n": 5,
    "top_n_must_match_titles": ["电子劳动合同", "微助手"],
    "top_n_must_not_match_titles": ["工单系统"],
    "must_include_terms": ["微助手"]
  }
}
```

## 六、常用 expected 字段

- `backend`：期望检索后端，例如 `table`。
- `top_doc`：第一名必须是某个文档 ID。
- `must_include_docs`：最终结果必须包含某些文档 ID。
- `must_not_include_docs`：最终结果不能包含某些文档 ID。
- `top_n` + `top_n_must_include_docs`：指定文档必须出现在前 N 名。
- `must_match_titles`：任意结果的标题/文件名必须包含这些词。
- `must_not_match_titles`：任意结果的标题/文件名不能包含这些词。
- `top_n_must_match_titles`：前 N 名里必须有标题/文件名匹配这些词。
- `top_n_must_not_match_titles`：前 N 名里不能有标题/文件名匹配这些词。
- `must_match_contexts`：任意结果的标题、文件名、正文、位置里必须匹配这些词。
- `must_not_match_contexts`：任意结果的标题、文件名、正文、位置里不能匹配这些词。
- `must_include_terms`：召回上下文里必须出现的证据词。
- `must_not_include_terms`：召回上下文里不能出现的词。
- `query_profile`：期望检索意图识别结果，例如 `{ "task": "esign_process", "actor": "employee" }`。
- `must_have_positive_signals`：期望排序解释里出现的正向信号。

标题匹配字段支持两种写法：

```json
"top_n_must_match_titles": ["电子劳动合同", "微助手"]
```

表示前 N 名里分别要有“电子劳动合同”和“微助手”。

```json
"top_n_must_match_titles": [["电子", "合同"], ["微助手"]]
```

表示某个结果标题要同时包含“电子”和“合同”；另一个结果标题要包含“微助手”。

## 七、维护建议

1. 每发现一次真实检索错误，就把它变成一个 case。
2. case 里一定写清楚：为什么这个问题重要、应该命中什么、不应该命中什么。
3. 优先测检索证据，不要一开始就测最终回答逐字一致。
4. 每次改检索、排序、文档解析、表格逻辑前后都跑一遍。
5. 如果真实评测失败，不要马上改算法；先看 `--explain`，判断是问题写错、文档缺失、权限问题、解析问题，还是排序问题。
