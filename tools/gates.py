"""质量门禁：静态检查只证明结构，--dynamic 才执行真实 API 行为验收。"""
from __future__ import annotations
import argparse
import ast
import re
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
ITEM_WHITELIST = {"item_id", "project_id", "item_type_id", "title", "status", "owner", "custom_attrs"}
EXPECTED_TRANSITIONS = {
    "draft": {"reviewing", "deprecated"}, "reviewing": {"approved", "deprecated"},
    "approved": {"implemented", "deprecated"}, "implemented": {"verified", "deprecated"},
    "verified": {"deprecated"}, "deprecated": {"deprecated"},
}
REQUIRED_ROUTES = {
    ("post", "/projects"), ("post", "/item-types"),
    ("post", "/item-types/{type_id}/attributes"), ("post", "/items"),
    ("get", "/items/{item_id}"), ("put", "/items/{item_id}"),
    ("post", "/relationships"), ("get", "/items/{item_id}/trace"),
}


def load(version, root=ROOT):
    return {p.name: p.read_text(encoding="utf-8") for p in sorted((Path(root) / version).glob("*.py"))}


def call_name(node):
    fn = node.func
    return fn.id if isinstance(fn, ast.Name) else fn.attr if isinstance(fn, ast.Attribute) else None


def calls(files):
    return {call_name(n) for src in files.values() for n in ast.walk(ast.parse(src)) if isinstance(n, ast.Call)}


def check_schema(files):
    for filename, source in files.items():
        for node in ast.walk(ast.parse(source)):
            if isinstance(node, ast.ClassDef) and node.name == "Item":
                columns = {stmt.targets[0].id for stmt in node.body
                           if isinstance(stmt, ast.Assign) and isinstance(stmt.targets[0], ast.Name)
                           and isinstance(stmt.value, ast.Call) and call_name(stmt.value) == "Column"}
                if columns:
                    return columns == ITEM_WHITELIST, f"多余={sorted(columns - ITEM_WHITELIST)}；缺少={sorted(ITEM_WHITELIST - columns)}"
    return False, "未找到 Item ORM 模型"


def check_state(files):
    for source in files.values():
        for node in ast.walk(ast.parse(source)):
            if not isinstance(node, (ast.Assign, ast.AnnAssign)):
                continue
            try:
                table = ast.literal_eval(node.value)
            except (ValueError, TypeError, SyntaxError):
                continue
            if isinstance(table, dict) and table == EXPECTED_TRANSITIONS:
                connected = bool(calls(files) & {"transition", "validate_status_transition"})
                return connected, "合法边集合准确；存在调用点（行为由动态测试验证）"
    return False, "缺少准确的合法流转表"


def check_rule_calls(files):
    source = "\n".join(files.values())
    names = calls(files)
    ok = (bool(names & {"validate_attributes", "apply_rules"})
          and bool(names & {"mark_downstream_suspect", "dispatch"})
          and bool(re.search(r"suspect\s*=\s*True", source)))
    return ok, "属性及传播调用结构；实际效果需 --dynamic 验证"


def check_sql(files):
    hits = []
    keywords = re.compile(r"\b(SELECT|INSERT|UPDATE|DELETE|FROM|WHERE)\b", re.I)
    for name, source in files.items():
        for node in ast.walk(ast.parse(source)):
            if isinstance(node, ast.JoinedStr):
                text = " ".join(str(n.value) for n in node.values if isinstance(n, ast.Constant))
                if keywords.search(text):
                    hits.append(f"{name}:{node.lineno} SQL f-string")
            if isinstance(node, ast.Call) and call_name(node) in {"text", "execute"}:
                if node.args and isinstance(node.args[0], (ast.JoinedStr, ast.BinOp)):
                    hits.append(f"{name}:{node.lineno} SQL 拼接")
    return not hits, "；".join(hits) or "未发现受检拼接模式；不替代全面安全审计"


def check_routes(files):
    routes = []
    for node in ast.walk(ast.parse(files.get("api.py", ""))):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for decorator in node.decorator_list:
            if (isinstance(decorator, ast.Call) and isinstance(decorator.func, ast.Attribute)
                    and decorator.args and isinstance(decorator.args[0], ast.Constant)):
                routes.append((decorator.func.attr, decorator.args[0].value))
    normalized = {(method, re.sub(r"\{(?:id|item_id)\}", "{item_id}",
                                  re.sub(r"\{id\}/attributes", "{type_id}/attributes", path)))
                  for method, path in routes}
    missing = REQUIRED_ROUTES - normalized
    duplicates = len(routes) != len(set(routes))
    order_ok = (("get", "/items/search") not in routes or
                (("get", "/items/{item_id}") in routes and
                 routes.index(("get", "/items/search")) < routes.index(("get", "/items/{item_id}"))))
    return not missing and order_ok and not duplicates, f"缺失接口={sorted(missing)}；重复路由={duplicates}；搜索顺序={'正确' if order_ok else '错误'}"


def check_bootstrap(files):
    ok = "create_all" in calls(files) and "create_engine" in calls(files)
    return ok, "数据库引擎和建表入口存在；真实导入由动态测试检查"


def check_schemas(files):
    source = files.get("schemas.py", "")
    classes = {n.name: n for n in ast.walk(ast.parse(source)) if isinstance(n, ast.ClassDef)}
    ok = all(name in classes and any(isinstance(b, ast.Name) and b.id == "ItemFields" for b in classes[name].bases)
             for name in ("ItemIn", "ItemUpdate"))
    return ok, "请求字段通过 ItemFields 继承复用；ORM 与 DTO 职责独立"


CHECKS = [
    ("C-01", check_schema), ("C-03", check_state), ("C-02/C-04", check_rule_calls),
    ("C-05", check_sql), ("接口", check_routes), ("启动", check_bootstrap), ("C-06", check_schemas),
]


def evaluate(version, root=ROOT):
    files = load(version, root)
    if not files:
        return [("文件", False, "版本目录不存在或为空")]
    try:
        for source in files.values():
            ast.parse(source)
        return [(name, *check(files)) for name, check in CHECKS]
    except (SyntaxError, ValueError) as exc:
        return [("语法", False, str(exc))]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("version", choices=["v1", "v2", "v3"])
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--dynamic", action="store_true")
    args = parser.parse_args()
    results = evaluate(args.version, args.root)
    print(f"== {args.version} 静态门禁 ==")
    for name, ok, detail in results:
        print(f"[{'PASS' if ok else 'FAIL'}] {name}: {detail}")
    static_ok = all(ok for _, ok, _ in results)
    print(f"静态结构：{sum(ok for _, ok, _ in results)}/{len(results)}")
    if args.dynamic:
        result = subprocess.run([
            sys.executable, "-m", "pytest", str(ROOT / "tests/test_contract.py"),
            "--rms-version", args.version, "--rms-root", str(args.root.resolve()),
            "-q", "-p", "no:cacheprovider", "--basetemp", str(ROOT / "test-work" / args.version),
        ], cwd=ROOT, check=False)
        return 0 if static_ok and result.returncode == 0 else 1
    return 0 if static_ok else 1


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
