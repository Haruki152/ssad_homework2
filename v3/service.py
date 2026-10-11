"""v3 应用服务：装配规则上下文、编排仓储访问，并在事务内处理内容变更事件。
注册表统一执行已注册规则；规则是否完整、行为是否正确仍需回归测试。
"""
from __future__ import annotations

from .domain import (
    ContentChanged, DomainError, Item, ItemCreated, StateMachine,
)
from .repository import ItemRepository
from .rules import REGISTRY, RuleContext


class NotFound(Exception):
    pass


UNSET = object()


def apply_rules(ctx: RuleContext) -> None:
    """按注册顺序执行全部规则，任一失败即抛出。"""
    for rule in REGISTRY:
        rule(ctx)


class ItemService:
    """条目应用服务。"""

    def __init__(self, session) -> None:
        self.repo = ItemRepository(session)
        self.events: list = []

    # ---------- 用例 ----------

    def create_item(
        self,
        project_id: int,
        item_type_id: int,
        title: str,
        owner: str | None = None,
        attrs: dict | None = None,
    ) -> Item:
        item = Item(
            project_id=project_id,
            item_type_id=item_type_id,
            title=title,
            owner=owner,
            attrs=dict(attrs or {}),
        )
        association_error = self.repo.ensure_type_project(project_id, item_type_id)
        if association_error:
            if association_error.endswith("not found"):
                raise NotFound(association_error)
            raise DomainError(association_error)
        ctx = RuleContext(
            item=item,
            attr_definitions=self.repo.attr_definitions(item_type_id),
            current_status=item.status,
        )
        apply_rules(ctx)

        self.repo.add(item)
        self.events.append(ItemCreated(item.item_id))
        return item

    def update_item(
        self,
        item_id: int,
        title: str | None = None,
        status: str | None = None,
        owner=UNSET,
        attrs: dict | None = None,
    ) -> Item:
        item = self.repo.get(item_id)
        if item is None:
            raise NotFound(f"item {item_id}")

        old_snapshot = (item.title, dict(item.attrs))

        if title is not None:
            item.title = title
        if owner is not UNSET:
            item.owner = owner
        if attrs is not None:
            item.attrs = dict(attrs)

        ctx = RuleContext(
            item=item,
            attr_definitions=self.repo.attr_definitions(item.item_type_id),
            current_status=item.status,
            target_status=status,
        )
        apply_rules(ctx)

        if status is not None:
            StateMachine.transition(item, status)

        self.repo.save(item)

        if (item.title, dict(item.attrs)) != old_snapshot:
            self.events.append(ContentChanged(item.item_id))

        return item

    def get_trace(self, item_id: int) -> dict:
        if self.repo.get(item_id) is None:
            raise NotFound(f"item {item_id}")
        return {
            "upstream": self.repo.upstream(item_id),
            "downstream": self.repo.downstream(item_id),
        }

    # ---------- 事件派发 ----------

    def dispatch(self) -> list:
        """在事务提交前派发领域事件。"""
        handled = []
        for ev in self.events:
            if isinstance(ev, ContentChanged):
                n = self.repo.mark_downstream_suspect(ev.item_id)
                handled.append((ev, n))
        self.events.clear()
        return handled
