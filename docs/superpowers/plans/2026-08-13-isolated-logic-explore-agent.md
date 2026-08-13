# Isolated Logic Explore Agent Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add one disabled-by-default, isolated Logic Explore worker that handles only Coverage-bound `business_logic` Intents and receives one fixed `logic-explore` Skill while preserving all existing task contracts.

**Architecture:** Extend existing worker configuration with a `logic_explore` capability and the runtime configuration with an opt-in switch. Resolve the current Explore Intent's family only from bound `CoverageItem.test_family`, filter workers before the existing priority/load ordering, and append the fixed Skill only to the selected Logic Explore worker's initial prompt. Keep knowledge lookup inside the worker's existing shell/`rg` path and keep all results on the existing Explore/Fact/Evidence/Verify lifecycle.

**Tech Stack:** Python 3.12, Pydantic, existing Dispatcher/worker drivers, Markdown prompt resources, pytest, PyYAML.

## Global Constraints

- Default `runtime.logic_explore_enabled` is `false`; omitted legacy configuration must retain existing routing.
- A Logic Explore worker has `logic_explore: true` and exactly `task_types: [explore]`.
- A Logic Explore worker is dormant while the runtime switch is false.
- When enabled, only non-Android `real_website` projects route Coverage-bound `business_logic` Intents to Logic Explore workers, with no general-worker fallback.
- CTF and Android projects retain the existing general Explore route even when the global switch is enabled.
- Other or unclassified Explore Intents may select only general Explore workers; conflicting multi-family bindings remain unclaimed.
- Resolve the family only from existing Coverage bindings; do not classify descriptions, parameters, or paths.
- Do not add task types, Coverage types, Fact fields, Evidence fields, terminal states, RAG, vector search, Skill resolvers, or new tools.
- Do not change Reason, Verify, Bootstrap, Android, CTF, mock, or general Explore prompt behavior.
- Do not modify or commit the existing untracked `business_logic/` directory.

---

## File structure

- Modify `skidc/src/skidc/dispatcher/config.py`: opt-in runtime switch, worker capability, and configuration invariants.
- Modify `skidc/src/skidc/dispatcher/scheduler/worker_select.py`: pure Coverage-family resolution and Explore-profile matching helpers.
- Modify `skidc/src/skidc/dispatcher/scheduler/loop.py`: pass the resolved family into worker selection and prevent cross-profile fallback.
- Create `skidc/src/skidc/dispatcher/skills/__init__.py`: package marker and fixed Skill loader.
- Create `skidc/src/skidc/dispatcher/skills/logic-explore.md`: the single Logic Explore operating procedure.
- Modify `skidc/src/skidc/dispatcher/tasks/explore.py`: append the Skill to the initial prompt only for the enabled Logic Explore worker.
- Modify `skidc/tests/test_config_and_drivers.py`: configuration and Skill-resource tests.
- Modify `skidc/tests/test_scheduler_and_runtime.py`: deterministic family resolution and isolation-routing tests.
- Modify `skidc/tests/test_real_website_coverage_closure.py`: prompt-contract and no-new-terminal regression checks.
- Create `dispatch_logic.example.yaml`: an explicit opt-in example; leave `dispatch.yaml`, `dispatch.example.yaml`, `dispatch_android.example.yaml`, and `dispatch_mock.yaml` unchanged.
- Modify `README.md`: short setup and safety explanation for the optional worker.

---

### Task 1: Add disabled-by-default configuration contracts

**Files:**
- Modify: `skidc/src/skidc/dispatcher/config.py:152-242`
- Modify: `skidc/tests/test_config_and_drivers.py:70-140`

**Interfaces:**
- Produces: `RuntimeConfig.logic_explore_enabled: bool = False`.
- Produces: `WorkerConfig.logic_explore: bool = False`.
- Enforces: a Logic Explore worker has exactly `task_types == ["explore"]`.
- Enforces: enabled mode contains at least one Logic Explore worker and at least one general Explore worker.
- Preserves: all existing dictionaries accepted by `DispatchConfig.model_validate()` without new required keys.

