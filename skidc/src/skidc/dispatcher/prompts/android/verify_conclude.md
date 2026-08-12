Conclude Android Verify Intent {intent_id} using only the evidence already collected for this candidate Fact:

```json
{candidate_fact}
```

Return one raw JSON object with `accepted: true`, a `data.result` of exactly `reproduced` or `not_reproduced`, an objective `data.description`, and any existing `data.evidence_refs`.

Do not run new commands, operate the device, create tasks, or output any other status.
