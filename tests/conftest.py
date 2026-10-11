import importlib
from pathlib import Path
import sys
import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def tmp_path(request):
    # 独立测试目录，避免 Windows 沙箱无法访问 mode=0o700 的临时目录。
    import uuid
    folder = Path(request.config.getoption("--rms-root")) / "test-work" / uuid.uuid4().hex
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def pytest_addoption(parser):
    parser.addoption("--rms-version", default="v3", choices=["v1", "v2", "v3"])
    parser.addoption("--rms-root", default=str(Path(__file__).resolve().parents[1]))


@pytest.fixture
def client(request, tmp_path, monkeypatch):
    root = Path(request.config.getoption("--rms-root")).resolve()
    version = request.config.getoption("--rms-version")
    monkeypatch.syspath_prepend(str(root))
    api = importlib.import_module(f"{version}.api")
    database = importlib.import_module(f"{version}.database")
    test_engine = database.make_engine("sqlite:///" + (tmp_path / "test.db").as_posix())
    monkeypatch.setattr(api, "engine", test_engine)
    with TestClient(api.app) as test_client:
        yield test_client
    test_engine.dispose()


@pytest.fixture
def seed(client):
    def post(path, body):
        result = client.post(path, json=body)
        assert result.status_code == 200, result.text
        return result.json()

    project_id = post("/projects", {"name": "测试项目"})["project_id"]
    type_id = post("/item-types", {"project_id": project_id, "name": "系统需求"})["item_type_id"]
    post(f"/item-types/{type_id}/attributes", {
        "name": "验收度量", "data_type": "text", "required": True,
    })
    post(f"/item-types/{type_id}/attributes", {
        "name": "优先级", "data_type": "int", "value_domain": "1,2,3,4,5",
    })
    post(f"/item-types/{type_id}/attributes", {
        "name": "稳定性", "data_type": "enum", "value_domain": "稳定,易变",
    })
    return {"project_id": project_id, "item_type_id": type_id,
            "title": "订单查询", "owner": "胡同学",
            "custom_attrs": {"验收度量": "95%响应时间小于3秒", "优先级": 3, "稳定性": "稳定"}}


@pytest.fixture
def item(client, seed):
    response = client.post("/items", json=seed)
    assert response.status_code == 200, response.text
    return response.json()["item_id"]
