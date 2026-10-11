"""文件驱动的角色编排。真实 API 生成写入 runs/，避免覆盖已修复代码。

运行前配置对应厂商密钥和 RMS_MODEL；RMS_PROVIDER支持anthropic/deepseek。
--stage all会产生真实API费用；小规模试跑使用tools/deepseek_trial.py。
单元测试使用假的客户端，仅验收编排逻辑，不声称进行了多智能体 API 实验。
"""
from __future__ import annotations
import argparse
import ast
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
import uuid

ROOT = Path(__file__).resolve().parent
AGENTS_DIR = ROOT / "agents"
RUNS = ROOT / "runs"
LOCAL_ZONE = timezone(timedelta(hours=8))


@dataclass(frozen=True)
class Agent:
    name: str

    @property
    def model(self):
        value = os.environ.get("RMS_MODEL_" + self.name.upper()) or os.environ.get("RMS_MODEL")
        if not value:
            raise ValueError("请设置 RMS_MODEL，或 RMS_MODEL_" + self.name.upper())
        return value

    @property
    def system_prompt(self):
        return (AGENTS_DIR / (self.name + ".md")).read_text(encoding="utf-8")


AGENTS = {name: Agent(name) for name in ("architect", "data", "backend", "critic", "refactor")}


def client_factory():
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise ValueError("请设置 ANTHROPIC_API_KEY；本地运行系统和测试不需要 API key")
    import anthropic
    return anthropic.Anthropic()


def log(run, category, data):
    folder = run / "logs"
    folder.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(LOCAL_ZONE).strftime("%Y%m%d-%H%M%S")
    destination = folder / f"{stamp}-{category}-{uuid.uuid4().hex[:8]}.json"
    destination.write_text(json.dumps({
        "timestamp": datetime.now(LOCAL_ZONE).isoformat(), **data,
    }, ensure_ascii=False, indent=2), encoding="utf-8")


def call_agent(agent, task, contract, run, client=None):
    model = agent.model
    system = agent.system_prompt
    if contract:
        system += "\n\n# 冻结接口契约\n" + contract
    request = {
        "model": model, "max_tokens": int(os.environ.get("RMS_MAX_TOKENS", "16000")),
        "system": system, "messages": [{"role": "user", "content": task}],
    }
    started = time.monotonic()
    try:
        if client is None and os.environ.get("RMS_PROVIDER", "anthropic") == "deepseek":
            from deepseek_client import chat
            request, response = chat(model, system, task, request["max_tokens"])
            choice = response["choices"][0]
            output = choice["message"]["content"]
            usage = response.get("usage", {})
            from types import SimpleNamespace
            message = SimpleNamespace(stop_reason=("end_turn" if choice["finish_reason"] == "stop" else choice["finish_reason"]))
            provider = "deepseek"
            actual_model = response.get("model", model)
        else:
            active_client = client if client is not None else client_factory()
            with active_client.messages.stream(**request) as stream:
                message = stream.get_final_message()
            output = "".join(block.text for block in message.content if block.type == "text")
            usage = message.usage.model_dump() if hasattr(message.usage, "model_dump") else {}
            provider = "anthropic"
            actual_model = model
        log(run, agent.name, {
            "kind": "model_call", "agent": agent.name, "request": request,
            "provider": provider, "actual_model": actual_model,
            "contract_sha256": hashlib.sha256(contract.encode()).hexdigest() if contract else None,
            "output": output, "usage": usage, "stop_reason": message.stop_reason,
            "elapsed_seconds": round(time.monotonic() - started, 3),
        })
        if message.stop_reason != "end_turn":
            raise ValueError(f"{agent.name} 返回未完成内容：{message.stop_reason}")
        return output
    except Exception as exc:
        # 仅记录异常类型，避免把认证信息写进日志。
        log(run, agent.name + "-failure", {"kind": "model_failure", "error_type": type(exc).__name__})
        raise


def parse_files(output, expected):
    stripped = output.strip()
    if stripped.startswith("```"):
        match = re.fullmatch(r"```(?:json)?\s*\n(.*?)\n```", stripped, re.S)
        if not match:
            raise ValueError("输出必须是一个完整 JSON 对象")
        stripped = match.group(1)

    def no_duplicates(pairs):
        result = {}
        for name, value in pairs:
            if name in result:
                raise ValueError("输出包含重复文件名或 JSON 键")
            result[name] = value
        return result

    document = json.loads(stripped, object_pairs_hook=no_duplicates)
    if not isinstance(document, dict) or set(document) != {"files"}:
        raise ValueError("JSON 顶层只允许 files 字段")
    files = document["files"]
    if not isinstance(files, dict) or set(files) != set(expected):
        raise ValueError(f"必须完整输出这些文件：{sorted(expected)}")
    for name, content in files.items():
        if Path(name).name != name or not name.endswith(".py") or not isinstance(content, str):
            raise ValueError("文件名或内容类型不合法")
        ast.parse(content, filename=name)
    return files


