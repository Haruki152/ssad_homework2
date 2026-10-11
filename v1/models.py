"""v1/models.py —— 同一会话分角色生成的缺陷示例的数据模型

Data agent 依据 contract.md 产出。
"""
from datetime import datetime

from sqlalchemy import (
    JSON, Boolean, Column, DateTime, ForeignKey, Integer, String,
)
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()


class Project(Base):
    __tablename__ = "project"

    project_id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String, nullable=False)
    created_at = Column(DateTime, default=datetime.now)

    item_types = relationship("ItemType", back_populates="project")
    items = relationship("Item", back_populates="project")


class ItemType(Base):
    __tablename__ = "item_type"

    item_type_id = Column(Integer, primary_key=True, autoincrement=True)
    project_id = Column(Integer, ForeignKey("project.project_id"), nullable=False)
    name = Column(String, nullable=False)

    project = relationship("Project", back_populates="item_types")
    attributes = relationship("AttributeDefinition", back_populates="item_type")
    items = relationship("Item", back_populates="item_type")


class AttributeDefinition(Base):
    __tablename__ = "attribute_definition"

    attr_id = Column(Integer, primary_key=True, autoincrement=True)
    item_type_id = Column(Integer, ForeignKey("item_type.item_type_id"), nullable=False)
    name = Column(String, nullable=False)
    data_type = Column(String, nullable=False)
    value_domain = Column(String, nullable=True)
    required = Column(Boolean, default=False, nullable=False)

    item_type = relationship("ItemType", back_populates="attributes")


class Item(Base):
    __tablename__ = "item"

    item_id = Column(Integer, primary_key=True, autoincrement=True)
    project_id = Column(Integer, ForeignKey("project.project_id"), nullable=False)
    item_type_id = Column(Integer, ForeignKey("item_type.item_type_id"), nullable=False)
    title = Column(String, nullable=False)
    status = Column(String, nullable=False, default="draft")
    owner = Column(String, nullable=True)

    # 常用业务属性直接建成列，方便查询
    priority = Column(Integer, default=3)
    source = Column(String, nullable=True)
    rationale = Column(String, nullable=True)
    acceptance = Column(String, nullable=True)
    stability = Column(String, nullable=True)

    custom_attrs = Column(JSON, nullable=True)

    project = relationship("Project", back_populates="items")
    item_type = relationship("ItemType", back_populates="items")


class Relationship(Base):
    __tablename__ = "relationship"

    rel_id = Column(Integer, primary_key=True, autoincrement=True)
    from_item_id = Column(Integer, ForeignKey("item.item_id"), nullable=False)
    to_item_id = Column(Integer, ForeignKey("item.item_id"), nullable=False)
    link_type = Column(String, nullable=False)
    suspect = Column(Boolean, default=False, nullable=False)


# 数据库引擎由独立模块统一配置。
from .database import engine
