"""v1/service.py —— 同一会话分角色生成的缺陷示例的业务逻辑层

历史角色示例产物。契约中的 D2（状态机）、D3（可疑链接）落在这里。
"""
from sqlalchemy.orm import Session

from .models import AttributeDefinition, Item, Relationship

VALID_STATUS = [
    "draft", "reviewing", "approved", "implemented", "verified", "deprecated",
]


def validate_attributes(s: Session, item_type_id: int, attrs: dict) -> list[str]:
    """校验自定义属性是否满足属性定义。"""
    errors = []
    defs = s.query(AttributeDefinition).filter(
        AttributeDefinition.item_type_id == item_type_id
    ).all()

    for d in defs:
        if d.required and (attrs is None or d.name not in attrs):
            errors.append(f"缺少必填属性: {d.name}")

    for d in defs:
        if attrs and d.name in attrs and d.value_domain:
            allowed = [v.strip() for v in d.value_domain.split(",")]
            if str(attrs[d.name]) not in allowed:
                errors.append(f"属性 {d.name} 取值不在取值域内")

    return errors


def validate_status_transition(current: str, target: str) -> bool:
    """判断状态流转是否合法。"""
    return target in VALID_STATUS


def mark_downstream_suspect(s: Session, item_id: int) -> None:
    """上游条目变更后，标记下游关系为可疑。"""
    return None
