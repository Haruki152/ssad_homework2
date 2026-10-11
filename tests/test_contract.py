"""两个修复版共用的行为验收，真实请求 API 和临时 SQLite 数据库。"""
import importlib
import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session


STATES = ["draft", "reviewing", "approved", "implemented", "verified", "deprecated"]
FORWARD = dict(zip(STATES[:4], STATES[1:5]))
PATHS = {
    "draft": [], "reviewing": ["reviewing"],
    "approved": ["reviewing", "approved"],
    "implemented": ["reviewing", "approved", "implemented"],
    "verified": ["reviewing", "approved", "implemented", "verified"],
    "deprecated": ["deprecated"],
}


def test_contract_routes(client):
    required = {
        ("post", "/projects"), ("post", "/item-types"),
        ("post", "/item-types/{type_id}/attributes"), ("post", "/items"),
        ("get", "/items/{item_id}"), ("put", "/items/{item_id}"),
        ("post", "/relationships"), ("get", "/items/{item_id}/trace"),
    }
    document = client.get("/openapi.json").json()
    for method, path in required:
        assert method in document["paths"].get(path, {}), (method, path)


def test_crud_and_persistence(client, seed, item):
    assert client.get(f"/items/{item}").json()["custom_attrs"] == seed["custom_attrs"]
    assert client.get("/items").json()[0]["item_id"] == item
    assert client.put(f"/items/{item}", json={"title": "订单查询修订"}).status_code == 200
    assert client.get(f"/items/{item}").json()["title"] == "订单查询修订"
    assert client.delete(f"/items/{item}").status_code == 200
    assert client.get(f"/items/{item}").status_code == 404


@pytest.mark.parametrize("path", ["/items/999", "/items/999/trace"])
def test_missing_item(client, path):
    assert client.get(path).status_code == 404


@pytest.mark.parametrize("src", STATES)
@pytest.mark.parametrize("dst", STATES)
def test_state_matrix(client, item, src, dst):
    for step in PATHS[src]:
        assert client.put(f"/items/{item}", json={"status": step}).status_code == 200
    legal = src == dst or dst == "deprecated" or FORWARD.get(src) == dst
    response = client.put(f"/items/{item}", json={"status": dst})
    assert response.status_code == (200 if legal else 400), response.text
    assert client.get(f"/items/{item}").json()["status"] == (dst if legal else src)


@pytest.mark.parametrize("attrs", [
    {}, {"验收度量": None}, {"验收度量": "   "}, {"验收度量": 123},
    {"验收度量": "可验收", "未知": "x"},
    {"验收度量": "可验收", "优先级": "3"},
    {"验收度量": "可验收", "优先级": True},
    {"验收度量": "可验收", "优先级": 6},
    {"验收度量": "可验收", "稳定性": "未知"},
])
def test_invalid_attributes_on_create(client, seed, attrs):
    response = client.post("/items", json={**seed, "custom_attrs": attrs})
    assert response.status_code == 400, response.text
    assert client.get("/items").json() == []


def test_invalid_update_rolls_back(client, item, seed):
    response = client.put(f"/items/{item}", json={
        "title": "不应该被保存", "status": "reviewing", "custom_attrs": {},
    })
    assert response.status_code == 400
    row = client.get(f"/items/{item}").json()
    assert row["title"] == seed["title"] and row["status"] == "draft"


def test_owner_omitted_and_cleared(client, item, seed):
    assert client.put(f"/items/{item}", json={"title": "改标题"}).status_code == 200
    assert client.get(f"/items/{item}").json()["owner"] == seed["owner"]
    assert client.put(f"/items/{item}", json={"owner": None}).status_code == 200
    assert client.get(f"/items/{item}").json()["owner"] is None


def test_legacy_attrs_alias(client, seed):
    payload = {k: v for k, v in seed.items() if k != "custom_attrs"}
    payload["attrs"] = seed["custom_attrs"]
    response = client.post("/items", json=payload)
    assert response.status_code == 200
    item_id = response.json()["item_id"]
    assert client.get(f"/items/{item_id}").json()["custom_attrs"] == seed["custom_attrs"]


def test_both_attrs_names_rejected(client, seed):
    assert client.post("/items", json={**seed, "attrs": {}}).status_code == 422


@pytest.mark.parametrize("payload", [{"title": None}, {"title": " "}, {"status": None},
                                    {"custom_attrs": None}, {"unexpected": 1}])
def test_invalid_request_fields(client, item, payload):
    assert client.put(f"/items/{item}", json=payload).status_code == 422


