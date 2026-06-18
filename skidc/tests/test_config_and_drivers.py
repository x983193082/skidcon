from __future__ import annotations

import pytest

from skidc.dispatcher.config import DispatchConfig, WorkerConfig
from skidc.dispatcher.contracts import (
    extract_reason_attack_paths,
    parse_json_output,
    validate_bootstrap_execute_payload,
    validate_explore_payload,
    validate_reason_payload,
)
from skidc.dispatcher.workers.registry import get_driver


def _claudecode_worker(model="deepseek-chat", base="https://api.deepseek.com/anthropic"):
    return WorkerConfig(
        name="cc", type="claudecode", task_types=["explore"], max_running=1, priority=0,
        env={"ANTHROPIC_MODEL": model, "ANTHROPIC_BASE_URL": base, "ANTHROPIC_AUTH_TOKEN": "sk-x"},
    )


def _codex_worker(model="qwen-max", base="https://dashscope.aliyuncs.com/compatible-mode/v1"):
    return WorkerConfig(
        name="cx", type="codex", task_types=["explore"], max_running=1, priority=0,
        env={"CODEX_MODEL": model, "CODEX_BASE_URL": base, "OPENAI_API_KEY": "sk-y"},
    )


# ---- model swap is the headline feature: assert the brain follows the env --------

def test_claudecode_driver_targets_deepseek_endpoint_and_model():
    driver = get_driver("claudecode")
    worker = _claudecode_worker()
    hc = driver.build_healthcheck(worker)
    assert any("api.deepseek.com/anthropic/v1/messages" in a for a in hc)
    assert any("deepseek-chat" in a for a in hc)
    execute = driver.build_execute(worker, "PROMPT", "sess-1")
    assert execute.argv[0] == "claude"
    assert "sess-1" in execute.argv


def test_codex_driver_targets_qwen_endpoint_and_model():
    driver = get_driver("codex")
    worker = _codex_worker()
    hc = driver.build_healthcheck(worker)
    assert any("dashscope.aliyuncs.com/compatible-mode/v1/responses" in a for a in hc)
    assert any("qwen-max" in a for a in hc)
    execute = driver.build_execute(worker, "PROMPT", None)
    assert execute.argv[0] == "codex"
    assert "qwen-max" in execute.argv


def test_codex_extracts_session_from_stderr():
    driver = get_driver("codex")
    assert driver.extract_session(None, "", "session id: 1a2b3c4d-0000") == "1a2b3c4d-0000"


def test_claudecode_seeds_session():
    driver = get_driver("claudecode")
    assert driver.prepare_session() is not None


# ---- config validation -----------------------------------------------------------

def _base_config(workers):
    return {
        "server": "http://x",
        "runtime": {
            "max_workers": 4, "max_running_projects": 2, "max_project_workers": 2,
            "interval": 3, "healthcheck_timeout": 10, "prompt_group": "default",
        },
        "tasks": {
            "bootstrap": {"timeout": 60, "conclude_timeout": 30},
            "reason": {"timeout": 45, "max_intents": 2},
            "explore": {"timeout": 120, "conclude_timeout": 30},
        },
        "container": {"image": "img", "network_mode": "host", "completed_action": "stop"},
        "workers": workers,
    }


def test_common_env_is_merged_then_overridden():
    cfg = DispatchConfig.model_validate(
        {
            **_base_config([
                {
                    "name": "cc", "type": "claudecode", "task_types": ["explore"],
                    "max_running": 1, "priority": 0,
                    "env": {"ANTHROPIC_MODEL": "deepseek-chat", "ANTHROPIC_AUTH_TOKEN": "sk-worker"},
                }
            ]),
            "common_env": {
                "ANTHROPIC_BASE_URL": "https://api.deepseek.com/anthropic",
                "ANTHROPIC_AUTH_TOKEN": "sk-common",
            },
        }
    )
    env = cfg.workers[0].env
    assert env["ANTHROPIC_BASE_URL"] == "https://api.deepseek.com/anthropic"  # from common
    assert env["ANTHROPIC_AUTH_TOKEN"] == "sk-worker"  # worker overrides common


def test_missing_env_keys_rejected():
    with pytest.raises(ValueError, match="missing env keys"):
        DispatchConfig.model_validate(
            _base_config([
                {"name": "cc", "type": "claudecode", "task_types": ["explore"], "max_running": 1, "priority": 0, "env": {}}
            ])
        )


