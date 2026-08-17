# Android Intent Contract Compatibility Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Accept Android-specific standard-risk Intent action kinds without weakening the custom-action safety rule for Web surfaces.

**Architecture:** Keep validation in the existing Reason-output normalizer. Introduce explicit generic and mobile standard-risk action-kind sets; mobile kinds are accepted only for normalized `android` and `mobile_api` surfaces, while all other custom standard-risk actions continue to fail closed.

**Tech Stack:** Python 3.12, pytest, existing `skidc.dispatcher.contracts` validation layer.

## Global Constraints

- Do not change project scope enforcement, high-risk authorization, execution behavior, or Android prompts.
- Generic standard-risk actions remain valid on every surface type.
- Mobile standard-risk actions are valid only for `android` and `mobile_api` surfaces.
- Unknown custom standard-risk actions remain rejected.
- Preserve unrelated working-tree changes.

---

### Task 1: Make Web-mode Reason normalization surface-aware for mobile actions

**Files:**
- Modify: `skidc/src/skidc/dispatcher/contracts.py:87-146`
- Test: `skidc/tests/test_config_and_drivers.py:617-700`

**Interfaces:**
- Consumes: `validate_reason_payload(payload, open_intents_empty, max_intents, web_mode=True)` and each Intent's `surface_type`, `action_kind`, and optional `risk_level`.
- Produces: normalized Intent dictionaries; standard-risk mobile kinds are accepted only for mobile surfaces, and unsupported standard-risk kinds raise `ValueError`.

- [ ] **Step 1: Write the failing acceptance test**

Add a parameterized test covering every Android action kind observed in `proj_147` and `proj_148`, plus the handoff action documented by the Android prompt:

```python
@pytest.mark.parametrize(
    ("surface_type", "action_kind"),
    [
        ("android", "android_app_launch"),
        ("android", "android_app_setup"),
        ("android", "mobile_app_setup"),
        ("android", "mobile_api_probe"),
        ("mobile_api", "mobile_authz_probe"),
    ],
)
def test_web_reason_accepts_standard_risk_mobile_actions_on_mobile_surfaces(
    surface_type: str, action_kind: str,
) -> None:
    kind, data, recon_complete = validate_reason_payload(
        {
            "accepted": True,
            "data": {
                "intent": {
                    "from": ["origin"],
                    "description": "Map the authorized Android application.",
                    "surface_type": surface_type,
                    "action_kind": action_kind,
                }
            },
        },
        open_intents_empty=True,
        max_intents=2,
        web_mode=True,
    )

    assert kind == "intents"
    assert recon_complete is False
    assert data[0]["surface_type"] == surface_type
    assert data[0]["action_kind"] == action_kind
```

- [ ] **Step 2: Run the acceptance test and verify RED**

Run from the repository root:

```powershell
Set-Location skidc
.\.venv-win\Scripts\python.exe -m pytest tests/test_config_and_drivers.py::test_web_reason_accepts_standard_risk_mobile_actions_on_mobile_surfaces -vv
```

Expected: five parameter cases fail with `A custom Web Intent action_kind requires high or irreversible risk_level`.

- [ ] **Step 3: Add safety-boundary preservation tests**

```python
def test_web_reason_rejects_standard_risk_mobile_action_on_web_surface() -> None:
    with pytest.raises(ValueError, match="custom Web Intent action_kind"):
        validate_reason_payload(
            {
                "accepted": True,
                "data": {
                    "intent": {
                        "from": ["origin"],
                        "description": "Do not classify a Web action as mobile.",
                        "surface_type": "web",
                        "action_kind": "mobile_api_probe",
                    }
                },
            },
            open_intents_empty=True,
            max_intents=2,
            web_mode=True,
        )


def test_web_reason_rejects_unknown_standard_risk_action() -> None:
    with pytest.raises(ValueError, match="custom Web Intent action_kind"):
        validate_reason_payload(
            {
                "accepted": True,
                "data": {
                    "intent": {
                        "from": ["origin"],
                        "description": "Reject an unknown standard-risk action.",
                        "surface_type": "android",
                        "action_kind": "unknown_mobile_action",
                    }
                },
            },
            open_intents_empty=True,
            max_intents=2,
            web_mode=True,
        )
```

- [ ] **Step 4: Run the safety tests against the existing behavior**

```powershell
Set-Location skidc
.\.venv-win\Scripts\python.exe -m pytest tests/test_config_and_drivers.py -k "rejects_standard_risk_mobile_action_on_web_surface or rejects_unknown_standard_risk_action" -vv
```

