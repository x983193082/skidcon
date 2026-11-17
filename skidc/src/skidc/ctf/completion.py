"""Cairn-style, model-reasoned Goal completion and fact dependency validation.

This validates recorded evidence relationships, not the truth of model text.
"""
import json
from uuid import uuid4


class InvalidEvidence(ValueError):
    pass


def validate_evidence(conn, pid, rid, sources):
    if not sources or len(sources) != len(set(sources)) or 'goal' in sources:
        raise InvalidEvidence('invalid_evidence')
    target = conn.execute('SELECT target_instance_id FROM runs WHERE project_id=? AND id=?', (pid, rid)).fetchone()[0]
    visiting, checked = set(), set()
    stack = [(fid, False) for fid in sources]
    while stack:
        fid, leaving = stack.pop()
        if leaving:
            visiting.remove(fid)
            checked.add(fid)
            continue
        if fid in checked:
            continue
        if fid in visiting or fid == 'goal':
            raise InvalidEvidence('invalid_evidence')
        fact = conn.execute('SELECT * FROM facts WHERE project_id=? AND id=?', (pid, fid)).fetchone()
        if fact is None or fact['validity'] != 'active':
            raise InvalidEvidence('invalid_evidence')
        # Artifact storage/verification is not implemented yet. Do not bless
        # arbitrary references as verified evidence merely because they exist.
        try:
            if json.loads(fact['evidence_refs']) != []:
                raise InvalidEvidence('invalid_evidence')
        except (TypeError, ValueError) as exc:
            raise InvalidEvidence('invalid_evidence') from exc
        if fact['created_run_id'] is not None:
            source_run = conn.execute('SELECT target_instance_id FROM runs WHERE project_id=? AND id=?',
                                      (pid, fact['created_run_id'])).fetchone()
            if source_run is None or source_run[0] != target:
                raise InvalidEvidence('invalid_evidence')
        elif fid != 'origin':
            raise InvalidEvidence('invalid_evidence')
        parents = []
        if fact['source_intent_id'] is not None:
            intent = conn.execute('SELECT * FROM intents WHERE project_id=? AND id=?',
                                  (pid, fact['source_intent_id'])).fetchone()
            if intent is None or intent['status'] != 'concluded' or intent['to_fact_id'] != fid:
                raise InvalidEvidence('invalid_evidence')
            parents = [r[0] for r in conn.execute('SELECT fact_id FROM intent_sources WHERE project_id=? AND intent_id=?',
                                                 (pid, intent['id']))]
            if not parents:
                raise InvalidEvidence('invalid_evidence')
        visiting.add(fid)
        stack.append((fid, True))
        stack.extend((parent, False) for parent in parents)


def record_completion(conn, pid, rid, tid, sources, description, revision, now):
    validate_evidence(conn, pid, rid, sources)
    cid = str(uuid4())
    conn.execute('''INSERT INTO completions(project_id,id,run_id,task_id,description,method,revision,goal_version,created_at)
        VALUES(?,?,?,?,?,'model_reasoned',?,1,?)''', (pid, cid, rid, tid, description, revision, now))
    conn.executemany('INSERT INTO completion_sources VALUES(?,?)', [(pid, fid) for fid in sources])
    conn.execute("UPDATE intents SET status='cancelled' WHERE project_id=? AND status='open'", (pid,))
    return cid
