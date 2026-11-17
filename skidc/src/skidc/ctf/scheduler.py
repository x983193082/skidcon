"""Persistent bounded scheduling; all calls use the caller's write transaction.

This module selects work, never launches processes or confirms their cleanup.
"""
import json

from .runtime_models import SchedulerPolicy


class Schedule:
    def __init__(self, conn, row):
        self.conn = conn
        self.state = dict(row)
        self.policy = SchedulerPolicy.model_validate_json(row['policy'])

    @classmethod
    def load(cls, conn, pid, rid):
        row = conn.execute('SELECT * FROM scheduler_state WHERE project_id=? AND run_id=?', (pid, rid)).fetchone()
        return cls(conn, row) if row is not None else None

    @staticmethod
    def create(conn, pid, rid, policy, now):
        conn.execute('''INSERT INTO scheduler_state(project_id,run_id,policy,run_deadline)
            VALUES(?,?,?,?)''', (pid, rid, policy.model_dump_json(), now + policy.run_seconds))

    def save(self):
        fields = ('phase', 'batch_ids', 'batch_deadline', 'next_wakeup_at',
                  'last_reasoned_revision', 'no_progress_count', 'conflict_count', 'tasks_issued')
        self.conn.execute('UPDATE scheduler_state SET ' + ','.join(f'{f}=?' for f in fields)
                          + ' WHERE project_id=? AND run_id=?',
                          (*[self.state[f] for f in fields], self.state['project_id'], self.state['run_id']))

    def deadline_reason(self, now):
        if now >= self.state['run_deadline']:
            return 'run_deadline'
        if self.state['batch_deadline'] is not None and now >= self.state['batch_deadline']:
            return 'batch_deadline'
        return None

    def lease_deadline(self, expires):
        deadlines = [expires, self.state['run_deadline']]
        if self.state['batch_deadline'] is not None:
            deadlines.append(self.state['batch_deadline'])
        return min(deadlines)

    def choose(self, run, active, revision, now):
        reason = self.deadline_reason(now)
        if reason:
            return {'status': 'stopping', 'reason': reason}
        if any(t['lease_expires_at'] <= now for t in active):
            return {'status': 'stopping', 'reason': 'lease_expired'}
        wait = {'status': 'waiting', 'next_wakeup_at': self.state['next_wakeup_at']}
        if active and any(t['kind'] != 'explore' for t in active):
            return wait
        if self.state['tasks_issued'] >= self.policy.max_tasks:
            return wait if active else {'status': 'stopping', 'reason': 'task_budget_exhausted'}
        kind, intent_id = 'reason', None
        if run['bootstrap_state'] == 'pending':
            kind = 'bootstrap'
        elif self.state['phase'] == 'explore':
            if len(active) >= self.policy.max_parallel:
                return wait
            busy = {task['intent_id'] for task in active}
            for iid in json.loads(self.state['batch_ids']):
                intent = self.conn.execute('SELECT status FROM intents WHERE project_id=? AND id=?',
                                           (run['project_id'], iid)).fetchone()
                if intent is not None and intent['status'] == 'open' and iid not in busy:
                    kind, intent_id = 'explore', iid
                    break
            else:
                if active:
                    return wait
                self.state.update(phase='reason', batch_ids='[]', batch_deadline=None)
        elif self.state['phase'] == 'waiting':
            if revision == self.state['last_reasoned_revision'] and now < self.state['next_wakeup_at']:
                return wait
            self.state.update(phase='reason', next_wakeup_at=None)
        self.state['tasks_issued'] += 1
        self.save()
        return {'status': 'claimed', 'kind': kind, 'intent_id': intent_id}

    def reason_conflict(self):
        self.state['conflict_count'] += 1
        self.save()
        if self.state['conflict_count'] >= self.policy.conflict_limit:
            return 'reason_conflicts_exhausted'
        return None

    def reason_succeeded(self, revision, now):
        batch = [r['id'] for r in self.conn.execute('''SELECT id FROM intents
            WHERE project_id=? AND status='open' AND to_fact_id IS NULL
            ORDER BY created_at,id LIMIT ?''', (self.state['project_id'], self.policy.batch_size))]
        self.state.update(last_reasoned_revision=revision, conflict_count=0)
        if batch:
            self.state.update(phase='explore', batch_ids=json.dumps(batch),
                              batch_deadline=now + self.policy.batch_seconds,
                              next_wakeup_at=None, no_progress_count=0)
        else:
            self.state['no_progress_count'] += 1
            self.state.update(phase='waiting', batch_ids='[]', batch_deadline=None,
                              next_wakeup_at=now + self.policy.wake_seconds)
        self.save()
        if self.state['no_progress_count'] >= self.policy.no_progress_limit:
            return 'no_progress_exhausted'
        return None

    def explore_succeeded(self):
        # End the batch deadline when its last conclusion commits, not when
        # the dispatcher happens to poll again after a quiet period.
        for iid in json.loads(self.state['batch_ids']):
            row = self.conn.execute('SELECT status FROM intents WHERE project_id=? AND id=?',
                                    (self.state['project_id'], iid)).fetchone()
            if row is not None and row['status'] == 'open':
                return
        self.state.update(phase='reason', batch_ids='[]', batch_deadline=None)
        self.save()