def test_cross_project_type(client, seed):
    other = client.post("/projects", json={"name": "另一个项目"}).json()["project_id"]
    assert client.post("/items", json={**seed, "project_id": other}).status_code == 400
    assert client.post("/items", json={**seed, "project_id": 999}).status_code == 404
    assert client.post("/items", json={**seed, "item_type_id": 999}).status_code == 404


def test_relationship_trace_and_suspect(client, seed, item):
    downstream = client.post("/items", json={**seed, "title": "验证用例"}).json()["item_id"]
    body = {"from_item_id": item, "to_item_id": downstream, "link_type": "verifies"}
    rel = client.post("/relationships", json=body)
    assert rel.status_code == 200, rel.text
    rel_id = rel.json()["rel_id"]
    assert client.post("/relationships", json=body).status_code == 409
    assert client.put(f"/items/{item}", json={"owner": "新负责人"}).status_code == 200
    assert not client.get(f"/items/{downstream}/trace").json()["upstream"][0]["suspect"]
    assert client.put(f"/items/{item}", json={"custom_attrs": seed["custom_attrs"]}).status_code == 200
    assert not client.get(f"/items/{downstream}/trace").json()["upstream"][0]["suspect"]
    assert client.put(f"/items/{item}", json={"title": "内容变更"}).status_code == 200
    entry = client.get(f"/items/{downstream}/trace").json()["upstream"][0]
    assert entry["item_id"] == item and entry["suspect"]
    assert client.get(f"/items/{item}/trace").json()["downstream"][0]["item_id"] == downstream
    assert client.post(f"/relationships/{rel_id}/clear-suspect").status_code == 200
    assert not client.get(f"/items/{downstream}/trace").json()["upstream"][0]["suspect"]
    assert client.delete(f"/items/{item}").status_code == 200
    assert client.get(f"/items/{downstream}/trace").json()["upstream"] == []
    assert client.post(f"/relationships/{rel_id}/clear-suspect").status_code == 404


def test_relationship_validation(client, seed, item):
    assert client.post("/relationships", json={
        "from_item_id": item, "to_item_id": item, "link_type": "depends",
    }).status_code == 400
    assert client.post("/relationships", json={
        "from_item_id": item, "to_item_id": 999, "link_type": "depends",
    }).status_code == 404
    project = client.post("/projects", json={"name": "外部项目"}).json()["project_id"]
    item_type = client.post("/item-types", json={"project_id": project, "name": "类型"}).json()["item_type_id"]
    other = client.post("/items", json={"project_id": project, "item_type_id": item_type, "title": "外部条目"}).json()["item_id"]
    assert client.post("/relationships", json={
        "from_item_id": item, "to_item_id": other, "link_type": "depends",
    }).status_code == 400


def test_search_route_and_literal_wildcards(client, seed, item):
    assert client.get("/items/search", params={"keyword": "订单"}).json() == [{"item_id": item, "title": seed["title"]}]
    for keyword in ["' OR '1'='1", "%", "_", "'; DROP TABLE item; --"]:
        response = client.get("/items/search", params={"keyword": keyword})
        assert response.status_code == 200 and response.json() == []
    assert client.get(f"/items/{item}").status_code == 200


def test_definition_constraints(client, seed, item):
    path = f"/item-types/{seed['item_type_id']}/attributes"
    assert client.post(path, json={"name": "验收度量", "data_type": "text"}).status_code == 409
    assert client.post(path, json={"name": "新增必填", "data_type": "text", "required": True}).status_code == 400
    assert client.post(path, json={"name": "枚举", "data_type": "enum"}).status_code == 400
    assert client.post(path, json={"name": "整数", "data_type": "int", "value_domain": "abc"}).status_code == 400
    assert client.post(path, json={"name": "备注", "data_type": "text"}).status_code == 200
    assert "新增必填" not in [d["name"] for d in client.get(path).json()]


def test_database_foreign_keys(client, request):
    version = request.config.getoption("--rms-version")
    api = importlib.import_module(f"{version}.api")
    models = importlib.import_module(f"{version}.models")
    with Session(api.engine) as session:
        session.add(models.Item(project_id=999, item_type_id=999, title="孤儿条目"))
        with pytest.raises(IntegrityError):
            session.commit()


def test_item_schema(client, request):
    version = request.config.getoption("--rms-version")
    models = importlib.import_module(f"{version}.models")
    assert set(models.Item.__table__.columns.keys()) == {
        "item_id", "project_id", "item_type_id", "title", "status", "owner", "custom_attrs",
    }
