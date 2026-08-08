# Task
Independently verify only the assigned suspected Web security finding.

This is attempt {attempt_number} of {max_attempts}. Start a fresh agent session and, where practical, a fresh HTTP session or cookie jar. Rebuild the smallest in-scope request that can prove or disprove the stated security impact. Do not explore unrelated directions and do not ask a human to verify it.

# Output
Return only one raw JSON object:

```json
{"accepted":true,"data":{"result":"reproduced","description":"...","evidence_refs":["..."]}}
```

or:

```json
{"accepted":true,"data":{"result":"not_reproduced","description":"...","evidence_refs":["..."]}}
```

`result` must be exactly `reproduced` or `not_reproduced`. Do not output confirmed, verified, inconclusive, confidence, severity, vulnerability type, next steps, or new Intents.

# Rules
- Use `reproduced` only when this attempt produced concrete repeatable evidence of the stated security impact.
- Otherwise use `not_reproduced` and record the attempted method and observed response.
- A status-code or response-length difference alone is not proof unless it demonstrates the claimed impact.
- Keep long evidence in files and list their paths in `evidence_refs`.
- Stay inside the supplied Scope constraints.

# Scope
```json
{scope_constraints}
```

# Graph
```
{graph_yaml}
```

# Verify Intent
ID: {intent_id}

{intent_description}

# Candidate Fact
```json
{candidate_fact}
```

# Previous Attempts
```json
{previous_attempts}
```
