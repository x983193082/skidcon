"""Cairn task outputs, isolated from transport identity and legacy Web code."""
import json

from .models import Board, Contract, Text
from .runtime_models import IntentProposal, TaskResult


class WorkerRejected(ValueError):
    pass


class NeedsConclusion(ValueError):
    """Keep the execution session and request its partial observations."""


class Observation(Contract):
    description: Text


def _object(value, allowed, required=()):
    if not isinstance(value, dict) or set(value) - set(allowed) or not set(required) <= set(value):
        raise ValueError('Unexpected Cairn output fields')
    return value


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('Duplicate JSON key')
        result[key] = value
    return result


def _data(payload):
    if isinstance(payload, str):
        payload = json.loads(payload, object_pairs_hook=_unique_object)
    if not isinstance(payload, dict):
        raise ValueError('Expected one JSON object')
    if 'accepted' not in payload:
        return payload, False
    _object(payload, ('accepted', 'data', 'reason'), ('accepted',))
    if type(payload['accepted']) is not bool:
        raise ValueError('accepted must be a JSON boolean')
    if not payload['accepted']:
        if payload.get('data') is not None:
            raise ValueError('Rejected output cannot contain actions')
        message = Observation(description=payload.get('reason', 'Worker rejected task')).description
        raise WorkerRejected(message)
    if 'reason' in payload or not isinstance(payload.get('data'), dict):
        raise ValueError('Accepted output requires data')
    return payload['data'], True


def _decision(value, board):
    proposal = IntentProposal.model_validate(value)
    known = {fact.id for fact in board.facts if fact.validity == 'active' and fact.id != 'goal'}
    if len(set(proposal.from_)) != len(proposal.from_) or not set(proposal.from_) <= known:
        raise ValueError('Sources must be distinct active Facts, never goal')
    return proposal.model_dump(by_alias=True)


def parse_worker_result(kind, payload, *, board: Board, phase='execute', max_intents=16):
    if kind not in ('bootstrap', 'reason', 'explore') or phase not in ('execute', 'conclude'):
        raise ValueError('Unknown Cairn task or phase')
    if kind == 'reason' and phase != 'execute':
        raise ValueError('Reason has no conclude phase')
    if type(max_intents) is not int or not 1 <= max_intents <= 16:
        raise ValueError('max_intents must be in 1..16')
    data, wrapped = _data(payload)
    if kind == 'reason':
        _object(data, ('intents', 'intent', 'complete'))
        if len(data) > 1 or (not wrapped and not data):
            raise ValueError('Reason must choose one action')
        if 'complete' in data:
            return {'complete': _decision(data['complete'], board)}
        intents = [data['intent']] if 'intent' in data else data.get('intents', [])
        if not isinstance(intents, list):
            raise ValueError('intents must be a list')
        if not intents:
            if not any(i.status == 'open' and i.to_fact_id is None for i in board.intents):
                raise ValueError('Cairn no-op requires an open Intent')
            return {'no_op': True}
        decisions = [_decision(item, board) for item in intents]
        return {'intents': decisions[:max_intents]}
    if kind == 'explore':
        return {'description': Observation.model_validate(data).description}
    if phase == 'conclude':
        # Cairn's fallback records a Fact only, even if a model adds Complete.
        _object(data, ('fact', 'complete'), ('fact',))
        if 'complete' in data:
            Observation.model_validate(data['complete'])
        return {'description': Observation.model_validate(data['fact']).description}
    if data == {'no_result': True} and type(data['no_result']) is bool:
        raise NeedsConclusion('Bootstrap needs partial-observation conclusion')
    _object(data, ('fact', 'complete'), ('fact', 'complete'))
    return {'bootstrap_complete': {
        'fact_description': Observation.model_validate(data['fact']).description,
        'complete_description': Observation.model_validate(data['complete']).description,
    }}


def build_task_result(grant, output, board: Board, *, phase='execute', max_intents=16):
    if grant['base_revision'] != board.revision or grant['run_id'] != board.project.current_run_id:
        raise ValueError('Task and snapshot identity differ')
    business = parse_worker_result(grant['kind'], output, board=board, phase=phase, max_intents=max_intents)
    return TaskResult(worker_instance_id=grant['worker_instance_id'], lease_token=grant['lease_token'],
                      idempotency_key=f"result:{grant['id']}", **business)
