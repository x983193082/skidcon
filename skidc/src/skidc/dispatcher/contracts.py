from __future__ import annotations

from typing import Any

from skidc.dispatcher.output_parser import extract_json_object


def parse_json_output(stdout: str) -> dict[str, Any]:
    return extract_json_object(stdout)


def _unwrap_wrapped_payload(payload: dict[str, Any]) -> tuple[bool | None, dict[str, Any] | None]:
    accepted = payload.get("accepted")
    if accepted is False:
        return False, None
    if accepted is True:
        data = payload.get("data")
        if not isinstance(data, dict):
            raise ValueError("data must be an object")
        return True, data
    return None, None


def _is_dict(value: Any) -> bool:
    return isinstance(value, dict)


def _looks_like_reason_data(payload: dict[str, Any]) -> bool:
    if not isinstance(payload, dict):
        return False
    keys = set(payload)
    metadata_keys = {"attack_paths", "attack_surface_map", "explore_seed_deck", "recon_complete"}
    if "complete" in keys and keys <= {"complete", *metadata_keys}:
        complete = payload["complete"]
        return isinstance(complete, dict) and "from" in complete and "description" in complete
    if "intents" in keys and keys <= {"intents", *metadata_keys}:
        return isinstance(payload["intents"], list)
    if "intent" in keys and keys <= {"intent", *metadata_keys}:
        intent = payload["intent"]
        return isinstance(intent, dict) and "from" in intent and "description" in intent
    if keys and keys <= metadata_keys:
        return "attack_surface_map" in keys or "explore_seed_deck" in keys
    return False


def _looks_like_bootstrap_execute_data(payload: dict[str, Any]) -> bool:
    if not isinstance(payload, dict) or set(payload) != {"fact", "complete"}:
        return False
    return _is_dict(payload.get("fact")) and _is_dict(payload.get("complete"))


def _looks_like_bootstrap_conclude_data(payload: dict[str, Any]) -> bool:
    if not isinstance(payload, dict):
        return False
    keys = set(payload)
    if keys not in ({"fact"}, {"fact", "complete"}):
        return False
    return _is_dict(payload.get("fact"))


def _looks_like_explore_data(payload: dict[str, Any]) -> bool:
    # Cairn-style Explore conclusions are objective text plus optional raw
    # evidence/surface observations. Semantic labels such as "confirmed",
    # severity, or vulnerability type are deliberately not part of the write
    # contract: the concluded Intent edge is the source of graph truth.
    return isinstance(payload, dict) and "description" in payload

_EXPLORE_STRING_FIELDS = (
    "scope",
    "vuln_type",
    "severity",
    "parent_fact",
    "verification_of",
    "goal_type",
    "status",
    "recon_category",
    "recon_tool",
    "recon_target",
    "recon_evidence_ref",
    "kind",
    "summary",
    "created_by",
)
_EXPLORE_BOOL_FIELDS = ("recon_executed", "recon_found_results")



_WEB_INTENT_FIELDS = frozenset(
    {
        "from",
        "description",
        "executor",
        "target",
        "port",
        "path",
        "surface_type",
        "surface_ref",
        "surface_refs",
        "action_kind",
        "test_variant",
        "priority",
        "suggested_tools",
        "coverage_refs",
        "risk_level",
        "test_identity",
        "test_data_refs",
    }
)


