import ast
from pathlib import Path
import sqlite3
import subprocess
import sys

from click.testing import CliRunner
from fastapi.testclient import TestClient
import pytest

TOKEN = "test-only-ctf-control-token-0123456789"
PREFIX = "/api/ctf/v1"
BODY = {"title": "CTF", "origin": "challenge.local", "goal": "Find flag", "bootstrap_enabled": False}


@pytest.fixture
def ctf_client(tmp_path):
    from skidc.ctf.app import create_app

    with TestClient(create_app(tmp_path / "ctf.db", TOKEN), headers={"Authorization": f"Bearer {TOKEN}"}) as client:
        yield client


def test_new_api_creates_only_ctf_drafts_and_persists_hints(ctf_client):
    health = ctf_client.get("/health").json()
    assert health == {"engine": "ctf", "schema_version": 4, "execution_enabled": False, "runtime_protocol_enabled": False}
    created = ctf_client.post(f"{PREFIX}/projects", json=BODY)
    assert created.status_code == 201
    board = created.json()
    pid = board["project"]["id"]
    assert board["project"]["mode"] == "ctf"
    assert board["project"]["status"] == "draft"
    assert board["project"]["bootstrap_enabled"] is False
    assert set(board) == {"project", "revision", "facts", "intents", "hints", "completion"}
    assert board['completion'] is None
    assert {f["id"] for f in board["facts"]} == {"origin", "goal"}
    hint = ctf_client.post(f"{PREFIX}/projects/{pid}/hints", json={"content": "Inspect Coverage endpoint wording"})
    assert hint.status_code == 201  # Text containing Web terminology is legitimate data.
    after = ctf_client.get(f"{PREFIX}/projects/{pid}/board").json()
    assert after["revision"] == 2
    assert after["hints"] == [hint.json()]
    assert ctf_client.get(f"{PREFIX}/projects").json() == [board["project"]]


@pytest.mark.parametrize("auth", [None, "Bearer wrong-token", "Basic anything"])
def test_all_blackboard_routes_require_control_identity(ctf_client, auth):
    pid = ctf_client.post(f"{PREFIX}/projects", json=BODY).json()["project"]["id"]
    before = ctf_client.get(f"{PREFIX}/projects/{pid}/board").json()
    headers = {} if auth is None else {"Authorization": auth}
    with TestClient(ctf_client.app, headers=headers) as anonymous:
        for method, path, body in [
            ("GET", "/projects", None), ("POST", "/projects", BODY),
            ("GET", f"/projects/{pid}/board", None),
            ("POST", f"/projects/{pid}/hints", {"content": "injected"}),
        ]:
            response = anonymous.request(method, PREFIX + path, json=body)
            assert response.status_code == 401
            assert response.headers["www-authenticate"] == "Bearer"
        assert anonymous.get("/health").status_code == 200
    assert ctf_client.get(f"{PREFIX}/projects/{pid}/board").json() == before
    assert len(ctf_client.get(f"{PREFIX}/projects").json()) == 1


@pytest.mark.parametrize("extra", [
    {"mode": "real_website"}, {"mode": None}, {"recon_profile": {}},
    {"phase": "explore"}, {"coverage_refs": []}, {"bootstrap_enabled": "false"},
    {"origin": "  "}, {"title": ""}, {"goal": 123},
])
def test_invalid_project_requests_are_atomic(ctf_client, extra):
    response = ctf_client.post(f"{PREFIX}/projects", json={**BODY, **extra})
    assert response.status_code == 422
    assert ctf_client.get(f"{PREFIX}/projects").json() == []


def test_hint_fields_and_missing_projects_are_rejected(ctf_client):
    board = ctf_client.post(f"{PREFIX}/projects", json={**BODY, "mode": "ctf"}).json()
    pid = board["project"]["id"]
    for body in ({"content": "  "}, {"content": "hint", "severity": "critical"}):
        assert ctf_client.post(f"{PREFIX}/projects/{pid}/hints", json=body).status_code == 422
    assert ctf_client.get(f"{PREFIX}/projects/{pid}/board").json() == board
    assert ctf_client.get(f"{PREFIX}/projects/missing/board").status_code == 404
    assert ctf_client.post(f"{PREFIX}/projects/missing/hints", json={"content": "hint"}).status_code == 404
    assert ctf_client.get(f"{PREFIX}/projects?limit=101").status_code == 422
    assert ctf_client.get(f"{PREFIX}/projects?offset=-1").status_code == 422


def test_no_legacy_web_or_unfenced_execution_routes(ctf_client):
    pid = ctf_client.post(f"{PREFIX}/projects", json=BODY).json()["project"]["id"]
    for path in ("/projects", "/api/web/v1/projects", f"{PREFIX}/projects/{pid}/coverage"):
        assert ctf_client.get(path).status_code == 404
    for suffix in ("runs", "facts", "intents", "complete", "tasks/claim"):
        assert ctf_client.post(f"{PREFIX}/projects/{pid}/{suffix}", json={}).status_code == 404


