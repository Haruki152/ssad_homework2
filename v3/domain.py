"""v3/domain.py —— 领域层（重新设计）

设计意图：
    把领域模型从 ORM 中解放出来，使其不依赖任何持久化框架。
    状态机由散落的 if 提升为独立对象，可单独测试。
    领域事件把"变更后要做什么"与"谁来做"解耦。

对应缺陷：D-02（状态机未接入）、D-06（分层缺失）
"""
from __future__ import annotations

from dataclasses import dataclass, field


class DomainError(Exception):
    """领域规则被违反。API 层统一转 400。"""


@dataclass
class Item:
    """条目领域模型。不含任何 ORM 依赖。"""

    project_id: int
    item_type_id: int
    title: str
    item_id: int | None = None
    status: str = "draft"
    owner: str | None = None
    attrs: dict = field(default_factory=dict)


class StateMachine:
    """需求生命周期状态机。

    对应契约 D2 / 约束 C-03。合法边共 10 条。
    """

    LEGAL: dict[str, set[str]] = {
        "draft":       {"reviewing", "deprecated"},
        "reviewing":   {"approved", "deprecated"},
        "approved":    {"implemented", "deprecated"},
        "implemented": {"verified", "deprecated"},
        "verified":    {"deprecated"},
        "deprecated":  {"deprecated"},
    }

    @classmethod
    def states(cls) -> set[str]:
        return set(cls.LEGAL)

    @classmethod
    def can(cls, src: str, dst: str) -> bool:
        return dst in cls.LEGAL.get(src, set())

    @classmethod
    def transition(cls, item: Item, dst: str) -> None:
        if dst == item.status and dst in cls.states():
            return
        if not cls.can(item.status, dst):
            raise DomainError(f"非法状态流转: {item.status} -> {dst}")
        item.status = dst


# ---------- 领域事件 ----------

@dataclass(frozen=True)
class DomainEvent:
    pass


@dataclass(frozen=True)
class ContentChanged(DomainEvent):
    """条目内容被修改，下游关系需要做可疑标记。对应约束 C-04。"""

    item_id: int


@dataclass(frozen=True)
class ItemCreated(DomainEvent):
    item_id: int
