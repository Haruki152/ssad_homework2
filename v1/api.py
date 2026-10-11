"""v1/api.py —— 同一会话分角色生成的缺陷示例的 API 层

Backend agent 依据 contract.md 产出。
"""
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

from .models import Base, AttributeDefinition, Item, ItemType, Project, Relationship, engine

@asynccontextmanager
async def lifespan(app):
    Base.metadata.create_all(engine)
    yield


app = FastAPI(title="需求管理系统 v1（缺陷演示，请勿用于真实数据）", lifespan=lifespan)


def get_session() -> Session:
    return Session(engine)


# ---------- 请求模型 ----------

class ProjectIn(BaseModel):
    name: str


class ItemTypeIn(BaseModel):
    project_id: int
    name: str


class AttributeIn(BaseModel):
    name: str
    data_type: str
    value_domain: str | None = None
    required: bool = False


class ItemIn(BaseModel):
    project_id: int
    item_type_id: int
    title: str
    priority: int = 3
    source: str | None = None
    rationale: str | None = None
    acceptance: str | None = None
    custom_attrs: dict | None = None


class ItemUpdate(BaseModel):
    title: str | None = None
    status: str | None = None
    owner: str | None = None
    priority: int | None = None
    custom_attrs: dict | None = None


class RelationshipIn(BaseModel):
    from_item_id: int
    to_item_id: int
    link_type: str


# ---------- 接口 ----------

@app.post("/projects")
def create_project(body: ProjectIn):
    with get_session() as s:
        p = Project(name=body.name)
        s.add(p)
        s.commit()
        return {"project_id": p.project_id}


@app.post("/item-types")
def create_item_type(body: ItemTypeIn):
    with get_session() as s:
        t = ItemType(project_id=body.project_id, name=body.name)
        s.add(t)
        s.commit()
        return {"item_type_id": t.item_type_id}


@app.post("/item-types/{type_id}/attributes")
def add_attribute(type_id: int, body: AttributeIn):
    with get_session() as s:
        a = AttributeDefinition(
            item_type_id=type_id,
            name=body.name,
            data_type=body.data_type,
            value_domain=body.value_domain,
            required=body.required,
        )
        s.add(a)
        s.commit()
        return {"attr_id": a.attr_id}


@app.post("/items")
def create_item(body: ItemIn):
    with get_session() as s:
        it = Item(
            project_id=body.project_id,
            item_type_id=body.item_type_id,
            title=body.title,
            priority=body.priority,
            source=body.source,
            rationale=body.rationale,
            acceptance=body.acceptance,
            custom_attrs=body.custom_attrs,
        )
        s.add(it)
        s.commit()
        return {"item_id": it.item_id}


@app.get("/items/search")
def search_items(keyword: str):
    """按标题模糊搜索条目。"""
    with get_session() as s:
        sql = f"SELECT item_id, title FROM item WHERE title LIKE '%{keyword}%'"
        rows = s.execute(text(sql)).fetchall()
        return [{"item_id": r[0], "title": r[1]} for r in rows]


@app.get("/items/{item_id}")
def get_item(item_id: int):
    with get_session() as s:
        it = s.get(Item, item_id)
        if it is None:
            raise HTTPException(404, "item not found")
        return {
            "item_id": it.item_id,
            "title": it.title,
            "status": it.status,
            "owner": it.owner,
            "priority": it.priority,
            "source": it.source,
            "rationale": it.rationale,
            "acceptance": it.acceptance,
            "custom_attrs": it.custom_attrs,
        }


@app.put("/items/{item_id}")
def update_item(item_id: int, body: ItemUpdate):
    with get_session() as s:
        it = s.get(Item, item_id)
        if it is None:
            raise HTTPException(404, "item not found")

        if body.title is not None:
            it.title = body.title
        if body.status is not None:
            it.status = body.status
        if body.owner is not None:
            it.owner = body.owner
        if body.priority is not None:
            it.priority = body.priority
        if body.custom_attrs is not None:
            it.custom_attrs = body.custom_attrs

        s.commit()
        return {"ok": True}


@app.post("/relationships")
def create_relationship(body: RelationshipIn):
    with get_session() as s:
        r = Relationship(
            from_item_id=body.from_item_id,
            to_item_id=body.to_item_id,
            link_type=body.link_type,
        )
        s.add(r)
        s.commit()
        return {"rel_id": r.rel_id}


@app.get("/items/{item_id}/trace")
def get_trace(item_id: int):
    with get_session() as s:
        up = s.query(Relationship).filter(
            Relationship.to_item_id == item_id
        ).all()
        down = s.query(Relationship).filter(
            Relationship.from_item_id == item_id
        ).all()
        return {
            "upstream": [
                {"rel_id": r.rel_id, "item_id": r.from_item_id,
                 "link_type": r.link_type, "suspect": r.suspect}
                for r in up
            ],
            "downstream": [
                {"rel_id": r.rel_id, "item_id": r.to_item_id,
                 "link_type": r.link_type, "suspect": r.suspect}
                for r in down
            ],
        }