- [ ] **Step 1: Write failing configuration tests**

Add these cases to `test_config_and_drivers.py` using `_base_config()`:

```python
def test_logic_explore_defaults_are_disabled() -> None:
    config = DispatchConfig.model_validate(
        _base_config([{
            "name": "general", "type": "mock", "task_types": ["explore"],
            "max_running": 1, "priority": 0, "env": {},
        }])
    )
    assert config.runtime.logic_explore_enabled is False
    assert config.workers[0].logic_explore is False


def test_logic_explore_worker_must_be_explore_only() -> None:
    data = _base_config([{
        "name": "logic", "type": "mock", "task_types": ["reason", "explore"],
        "logic_explore": True, "max_running": 1, "priority": 0, "env": {},
    }])
    with pytest.raises(ValueError, match="exactly task_types.*explore"):
        DispatchConfig.model_validate(data)


def test_enabled_logic_explore_requires_both_worker_profiles() -> None:
    logic_only = _base_config([{
        "name": "logic", "type": "mock", "task_types": ["explore"],
        "logic_explore": True, "max_running": 1, "priority": 0, "env": {},
    }])
    logic_only["runtime"]["logic_explore_enabled"] = True
    with pytest.raises(ValueError, match="general Explore worker"):
        DispatchConfig.model_validate(logic_only)

    general_only = _base_config([{
        "name": "general", "type": "mock", "task_types": ["explore"],
        "max_running": 1, "priority": 0, "env": {},
    }])
    general_only["runtime"]["logic_explore_enabled"] = True
    with pytest.raises(ValueError, match="Logic Explore worker"):
        DispatchConfig.model_validate(general_only)
```

- [ ] **Step 2: Run the tests and verify they fail**

Run:

```powershell
Set-Location skidc
uv run --group dev pytest tests/test_config_and_drivers.py -k "logic_explore" -v
```

Expected: failures because both fields and validation rules are absent.

- [ ] **Step 3: Implement the minimal configuration fields and validators**

Add to `RuntimeConfig`:

```python
logic_explore_enabled: bool = False
```

Add to `WorkerConfig`:

```python
logic_explore: bool = False
```

Extend the existing worker model validator:

```python
if self.logic_explore and self.task_types != ["explore"]:
    raise ValueError("logic_explore worker must declare exactly task_types: [explore]")
```

Extend `DispatchConfig.validate_workers()` after the existing worker-name and runtime-cap checks:

```python
if self.runtime.logic_explore_enabled:
    logic_workers = [worker for worker in self.workers if worker.logic_explore]
    general_explore_workers = [
        worker for worker in self.workers
        if "explore" in worker.task_types and not worker.logic_explore
    ]
    if not logic_workers:
        raise ValueError("logic_explore_enabled requires a Logic Explore worker")
    if not general_explore_workers:
        raise ValueError("logic_explore_enabled requires a general Explore worker")
```

- [ ] **Step 4: Run focused and legacy configuration tests**

Run:

```powershell
uv run --group dev pytest tests/test_config_and_drivers.py -v
```

Expected: all tests pass, including legacy configuration tests.

- [ ] **Step 5: Commit**

```powershell
git add skidc/src/skidc/dispatcher/config.py skidc/tests/test_config_and_drivers.py
git commit -m "feat: add isolated logic explore configuration"
```

---

### Task 2: Resolve Coverage family and isolate scheduler routing

**Files:**
- Modify: `skidc/src/skidc/dispatcher/scheduler/worker_select.py:1-17`
- Modify: `skidc/src/skidc/dispatcher/scheduler/loop.py:474-506,562-599`
- Modify: `skidc/tests/test_scheduler_and_runtime.py:35-68,291-388`

**Interfaces:**
- Produces: `resolve_intent_test_family(project: ProjectDetail, intent: Intent) -> tuple[str | None, bool]`, where the boolean reports conflicting family bindings.
- Produces: `worker_matches_explore_family(worker: WorkerConfig, *, logic_route: bool) -> bool`.
- Changes: `DispatcherLoop._select_worker(..., logic_route: bool = False)`.
- Consumes: `CoverageItem.id`, `intent_id`, `intent_ids`, `test_family`, and `Intent.coverage_refs`.