Expected: both pass, documenting the safety behavior that the production change must preserve.

- [ ] **Step 5: Implement the minimal surface-aware allowlist**

In `contracts.py`, define immutable sets near `_WEB_INTENT_FIELDS`:

```python
_STANDARD_RISK_ACTION_KINDS = frozenset(
    {"surface_mapping", "security_test", "verify", "state_check"}
)
_STANDARD_RISK_MOBILE_ACTION_KINDS = frozenset(
    {
        "android_app_launch",
        "android_app_setup",
        "mobile_app_setup",
        "mobile_api_probe",
        "mobile_authz_probe",
    }
)
_MOBILE_SURFACE_TYPES = frozenset({"android", "mobile_api"})
```

Replace the inline four-item check with a surface-aware decision:

```python
    raw_surface_type = normalized.get("surface_type")
    surface_type = (
        raw_surface_type.strip().casefold().replace("-", "_")
        if isinstance(raw_surface_type, str)
        else None
    )
    if surface_type is not None:
        normalized["surface_type"] = surface_type
    standard_risk_action = (
        action_kind in _STANDARD_RISK_ACTION_KINDS
        or (
            surface_type in _MOBILE_SURFACE_TYPES
            and action_kind in _STANDARD_RISK_MOBILE_ACTION_KINDS
        )
    )
    if not standard_risk_action and risk_level == "standard":
        raise ValueError(
            "A custom Web Intent action_kind requires high or irreversible risk_level"
        )
```

- [ ] **Step 6: Run the focused RED/GREEN regression set**

```powershell
Set-Location skidc
.\.venv-win\Scripts\python.exe -m pytest tests/test_config_and_drivers.py -k "standard_risk_mobile or unknown_standard_risk" -vv
```

Expected: all seven selected parameter/test cases pass.

- [ ] **Step 7: Run the complete contract/config test module**

```powershell
Set-Location skidc
.\.venv-win\Scripts\python.exe -m pytest tests/test_config_and_drivers.py -q
```

Expected: exit code 0 with no failed tests.

- [ ] **Step 8: Check the patch and commit only the repair files**

```powershell
git diff --check -- skidc/src/skidc/dispatcher/contracts.py skidc/tests/test_config_and_drivers.py
git diff -- skidc/src/skidc/dispatcher/contracts.py skidc/tests/test_config_and_drivers.py
git add -- skidc/src/skidc/dispatcher/contracts.py skidc/tests/test_config_and_drivers.py
git commit -m "fix: accept scoped Android reason actions"
```

Expected: the commit contains only the contract and regression-test changes; pre-existing benchmark and local configuration files remain untouched.

---

### Task 2: Rebuild the Dispatcher and recover the stopped DVBA project

**Files:**
- Read: `scripts/android-lab.sh:143-160`
- Read: `scripts/android-lab.sh:242-270`

**Interfaces:**
- Consumes: committed repository `HEAD`, the existing `skidc-app:latest` image tag, and stopped project `proj_148`.
- Produces: a rebuilt Dispatcher using the repaired contract and a reactivated project that can create Android Intents.

- [ ] **Step 1: Rebuild images from the repaired commit**

Run in WSL from the repository root:

```bash
./scripts/android-lab.sh build
```

Expected: all three images build successfully, including `skidc-app:latest`. The script intentionally archives committed `HEAD`, so Task 1 must be committed first.

- [ ] **Step 2: Recreate the lab services with the rebuilt application image**

```bash
./scripts/android-lab.sh up
./scripts/android-lab.sh status
```

Expected: `skidc-server`, `skidc-dispatcher`, `android-emulator`, and `android-bridge` are running.

- [ ] **Step 3: Remove the stopped per-project worker and reactivate the project**

```bash
docker rm skidc-dispatch-proj_148
curl -sS -X PUT http://127.0.0.1:8000/projects/proj_148/status \
  -H 'Content-Type: application/json' \
  -d '{"status":"active"}'
```

Expected: the old stopped worker is removed and the project status response reports `active`.

- [ ] **Step 4: Verify the original runtime symptom is gone**

```bash
docker logs --since 5m skidc-dispatcher 2>&1 | grep -E 'proj_148|reason parse failed'
curl -sS http://127.0.0.1:8000/projects/proj_148
```

Expected: the Dispatcher log contains no `custom Web Intent action_kind` parse failure for the new run, and `proj_148` contains at least one Intent or has advanced beyond the empty RECON graph.
