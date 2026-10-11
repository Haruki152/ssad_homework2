"""v2：保持直接业务校验结构，修复属性、状态和可疑传播。"""
from sqlalchemy import select
from .models import AttributeDefinition, Relationship
from .validation import ValidationError, validate_values


LEGAL_TRANSITIONS = {
    "draft": {"reviewing", "deprecated"},
    "reviewing": {"approved", "deprecated"},
    "approved": {"implemented", "deprecated"},
    "implemented": {"verified", "deprecated"},
    "verified": {"deprecated"},
    "deprecated": {"deprecated"},
}


def validate_status_transition(current, target):
    return target in LEGAL_TRANSITIONS.get(current, set())


def validate_attributes(session, item_type_id, attrs):
    definitions = list(session.scalars(select(AttributeDefinition).where(
        AttributeDefinition.item_type_id == item_type_id
    )))
    validate_values(definitions, attrs)


def mark_downstream_suspect(session, item_id):
    relationships = list(session.scalars(select(Relationship).where(
        Relationship.from_item_id == item_id
    )))
    for relationship in relationships:
        relationship.suspect = True
    return len(relationships)


def clear_suspect(session, rel_id):
    relationship = session.get(Relationship, rel_id)
    if relationship is None:
        raise ValidationError("relationship not found")
    relationship.suspect = False