def write_files(folder, files):
    folder.mkdir(parents=True, exist_ok=True)
    # 在内存中完整解析、校验后才写文件；输入顺序不会影响文件名。
    for name, content in files.items():
        (folder / name).write_text(content, encoding="utf-8")


def bundle_prompt(expected, task):
    return task + "\n\n必须只返回 JSON：{\"files\": {\"文件名.py\": \"完整源码\"}}。" + \
        "文件名集合必须严格等于：" + ", ".join(sorted(expected)) + \
        "。包内使用相对导入。不要省略源码；不要输出不在清单内的文件。"


def read(run, path):
    return (run / path).read_text(encoding="utf-8")


def code_bundle(run, version):
    return "\n\n".join("### " + p.name + "\n" + p.read_text(encoding="utf-8")
                         for p in sorted((run / version).glob("*.py")))


def run_checks(run, version, smoke=False):
    if smoke:
        command = [sys.executable, "-m", "pytest", str(ROOT / "tests/test_contract.py"),
                   "--rms-version", version, "--rms-root", str(run), "-k", "contract_routes",
                   "-q", "-p", "no:cacheprovider", "--basetemp", str(run / "test-work" / version)]
    else:
        command = [sys.executable, str(ROOT / "tools/gates.py"), version, "--root", str(run), "--dynamic"]
    result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, encoding="utf-8",
                            errors="replace", check=False, env={**os.environ, "PYTHONIOENCODING": "utf-8"})
    log(run, "gate-" + version, {
        "kind": "quality_gate", "command": command, "exit_code": result.returncode,
        "stdout": result.stdout, "stderr": result.stderr, "scope": "smoke" if smoke else "full",
    })
    print(result.stdout)
    if result.stderr:
        print(result.stderr, file=sys.stderr)
    return result


def require_pass(result, name):
    if result.returncode != 0:
        raise RuntimeError(name + " 未通过，详见该次运行的 logs；阶段未放行")


def stage_v1(run):
    if (run / "artifacts/contract.md").exists() or (run / "v1").exists():
        raise ValueError("该运行已存在 v1/契约；请使用新的运行目录")
    contract = call_agent(AGENTS["architect"],
        "基于以下已确定的系统设计，产出完整接口契约，含表结构、接口签名、编号设计约束。\n\n" +
        (ROOT / "artifacts/contract.md").read_text(encoding="utf-8"), "", run)
    required_sections = ["设计约束", "接口签名", "attribute_definition", "relationship"]
    if not all(value in contract for value in required_sections):
        raise ValueError("G1 契约不完整，未写入冻结文件")
    (run / "artifacts").mkdir(parents=True, exist_ok=True)
    (run / "artifacts/contract.md").write_text(contract, encoding="utf-8")
    model_output = call_agent(AGENTS["data"], bundle_prompt(
        {"models.py"}, "按冻结契约实现 ORM；数据库引擎来自 .database import engine。"), contract, run)
    models = parse_files(model_output, {"models.py"})
    write_files(run / "v1", models)
    (run / "v1/database.py").write_text((ROOT / "v3/database.py").read_text(encoding="utf-8").replace("v3.db", "v1.db"), encoding="utf-8")
    (run / "v1/__init__.py").write_text("", encoding="utf-8")
    backend_output = call_agent(AGENTS["backend"], bundle_prompt(
        {"api.py", "service.py", "schemas.py", "validation.py"},
        "按契约完整实现 API 和业务逻辑，app 启动时 Base.metadata.create_all(engine)，"
        "api 模块公开 engine 以便测试替换；database 模块已提供 make_engine(url)。采用 Depends(get_session, function scope) 以在响应发送前提交事务。接口请求字段采用 custom_attrs，attrs 仅为兼容别名。以下是 Data 的实际产物：\n\n" + models["models.py"]), contract, run)
    write_files(run / "v1", parse_files(backend_output, {"api.py", "service.py", "schemas.py", "validation.py"}))
    require_pass(run_checks(run, "v1", smoke=True), "G2 启动和接口完整性")
    # 首轮完整行为验收用于诊断；失败会交给 Critic，而非假装通过。
    run_checks(run, "v1")


def stage_critique(run):
    contract = read(run, "artifacts/contract.md")
    evidence = "\n".join(p.read_text(encoding="utf-8") for p in sorted((run / "logs").glob("*gate-v1*.json")))
    defects = call_agent(AGENTS["critic"],
        "根据实际代码与门禁结果审查。每条问题写现象、位置、后果、根因；"
        "没有发现问题就明确写没有，不要人为制造缺陷或预设多智能体更优。\n\n" +
        code_bundle(run, "v1") + "\n\n实际检查结果：\n" + evidence, contract, run)
    if "根因" not in defects:
        raise ValueError("G3 缺陷报告缺少根因分析")
    (run / "artifacts/defects.md").write_text(defects, encoding="utf-8")


