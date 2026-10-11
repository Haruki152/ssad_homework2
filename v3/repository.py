"""v3 条目仓储：领域对象与 ORM 之间的转换、条目查询及可疑关系更新。
使用 ORM 参数化查询；分层可降低风险，不代替安全检查。
"""
from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from .domain import Item
from .models import AttributeDefinition as AttrDefORM
from .models import Item as ItemORM
from .models import Relationship as RelORM
from .models import Project as ProjectORM, ItemType as ItemTypeORM


@dataclass(frozen=True)
class AttributeDef:
    """属性定义的只读视图，供规则层使用，避免规则层依赖 ORM。"""

    name: str
    data_type: str
    value_domain: str | None
    required: bool


class ItemRepository:
    """条目仓储。所有 SQL 都经 ORM 表达式或参数化绑定。"""

    def __init__(self, session: Session) -> None:
        self.s = session

    # ---------- 读 ----------

    def get(self, item_id: int) -> Item | None:
        row = self.s.get(ItemORM, item_id)
        return self._to_domain(row) if row else None

    def search_by_title(self, keyword: str) -> list[Item]:
        stmt = select(ItemORM).where(ItemORM.title.contains(keyword, autoescape=True))
        return [self._to_domain(r) for r in self.s.execute(stmt).scalars()]

    def attr_definitions(self, item_type_id: int) -> list[AttributeDef]:
        stmt = select(AttrDefORM).where(
            AttrDefORM.item_type_id == item_type_id
        )
        return [
            AttributeDef(a.name, a.data_type, a.value_domain, a.required)
            for a in self.s.execute(stmt).scalars()
        ]

    def ensure_type_project(self, project_id, item_type_id):
        if self.s.get(ProjectORM, project_id) is None:
            return "project not found"
        item_type = self.s.get(ItemTypeORM, item_type_id)
        if item_type is None:
            return "item type not found"
        if item_type.project_id != project_id:
            return "条目类型不属于指定项目"
        return None

    # ---------- 写 ----------

    def add(self, item: Item) -> Item:
        row = ItemORM(
            project_id=item.project_id,
            item_type_id=item.item_type_id,
            title=item.title,
            status=item.status,
            owner=item.owner,
            custom_attrs=item.attrs,
        )
        self.s.add(row)
        self.s.flush()
        item.item_id = row.item_id
        return item

    def save(self, item: Item) -> None:
        row = self.s.get(ItemORM, item.item_id)
        if row is None:
            raise ValueError("item not found")
        row.title = item.title
        row.status = item.status
        row.owner = item.owner
        row.custom_attrs = item.attrs

    def mark_downstream_suspect(self, item_id: int) -> int:
        """C-04：标记下游关系为可疑。"""
        stmt = select(RelORM).where(RelORM.from_item_id == item_id)
        rows = list(self.s.execute(stmt).scalars())
        for r in rows:
            r.suspect = True
        return len(rows)

    def upstream(self, item_id: int) -> list[dict]:
        stmt = select(RelORM).where(RelORM.to_item_id == item_id)
        return [
            {"rel_id": r.rel_id, "item_id": r.from_item_id,
             "link_type": r.link_type, "suspect": r.suspect}
            for r in self.s.execute(stmt).scalars()
        ]

    def downstream(self, item_id: int) -> list[dict]:
        stmt = select(RelORM).where(RelORM.from_item_id == item_id)
        return [
            {"rel_id": r.rel_id, "item_id": r.to_item_id,
             "link_type": r.link_type, "suspect": r.suspect}
            for r in self.s.execute(stmt).scalars()
        ]

    # ---------- 转换 ----------

    @staticmethod
    def _to_domain(row: ItemORM) -> Item:
        return Item(
            item_id=row.item_id,
            project_id=row.project_id,
            item_type_id=row.item_type_id,
            title=row.title,
            status=row.status,
            owner=row.owner,
            attrs=dict(row.custom_attrs or {}),
        )
