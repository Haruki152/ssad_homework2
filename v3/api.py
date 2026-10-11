"""v3 HTTP API：条目用例经过领域/仓储；项目、类型及关系的管理接口直接使用 ORM。
本次没有声称所有接口都完成了纯 HTTP 适配层的分离。
"""
from contextlib import asynccontextmanager
from fastapi import Depends, FastAPI, HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from .database import engine
from .models import Base, Project, ItemType, AttributeDefinition, Item, Relationship
from .schemas import ProjectIn, ItemTypeIn, AttributeIn, ItemIn, ItemUpdate, RelationshipIn
from .validation import ValidationError, validate_definition, validate_values
from .domain import DomainError
from .service import ItemService, NotFound, UNSET


def handle(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except NotFound as exc:
        raise HTTPException(404, str(exc)) from exc
    except DomainError as exc:
        raise HTTPException(400, str(exc)) from exc


@asynccontextmanager
async def lifespan(app):
    Base.metadata.create_all(engine)
    yield


app = FastAPI(title="需求管理系统 v3", lifespan=lifespan)


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
    service = ItemService(session)
    item = handle(service.create_item, body.project_id, body.item_type_id,
                  body.title, body.owner, body.custom_attrs)
    service.dispatch()
    session.flush()
    return {"item_id": item.item_id}


@app.get("/items/{item_id}")
def get_item(item_id: int, session: Session = Depends(get_session, scope="function")):
    return item_view(require(session, Item, item_id, "item not found"))


@app.put("/items/{item_id}")
def update_item(item_id: int, body: ItemUpdate, session: Session = Depends(get_session, scope="function")):
    service = ItemService(session)
    handle(service.update_item, item_id, body.title, body.status,
           body.owner if "owner" in body.model_fields_set else UNSET,
           body.custom_attrs)
    service.dispatch()
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
    return handle(ItemService(session).get_trace, item_id)
