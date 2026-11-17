"""Explicitly constructed CTF API; never mounted into the legacy application."""
from contextlib import asynccontextmanager
from pathlib import Path
import secrets

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from .db import CtfDatabase, SCHEMA_VERSION
from .models import Board, CreateHint, CreateProject, Hint, Project
from .store import BoardStore, ProjectNotFound
from .runtime import RuntimeConflict, RuntimeStore


def create_app(database_path: Path, control_token: str, *, dispatcher_token: str | None = None, runtime_token: str | None = None) -> FastAPI:
    if (dispatcher_token is None) != (runtime_token is None):
        raise ValueError("Both dispatcher and runtime tokens are required for the runtime protocol")
    tokens = {"control": control_token}
    if dispatcher_token is not None:
        tokens.update(dispatcher=dispatcher_token, runtime=runtime_token)
    for token in tokens.values():
        if not 32 <= len(token) <= 512 or not all(33 <= ord(char) <= 126 for char in token):
            raise ValueError("CTF token must contain 32..512 printable ASCII characters without spaces")
    if len(set(tokens.values())) != len(tokens):
        raise ValueError("CTF role tokens must be different")
    expected_tokens = {role: token.encode("ascii") for role, token in tokens.items()}
    database = CtfDatabase(database_path)
    store = BoardStore(database)
    runtime_store = RuntimeStore(database)
    runtime_enabled = dispatcher_token is not None
    bearer = HTTPBearer(auto_error=False)

    def authorize(*allowed_roles):
        def check(credentials: HTTPAuthorizationCredentials | None = Depends(bearer)) -> None:
            if credentials is not None:
                provided = credentials.credentials.encode("utf-8")
                for role, expected in expected_tokens.items():
                    if secrets.compare_digest(provided, expected):
                        if role not in allowed_roles:
                            raise HTTPException(403, detail={"code": "role_forbidden"})
                        return
            raise HTTPException(401, detail={"code": "unauthorized"}, headers={"WWW-Authenticate": "Bearer"})
        return check

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        database.initialize()
        if runtime_enabled:
            runtime_store.reap_expired()
        yield

    app = FastAPI(title="Skidc CTF blackboard", version="1", lifespan=lifespan)

    @app.exception_handler(ProjectNotFound)
    async def not_found(request: Request, exc: ProjectNotFound):
        return JSONResponse(status_code=404, content={"detail": {"code": "project_not_found"}})

    @app.exception_handler(RuntimeConflict)
    async def conflict(request: Request, exc: RuntimeConflict):
        return JSONResponse(status_code=409, content={"detail": {"code": exc.code}})

    @app.get("/health")
    def health():
        return {"engine": "ctf", "schema_version": SCHEMA_VERSION, "execution_enabled": False,
                "runtime_protocol_enabled": runtime_enabled}

    router = APIRouter(prefix="/api/ctf/v1")

    @router.post("/projects", response_model=Board, status_code=201, dependencies=[Depends(authorize("control"))])
    def create_project(body: CreateProject):
        return store.create_project(body)

    @router.get("/projects", response_model=list[Project], dependencies=[Depends(authorize("control", "dispatcher"))])
    def list_projects(limit: int = Query(100, ge=1, le=100), offset: int = Query(0, ge=0)):
        return store.list_projects(limit, offset)

    @router.get("/projects/{project_id}/board", response_model=Board, dependencies=[Depends(authorize("control", "dispatcher"))])
    def get_board(project_id: str):
        return store.get_board(project_id)

    @router.post("/projects/{project_id}/hints", response_model=Hint, status_code=201, dependencies=[Depends(authorize("control"))])
    def add_hint(project_id: str, body: CreateHint):
        return store.add_hint(project_id, body)

    app.include_router(router)
    if runtime_enabled:
        from .runtime_api import register_runtime_routes
        register_runtime_routes(app, runtime_store, authorize)
    return app