- [ ] **Step 1: Write failing pure-helper tests**

Import the new helpers into `test_scheduler_and_runtime.py`. Build Coverage items with `CoverageItem.model_validate()` and attach them to the existing `_project()` result. Cover:

```python
def test_resolve_intent_test_family_uses_bound_coverage_only() -> None:
    project = _project(facts=1, hints=0, open_intents=1)
    intent = project.intents[0]
    intent.description = "refund amount looks numeric"
    project.coverage_items = [CoverageItem.model_validate({
        "id": "cov-logic", "item_type": "route", "description": "refund",
        "test_family": "business_logic", "test_variants": ["workflow_integrity"],
        "intent_id": intent.id,
        "created_at": "2025-01-01T00:00:00Z",
        "updated_at": "2025-01-01T00:00:00Z",
    })]
    assert resolve_intent_test_family(project, intent) == ("business_logic", False)


def test_resolve_intent_test_family_does_not_guess_from_description() -> None:
    project = _project(facts=1, hints=0, open_intents=1)
    project.intents[0].description = "refund amount workflow replay"
    assert resolve_intent_test_family(project, project.intents[0]) == (None, False)


def test_resolve_intent_test_family_rejects_ambiguous_bindings() -> None:
    project = _project(facts=1, hints=0, open_intents=1)
    intent = project.intents[0]
    common = {
        "item_type": "route",
        "description": "assigned test",
        "intent_id": intent.id,
        "created_at": "2025-01-01T00:00:00Z",
        "updated_at": "2025-01-01T00:00:00Z",
    }
    project.coverage_items = [
        CoverageItem.model_validate({
            **common, "id": "cov-logic", "test_family": "business_logic",
        }),
        CoverageItem.model_validate({
            **common, "id": "cov-auth", "test_family": "identity_auth",
        }),
    ]
    assert resolve_intent_test_family(project, intent) == (None, True)
```

Add a parameterized profile matrix:

```python
@pytest.mark.parametrize(
    ("logic_route", "logic_worker", "expected"),
    [
        (False, False, True),
        (False, True, False),
        (True, False, False),
        (True, True, True),
    ],
)
def test_worker_matches_explore_family_matrix(
    logic_route: bool, logic_worker: bool, expected: bool,
) -> None:
    worker = _worker("worker", priority=0).model_copy(
        update={"logic_explore": logic_worker}
    )
    assert worker_matches_explore_family(
        worker, logic_route=logic_route,
    ) is expected
```

- [ ] **Step 2: Run the helper tests and verify they fail**

Run:

```powershell
uv run --group dev pytest tests/test_scheduler_and_runtime.py -k "intent_test_family or worker_matches_explore" -v
```

Expected: import or assertion failures because the helpers do not exist.

- [ ] **Step 3: Implement deterministic Coverage resolution and profile matching**

In `worker_select.py`, add:

```python
from skidc.server.models import Intent, ProjectDetail


def resolve_intent_test_family(
    project: ProjectDetail, intent: Intent,
) -> tuple[str | None, bool]:
    explicit_refs = set(intent.coverage_refs)
    families = {
        item.test_family
        for item in project.coverage_items
        if item.test_family is not None
        and (
            item.id in explicit_refs
            or item.intent_id == intent.id
            or intent.id in item.intent_ids
        )
    }
    if len(families) > 1:
        return None, True
    return (next(iter(families)), False) if families else (None, False)


def worker_matches_explore_family(
    worker: WorkerConfig, *, logic_route: bool,
) -> bool:
    return worker.logic_explore is logic_route
```

This intentionally treats no binding as unclassified and reports conflicting bindings separately. It does not infer a family from `test_variant` or natural language.

- [ ] **Step 4: Write failing Dispatcher isolation tests**

Import `CoverageItem`. Add helpers that build a `DispatchConfig` containing one general and one logic mock worker and a scheduler stub capable of recording `_dispatch_explore()` submissions:

```python
class _RecordingExecutor:
    def __init__(self) -> None:
        self.calls: list[tuple[object, ...]] = []

    def submit(self, *args: object) -> Future[str]:
        self.calls.append(args)
        return Future()


def _logic_routing_loop() -> tuple[DispatcherLoop, _RecordingExecutor]:
    base = mock_config(
        bootstrap=phase("complete"), reason=phase("intent"), explore=phase("fact"),
    )
    general = base.workers[0].model_copy(update={
        "name": "general", "task_types": ["explore"],
        "logic_explore": False, "max_running": 4,
    })
    logic = base.workers[0].model_copy(update={
        "name": "logic", "task_types": ["explore"],
        "logic_explore": True, "max_running": 1,
    })
    config = base.model_copy(update={
        "runtime": base.runtime.model_copy(update={
            "logic_explore_enabled": True, "max_workers": 2,
        }),
        "workers": [general, logic],
    })
    loop = _bare_loop()
    loop.config = config
    loop.futures = {}
    loop.worker_unhealthy_until = {}
    loop.worker_rejected_until = {}
    loop.startup_unhealthy_workers = set()
    loop.runtime_project_ids = set()
    loop._log_state = {}
    loop.container_manager = object()

    class _Client:
        def heartbeat(self, _project_id: str, _intent_id: str, _worker: str) -> ApiResult:
            return ApiResult(200, {})

    executor = _RecordingExecutor()
    loop.client = _Client()
    loop.executor = executor
    return loop, executor


def _coverage(
    coverage_id: str, intent_id: str, family: str,
) -> CoverageItem:
    return CoverageItem.model_validate({
        "id": coverage_id,
        "item_type": "route",
        "description": f"{family} assignment",
        "test_family": family,
        "intent_id": intent_id,
        "created_at": "2025-01-01T00:00:00Z",
        "updated_at": "2025-01-01T00:00:00Z",
    })
```

Test `_select_worker()` directly:

```python
def test_enabled_logic_family_selects_only_logic_worker() -> None:
    loop, _ = _logic_routing_loop()
    selection = loop._select_worker(
        "proj_001", "explore", logic_route=True,
    )
    assert selection.worker is not None
    assert selection.worker.name == "logic"


def test_enabled_non_logic_family_selects_only_general_worker() -> None:
    loop, _ = _logic_routing_loop()
    selection = loop._select_worker(
        "proj_001", "explore", logic_route=False,
    )
    assert selection.worker is not None
    assert selection.worker.name == "general"


def test_business_logic_does_not_fallback_when_logic_worker_is_busy() -> None:
    loop, _ = _logic_routing_loop()
    loop.futures[Future()] = RunningTask(
        "other-project", "explore", "logic", TaskCancellation(),
    )
    selection = loop._select_worker(
        "proj_001", "explore", logic_route=True,
    )
    assert selection.worker is None


def test_disabled_mode_keeps_general_selection_and_logic_worker_dormant() -> None:
    loop, _ = _logic_routing_loop()
    loop.config.runtime.logic_explore_enabled = False
    selection = loop._select_worker(
        "proj_001", "explore", logic_route=True,
    )
    assert selection.worker is not None
    assert selection.worker.name == "general"


def test_disabled_mode_does_not_block_legacy_ambiguous_coverage() -> None:
    loop, executor = _logic_routing_loop()
    loop.config.runtime.logic_explore_enabled = False
    project = _project(facts=1, hints=0, open_intents=1)
    project.project.mode = "real_website"
    intent = project.intents[0]
    project.coverage_items = [
        _coverage("cov-logic", intent.id, "business_logic"),
        _coverage("cov-auth", intent.id, "identity_auth"),
    ]
    assert loop._dispatch_explore(project, "graph", intent) is True
    submitted_worker = executor.calls[0][7]
    assert submitted_worker.name == "general"


@pytest.mark.parametrize(("mode", "target_type"), [("ctf", "domain"), ("real_website", "android")])
def test_logic_route_is_not_used_for_ctf_or_android(
    mode: str, target_type: str,
) -> None:
    loop, executor = _logic_routing_loop()
    project = _project(facts=1, hints=0, open_intents=1)
    project.project.mode = mode
    project.project.recon_profile.target_type = target_type
    intent = project.intents[0]
    project.coverage_items = [
        _coverage("cov-logic", intent.id, "business_logic"),
    ]
    assert loop._dispatch_explore(project, "graph", intent) is True
    submitted_worker = executor.calls[0][7]
    assert submitted_worker.name == "general"
```

