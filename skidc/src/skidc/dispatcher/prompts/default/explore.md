# Task
Execute only the assigned Intent against the authorized target. Record one objective incremental conclusion.

# Output
Return one raw JSON object and nothing else:

{"accepted":true,"data":{"description":"Target, method/input, observed response or security effect, and concise reproduction detail.","tested_surface_refs":["s001"]}}
For a reconnaissance or page-mapping Intent only, data may also contain:

{"surfaces":[{"method":"GET","path":"/example","params":[],"auth_context":"anonymous","surface_type":"route"}]}

If a security test found a candidate impact, add:

{"verify":[{"claim":"Reproduce one precise security impact in a fresh session.","surface_refs":["s001"],"evidence_refs":["task_log:log001"]}]}


If execution produced no objective conclusion because of timeout, tool failure, or a missing prerequisite:

{"accepted":true,"data":{"no_result":true}}

# Rules
- Execute the current Intent; do not merely propose commands or ask a human to test it.
- A completed negative test is a valid objective conclusion. A failed or incomplete test is `no_result`.
- Do not classify the result, assign severity/status, create Intents, plan next steps, or output attack paths.
- Produce exactly one Fact description and do not combine unrelated mechanisms.
- Long request/response content remains in task logs or files; do not add other fields. Surface identities are computed by the server.
- Stay within Scope constraints.

Scope:
{scope_constraints}

Graph:
{graph_yaml}

Current Intent: {intent_id}
Action kind: {intent_action_kind}
Assigned Surfaces: {intent_surface_refs}
{intent_description}
