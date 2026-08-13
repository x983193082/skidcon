# Isolated Logic Explore Agent Design

## Goal

Add one opt-in Logic Explore Agent for `business_logic` Intents without changing the normal behavior of Reason, general Explore, Verify, Android, CTF, or projects that do not enable the agent.

The agent uses one fixed `logic-explore` Skill. It may search the existing offline corpora under `/home/kali/knowledges/` with `rg`, but no Skill resolver, RAG service, vector database, knowledge scheduler, new Fact type, or new terminal state is introduced.

## Non-goals

- Do not add a second Coverage system.
- Do not add an AI classifier.
- Do not dynamically load multiple specialist Skills.
- Do not change Reason's responsibility for producing Coverage and Intents.
- Do not change Explore, Verify, Fact, Evidence, or Intent terminal contracts.
- Do not treat knowledge-base text as evidence about the current target.
- Do not automatically enable the new agent for existing configurations.

## Baseline definition

A baseline is a valid control observation for the exact business action under test. It establishes what a normal request changes so that a later bounded mutation can be compared against it.

A baseline consists of:

1. the authoritative state before the normal action;
2. one valid request or an already captured valid request for the same action;
3. the response or business completion signal;
4. the authoritative state after the action; and
5. identifiers that correlate the request with the observed state change.

The baseline is not a new system state and does not require a new terminal result. It also does not always require performing a new state-changing operation. The agent must prefer, in order:

1. an existing normal request and its already observable before/after state;
2. a reversible, minimal action on an authorized test object;
3. no mutation when the action cannot be performed safely or its state cannot be observed.

For example, a refund baseline may reuse an existing authorized test-order refund and confirm that the order's cumulative refunded amount and refund record changed by the accepted amount. The agent must not create a real refund merely to satisfy the baseline procedure when authorization, reversibility, or authoritative state observation is absent.

If the baseline fails, times out, cannot be correlated, or cannot be observed, the task follows the existing Explore `no_result` behavior. It must not become a negative security conclusion.

## Architecture

```text
Reason
  -> existing business_logic Coverage and Intent
  -> Dispatcher opt-in routing guard
  -> isolated Logic Explore worker
  -> fixed logic-explore Skill
       -> current Intent and graph facts
       -> bounded baseline and mutation workflow
       -> optional rg search of existing offline corpora
  -> existing Explore output validation
  -> existing Fact/Evidence path
  -> existing Verify handoff for concrete candidates
```

There is no new protocol participant. "Logic Explore Agent" means a separately configured Explore worker with an isolated routing capability and a dedicated prompt/Skill, while it continues to use the existing Explore task lifecycle and output validator.

## Opt-in isolation

The feature is disabled by default. Existing configurations that omit the new settings retain current worker selection and prompt behavior byte-for-byte.

When enabled:

- a worker explicitly declares the `business_logic` Explore capability;
- only `business_logic` Intents may be assigned to that worker;
- general Explore workers may not claim `business_logic` Intents;
- non-business-logic Intents may not be assigned to the Logic Explore worker;
- Reason, Verify, Bootstrap, Android routing, and their workers are unchanged;
- if no compatible Logic Explore worker is available, the Intent remains unclaimed instead of falling back to a general Explore worker;
- startup validation rejects an enabled configuration with no compatible Logic Explore worker.

This keeps the rollout reversible: removing the opt-in configuration restores the pre-existing dispatch path.

## Fixed Skill

The agent receives exactly one fixed `logic-explore` Skill. The Skill is a concise operating procedure rather than a vulnerability encyclopedia.

It defines:

- current-Intent and assigned-Surface boundaries;
- authorization and impact checks;
- business-object, actor, action, state, and invariant identification;
- valid baseline construction;
- selection of the smallest relevant mutation;
- authoritative before/after state comparison;
- false-positive rejection;
- optional knowledge lookup rules;
- existing Evidence and Verify handoff requirements;
- existing Explore output and `no_result` behavior.

The first version covers these reasoning lenses within the one Skill:

- workflow integrity;
- actor/resource boundary;
- replay and idempotency;
- numeric invariants; and
- client-trusted business fields.

These are sections of one Skill, not separately loaded Skills. The agent selects only the lens relevant to the current Intent.

## Knowledge lookup

The Skill tells the agent when and where to search, but the agent continues to use its existing shell and `rg`. No new retrieval tool is added.

