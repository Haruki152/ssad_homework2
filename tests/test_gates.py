"""防止门禁再次把缺列、错误状态边和缺接口判为通过。"""
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("rms_gates", ROOT / "tools/gates.py")
gates = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gates)


def test_missing_column_is_failure():
    files = gates.load("v3")
    files["models.py"] = files["models.py"].replace('    title = Column(String, nullable=False)\n', '')
    assert not gates.check_schema(files)[0]


def test_wrong_edge_is_failure():
    files = gates.load("v3")
    files["domain.py"] = files["domain.py"].replace('{"reviewing", "deprecated"}', '{"approved", "deprecated"}')
    assert not gates.check_state(files)[0]


def test_missing_endpoint_is_failure():
    files = gates.load("v3")
    files["api.py"] = files["api.py"].replace('@app.post("/projects")', '@app.post("/not-projects")')
    assert not gates.check_routes(files)[0]


def test_duplicate_route_is_failure():
    files = gates.load("v3")
    files["api.py"] = files["api.py"].replace('@app.get("/items/search")', '@app.get("/items/{item_id}")', 1)
    assert not gates.check_routes(files)[0]


def test_search_order_is_failure():
    files = gates.load("v3")
    source = files["api.py"]
    start = source.index('@app.get("/items/search")')
    end = source.index('@app.get("/items")', start)
    block = source[start:end]
    files["api.py"] = source[:start] + source[end:] + "\n\n" + block
    assert not gates.check_routes(files)[0]


def test_v1_keeps_original_defects():
    results = {name: ok for name, ok, _ in gates.evaluate("v1")}
    assert not results["C-01"] and not results["C-03"] and not results["C-05"]
