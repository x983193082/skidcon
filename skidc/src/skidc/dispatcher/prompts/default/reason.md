# Task
Read the Fact-Intent graph and make exactly one decision:

1. If the current Facts satisfy Goal, complete.
2. Otherwise, propose one smallest useful Intent.
3. Return empty data only when an existing Open Intent already covers the next work.

# Output
Return one raw JSON object and nothing else.

Complete:
{"accepted":true,"data":{"complete":{"from":["f001"],"description":"..."}}}

Explore Intent:
{"accepted":true,"data":{"intent":{"from":["f001"],"description":"Map the assigned area.","action_kind":"surface_mapping"}}}

Security-test Intent for one or more related Surfaces:
{"accepted":true,"data":{"intent":{"from":["f001"],"description":"Run one precise security check.","action_kind":"security_test","surface_refs":["s001"]}}}

Verify Intent for one suspected finding:
{"accepted":true,"data":{"intent":{"from":["f006"],"description":"Reproduce the suspected security impact in a fresh session.","action_kind":"verify","surface_refs":["s001"]}}}

No new work:
{"accepted":true,"data":{}}

# Rules
- Facts and concluded Intent edges are causal truth. Surface, Coverage, and Hypothesis rows are context only.
- Use only ids from Valid Facts in `from`.
- If Open Intents is empty, do not return empty data: complete or create one Intent.
- Create at most {max_intents} non-duplicate Intent. Never restate completed work with different wording.
- Reason plans only. Do not test the target and do not output attack paths or narrative chains.
- Every Intent must use exactly one action_kind: `surface_mapping`, `security_test`, or `verify`.
- A `security_test` Intent must name every assigned Surface in `surface_refs`. Related Surfaces may share one Intent only when the same precise method tests them.
- Use `verify` only for one concrete suspected security finding that needs independent reproduction.
- Only a `reproduced` Verification Fact is vulnerability evidence for `complete.from`. If no vulnerability was reproduced, `from` is empty.
- Surface records are indexes, not vulnerability evidence.
- `index_status=indexed` means only that the Behavior is present in the inventory; it never means tested.
- Every Behavior shown in `behaviors` is an open critical/high-priority frontier item. Do not complete while `behavior_coverage.open` is greater than zero.
- A Behavior closes only after a concluded `security_test` Fact explicitly records one of its assigned Surface ids in `tested_surface_refs`. Tested items leave the frontier and the next batch is shown automatically.
- Do not create one Intent per URL mechanically and do not combine unrelated security mechanisms.
- Stay within Scope constraints.

# Context
Phase: {current_phase}

Scope:
{scope_constraints}

Recon status:
{recon_status}

Graph:
{graph_yaml}

Valid Facts:
{fact_ids}

Open Intents:
{open_intents}
