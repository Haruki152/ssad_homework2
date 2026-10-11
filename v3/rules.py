"""v3：规则注册表只声明实际可执行的业务校验。结构约束另由门禁验收。"""
from dataclasses import dataclass
from typing import Callable
from .domain import DomainError, StateMachine
from .validation import ValidationError, validate_values


@dataclass(frozen=True)
class RuleContext:
    item: object
    attr_definitions: list
    current_status: str
    target_status: str | None = None


@dataclass(frozen=True)
class Rule:
    code: str
    title: str
    check: Callable

    def __call__(self, context):
        self.check(context)


def _attributes(context):
    try:
        validate_values(context.attr_definitions, context.item.attrs)
    except ValidationError as exc:
        raise DomainError(str(exc)) from exc


def _state_transition(context):
    target = context.target_status
    if target is None:
        return
    if target == context.current_status and target in StateMachine.states():
        return
    if not StateMachine.can(context.current_status, target):
        raise DomainError(f"非法状态流转: {context.current_status} -> {target}")


REGISTRY = [
    Rule("C-02", "属性定义、必填值、类型与取值域", _attributes),
    Rule("C-03", "合法状态流转", _state_transition),
]