- [ ] **Step 5: Wire family resolution into `_dispatch_explore()` and filtering into `_select_worker()`**

Update imports in `loop.py`:

```python
from skidc.dispatcher.scheduler.worker_select import (
    choose_worker,
    resolve_intent_test_family,
    worker_matches_explore_family,
)
```

At the start of `_dispatch_explore()`:

```python
logic_feature_applies = (
    self.config.runtime.logic_explore_enabled
    and project.project.mode == "real_website"
    and project.project.recon_profile.target_type != "android"
)
logic_route = False
if logic_feature_applies:
    test_family, ambiguous_family = resolve_intent_test_family(project, intent)
    if ambiguous_family:
        LOG.warning(
            "explore family binding is ambiguous project=%s intent=%s",
            project.project.id,
            intent.id,
        )
        return False
    logic_route = test_family == "business_logic"
selection = self._select_worker(
    project.project.id,
    "explore",
    avoid_worker=intent.last_worker if project.project.mode == "real_website" else None,
    logic_route=logic_route,
)
```

Extend `_select_worker()` with keyword-only `logic_route: bool = False`. After checking `task_types` and before capacity/health checks, skip workers that fail `worker_matches_explore_family()` when `task_type == "explore"`. Apply this check even while the feature is disabled so declared Logic Explore workers remain dormant.

Do not resolve or reject ambiguous Coverage bindings while the feature is disabled or the project is CTF/Android; those paths must retain their legacy general Explore behavior.

- [ ] **Step 6: Run scheduler tests**

Run:

```powershell
uv run --group dev pytest tests/test_scheduler_and_runtime.py -v
```

Expected: all scheduler tests pass, including Android target-local worker submission.

- [ ] **Step 7: Commit**

```powershell
git add skidc/src/skidc/dispatcher/scheduler/worker_select.py skidc/src/skidc/dispatcher/scheduler/loop.py skidc/tests/test_scheduler_and_runtime.py
git commit -m "feat: isolate business logic explore routing"
```

---

### Task 3: Add the fixed Logic Explore Skill and prompt injection

**Files:**
- Create: `skidc/src/skidc/dispatcher/skills/__init__.py`
- Create: `skidc/src/skidc/dispatcher/skills/logic-explore.md`
- Modify: `skidc/src/skidc/dispatcher/tasks/explore.py:1-205`
- Modify: `skidc/tests/test_config_and_drivers.py`
- Modify: `skidc/tests/test_real_website_coverage_closure.py:1035-1060`

**Interfaces:**
- Produces: `load_logic_explore_skill() -> str` using `importlib.resources`.
- Produces: `with_logic_explore_skill(prompt: str, config: DispatchConfig, worker: WorkerConfig) -> str`.
- Preserves: the default, mock, and Android prompt files and all Explore JSON output validation.

- [ ] **Step 1: Write failing Skill resource tests**

In `test_config_and_drivers.py`, import `load_logic_explore_skill` and assert that the fixed resource contains the non-negotiable contracts:

```python
def test_logic_explore_skill_preserves_existing_contracts() -> None:
    skill = load_logic_explore_skill()
    assert "Current Intent" in skill
    assert "authoritative" in skill
    assert "baseline" in skill
    assert "/home/kali/knowledges/" in skill
    assert "rg" in skill
    assert "knowledge" in skill and "evidence" in skill
    assert "no_result" in skill
    assert "Verify" in skill
    assert "candidate:" not in skill
    assert "inconclusive:" not in skill
    assert "not_applicable:" not in skill
    assert "not_vulnerable:" not in skill
```