def stage_constraints(run):
    contract = read(run, "artifacts/contract.md")
    constraints = call_agent(AGENTS["critic"],
        "将以下真实缺陷转化为 C-01 至 C-06 编号的可验收约束。"
        "不得修改已冻结契约；若无缺陷则描述维持已有规则的回归验收。\n\n" +
        read(run, "artifacts/defects.md") + "\n\n原有验收约定：\n" +
        (ROOT / "artifacts/constraints.md").read_text(encoding="utf-8"), contract, run)
    if not all(f"C-0{i}" in constraints for i in range(1, 7)):
        raise ValueError("约束文件缺少必需编号")
    (run / "artifacts/constraints.md").write_text(constraints, encoding="utf-8")


def refactor_stage(run, version, previous, redesign=False):
    if (run / version).exists():
        raise ValueError(version + " 已存在，请创建新的运行以保留原产物")
    contract = read(run, "artifacts/contract.md")
    expected = {"models.py", "database.py", "api.py", "service.py", "schemas.py", "validation.py"}
    if redesign:
        expected |= {"domain.py", "rules.py", "repository.py"}
    task = ("在保持接口与行为兼容的基础上做架构重新设计。" if redesign else
            "按实际缺陷与约束修复，保持改动范围最小。")
    task += "必须包含完整数据库设施，database 导出 make_engine(url)，API 导出 engine；启动时建表。请求字段用 custom_attrs，attrs 仅作为兼容别名；以依赖的 function scope 在响应前提交事务。\n\n# 约束\n" + \
        read(run, "artifacts/constraints.md") + "\n\n# 缺陷\n" + \
        read(run, "artifacts/defects.md") + "\n\n# 上一版实际源码\n" + code_bundle(run, previous)
    attempts = int(os.environ.get("RMS_REPAIR_ATTEMPTS", "2"))
    if not 1 <= attempts <= 3:
        raise ValueError("RMS_REPAIR_ATTEMPTS 必须为 1 至 3")
    for attempt in range(1, attempts + 1):
        output = call_agent(AGENTS["refactor"], bundle_prompt(expected, task), contract, run)
        files = parse_files(output, expected)
        files["__init__.py"] = ""
        write_files(run / version, files)
        archive = run / "attempts" / f"{version}-{attempt}"
        archive.mkdir(parents=True, exist_ok=True)
        for name, content in files.items():
            (archive / name).write_text(content, encoding="utf-8")
        result = run_checks(run, version)
        if result.returncode == 0:
            return
        task += "\n\n# 本次产物\n" + code_bundle(run, version) + \
            "\n\n# 真实失败结果，请仅针对失败修复\n" + result.stdout + result.stderr
    require_pass(result, "G5" if redesign else "G4")


def checked_run(path=None):
    RUNS.mkdir(exist_ok=True)
    root = RUNS.resolve()
    run = Path(path).resolve() if path else root / (
        datetime.now(LOCAL_ZONE).strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:8])
    if run == root or not run.is_relative_to(root):
        raise ValueError("运行目录必须是仓库根目录 runs 的子目录")
    run.mkdir(parents=True, exist_ok=True)
    return run


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--stage", required=True, choices=["v1", "critique", "constraints", "v2", "v3", "all"])
    parser.add_argument("--run-dir", type=Path)
    args = parser.parse_args()
    if args.stage not in {"v1", "all"} and args.run_dir is None:
        parser.error("继续阶段必须用 --run-dir 指定同一次运行")
    # 先检查配置，避免没有凭据时创建空运行。
    AGENTS["architect"].model
    provider = os.environ.get("RMS_PROVIDER", "anthropic")
    if provider not in {"anthropic", "deepseek"}:
        parser.error("RMS_PROVIDER仅支持anthropic/deepseek")
    key_name = "DEEPSEEK_API_KEY" if provider == "deepseek" else "ANTHROPIC_API_KEY"
    if not os.environ.get(key_name):
        parser.error("真实生成需要" + key_name + "；本地代码测试不需要")
    run = checked_run(args.run_dir)
    print("本次运行：", run)
    stages = {
        "v1": stage_v1, "critique": stage_critique, "constraints": stage_constraints,
        "v2": lambda folder: refactor_stage(folder, "v2", "v1"),
        "v3": lambda folder: refactor_stage(folder, "v3", "v2", redesign=True),
    }
    for name in stages if args.stage == "all" else [args.stage]:
        print("== 阶段", name, "==")
        stages[name](run)


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    main()