def test_two_ctf_apps_and_legacy_server_keep_their_own_databases(tmp_path, http_client, monkeypatch):
    from skidc.ctf.app import create_app
    from skidc.ctf import store

    web = http_client.post("/projects", json={**BODY, "mode": "real_website"}).json()
    pid = web["project"]["id"]
    # Deliberately collide IDs, which normal UUID creation avoids.
    monkeypatch.setattr(store, "uuid4", lambda: pid)
    with TestClient(create_app(tmp_path / "one.db", TOKEN), headers={"Authorization": f"Bearer {TOKEN}"}) as first:
        a = first.post(f"{PREFIX}/projects", json={**BODY, "title": "first CTF"}).json()
        with TestClient(create_app(tmp_path / "two.db", TOKEN + "other"), headers={"Authorization": f"Bearer {TOKEN}other"}) as second:
            b = second.post(f"{PREFIX}/projects", json={**BODY, "title": "second CTF"}).json()
            assert a["project"]["id"] == b["project"]["id"] == pid
            assert first.get(f"{PREFIX}/projects/{pid}/board").json() == a
            assert second.get(f"{PREFIX}/projects/{pid}/board").json() == b
            assert second.get(f"{PREFIX}/projects", headers={"Authorization": f"Bearer {TOKEN}"}).status_code == 401
            legacy_after = http_client.get(f"/projects/{pid}").json()
            assert legacy_after["project"]["mode"] == "real_website"
            assert legacy_after["project"]["title"] == BODY["title"]
            assert http_client.get(f"{PREFIX}/projects").status_code == 404


def test_legacy_service_rejects_ctf_database_before_migration(tmp_path, monkeypatch):
    from skidc.ctf.db import CtfDatabase
    from skidc.server import db

    path = tmp_path / "ctf.db"
    CtfDatabase(path).initialize()
    before = path.read_bytes()
    monkeypatch.setattr(db, "_db_path", None)
    with pytest.raises(RuntimeError, match="database"):
        db.configure(path)
    assert db._db_path is None
    assert path.read_bytes() == before
    # Failure must not poison later configuration of a valid legacy database.
    db.configure(tmp_path / "legacy.db")
    with db.get_conn() as conn:
        assert conn.execute("SELECT count(*) FROM projects").fetchone()[0] == 0


def test_new_service_rejects_real_legacy_database_without_migration(tmp_path, http_client):
    from skidc.ctf.app import create_app
    from skidc.ctf.db import DatabaseCompatibilityError
    from skidc.server import db

    with db.get_conn() as conn:
        before = list(conn.iterdump())
    with pytest.raises(DatabaseCompatibilityError):
        with TestClient(create_app(db._db_path, TOKEN)):
            pass
    with db.get_conn() as conn:
        assert list(conn.iterdump()) == before


def test_independent_cli_requires_explicit_database_and_token(tmp_path, monkeypatch):
    from skidc.ctf.cli import main
    import uvicorn

    runner = CliRunner()
    assert runner.invoke(main, ["serve"]).exit_code == 2
    assert runner.invoke(main, ["serve", "--db-path", str(tmp_path / "ctf.db")]).exit_code == 2
    token_file = tmp_path / "token"
    token_file.write_text(TOKEN, encoding="utf-8")
    observed = {}

    def run(app, **kwargs):
        observed.update(kwargs)
        with TestClient(app, headers={"Authorization": f"Bearer {TOKEN}"}) as client:
            assert client.post(f"{PREFIX}/projects", json=BODY).status_code == 201

    monkeypatch.setattr(uvicorn, "run", run)
    result = runner.invoke(main, ["serve", "--db-path", str(tmp_path / "ctf.db"), "--token-file", str(token_file)])
    assert result.exit_code == 0, result.output
    assert observed["host"] == "127.0.0.1"
    assert observed["port"] == 8001
    assert TOKEN not in result.output
    token_file.write_text("", encoding="utf-8")
    result = runner.invoke(main, ["serve", "--db-path", str(tmp_path / "bad.db"), "--token-file", str(token_file)])
    assert result.exit_code != 0
    assert not (tmp_path / "bad.db").exists()


@pytest.mark.parametrize("token", ["", "short", "x" * 31, "x" * 32 + "\n", "令牌" * 32])
def test_app_requires_a_nonempty_explicit_control_token(tmp_path, token):
    from skidc.ctf.app import create_app

    with pytest.raises(ValueError, match="token"):
        create_app(tmp_path / "ctf.db", token)
    assert not (tmp_path / "ctf.db").exists()


def test_ctf_package_has_no_legacy_business_dependencies():
    from skidc import ctf

    root = Path(ctf.__file__).parent
    for source in root.glob("*.py"):
        for node in ast.walk(ast.parse(source.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or ""]
            else:
                continue
            assert not any(name.startswith(("skidc.server", "skidc.dispatcher", "skidc.cli")) for name in names), source
    result = subprocess.run([
        sys.executable, "-c",
        "import skidc.ctf.cli, sys; assert not any(n.startswith(('skidc.server', 'skidc.dispatcher')) for n in sys.modules)",
    ], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