Add pure injection tests for all four cases:

```python
def test_logic_skill_is_injected_only_for_enabled_logic_worker() -> None:
    workers = [
        {
            "name": "general", "type": "mock", "task_types": ["explore"],
            "max_running": 1, "priority": 0, "env": {},
        },
        {
            "name": "logic", "type": "mock", "task_types": ["explore"],
            "logic_explore": True, "max_running": 1, "priority": 0,
            "env": {},
        },
    ]
    data = _base_config(workers)
    data["runtime"]["logic_explore_enabled"] = True
    enabled_config = DispatchConfig.model_validate(data)
    disabled_config = enabled_config.model_copy(
        update={
            "runtime": enabled_config.runtime.model_copy(
                update={"logic_explore_enabled": False}
            )
        }
    )
    general_worker = next(
        worker for worker in enabled_config.workers if not worker.logic_explore
    )
    logic_worker = next(
        worker for worker in enabled_config.workers if worker.logic_explore
    )

    assert "# Logic Explore Skill" in with_logic_explore_skill(
        "BASE", enabled_config, logic_worker,
    )
    assert with_logic_explore_skill("BASE", disabled_config, logic_worker) == "BASE"
    assert with_logic_explore_skill("BASE", enabled_config, general_worker) == "BASE"
```

- [ ] **Step 2: Run the tests and verify they fail**

Run:

```powershell
uv run --group dev pytest tests/test_config_and_drivers.py -k "logic_explore_skill or logic_skill" -v
```

Expected: import failures because the Skill package and injection helper do not exist.

- [ ] **Step 3: Create the Skill loader**

Create `skills/__init__.py`:

```python
from importlib import resources


def load_logic_explore_skill() -> str:
    return resources.files(__package__).joinpath("logic-explore.md").read_text(
        encoding="utf-8"
    )
```

Do not add a general-purpose Skill registry or accept a caller-supplied filename.

- [ ] **Step 4: Write the fixed `logic-explore.md` Skill**

The file must use imperative instructions and contain these sections:

```markdown
# Logic Explore Skill

## Contract
Execute only the Current Intent and assigned Surfaces. Preserve Graph facts,
Coverage, authorization scope, and the existing Explore output contract. Do
not create states, classifications, Intents, or Coverage.

## Model the business action
Identify one actor, business object, action, relevant before/after state,
authoritative state source, invariant, and explicit violation predicate.
Choose only the relevant lens: workflow integrity, actor/resource boundary,
replay/idempotency, numeric invariant, or client-trusted business field.

## Establish a baseline
Prefer an existing captured valid request with observable state. Otherwise,
perform at most one minimal, reversible normal action on an explicitly
authorized test object. Record authoritative before-state, request/completion
signal, authoritative after-state, and correlation identifiers. Do not create
a financial or irreversible action merely to obtain a baseline. If the
baseline fails, times out, cannot be correlated, or cannot be observed,
return the existing `no_result` output.

## Search knowledge only when needed
Skip search when the invariant, mutation, and validation method are clear.
Otherwise use `rg` against `/home/kali/knowledges/`, initially searching no
more than two corpora with one query built from the current business object,
action, and invariant. Inspect no more than three directly relevant files and
read only matching context.

- Use `owasp-bla-top10` for abuse models.
- Use `wooyun-legacy` for comparable logic cases.
- Use `hack-skills` for agent-oriented procedures.
- Use `vulnerability-Checklist` for missed boundary checks.
- Use `hacktricks` for general methodology.
- Use `PayloadsAllTheThings` for concrete payload or encoding variants.

Treat retrieved knowledge only as hypothesis and method guidance. It is not
evidence that the current target is vulnerable. Before adopting a historical
method, re-check scope, authorization, impact, test data, reversibility, and
authoritative state-observation ability.

## Execute one bounded mutation
Choose the smallest mutation that tests the Current Intent's invariant.
Confirm safety immediately before execution. Execute once unless the Intent
explicitly requires bounded replay or concurrency and authorization permits
it. Never operate on another user's or an unapproved production object.

## Validate and report
Query authoritative post-operation state and persistent side effects. Compare
them with the baseline and invariant. Do not infer impact from HTTP status,
response text, UI-only differences, request failure, tool failure, or a
knowledge-base example. Keep requests, responses, state snapshots, `rg`
commands, and matched paths in existing task logs. Return objective
observations through the existing Explore Fact contract; hand a concrete
candidate impact to the existing Verify flow. Use existing `no_result` for an
incomplete, unsafe, failed, timed-out, or unobservable execution.
```

