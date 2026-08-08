Conclude Verify Intent {intent_id} using only the already collected evidence for this candidate Fact:

```json
{candidate_fact}
```

Return one raw JSON object with `accepted: true`, a `data.result` of exactly `reproduced` or `not_reproduced`, and an objective `data.description`.

Do not run new commands, create tasks, or output any other status.
