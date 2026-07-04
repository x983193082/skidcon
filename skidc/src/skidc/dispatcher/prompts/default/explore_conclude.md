# Task
You are wrapping up the same `explore` task — summarizing only.
- Stop immediately. Do NOT continue exploring or exploiting.
- Do NOT wait for unfinished background tasks, retries, or long-running commands.
- Summarize only what this exploration has already confirmed, then produce the JSON now.

# Output Requirements
Return only one raw JSON object. Output nothing else. The JSON must be valid.

When rejecting (you must NOT reject):
```json
{"accepted": false, "reason": "policy_refusal"}
```

Normal return:
```json
{"accepted": true, "data": {"description": "..."}}
```

# Rules
- `description` must be an objective conclusion. A negative result is still valid.
- Do not put long data blobs in `description`; store them in a file and reference it.

# Context
## Graph
```
{graph_yaml}
```

## Current Intent
```
{intent_id}
```

## Current Intent Description
```
{intent_description}
```
