import json

from .graph_schema import ENTITY_TYPES, RELATION_TYPES


def build_graph_extraction_messages(document_title: str, chunk_text: str) -> list[dict]:
    allowed_entity_types = ", ".join(ENTITY_TYPES.keys())
    allowed_relation_types = ", ".join(RELATION_TYPES.keys())
    system = (
        "你是企业知识库的知识图谱抽取器。只能根据用户提供的文档片段抽取事实，"
        "不要补充常识、不要推测。必须只输出合法 JSON，不要 Markdown，不要解释。"
    )
    schema = {
        "entities": [
            {
                "name": "实体名称，尽量使用文档原词",
                "type": "允许的实体类型之一",
                "description": "不超过80字的说明，可为空",
                "confidence": 0.8,
            }
        ],
        "relations": [
            {
                "source": "源实体名称，必须出现在 entities 中或片段中",
                "relation_type": "允许的关系类型之一",
                "target": "目标实体名称，必须出现在 entities 中或片段中",
                "evidence": "能直接证明关系的原文短句",
                "confidence": 0.8,
            }
        ],
    }
    user = (
        f"文档标题：{document_title or '未命名文档'}\n\n"
        f"允许的实体类型：{allowed_entity_types}\n"
        f"允许的关系类型：{allowed_relation_types}\n\n"
        "抽取规则：\n"
        "1. 只抽取对企业知识库问答有帮助的流程、角色、系统、表单、字段、规则、截止时间、工单、操作步骤等。\n"
        "2. 关系必须有原文证据，证据不超过120字。\n"
        "3. 不确定的实体或关系不要输出；confidence 使用 0 到 1。\n"
        "4. 没有可抽取内容时输出 {\"entities\": [], \"relations\": []}。\n"
        "5. 输出 JSON 格式必须类似：\n"
        f"{json.dumps(schema, ensure_ascii=False)}\n\n"
        "文档片段：\n"
        f"{chunk_text}"
    )
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]