def _normalize_web_reason_intent(intent: object) -> dict[str, Any]:
    if not isinstance(intent, dict):
        raise ValueError("invalid intent")
    extra_fields = set(intent) - _WEB_INTENT_FIELDS
    if extra_fields:
        raise ValueError(
            f"unexpected Web Intent fields: {', '.join(sorted(extra_fields))}"
        )
    from_ids = intent.get("from")
    description = intent.get("description")
    if not isinstance(from_ids, list) or not from_ids or not all(
        isinstance(fact_id, str) and fact_id.strip() for fact_id in from_ids
    ):
        raise ValueError("intent.from must contain Fact ids")
    if not isinstance(description, str) or not description.strip():
        raise ValueError("intent.description is required")
    normalized = dict(intent)
    normalized["from"] = [fact_id.strip() for fact_id in from_ids]
    normalized["description"] = description.strip()
    executor = normalized.pop("executor", "explore")
    if executor not in {"explore", "verify"}:
        raise ValueError("intent.executor must be explore or verify")
    if executor == "verify":
        normalized["action_kind"] = "verify"
    action_kind = normalized.get("action_kind")
    if not isinstance(action_kind, str) or not action_kind.strip():
        raise ValueError("Web Intent action_kind is required")
    action_kind = action_kind.strip().casefold().replace("-", "_")
    risk_level = normalized.get("risk_level", "standard")
    if risk_level not in {"standard", "high", "irreversible"}:
        raise ValueError("intent.risk_level must be standard, high, or irreversible")
    if action_kind not in {"surface_mapping", "security_test", "verify", "state_check"} and risk_level == "standard":
        raise ValueError(
            "A custom Web Intent action_kind requires high or irreversible risk_level"
        )
    normalized["action_kind"] = action_kind
    if "risk_level" in intent:
        normalized["risk_level"] = risk_level
    if risk_level in {"high", "irreversible"}:
        test_identity = normalized.get("test_identity")
        test_data_refs = normalized.get("test_data_refs")
        if not isinstance(test_identity, str) or not test_identity.strip():
            raise ValueError("high-risk intent.test_identity is required")
        if not isinstance(test_data_refs, list) or not test_data_refs or not all(
            isinstance(ref, str) and ref.strip() for ref in test_data_refs
        ):
            raise ValueError("high-risk intent.test_data_refs must contain references")
        normalized["test_identity"] = test_identity.strip()
        normalized["test_data_refs"] = list(dict.fromkeys(ref.strip() for ref in test_data_refs))
    surface_ref = normalized.get("surface_ref")
    raw_surface_refs = normalized.get("surface_refs")
    if raw_surface_refs is None:
        raw_surface_refs = [surface_ref] if isinstance(surface_ref, str) else []
    if not isinstance(raw_surface_refs, list) or not all(
        isinstance(surface_id, str) and surface_id.strip()
        for surface_id in raw_surface_refs
    ):
        raise ValueError("intent.surface_refs must contain Surface ids")
    surface_refs = list(dict.fromkeys(surface_id.strip() for surface_id in raw_surface_refs))
    if len(surface_refs) > 5:
        raise ValueError("one Web Intent may bind at most 5 related Surfaces")
    if surface_ref is not None and (
        not isinstance(surface_ref, str) or surface_ref.strip() not in surface_refs
    ):
        raise ValueError("intent.surface_ref must also appear in surface_refs")
    if action_kind == "security_test" and not surface_refs:
        raise ValueError("security_test Intent requires surface_ref or surface_refs")
    if surface_refs:
        normalized["surface_refs"] = surface_refs
        normalized["surface_ref"] = surface_refs[0]
    else:
        normalized.pop("surface_refs", None)
        normalized.pop("surface_ref", None)
    return normalized


def _validate_web_reason_data(
    data: dict[str, Any], *, open_intents_empty: bool, max_intents: int,
) -> tuple[str, dict[str, Any] | list[dict[str, Any]] | None, bool]:
    keys = set(data)
    if keys - {"complete", "intent", "intents"}:
        raise ValueError("Web Reason data may contain only complete, intent, or intents")
    if "intent" in data and "intents" in data:
        raise ValueError("intent and intents cannot coexist")
    if "complete" in data and ({"intent", "intents"} & keys):
        raise ValueError("complete and intents cannot coexist")

    complete = data.get("complete")
    if complete is not None:
        if not isinstance(complete, dict) or set(complete) != {"from", "description"}:
            raise ValueError("invalid complete payload")
        if not isinstance(complete.get("from"), list):
            raise ValueError("complete.from must be an array")
        if not isinstance(complete.get("description"), str) or not complete["description"].strip():
            raise ValueError("complete.description is required")
        return "complete", complete, False

    intents = data.get("intents")
    if intents is None and data.get("intent") is not None:
        singular_or_list = data["intent"]
        # Some model backends emit the plural shape under the singular key.
        # It is unambiguous here, so normalize it instead of discarding valid work.
        intents = singular_or_list if isinstance(singular_or_list, list) else [singular_or_list]
    if intents is not None:
        if not isinstance(intents, list):
            raise ValueError("intents must be an array")
        normalized = [_normalize_web_reason_intent(intent) for intent in intents]
        if not normalized:
            if open_intents_empty:
                raise ValueError("Web Reason must return work when no Open Intent exists")
            return "noop", None, False
        return "intents", normalized[:max(1, max_intents)], False

    if open_intents_empty:
        raise ValueError("Web Reason cannot return noop when no Open Intent exists")
    return "noop", None, False


