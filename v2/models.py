"""v2 数据模型：七字段 Item、可配置属性、唯一关系及 SQLite 外键。"""
from datetime import datetime

from sqlalchemy import (
    JSON, Boolean, CheckConstraint, Column, DateTime, ForeignKey, Integer, String, UniqueConstraint,
)
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()

ITEM_COLUMN_WHITELIST = frozenset({
    "item_id", "project_id", "item_type_id",
    "title", "status", "owner", "custom_attrs",
})


class Project(Base):
    __tablename__ = "project"

    project_id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String, nullable=False)
    created_at = Column(DateTime, default=datetime.now)

    item_types = relationship("ItemType", back_populates="project")
    items = relationship("Item", back_populates="project")


class ItemType(Base):
    __tablename__ = "item_type"
    __table_args__ = (UniqueConstraint("project_id", "name"),)

    item_type_id = Column(Integer, primary_key=True, autoincrement=True)
    project_id = Column(Integer, ForeignKey("project.project_id"), nullable=False)
    name = Column(String, nullable=False)

    project = relationship("Project", back_populates="item_types")
    attributes = relationship(
        "AttributeDefinition", back_populates="item_type",
        cascade="all, delete-orphan",
    )
    items = relationship("Item", back_populates="item_type")


class AttributeDefinition(Base):
    __tablename__ = "attribute_definition"
    __table_args__ = (UniqueConstraint("item_type_id", "name"),)

    attr_id = Column(Integer, primary_key=True, autoincrement=True)
    item_type_id = Column(
        Integer, ForeignKey("item_type.item_type_id", ondelete="CASCADE"),
        nullable=False,
    )
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
    custom_attrs = Column(JSON, nullable=True)

    project = relationship("Project", back_populates="items")
    item_type = relationship("ItemType", back_populates="items")


class Relationship(Base):
    __tablename__ = "relationship"
    __table_args__ = (
        UniqueConstraint("from_item_id", "to_item_id", "link_type"),
        CheckConstraint("from_item_id != to_item_id"),
    )

    rel_id = Column(Integer, primary_key=True, autoincrement=True)
    from_item_id = Column(
        Integer, ForeignKey("item.item_id", ondelete="CASCADE"), nullable=False,
    )
    to_item_id = Column(
        Integer, ForeignKey("item.item_id", ondelete="CASCADE"), nullable=False,
    )
    link_type = Column(String, nullable=False)
    suspect = Column(Boolean, default=False, nullable=False)


def item_columns_ok() -> bool:
    """C-01 验收：实际列集合与白名单相等。"""
    return frozenset(Item.__table__.columns.keys()) == ITEM_COLUMN_WHITELIST


# 数据库引擎由独立模块统一配置。
from .database import engine
