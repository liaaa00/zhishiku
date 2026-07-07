# 检索回归铁律

改动检索 / 排序 / 路由相关代码（尤其 `backend/app/rag/pipeline.py`、`backend/app/retrieval.py`、`backend/app/retrieval_router.py`）前后，**必须**跑统一评测集，净分不得低于当前基线 **24/24**：

```bash
cd backend
python -X utf8 tests/qa_retrieval_eval_runner.py --real-db --cases tests/retrieval_eval_real_cases.json
```

- 该评测集 `backend/tests/retrieval_eval_real_cases.json` 是「改动前后净效果」的唯一权威视图，每条用例标注 `source_script` 来源。
- 只判断证据是否找对（路由到哪个后端、命中哪个文档、含哪些证据词），不要求最终回答文字一致；聚合/计数由 LLM 从检索到的表格行完成。
- 修一个问题导致其他用例下降，即视为回归，须回退或换方案，不得靠 fixture 专用测试掩盖真实冲突。
- 新增真实问题时，先用真实库探测其实际路由，再据此写断言，并同步更新此处基线数字。

Python 解释器：`$LOCALAPPDATA/Programs/Python/Python312/python.exe`，须加 `-X utf8`。

# 分公司统计口径铁律

北仑分公司开设进度统计最终采用 **36**：以 `当前进度-4.开设公司名称` 有效为准，非空且不是 `未开设/无/暂无/否` 即计入；不要求名称必须包含“分公司”，因此 `宁波北仑 -> 外服（浙江）企业服务有限公司` 计入。城市范围问句中的“开设了/开了分公司”不得自动叠加银行账户、社保公积金账户完成过滤；只有用户显式要求“银行和社保都办好/开具完成”时才叠加完成度过滤。详见 `docs/分公司统计口径确认.md`。