def validate_reason_payload(
    payload: dict[str, Any], open_intents_empty: bool, max_intents: int,
    *, web_mode: bool = False,
) -> tuple[str, dict[str, Any] | list[dict[str, Any]] | None, bool]:
    accepted, data = _unwrap_wrapped_payload(payload)
    if accepted is False:
        return "rejected", None, False
    if web_mode:
        if accepted is not True or not isinstance(data, dict):
            raise ValueError("accepted must be true")
        return _validate_web_reason_data(
            dict(data),
            open_intents_empty=open_intents_empty,
            max_intents=max_intents,
        )
    if accepted is None:
        if not _looks_like_reason_data(payload):
            raise ValueError("accepted must be true or false")
        data = payload
    if not isinstance(data, dict):
        raise ValueError("accepted must be true or false")
    recon_complete = bool(data.pop("recon_complete", False))
    complete = data.get("complete")
    intents = data.get("intents")
    # backward compat: accept singular "intent" key from models
    if intents is None:
        singular = data.get("intent")
        if isinstance(singular, dict):
            intents = [singular]
    if complete is not None:
        if intents is not None:
            raise ValueError("complete and intents cannot coexist")
        if not isinstance(complete, dict) or "from" not in complete or "description" not in complete:
            raise ValueError("invalid complete payload")
        return "complete", complete, recon_complete
    if intents is not None:
        if not isinstance(intents, list):
            raise ValueError("intents must be an array")
        for i, intent in enumerate(intents):
            if not isinstance(intent, dict) or "from" not in intent or "description" not in intent:
                raise ValueError(f"invalid intent at index {i}")
        intents = intents[:max_intents]
        if not intents:
            return "noop", None, recon_complete
        return "intents", intents, recon_complete
    if any(key in data for key in ("attack_surface_map", "explore_seed_deck", "attack_paths")):
        return "noop", None, recon_complete
    return "noop", None, recon_complete


def _normalize_explore_seed_deck(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, dict):
        value = value.get("seeds")
    if not isinstance(value, list):
        return []
    seeds: list[dict[str, Any]] = []
    for entry in value:
        if not isinstance(entry, dict):
            continue
        fact_ids = entry.get("from")
        description = entry.get("description")
        if not isinstance(fact_ids, list) or not fact_ids:
            continue
        if not all(isinstance(fact_id, str) and fact_id.strip() for fact_id in fact_ids):
            continue
        if not isinstance(description, str) or not description.strip():
            continue
        seed = dict(entry)
        seed["from"] = [fact_id.strip() for fact_id in fact_ids]
        seed["description"] = description.strip()
        seeds.append(seed)
    return seeds


def extract_reason_handoff(payload: dict[str, Any]) -> dict[str, Any]:
    accepted, data = _unwrap_wrapped_payload(payload)
    if accepted is False:
        return {"attack_surface_map": None, "explore_seed_deck": []}
    if data is None:
        data = payload if isinstance(payload, dict) else {}
    attack_surface_map = data.get("attack_surface_map")
    if not isinstance(attack_surface_map, dict):
        attack_surface_map = None
    return {
        "attack_surface_map": attack_surface_map,
        "explore_seed_deck": _normalize_explore_seed_deck(data.get("explore_seed_deck")),
    }