Do not copy the existing untracked `business_logic/numeric_invariant.md`; this Skill is intentionally smaller and covers the five lenses in one workflow.

- [ ] **Step 5: Add narrow prompt injection**

In `tasks/explore.py`, add:

```python
from skidc.dispatcher.skills import load_logic_explore_skill


def with_logic_explore_skill(
    prompt: str, config: DispatchConfig, worker: WorkerConfig,
) -> str:
    if not config.runtime.logic_explore_enabled or not worker.logic_explore:
        return prompt
    return f"{prompt.rstrip()}\n\n{load_logic_explore_skill().strip()}\n"
```

Call it immediately after `_with_web_fact_output_rules()` in the initial `run_explore_task()` path and before `driver.build_execute()`. Do not add it to `explore_conclude.md`: conclude resumes the same session or summarizes existing execution and must not restart testing.

- [ ] **Step 6: Add real-web prompt contract regression tests**

In `test_real_website_coverage_closure.py`, extend the prompt checks to assert:

- the normal default `explore.md` does not contain `Logic Explore Skill`;
- the Skill contains no new terminal-state instructions;
- `_WEB_FACT_OUTPUT_RULES` continues to say failed/incomplete testing is `no_result` and Verify remains a handoff.

- [ ] **Step 7: Run Skill and prompt tests**

Run:

```powershell
uv run --group dev pytest tests/test_config_and_drivers.py tests/test_real_website_coverage_closure.py -v
```

Expected: all tests pass.

- [ ] **Step 8: Commit**

```powershell
git add skidc/src/skidc/dispatcher/skills skidc/src/skidc/dispatcher/tasks/explore.py skidc/tests/test_config_and_drivers.py skidc/tests/test_real_website_coverage_closure.py
git commit -m "feat: add fixed logic explore skill"
```

---

### Task 4: Add an isolated opt-in example and operator documentation

**Files:**
- Create: `dispatch_logic.example.yaml`
- Modify: `README.md:330-425,520-565`
- Modify: `skidc/tests/test_config_and_drivers.py`

**Interfaces:**
- Produces: a loadable example with one general Explore-capable worker and one `logic_explore: true` Explore-only worker.
- Preserves: all existing example and active configuration files unchanged.

- [ ] **Step 1: Write a failing example-configuration test**

Add:

```python
def test_logic_example_is_explicitly_enabled_and_isolated() -> None:
    path = Path(__file__).parents[2] / "dispatch_logic.example.yaml"
    config = DispatchConfig.load(path)
    assert config.runtime.logic_explore_enabled is True
    logic_workers = [worker for worker in config.workers if worker.logic_explore]
    assert len(logic_workers) == 1
    assert logic_workers[0].task_types == ["explore"]
    assert any(
        "explore" in worker.task_types and not worker.logic_explore
        for worker in config.workers
    )
```

- [ ] **Step 2: Run the test and verify it fails**

Run:

```powershell
uv run --group dev pytest tests/test_config_and_drivers.py -k "logic_example" -v
```

Expected: failure because `dispatch_logic.example.yaml` does not exist.

- [ ] **Step 3: Create the opt-in example**

Copy the operational structure of `dispatch.example.yaml`, set:

```yaml
runtime:
  logic_explore_enabled: true
```

Keep one existing general worker with normal task types. Add one worker such as:

```yaml
- name: "logic_explore_qwen"
  type: "codex"
  task_types: [explore]
  logic_explore: true
  max_running: 1
  priority: 0
  env:
    CODEX_MODEL: "qwen3.7-plus"
    CODEX_BASE_URL: "https://dashscope.aliyuncs.com/compatible-mode/v1"
    OPENAI_API_KEY: "<YOUR_LOGIC_EXPLORE_OPENAI_API_KEY>"
```

Do not edit `dispatch.yaml`; the new worker must not become active merely by pulling the change.

- [ ] **Step 4: Document setup and baseline behavior**

Add a concise README section explaining:

- the feature is optional and disabled by default;
- use `dispatch_logic.example.yaml` as the starting configuration;
- only non-Android `real_website` Coverage-bound `business_logic` Intents reach the Logic Explore worker;
- the worker uses one fixed Skill and existing `rg` access to `/home/kali/knowledges/`;
- a baseline is a valid control observation and should preferably reuse an existing normal request;
- no compatible Logic Explore capacity means the business-logic Intent waits rather than falling back;
- all outputs continue through existing Explore/Fact/Evidence/Verify contracts.

- [ ] **Step 5: Run configuration tests**

Run:

```powershell
uv run --group dev pytest tests/test_config_and_drivers.py -v
```

Expected: all tests pass and the new YAML parses through `DispatchConfig.load()`.

- [ ] **Step 6: Commit**

```powershell
git add dispatch_logic.example.yaml README.md skidc/tests/test_config_and_drivers.py
git commit -m "docs: add opt-in logic explore worker example"
```

---

### Task 5: Run compatibility and isolation verification

**Files:**
- Verify only; modify earlier files only when a failing test demonstrates an in-scope defect.

**Interfaces:**
- Verifies the complete feature against existing project contracts.

- [ ] **Step 1: Run focused isolation tests**

```powershell
Set-Location skidc
uv run --group dev pytest tests/test_config_and_drivers.py tests/test_scheduler_and_runtime.py tests/test_real_website_coverage_closure.py -v
```

Expected: all tests pass.

- [ ] **Step 2: Run mock lifecycle regression tests**

```powershell
uv run --group dev pytest tests/test_mock_end_to_end.py tests/test_scheduler_retry.py -v
```

Expected: all tests pass with the existing mock prompt group and no Logic Skill injection.

- [ ] **Step 3: Run Android regression tests**

```powershell
uv run --group dev pytest tests/test_android_docker_config.py tests/test_android_mcp.py tests/test_android_static_analysis.py -v
```

Expected: all tests pass; Android prompt routing and authenticated bridge behavior remain unchanged.

- [ ] **Step 4: Run the complete test suite**

```powershell
uv run --group dev pytest -v
```

Expected: all tests pass.

- [ ] **Step 5: Verify packaging includes the Markdown Skill**

Run a clean resource-load check from the package environment:

```powershell
uv run python -c "from skidc.dispatcher.skills import load_logic_explore_skill; s=load_logic_explore_skill(); assert '# Logic Explore Skill' in s; print(len(s))"
```

Expected: a positive integer is printed and the process exits with code 0.

- [ ] **Step 6: Check the final diff and protected files**

```powershell
git diff --check
git status --short
git diff --name-only HEAD~4..HEAD
```

Expected:

- no whitespace errors;
- `business_logic/` remains untracked and unchanged;
- `dispatch.yaml`, existing prompt files, server models, Fact contracts, and Verify contracts are absent from the feature diff.

- [ ] **Step 7: Commit any test-proven correction, otherwise record verification without an empty commit**

If verification exposes an in-scope defect, first add a regression test to the matching existing test file, make the minimal correction in the corresponding implementation file, rerun that focused test and the complete suite, then stage those explicit files. For example, a scheduler-isolation correction uses:

```powershell
git add skidc/src/skidc/dispatcher/scheduler/worker_select.py skidc/src/skidc/dispatcher/scheduler/loop.py skidc/tests/test_scheduler_and_runtime.py
git commit -m "fix: preserve logic explore isolation"
```

If no correction is necessary, do not create an empty commit.