def test_duplicate_worker_names_rejected():
    w = {"name": "dup", "type": "mock", "task_types": ["explore"], "max_running": 1, "priority": 0, "env": {}}
    with pytest.raises(ValueError, match="worker names must be unique"):
        DispatchConfig.model_validate(_base_config([w, dict(w)]))


def test_max_project_workers_cannot_exceed_max_workers():
    cfg = _base_config([
        {"name": "m", "type": "mock", "task_types": ["explore"], "max_running": 1, "priority": 0, "env": {}}
    ])
    cfg["runtime"]["max_project_workers"] = 99
    with pytest.raises(ValueError, match="max_project_workers cannot exceed"):
        DispatchConfig.model_validate(cfg)


# ---- contract parsing ------------------------------------------------------------

def test_parse_json_from_fenced_block():
    out = 'noise\n```json\n{"accepted": true, "data": {"description": "x"}}\n```\ntrailer'
    assert parse_json_output(out)["accepted"] is True


def test_validate_explore_accepts_wrapped_and_bare():
    assert validate_explore_payload({"accepted": True, "data": {"description": "found it"}}) == ("fact", {"description": "found it"})
    assert validate_explore_payload({"description": "bare"}) == ("fact", {"description": "bare"})


def test_validate_explore_carries_structured_fields():
    kind, data = validate_explore_payload(
        {"accepted": True, "data": {
            "description": "IDOR on /admin", "scope": "api.example.com/admin",
            "vuln_type": "IDOR", "severity": "high", "parent_fact": "f002",
        }}
    )
    assert kind == "fact"
    assert data == {
        "description": "IDOR on /admin", "scope": "api.example.com/admin",
        "vuln_type": "IDOR", "severity": "high", "parent_fact": "f002",
    }


def test_validate_explore_rejection():
    assert validate_explore_payload({"accepted": False, "reason": "no"}) == ("rejected", None)


def test_validate_reason_complete_and_intents():
    kind, data = validate_reason_payload(
        {"accepted": True, "data": {"complete": {"from": ["f001"], "description": "done"}}},
        open_intents_empty=True, max_intents=3,
    )
    assert kind == "complete"
    kind, data = validate_reason_payload(
        {"accepted": True, "data": {"intents": [{"from": ["f001"], "description": "a"}, {"from": ["f002"], "description": "b"}]}},
        open_intents_empty=True, max_intents=1,
    )
    assert kind == "intents" and len(data) == 1  # capped to max_intents


def test_validate_reason_requires_intent_when_no_open_intents():
    with pytest.raises(ValueError):
        validate_reason_payload({"accepted": True, "data": {}}, open_intents_empty=True, max_intents=3)


def test_reason_intents_with_attack_paths_still_valid():
    # intents + attack_paths coexisting must still parse as "intents"
    kind, data = validate_reason_payload(
        {"accepted": True, "data": {
            "intents": [{"from": ["f001"], "description": "a"}],
            "attack_paths": [{"name": "chain", "fact_chain": ["f001", "f002"], "description": "d", "severity": "high"}],
        }},
        open_intents_empty=True, max_intents=3,
    )
    assert kind == "intents" and len(data) == 1


def test_extract_reason_attack_paths():
    payload = {"accepted": True, "data": {
        "intents": [],
        "attack_paths": [
            {"name": "auth->idor->dump", "fact_chain": ["f001", "f003"], "description": "full chain", "severity": "critical"},
            {"name": "no chain", "fact_chain": [], "description": "x"},          # dropped: empty chain
            {"fact_chain": ["f001"], "description": "x"},                          # dropped: no name
            {"name": "default sev", "fact_chain": ["f002"], "description": "d"},   # severity defaults to medium
        ],
    }}
    paths = extract_reason_attack_paths(payload)
    assert len(paths) == 2
    assert paths[0] == {"name": "auth->idor->dump", "fact_chain": ["f001", "f003"], "description": "full chain", "severity": "critical"}
    assert paths[1]["severity"] == "medium"


def test_extract_reason_attack_paths_absent():
    assert extract_reason_attack_paths({"accepted": True, "data": {"intents": []}}) == []
    assert extract_reason_attack_paths({"accepted": False, "reason": "no"}) == []


def test_validate_bootstrap_requires_fact_and_complete():
    kind, data = validate_bootstrap_execute_payload(
        {"accepted": True, "data": {"fact": {"description": "flag{x}"}, "complete": {"description": "goal met"}}}
    )
    assert kind == "complete"
    assert data["fact_description"] == "flag{x}"
    with pytest.raises(ValueError):
        validate_bootstrap_execute_payload({"accepted": True, "data": {"fact": {"description": "only fact"}}})