def extract_reason_attack_paths(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Pull optional attack_paths out of a reason payload (wrapped or bare).
    Returns only well-formed entries (name + non-empty fact_chain); skips the rest.
    Kept separate from validate_reason_payload so its return contract is unchanged."""
    accepted, data = _unwrap_wrapped_payload(payload)
    if accepted is False:
        return []
    if data is None:
        data = payload if isinstance(payload, dict) else {}
    raw = data.get("attack_paths")
    if not isinstance(raw, list):
        return []
    paths: list[dict[str, Any]] = []
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        name = entry.get("name")
        chain = entry.get("fact_chain")
        description = entry.get("description")
        if not isinstance(name, str) or not name.strip():
            continue
        if not isinstance(chain, list) or not chain or not all(isinstance(c, str) and c.strip() for c in chain):
            continue
        if not isinstance(description, str) or not description.strip():
            continue
        severity = entry.get("severity")
        status = entry.get("status")
        normalized_status = status.strip() if isinstance(status, str) and status.strip() else "hypothesis"
        if normalized_status not in ("hypothesis", "confirmed", "inconclusive", "refuted"):
            normalized_status = "hypothesis"
        paths.append({
            "name": name.strip(),
            "fact_chain": [c.strip() for c in chain],
            "description": description.strip(),
            "severity": severity.strip() if isinstance(severity, str) and severity.strip() else "medium",
            "status": normalized_status,
        })
    return paths


def validate_bootstrap_execute_payload(payload: dict[str, Any]) -> tuple[str, dict[str, str] | None]:
    accepted, data = _unwrap_wrapped_payload(payload)
    if accepted is False:
        return "rejected", None
    if accepted is None:
        if not _looks_like_bootstrap_execute_data(payload):
            raise ValueError("accepted must be true or false")
        data = payload
    if not isinstance(data, dict):
        raise ValueError("accepted must be true or false")

    fact = data.get("fact")
    if not isinstance(fact, dict):
        raise ValueError("fact is required")
    fact_description = fact.get("description")
    if not isinstance(fact_description, str) or not fact_description.strip():
        raise ValueError("fact.description is required")

    result = {"fact_description": fact_description.strip()}
    complete = data.get("complete")
    if complete is None:
        raise ValueError("complete is required")
    if not isinstance(complete, dict):
        raise ValueError("complete must be an object")
    complete_description = complete.get("description")
    if not isinstance(complete_description, str) or not complete_description.strip():
        raise ValueError("complete.description is required")
    result["complete_description"] = complete_description.strip()
    return "complete", result


def validate_bootstrap_conclude_payload(payload: dict[str, Any]) -> tuple[str, str | None]:
    accepted, data = _unwrap_wrapped_payload(payload)
    if accepted is False:
        return "rejected", None
    if accepted is None:
        if not _looks_like_bootstrap_conclude_data(payload):
            raise ValueError("accepted must be true or false")
        data = payload
    if not isinstance(data, dict):
        raise ValueError("accepted must be true or false")
    extra_keys = set(data) - {"fact", "complete"}
    if extra_keys:
        raise ValueError("unexpected keys in conclude payload")
    fact = data.get("fact")
    if not isinstance(fact, dict):
        raise ValueError("fact is required")
    fact_description = fact.get("description")
    if not isinstance(fact_description, str) or not fact_description.strip():
        raise ValueError("fact.description is required")
    return "fact", fact_description.strip()


MAX_WEB_SURFACES_PER_RESULT = 500


def _validate_web_surfaces(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        raise ValueError("surfaces must be an array")
    if len(value) > MAX_WEB_SURFACES_PER_RESULT:
        raise ValueError(
            f"surfaces may contain at most {MAX_WEB_SURFACES_PER_RESULT} entries"
        )
    allowed = {"method", "path", "params", "auth_context", "surface_type"}
    normalized: list[dict[str, Any]] = []
    for index, raw in enumerate(value):
        if not isinstance(raw, dict):
            raise ValueError(f"surfaces[{index}] must be an object")
        extra = set(raw) - allowed
        if extra:
            raise ValueError(
                f"unexpected Surface fields: {', '.join(sorted(extra))}"
            )
        method = raw.get("method")
        path = raw.get("path")
        params = raw.get("params", [])
        auth_context = raw.get("auth_context", "anonymous")
        surface_type = raw.get("surface_type", "route")
        if not isinstance(method, str) or not method.strip():
            raise ValueError(f"surfaces[{index}].method is required")
        if not isinstance(path, str) or not path.strip():
            raise ValueError(f"surfaces[{index}].path is required")
        if not isinstance(params, list) or not all(
            isinstance(item, str) and item.strip() for item in params
        ):
            raise ValueError(f"surfaces[{index}].params must contain strings")
        if not isinstance(auth_context, str) or not auth_context.strip():
            raise ValueError(f"surfaces[{index}].auth_context is required")
        if not isinstance(surface_type, str) or not surface_type.strip():
            raise ValueError(f"surfaces[{index}].surface_type is required")
        normalized.append({
            "method": method.strip().upper(),
            "path": path.strip(),
            "params": list(dict.fromkeys(item.strip() for item in params)),
            "auth_context": auth_context.strip(),
            "surface_type": surface_type.strip(),
        })
    return normalized


def _validate_web_surface_refs(value: Any, field: str) -> list[str]:
    if not isinstance(value, list) or not all(
        isinstance(item, str) and item.strip() for item in value
    ):
        raise ValueError(f"{field} must contain Surface ids")
    return list(dict.fromkeys(item.strip() for item in value))


def _validate_web_verify_requests(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, str):
        value = [{"claim": value}]
    elif isinstance(value, dict):
        value = [value]
    if not isinstance(value, list) or not value:
        raise ValueError("verify must be a non-empty string, object, or array")
    normalized: list[dict[str, Any]] = []
    allowed = {"claim", "surface_ref", "surface_refs", "evidence_refs"}
    for index, raw in enumerate(value):
        if not isinstance(raw, dict) or set(raw) - allowed:
            raise ValueError(f"verify[{index}] contains unexpected fields")
        claim = raw.get("claim")
        if not isinstance(claim, str) or not claim.strip():
            raise ValueError(f"verify[{index}].claim is required")
        surface_refs = raw.get("surface_refs")
        if surface_refs is None:
            surface_ref = raw.get("surface_ref")
            surface_refs = [surface_ref] if isinstance(surface_ref, str) else []
        surface_refs = _validate_web_surface_refs(surface_refs, f"verify[{index}].surface_refs")
        evidence_refs = raw.get("evidence_refs", [])
        if not isinstance(evidence_refs, list) or not all(
            isinstance(item, str) and item.strip() for item in evidence_refs
        ):
            raise ValueError(f"verify[{index}].evidence_refs must contain references")
        normalized.append({
            "claim": claim.strip(),
            "surface_refs": surface_refs,
            "evidence_refs": list(dict.fromkeys(item.strip() for item in evidence_refs)),
        })
    return normalized


def validate_explore_payload(
    payload: dict[str, Any], *, fact_only: bool = False, allow_surfaces: bool = False,
    action_kind: str | None = None,
) -> tuple[str, dict[str, Any] | None]:
    accepted, data = _unwrap_wrapped_payload(payload)
    if accepted is False:
        return "rejected", None
    if fact_only:
        if accepted is not True or not isinstance(data, dict):
            raise ValueError("accepted must be true")
        if data == {"no_result": True}:
            return "no_result", None
        allowed_fields = {"description", "tested_surface_refs", "verify"}
        normalized_action = str(action_kind or "").strip().casefold().replace("-", "_")
        if normalized_action == "state_check":
            allowed_fields.add("state_check")
        elif "state_check" in data:
            raise ValueError("only state_check Intents may submit state_check data")
        if allow_surfaces:
            allowed_fields.add("surfaces")
        required_fields = {"description"}
        if not required_fields.issubset(data) or not set(data).issubset(allowed_fields):
            raise ValueError("Web Explore data may contain only description, verify, or allowed surfaces")
        description = data.get("description")
        if not isinstance(description, str) or not description.strip():
            raise ValueError("description is required")
        result: dict[str, Any] = {"description": description.strip()}
        if "state_check" in data:
            if normalized_action != "state_check":
                raise ValueError("only state_check Intents may submit state_check data")
            raw_check = data["state_check"]
            if not isinstance(raw_check, dict) or set(raw_check) != {
                "mutation_intent_id", "observed_state", "evidence_refs",
            }:
                raise ValueError("state_check must contain mutation_intent_id, observed_state, and evidence_refs")
            mutation_id = raw_check.get("mutation_intent_id")
            observed_state = raw_check.get("observed_state")
            evidence_refs = raw_check.get("evidence_refs")
            if not isinstance(mutation_id, str) or not mutation_id.strip():
                raise ValueError("state_check.mutation_intent_id is required")
            if observed_state not in {"applied", "not_applied", "unknown"}:
                raise ValueError("state_check.observed_state is invalid")
            if not isinstance(evidence_refs, list) or not evidence_refs or not all(
                isinstance(ref, str) and ref.strip() for ref in evidence_refs
            ):
                raise ValueError("state_check.evidence_refs must contain references")
            result["state_check"] = {
                "mutation_intent_id": mutation_id.strip(),
                "observed_state": observed_state,
                "evidence_refs": list(dict.fromkeys(ref.strip() for ref in evidence_refs)),
            }
        if "tested_surface_refs" in data:
            result["tested_surface_refs"] = _validate_web_surface_refs(
                data["tested_surface_refs"], "tested_surface_refs",
            )
        verify = data.get("verify")
        if verify is not None:
            result["verify_requests"] = _validate_web_verify_requests(verify)
        if "surfaces" in data:
            result["observed_surfaces"] = _validate_web_surfaces(data["surfaces"])
        return "fact", result
    if accepted is None:
        if not _looks_like_explore_data(payload):
            raise ValueError("accepted must be true or false")
        data = payload
    if not isinstance(data, dict):
        raise ValueError("accepted must be true or false")
    if data.get("no_result") is True:
        return "no_result", None
    description = data.get("description")
    if not isinstance(description, str) or not description.strip():
        raise ValueError("description is required")
    result: dict[str, Any] = {"description": description.strip()}
    evidence_refs = data.get("evidence_refs")
    if not fact_only:
        for field in _EXPLORE_STRING_FIELDS:
            value = data.get(field)
            if isinstance(value, str) and value.strip():
                result[field] = value.strip()
        for field in _EXPLORE_BOOL_FIELDS:
            value = data.get(field)
            if isinstance(value, bool):
                result[field] = value
        for field in ("subject", "data"):
            value = data.get(field)
            if isinstance(value, dict):
                result[field] = dict(value)
        parent_fact_ids = data.get("parent_fact_ids")
        if isinstance(parent_fact_ids, list):
            result["parent_fact_ids"] = [item.strip() for item in parent_fact_ids if isinstance(item, str) and item.strip()]
        confidence = data.get("confidence")
        if isinstance(confidence, (int, float)) and 0 <= float(confidence) <= 1:
            result["confidence"] = float(confidence)
        schema_version = data.get("schema_version")
        if isinstance(schema_version, int) and schema_version >= 1:
            result["schema_version"] = schema_version
    if isinstance(evidence_refs, list):
        result["evidence_refs"] = [
            item.strip() for item in evidence_refs
            if isinstance(item, str) and item.strip()
        ]
    observed_surfaces = data.get("observed_surfaces")
    if isinstance(observed_surfaces, list):
        result["observed_surfaces"] = [
            dict(surface) for surface in observed_surfaces[:100] if isinstance(surface, dict)
        ]
    return "fact", result


_VERIFY_RESULTS = frozenset({"reproduced", "not_reproduced"})


def validate_verify_payload(payload: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    """Validate the deliberately small Verify Agent terminal protocol."""
    accepted, data = _unwrap_wrapped_payload(payload)
    if accepted is not True or not isinstance(data, dict):
        raise ValueError("accepted must be true")

    extra_keys = set(data) - {"result", "description", "evidence_refs"}
    if extra_keys:
        raise ValueError(f"unexpected verify fields: {', '.join(sorted(extra_keys))}")

    result = data.get("result")
    if result not in _VERIFY_RESULTS:
        raise ValueError("result must be reproduced or not_reproduced")

    description = data.get("description")
    if not isinstance(description, str) or not description.strip():
        raise ValueError("description is required")

    normalized: dict[str, Any] = {
        "result": result,
        "description": description.strip(),
    }
    evidence_refs = data.get("evidence_refs")
    if evidence_refs is not None:
        if not isinstance(evidence_refs, list) or not all(
            isinstance(item, str) and item.strip() for item in evidence_refs
        ):
            raise ValueError("evidence_refs must be an array of non-empty strings")
        normalized["evidence_refs"] = [
            item.strip() for item in evidence_refs
        ]
    return result, normalized
