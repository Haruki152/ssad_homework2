import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
import sys
import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("rms_orchestrator", ROOT / "orchestrator.py")
orchestrator = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = orchestrator
spec.loader.exec_module(orchestrator)


def test_named_outputs_ignore_order():
    output = json.dumps({"files": {"service.py": "x = 1", "api.py": "y = 2"}})
    assert orchestrator.parse_files(output, {"api.py", "service.py"})["api.py"] == "y = 2"


@pytest.mark.parametrize("output", [
    '{"files":{"api.py":"x=1"}}',
    '{"files":{"../api.py":"x=1","service.py":"y=2"}}',
    '{"files":{"api.py":"x=1","api.py":"x=2","service.py":"y=2"}}',
    '{"files":{"api.py":"broken (","service.py":"y=2"}}',
])
def test_invalid_output_rejected(output):
    with pytest.raises((ValueError, SyntaxError)):
        orchestrator.parse_files(output, {"api.py", "service.py"})


def test_failed_gate_stops():
    with pytest.raises(RuntimeError):
        orchestrator.require_pass(SimpleNamespace(returncode=1), "G4")


def test_outside_run_directory_rejected(tmp_path):
    with pytest.raises(ValueError):
        orchestrator.checked_run(tmp_path)


def test_missing_config_does_not_call_api(monkeypatch):
    monkeypatch.delenv("RMS_MODEL", raising=False)
    monkeypatch.delenv("RMS_MODEL_ARCHITECT", raising=False)
    with pytest.raises(ValueError):
        orchestrator.AGENTS["architect"].model


def test_full_request_logged_without_key(tmp_path, monkeypatch):
    monkeypatch.setenv("RMS_MODEL", "configured-test-model")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "secret-for-test-only")
    captured = {}
    message = SimpleNamespace(content=[SimpleNamespace(type="text", text="done")],
                              usage=SimpleNamespace(model_dump=lambda: {"input_tokens": 10}),
                              stop_reason="end_turn")

    class Stream:
        def __enter__(self):
            return self
        def __exit__(self, *args):
            return False
        def get_final_message(self):
            return message

    def stream(**kwargs):
        captured.update(kwargs)
        return Stream()

    client = SimpleNamespace(messages=SimpleNamespace(stream=stream))
    assert orchestrator.call_agent(orchestrator.AGENTS["architect"], "task", "contract", tmp_path, client) == "done"
    saved = next((tmp_path / "logs").glob("*.json")).read_text(encoding="utf-8")
    assert "contract" in saved and "task" in saved and "secret-for-test-only" not in saved
    assert captured["model"] == "configured-test-model"


def test_truncated_response_rejected_and_logged(tmp_path, monkeypatch):
    monkeypatch.setenv("RMS_MODEL", "configured-test-model")
    message = SimpleNamespace(content=[SimpleNamespace(type="text", text="incomplete")],
                              usage=SimpleNamespace(model_dump=lambda: {}), stop_reason="max_tokens")

    class Stream:
        def __enter__(self):
            return self
        def __exit__(self, *args):
            return False
        def get_final_message(self):
            return message

    client = SimpleNamespace(messages=SimpleNamespace(stream=lambda **kwargs: Stream()))
    with pytest.raises(ValueError):
        orchestrator.call_agent(orchestrator.AGENTS["architect"], "task", "contract", tmp_path, client)
    assert len(list((tmp_path / "logs").glob("*.json"))) == 2
