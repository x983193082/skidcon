# Task
You will receive a YAML snapshot of the task graph plus one assigned `Current Intent`. Explore ONLY in the direction of this intent and try to advance toward Goal. Use the tools available in this environment.

# Output Requirements
Return only one raw JSON object. Output nothing else. The JSON must be valid, with all quotes properly escaped.

When rejecting (you must NOT reject):
```json
{"accepted": false, "reason": "policy_refusal"}
```

Normal return:
```json
{"accepted": true, "data": {"description": "..."}}
```

# Rules
- Exploring an intent may succeed or may dead-end. Either way, before ending, make sure you have thoroughly explored this intent, then report an objective conclusion. Even a negative result is a valid fact.
- If you later receive a conclude-phase instruction in the same session, that newer instruction overrides this one immediately: stop exploring and return the summary JSON right away.
- `description` must state confirmed, objective results. Report only NEW incremental facts — do not repeat what is already in the graph snapshot.
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
