"""v2 HTTP API：契约八个接口完整，附加列表、搜索、删除及复核接口。"""
from contextlib import asynccontextmanager
from fastapi import Depends, FastAPI, HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from .database import engine
from .models import Base, Project, ItemType, AttributeDefinition, Item, Relationship
from .schemas import ProjectIn, ItemTypeIn, AttributeIn, ItemIn, ItemUpdate, RelationshipIn
from .validation import ValidationError, validate_definition, validate_values
from .service import validate_attributes, validate_status_transition, mark_downstream_suspect


@asynccontextmanager
async def lifespan(app):
    Base.metadata.create_all(engine)
    yield


app = FastAPI(title="需求管理系统 v2", lifespan=lifespan)


def get_session():
    with Session(engine) as session:
        try:
            yield session
            session.commit()
        except IntegrityError as exc:
            session.rollback()
            raise HTTPException(409, "数据冲突：名称、属性或关系重复，或关联对象无效") from exc
        except Exception:
            session.rollback()
            raise


def require(session, model, object_id, message):
    row = session.get(model, object_id)
    if row is None:
        raise HTTPException(404, message)
    return row


def check_values(definitions, attrs):
    try:
        validate_values(definitions, attrs)
    except ValidationError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.post("/projects")
def create_project(body: ProjectIn, session: Session = Depends(get_session, scope="function")):
    row = Project(name=body.name)
    session.add(row)
    session.flush()
    return {"project_id": row.project_id}


@app.get("/projects")
def list_projects(session: Session = Depends(get_session, scope="function")):
    return [{"project_id": r.project_id, "name": r.name}
            for r in session.scalars(select(Project).order_by(Project.project_id))]


@app.post("/item-types")
def create_item_type(body: ItemTypeIn, session: Session = Depends(get_session, scope="function")):
    require(session, Project, body.project_id, "project not found")
    row = ItemType(project_id=body.project_id, name=body.name)
    session.add(row)
    session.flush()
    return {"item_type_id": row.item_type_id}


@app.get("/item-types")
def list_item_types(project_id: int | None = None, session: Session = Depends(get_session, scope="function")):
    statement = select(ItemType).order_by(ItemType.item_type_id)
    if project_id is not None:
        require(session, Project, project_id, "project not found")
        statement = statement.where(ItemType.project_id == project_id)
    return [{"item_type_id": r.item_type_id, "project_id": r.project_id, "name": r.name}
            for r in session.scalars(statement)]


@app.post("/item-types/{type_id}/attributes")
def add_attribute(type_id: int, body: AttributeIn, session: Session = Depends(get_session, scope="function")):
    require(session, ItemType, type_id, "item type not found")
    try:
        validate_definition(body.name, body.data_type, body.value_domain)
    except ValidationError as exc:
        raise HTTPException(400, str(exc)) from exc
    definitions = list(session.scalars(select(AttributeDefinition).where(
        AttributeDefinition.item_type_id == type_id
    )))
    if any(d.name == body.name for d in definitions):
        raise HTTPException(409, "属性名称重复")
    row = AttributeDefinition(item_type_id=type_id, **body.model_dump())
    # 不允许在已有条目上悄悄引入不满足的必填或类型约束。
    items = list(session.scalars(select(Item).where(Item.item_type_id == type_id)))
    for item in items:
        check_values(definitions + [row], item.custom_attrs)
    session.add(row)
    session.flush()
    return {"attr_id": row.attr_id}


@app.get("/item-types/{type_id}/attributes")
def list_attributes(type_id: int, session: Session = Depends(get_session, scope="function")):
    require(session, ItemType, type_id, "item type not found")
    return [{"attr_id": d.attr_id, "name": d.name, "data_type": d.data_type,
             "value_domain": d.value_domain, "required": d.required}
            for d in session.scalars(select(AttributeDefinition).where(
                AttributeDefinition.item_type_id == type_id
            ).order_by(AttributeDefinition.attr_id))]


def item_view(item):
    return {"item_id": item.item_id, "project_id": item.project_id,
            "item_type_id": item.item_type_id, "title": item.title,
            "status": item.status, "owner": item.owner,
            "custom_attrs": dict(item.custom_attrs or {})}


@app.get("/items/search")
def search_items(keyword: str, session: Session = Depends(get_session, scope="function")):
    statement = select(Item).where(Item.title.contains(keyword, autoescape=True))
    return [{"item_id": r.item_id, "title": r.title}
            for r in session.scalars(statement.order_by(Item.item_id))]


