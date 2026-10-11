"""HTTP 请求模型。ORM 与请求模型各自承担职责，共同字段通过继承复用。"""
from typing import Literal
from pydantic import AliasChoices, BaseModel, ConfigDict, Field, field_validator


class RequestModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Named(RequestModel):
    name: str

    @field_validator("name")
    @classmethod
    def nonempty(cls, value):
        value = value.strip()
        if not value:
            raise ValueError("名称不能为空")
        return value


class ProjectIn(Named):
    pass


class ItemTypeIn(Named):
    project_id: int = Field(gt=0)


class AttributeIn(Named):
    data_type: Literal["text", "int", "enum"]
    value_domain: str | None = None
    required: bool = False


class ItemFields(RequestModel):
    title: str | None = None
    status: str | None = None
    owner: str | None = None
    custom_attrs: dict | None = Field(
        default=None, validation_alias=AliasChoices("custom_attrs", "attrs")
    )

    @field_validator("title", "status")
    @classmethod
    def nonempty_if_present(cls, value):
        if value is None or not value.strip():
            raise ValueError("title/status 显式提交时不能为空")
        return value.strip()

    @field_validator("custom_attrs")
    @classmethod
    def attrs_not_null(cls, value):
        if value is None:
            raise ValueError("属性对象不可为 null，请使用 {} 或省略该字段")
        return value


class ItemIn(ItemFields):
    project_id: int = Field(gt=0)
    item_type_id: int = Field(gt=0)
    title: str

    @field_validator("status")
    @classmethod
    def initial_status(cls, value):
        if value != "draft":
            raise ValueError("新条目只能以 draft 状态创建")
        return value


class ItemUpdate(ItemFields):
    pass


class RelationshipIn(RequestModel):
    from_item_id: int = Field(gt=0)
    to_item_id: int = Field(gt=0)
    link_type: str

    @field_validator("link_type")
    @classmethod
    def nonempty(cls, value):
        if not value.strip():
            raise ValueError("关系类型不能为空")
        return value.strip()
