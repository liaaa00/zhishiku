ENTITY_TYPES = {
    "process": "流程",
    "role": "角色/部门",
    "system": "系统",
    "document": "文档",
    "form": "表单",
    "field": "字段",
    "city": "城市/地区",
    "rule": "规则",
    "deadline": "截止时间",
    "task": "工单/任务",
    "action": "操作步骤",
    "other": "其他",
}

RELATION_TYPES = {
    "part_of": "属于",
    "handled_by": "由谁处理",
    "uses_system": "使用系统",
    "triggers": "触发",
    "requires": "需要",
    "has_step": "包含步骤",
    "applies_to": "适用于",
    "has_deadline": "有截止时间",
    "mentioned_in": "出现在文档",
    "depends_on": "依赖",
    "same_as": "同义实体",
    "related_to": "相关",
}

DEFAULT_ENTITY_TYPE = "other"
DEFAULT_RELATION_TYPE = "related_to"


def normalize_entity_type(value: str | None) -> str:
    key = str(value or "").strip().lower()
    return key if key in ENTITY_TYPES else DEFAULT_ENTITY_TYPE


def normalize_relation_type(value: str | None) -> str:
    key = str(value or "").strip().lower()
    return key if key in RELATION_TYPES else DEFAULT_RELATION_TYPE