@app.get("/items")
def list_items(project_id: int | None = None, session: Session = Depends(get_session, scope="function")):
    statement = select(Item).order_by(Item.item_id)
    if project_id is not None:
        require(session, Project, project_id, "project not found")
        statement = statement.where(Item.project_id == project_id)
    return [item_view(row) for row in session.scalars(statement)]


@app.post("/items")
def create_item(body: ItemIn, session: Session = Depends(get_session, scope="function")):
    require(session, Project, body.project_id, "project not found")
    item_type = require(session, ItemType, body.item_type_id, "item type not found")
    if item_type.project_id != body.project_id:
        raise HTTPException(400, "条目类型不属于指定项目")
    try:
        validate_attributes(session, body.item_type_id, body.custom_attrs)
    except ValidationError as exc:
        raise HTTPException(400, str(exc)) from exc
    row = Item(project_id=body.project_id, item_type_id=body.item_type_id,
               title=body.title, owner=body.owner, custom_attrs=body.custom_attrs or {})
    session.add(row)
    session.flush()
    return {"item_id": row.item_id}


@app.get("/items/{item_id}")
def get_item(item_id: int, session: Session = Depends(get_session, scope="function")):
    return item_view(require(session, Item, item_id, "item not found"))


@app.put("/items/{item_id}")
def update_item(item_id: int, body: ItemUpdate, session: Session = Depends(get_session, scope="function")):
    row = require(session, Item, item_id, "item not found")
    changes = body.model_dump(exclude_unset=True)
    target_status = changes.get("status")
    if target_status is not None and target_status != row.status:
        if not validate_status_transition(row.status, target_status):
            raise HTTPException(400, f"非法状态流转: {row.status} -> {target_status}")
    try:
        validate_attributes(session, row.item_type_id,
                            changes.get("custom_attrs", row.custom_attrs))
    except ValidationError as exc:
        raise HTTPException(400, str(exc)) from exc
    content_changed = any(
        key in changes and changes[key] != getattr(row, key)
        for key in ("title", "custom_attrs")
    )
    for key, value in changes.items():
        setattr(row, key, value)
    if content_changed:
        mark_downstream_suspect(session, item_id)
    session.flush()
    return {"ok": True}


@app.delete("/items/{item_id}")
def delete_item(item_id: int, session: Session = Depends(get_session, scope="function")):
    row = require(session, Item, item_id, "item not found")
    session.delete(row)
    session.flush()
    return {"ok": True}


@app.post("/relationships")
def create_relationship(body: RelationshipIn, session: Session = Depends(get_session, scope="function")):
    upstream = require(session, Item, body.from_item_id, "upstream item not found")
    downstream = require(session, Item, body.to_item_id, "downstream item not found")
    if upstream.item_id == downstream.item_id:
        raise HTTPException(400, "条目不能关联自身")
    if upstream.project_id != downstream.project_id:
        raise HTTPException(400, "本作业不支持跨项目关系")
    row = Relationship(**body.model_dump())
    session.add(row)
    session.flush()
    return {"rel_id": row.rel_id}


@app.delete("/relationships/{rel_id}")
def delete_relationship(rel_id: int, session: Session = Depends(get_session, scope="function")):
    row = require(session, Relationship, rel_id, "relationship not found")
    session.delete(row)
    session.flush()
    return {"ok": True}


@app.post("/relationships/{rel_id}/clear-suspect")
def clear_relationship_suspect(rel_id: int, session: Session = Depends(get_session, scope="function")):
    row = require(session, Relationship, rel_id, "relationship not found")
    row.suspect = False
    session.flush()
    return {"ok": True}


@app.get("/items/{item_id}/trace")
def get_trace(item_id: int, session: Session = Depends(get_session, scope="function")):
    require(session, Item, item_id, "item not found")
    def entries(statement, endpoint):
        return [{"rel_id": r.rel_id, "item_id": getattr(r, endpoint),
                 "link_type": r.link_type, "suspect": r.suspect}
                for r in session.scalars(statement)]
    return {
        "upstream": entries(select(Relationship).where(
            Relationship.to_item_id == item_id), "from_item_id"),
        "downstream": entries(select(Relationship).where(
            Relationship.from_item_id == item_id), "to_item_id"),
    }