Search is optional. The agent skips it when the invariant, mutation, and validation method are already clear. It searches when it needs a comparable abuse pattern, an overlooked boundary, a validation method, or a false-positive explanation.

The Skill includes this source map:

| Need | Preferred corpus |
|---|---|
| Business-abuse model | `owasp-bla-top10` |
| Comparable real-world logic cases | `wooyun-legacy` |
| Agent-oriented testing procedure | `hack-skills` |
| Missed checks and boundary variants | `vulnerability-Checklist` |
| General penetration-testing methodology | `hacktricks` |
| Concrete payload or encoding variants | `PayloadsAllTheThings` |

Each lookup is bounded:

- search no more than two corpora initially;
- start with one query built from the current business object, action, and invariant;
- inspect no more than three directly relevant files per lookup round;
- read only the necessary matching context;
- stop when results do not materially change the current test hypothesis;
- never execute a historical technique without checking scope, authorization, impact, test data, and state-observation ability.

The executed `rg` command, matched paths, and any adopted method remain in the existing task execution log. No new `knowledge_refs` or `skill_used` Fact field is required.

## Test workflow

For one assigned Intent, the agent performs:

1. Read the graph facts, assigned Coverage, Surface, scope, and authorization constraints.
2. Identify one primary business object, actor, action, relevant state, and invariant.
3. Define the explicit violation predicate and authoritative state source.
4. Establish or reuse a valid baseline.
5. Optionally search the bounded offline corpora when it materially improves the hypothesis.
6. Select the smallest relevant mutation for the current Intent.
7. Confirm safety and reversibility immediately before mutation.
8. Execute the mutation once unless the current Intent explicitly requires bounded replay or concurrency and the authorization permits it.
9. Query authoritative post-operation state and persistent side effects.
10. Compare the observation with the invariant and baseline.
11. Return through the existing Explore contract.

The agent must not turn an HTTP status code, UI-only difference, request failure, tool failure, or knowledge-base example into proof of a business impact.

## Facts, Evidence, and terminal behavior

The design respects existing system facts and contracts:

- confirmed observations use the current Fact path;
- raw requests, responses, commands, state snapshots, and knowledge searches remain in existing task logs and Evidence artifacts;
- a concrete candidate uses the current Verify handoff;
- independent Verify remains responsible for reproduction;
- incomplete, unsafe, timed-out, failed, or unobservable execution follows current `no_result` handling;
- the Skill does not emit `candidate`, `inconclusive`, `not_applicable`, or `not_vulnerable` as new system states;
- the agent does not rewrite or contradict graph facts and does not create unassigned Coverage.

## Safety boundary

"Test account" means an identity explicitly authorized for the assessment whose state may be changed without affecting another user. "Test object" means an order, coupon, subscription, balance, tenant resource, or similar object created for or explicitly approved for testing.

The Skill prefers test accounts and test objects but does not assume they exist. Their absence does not authorize the agent to substitute production users or objects. If a necessary mutation cannot be performed safely, the agent preserves the existing system facts and returns through the existing incomplete/no-result path.

The first version does not automatically perform:

- real financial transfers or irreversible refunds;
- operations on objects not controlled or explicitly approved for testing;
- destructive inventory, account, tenant, or subscription changes;
- unbounded replay, fuzzing, or concurrency;
- actions outside the assigned Intent and Surface.

## Rollout and compatibility

The implementation is delivered behind an explicit configuration switch and a dedicated worker declaration. Tests must prove:

1. legacy configurations still parse and select workers as before;
2. disabled mode produces the existing Explore routing;
3. enabled mode routes only `business_logic` Intents to the Logic Explore worker;
4. enabled mode keeps other Explore Intents on general workers;
5. Reason, Verify, Android, CTF, and mock task behavior remains unchanged;
6. Logic Explore output passes the existing Explore validator without new terminal values;
7. unavailable or failed baseline execution cannot produce a negative security conclusion.

## Acceptance criteria

The first version is complete when an opt-in test configuration can run one `business_logic` Intent through the isolated Logic Explore worker with the fixed Skill, optionally search `/home/kali/knowledges/` using `rg`, and submit a result through the existing Explore/Fact/Evidence/Verify path, while all legacy configurations and non-business-logic routing tests remain unchanged.
