"""Strict CTF blackboard outputs, independent of the Web planning protocol."""
from __future__ import annotations

from typing import Any


def _object(value: Any, allowed: set[str], required: set[str]) -> dict:
    if not isinstance(value, dict) or not required <= value.keys() or value.keys() - allowed:
        raise ValueError(f"Expected CTF object with required keys {sorted(required)} and allowed keys {sorted(allowed)}")
    return value


def _text(value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("CTF description and references must be non-empty strings")
    return value.strip()


def _refs(value: Any, *, required: bool = False) -> list[str]:
    if not isinstance(value, list) or (required and not value):
        raise ValueError("CTF references must be a list")
    return [_text(item) for item in value]


def _envelope(payload: Any) -> dict | None:
    _object(payload, {"accepted", "data", "reason"}, {"accepted"})
    if type(payload["accepted"]) is not bool:
        raise ValueError("CTF accepted must be a JSON boolean")
    if not payload["accepted"]:
        if "data" in payload and payload["data"] is not None:
            raise ValueError("Rejected CTF output cannot include actions")
        if "reason" in payload:
            _text(payload["reason"])
        return None
    if "reason" in payload or not isinstance(payload.get("data"), dict):
        raise ValueError("Accepted CTF output requires data only")
    return payload["data"]


def _decision(value: Any) -> dict:
    value = _object(value, {"from", "description"}, {"from", "description"})
    sources = _refs(value["from"], required=True)
    if "goal" in sources:
        raise ValueError("CTF goal is not evidence")
    return {"from": sources, "description": _text(value["description"])}


def validate_ctf_reason_payload(payload: dict, open_intents_empty: bool, max_intents: int) -> tuple[str, Any, bool]:
    data = _envelope(payload)
    if data is None:
        return "rejected", None, False
    _object(data, {"intents", "complete"}, set())
    if not data or data == {"intents": []}:
        if open_intents_empty:
            raise ValueError("CTF Reason must propose work or completion when no work remains")
        return "noop", None, False
    if len(data) != 1:
        raise ValueError("CTF Reason must choose one action")
    if "complete" in data:
        return "complete", _decision(data["complete"]), False
    intents = data["intents"]
    if not isinstance(intents, list) or not 1 <= len(intents) <= max_intents:
        raise ValueError("CTF intent count exceeds the available slots")
    return "intents", [_decision(item) for item in intents], False


def validate_ctf_explore_payload(payload: dict) -> tuple[str, dict | None]:
    data = _envelope(payload)
    if data is None:
        return "rejected", None
    if set(data) == {"no_result"} and data["no_result"] is True:
        return "no_result", None
    _object(data, {"description", "evidence_refs"}, {"description"})
    fact = {"description": _text(data["description"])}
    if "evidence_refs" in data:
        fact["evidence_refs"] = _refs(data["evidence_refs"])
    return "fact", fact


def _description(value: Any) -> str:
    return _text(_object(value, {"description"}, {"description"})["description"])


def validate_ctf_bootstrap_execute_payload(payload: dict) -> tuple[str, dict | None]:
    data = _envelope(payload)
    if data is None:
        return "rejected", None
    if set(data) == {"no_result"} and data["no_result"] is True:
        return "incomplete", None
    _object(data, {"fact", "complete"}, {"fact", "complete"})
    return "complete", {
        "fact_description": _description(data["fact"]),
        "complete_description": _description(data["complete"]),
    }


def validate_ctf_bootstrap_conclude_payload(payload: dict) -> tuple[str, str | None]:
    data = _envelope(payload)
    if data is None:
        return "rejected", None
    _object(data, {"fact"}, {"fact"})
    return "fact", _description(data["fact"])
