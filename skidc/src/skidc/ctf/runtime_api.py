"""Opt-in execution protocol, with separate control/dispatcher/runtime roles."""
from fastapi import APIRouter, Depends

from .runtime_models import ClaimNext, ClaimTask, LeaseIdentity, StartRun, TaskResult


def register_runtime_routes(app, store, authorize):
    router = APIRouter(prefix="/api/ctf/v1")
    control = [Depends(authorize("control"))]
    dispatch = [Depends(authorize("dispatcher"))]
    runtime = [Depends(authorize("runtime"))]

    @router.post("/projects/{pid}/runs", status_code=201, dependencies=control)
    def start_run(pid: str, body: StartRun):
        return store.start(pid, body)

    @router.get("/projects/{pid}/runs/{rid}", dependencies=[Depends(authorize("control", "dispatcher"))])
    def get_run(pid: str, rid: str):
        return store.get_run(pid, rid)

    @router.post("/projects/{pid}/runs/{rid}/stop", dependencies=control)
    def stop(pid: str, rid: str):
        return store.stop(pid, rid)

    @router.post("/projects/{pid}/runs/{rid}/tasks/claim", dependencies=dispatch)
    def claim(pid: str, rid: str, body: ClaimTask):
        return store.claim(pid, rid, body)

    @router.post("/projects/{pid}/runs/{rid}/tasks/claim-next", dependencies=dispatch)
    def claim_next(pid: str, rid: str, body: ClaimNext):
        return store.claim_next(pid, rid, body.worker_instance_id)

    @router.post("/projects/{pid}/runs/{rid}/tasks/{tid}/heartbeat", dependencies=dispatch)
    def heartbeat(pid: str, rid: str, tid: str, body: LeaseIdentity):
        return store.heartbeat(pid, rid, tid, body.worker_instance_id, body.lease_token)

    @router.post("/projects/{pid}/runs/{rid}/tasks/{tid}/result", dependencies=dispatch)
    def submit(pid: str, rid: str, tid: str, body: TaskResult):
        return store.submit(pid, rid, tid, body)

    @router.get("/runtime/operations", dependencies=runtime)
    def operations():
        return store.pending_operations()

    @router.post("/runtime/operations/{operation_id}/confirm", dependencies=runtime)
    def confirm(operation_id: str):
        return store.confirm_cleanup(operation_id)

    @router.post("/runtime/reap-expired", dependencies=runtime)
    def reap_expired():
        return {"stopped_runs": store.reap_expired()}

    app.include_router(router)
