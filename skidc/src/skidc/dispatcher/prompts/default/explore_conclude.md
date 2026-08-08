# Task
Stop execution and summarize only the objective result already observed for the assigned Intent.

# Output
Return one raw JSON object and nothing else:

{"accepted":true,"data":{"description":"Target, method/input, observed response or security effect, and concise reproduction detail.","tested_surface_refs":["s001"]}}
For a reconnaissance or page-mapping Intent only, data may also contain:

{"surfaces":[{"method":"GET","path":"/example","params":[],"auth_context":"anonymous","surface_type":"route"}]}

If a completed security test found a candidate impact, add:

{"verify":[{"claim":"Reproduce one precise security impact in a fresh session.","surface_refs":["s001"],"evidence_refs":["task_log:log001"]}]}


If no objective result was obtained:

{"accepted":true,"data":{"no_result":true}}

# Rules
- Do not run commands, wait, retry, continue testing, or plan more work.
- Do not classify the result, assign severity/status, create Intents, or output other fields. Surface identities are computed by the server.
- A negative conclusion is valid only when the relevant test already completed.

Scope:
{scope_constraints}

Graph:
{graph_yaml}

Current Intent: {intent_id}
Action kind: {intent_action_kind}
Assigned Surfaces: {intent_surface_refs}
{intent_description}
