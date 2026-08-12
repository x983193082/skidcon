from __future__ import annotations

from datetime import datetime
import json
import zipfile

from click.testing import CliRunner
import pytest
from fastapi.testclient import TestClient

from skidc.android_mcp.adb import AdbController, CommandResult, parse_uiautomator_xml
from skidc.android_mcp.app import app, configure, state
from skidc.android_mcp.auth import BearerTokenAuth
from skidc.cli import main


@pytest.fixture(autouse=True)
def explicitly_disable_android_auth_for_tests():
    configure(token_file=None)
    yield
    configure(token_file=None)


def test_android_mcp_unconfigured_auth_fails_closed() -> None:
    state.auth = BearerTokenAuth()
    client = TestClient(app)

    response = client.get("/lab/profiles")

    assert response.status_code == 401


def test_android_mcp_requires_bearer_token_except_for_liveness(tmp_path, caplog) -> None:
    token = "bridge-secret-value"
    token_file = tmp_path / "android-mcp-token"
    token_file.write_text(f"{token}\n", encoding="utf-8")
    configure(token_file=token_file)
    client = TestClient(app)

    try:
        live = client.get("/health/live")
        missing = client.get("/lab/profiles")
        malformed = client.get(
            "/lab/profiles",
            headers={"Authorization": token},
        )
        incorrect = client.get(
            "/lab/profiles",
            headers={"Authorization": "Bearer wrong-secret"},
        )
        accepted = client.get(
            "/lab/profiles",
            headers={"Authorization": f"Bearer {token}"},
        )
    finally:
        configure(token_file=None)

    assert live.status_code == 200
    assert live.json() == {"ok": True}
    assert missing.status_code == 401
    assert missing.headers["www-authenticate"] == "Bearer"
    assert malformed.status_code == 401
    assert incorrect.status_code == 403
    assert accepted.status_code == 200
    assert token not in "".join(
        response.text for response in (live, missing, malformed, incorrect, accepted)
    )
    assert token not in caplog.text


def test_android_mcp_ready_requires_auth_and_reports_boot_state(tmp_path, monkeypatch) -> None:
    token_file = tmp_path / "android-mcp-token"
    token_file.write_text("ready-secret", encoding="utf-8")
    configure(token_file=token_file)
    monkeypatch.setattr(
        state.controller,
        "health",
        lambda: {"ok": True, "devices": [{"id": "emulator"}]},
    )
    monkeypatch.setattr(state.controller, "boot_completed", lambda: True)
    client = TestClient(app)
    headers = {"Authorization": "Bearer ready-secret"}

    try:
        missing = client.get("/health/ready")
        ready = client.get("/health/ready", headers=headers)
        monkeypatch.setattr(state.controller, "boot_completed", lambda: False)
        not_ready = client.get("/health/ready", headers=headers)
    finally:
        configure(token_file=None)

    assert missing.status_code == 401
    assert ready.status_code == 200
    assert ready.json()["ready"] is True
    assert ready.json()["boot_completed"] is True
    assert not_ready.status_code == 503
    assert not_ready.json()["ready"] is False
    assert not_ready.json()["boot_completed"] is False


def test_android_mcp_rejects_empty_token_file(tmp_path) -> None:
    token_file = tmp_path / "android-mcp-token"
    token_file.write_text(" \n", encoding="utf-8")

    with pytest.raises(ValueError, match="token file must not be empty"):
        configure(token_file=token_file)


def test_android_mcp_cli_requires_token_file() -> None:
    result = CliRunner().invoke(main, ["android-mcp"])

    assert result.exit_code == 2
    assert "Missing option '--token-file'" in result.output


@pytest.mark.parametrize(
    ("property_value", "expected"),
    [("1\n", True), ("0\n", False), ("", False)],
)
def test_adb_boot_completed_reads_android_system_property(
    property_value: str,
    expected: bool,
    monkeypatch,
) -> None:
    controller = AdbController()
    calls: list[tuple[str, ...]] = []

    def fake_adb_shell(*args: str, timeout: int | None = None) -> CommandResult:
        calls.append(args)
        return CommandResult(
            argv=["adb", *args],
            returncode=0,
            stdout=property_value,
            stderr="",
        )

    monkeypatch.setattr(controller, "_adb_shell", fake_adb_shell)

    assert controller.boot_completed() is expected
    assert calls == [("getprop", "sys.boot_completed")]


def test_assessment_history_store_bounds_namespaces_entries_and_total_bytes() -> None:
    from skidc.android_mcp.app import AssessmentHistoryStore

    store = AssessmentHistoryStore(max_assessments=2, max_items_per_assessment=2, max_total_bytes=500)
    store.append("assessment-a", {"value": "a"})
    store.append("assessment-b", {"value": "b"})
    store.append("assessment-c", {"value": "c"})
    store.append("assessment-c", {"value": "d"})
    store.append("assessment-c", {"value": "e"})

    assert store.list("assessment-a") == []
    assert store.list("assessment-b") == [{"value": "b"}]
    assert store.list("assessment-c") == [{"value": "d"}, {"value": "e"}]
    assert store.assessment_count == 2
    assert store.total_bytes <= 500
    with pytest.raises(ValueError, match="history byte limit"):
        store.append("assessment-c", {"value": "x" * 501})


def test_network_import_parses_jsonl_and_nested_proxy_events() -> None:
    from skidc.android_mcp.mobile_analysis import parse_network_import

    events = parse_network_import(
        """
{"request":{"method":"POST","url":"https://bank.test/api/login","headers":{"Accept":"application/json"}},"response":{"status_code":200}}
{"method":"GET","url":"https://bank.test/api/balance","status_code":200}
"""
    )

    events_without_timestamps = [
        {key: value for key, value in event.items() if key != "imported_at"}
        for event in events
    ]
    assert events_without_timestamps == [
        {
            "method": "POST",
            "url": "https://bank.test/api/login",
            "status_code": 200,
            "request_headers": {"Accept": "application/json"},
            "response_headers": {},
            "request_body_preview": None,
            "response_body_preview": None,
            "note": None,
        },
        {
            "method": "GET",
            "url": "https://bank.test/api/balance",
            "status_code": 200,
            "request_headers": {},
            "response_headers": {},
            "request_body_preview": None,
            "response_body_preview": None,
            "note": None,
        },
    ]
    assert all(datetime.fromisoformat(event["imported_at"]).tzinfo is not None for event in events)

    with pytest.raises(ValueError, match="index 1"):
        parse_network_import('[{"url":"https://bank.test/api/profile"},42]')


def test_apk_analysis_extracts_endpoints_paths_and_secret_indicators(tmp_path) -> None:
    from skidc.android_mcp.mobile_analysis import analyze_apk

    apk = tmp_path / "demo.apk"
    with zipfile.ZipFile(apk, "w") as archive:
        archive.writestr(
            "classes.dex",
            b"https://bank.test/api/login\x00/api/transfer\x00jwt_token\x00",
        )

    report = analyze_apk(apk)

    assert report["apk_path"] == str(apk)
    assert "https://bank.test/api/login" in report["endpoints"]
    assert "/api/transfer" in report["endpoint_paths"]
    assert any("jwt" in indicator.lower() for indicator in report["secret_indicators"])
    assert datetime.fromisoformat(report["analyzed_at"]).tzinfo is not None


def test_apk_analysis_rejects_archives_over_resource_budgets(tmp_path) -> None:
    from skidc.android_mcp.mobile_analysis import analyze_apk

    too_many = tmp_path / "too-many.apk"
    with zipfile.ZipFile(too_many, "w") as archive:
        for index in range(3):
            archive.writestr(f"entry-{index}.txt", b"value")

    high_ratio = tmp_path / "high-ratio.apk"
    with zipfile.ZipFile(high_ratio, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("classes.dex", b"0" * 100_000)

    over_total = tmp_path / "over-total.apk"
    with zipfile.ZipFile(over_total, "w") as archive:
        archive.writestr("classes.dex", b"a" * 700)
        archive.writestr("resources.arsc", b"b" * 700)

    long_match = tmp_path / "long-match.apk"
    with zipfile.ZipFile(long_match, "w") as archive:
        archive.writestr("classes.dex", b"https://bank.test/api/" + b"a" * 10_000)

    with pytest.raises(ValueError, match="entry limit"):
        analyze_apk(too_many, max_entries=2)
    with pytest.raises(ValueError, match="compression ratio"):
        analyze_apk(high_ratio, max_compression_ratio=10)
    with pytest.raises(ValueError, match="uncompressed byte budget"):
        analyze_apk(over_total, max_total_uncompressed_bytes=1_000)
    assert analyze_apk(long_match, max_match_bytes=128)["endpoints"] == []
    with pytest.raises(ValueError, match="report byte budget"):
        analyze_apk(long_match, max_report_bytes=100)


def test_mobile_analysis_describes_available_tools_labs_and_frida_templates() -> None:
    from skidc.android_mcp.mobile_analysis import frida_script_templates, lab_profiles, tool_status

    tools = tool_status()
    labs = lab_profiles()
    templates = frida_script_templates()

    assert set(tools) == {"adb", "aapt", "apktool", "jadx", "frida", "frida-ps", "mitmproxy"}
    assert all(isinstance(available, bool) for available in tools.values())
    assert [lab["id"] for lab in labs] == ["dvba", "bugbazaar"]
    assert [template["id"] for template in templates] == [
        "okhttp_request_observer",
        "retrofit_endpoint_observer",
        "ssl_pinning_observer",
        "token_source_observer",
    ]


def test_android_mcp_imports_normalized_network_events() -> None:
    client = TestClient(app)
    client.delete("/network/history")

    imported = client.post(
        "/network/import",
        json={
            "source": "mitmproxy",
            "content": (
                '{"events":[{"method":"GET",'
                '"url":"https://bank.test/api/profile","status_code":200}]}'
            ),
        },
    )

    assert imported.status_code == 200
    import_result = imported.json()
    assert import_result["stored"] == 1
    assert import_result["total"] == 1
    assert import_result["source"] == "mitmproxy"
    assert len(import_result["event_ids"]) == 1
    events = client.get("/network/history").json()["events"]
    assert len(events) == 1
    assert events[0]["url"] == "https://bank.test/api/profile"
    assert events[0]["source"] == "mitmproxy"
    assert events[0]["event_id"] == import_result["event_ids"][0]
    assert datetime.fromisoformat(events[0]["imported_at"]).tzinfo is not None


def test_android_mcp_redacts_and_bounds_imported_network_evidence() -> None:
    client = TestClient(app)
    client.delete("/network/history")

    imported = client.post(
        "/network/import",
        json={
            "source": "mitmproxy",
            "content": json.dumps(
                {
                    "request": {
                        "method": "POST",
                        "url": "https://bank.test/api/login",
                        "headers": {
                            "Authorization": "Bearer secret",
                            "Cookie": "session=secret",
                            " X-API-Key ": "api-secret",
                        },
                        "body": "x" * 9_000,
                    },
                    "response": {
                        "status_code": 200,
                        "headers": {"Set-Cookie": "session=secret"},
                        "body": {
                            "password": "response-secret",
                            "nested": {"accessToken": "response-token"},
                        },
                    },
                }
            ),
        },
    )

    assert imported.status_code == 200
    event = client.get("/network/history").json()["events"][0]
    assert event["request_headers"] == {
        "Authorization": "[REDACTED]",
        "Cookie": "[REDACTED]",
        "X-API-Key": "[REDACTED]",
    }
    assert event["response_headers"] == {"Set-Cookie": "[REDACTED]"}
    assert len(event["request_body_preview"]) == 8_192
    assert json.loads(event["response_body_preview"]) == {
        "password": "[REDACTED]",
        "nested": {"accessToken": "[REDACTED]"},
    }


def test_android_mcp_rejects_oversized_or_excessive_network_imports() -> None:
    client = TestClient(app)

    oversized = client.post(
        "/network/import",
        json={"source": "manual", "content": "x" * 2_000_001},
    )
    excessive = client.post(
        "/network/import",
        json={
            "source": "manual",
            "content": json.dumps(
                [
                    {"method": "GET", "url": f"https://bank.test/api/items/{index}"}
                    for index in range(1_001)
                ]
            ),
        },
    )

    assert oversized.status_code == 422
    assert excessive.status_code == 400
    assert "at most 1000" in excessive.json()["detail"]


def test_android_mcp_rejects_oversized_network_fields_and_utf8_imports() -> None:
    client = TestClient(app)
    client.delete("/network/history")

    oversized_header = client.post(
        "/network/events",
        json={
            "url": "https://bank.test/api/profile",
            "request_headers": {"X-Debug": "x" * 8_193},
        },
    )
    oversized_event = client.post(
        "/network/import",
        json={
            "source": "manual",
            "content": json.dumps(
                {"url": "https://bank.test/api/profile", "note": "x" * 70_000}
            ),
        },
    )
    oversized_utf8 = client.post(
        "/network/import",
        json={
            "source": "manual",
            "content": json.dumps(
                {"url": "https://bank.test/api/profile", "note": "界" * 700_000},
                ensure_ascii=False,
            ),
        },
    )

    assert oversized_header.status_code == 422
    assert oversized_event.status_code == 400
    assert "at most 2000" in oversized_event.json()["detail"]
    assert oversized_utf8.status_code == 422


def test_android_mcp_keeps_network_history_bounded() -> None:
    client = TestClient(app)
    client.delete("/network/history")

    for start in (0, 600):
        imported = client.post(
            "/network/import",
            json={
                "source": "manual",
                "content": json.dumps(
                    [
                        {"method": "GET", "url": f"https://bank.test/api/items/{index}"}
                        for index in range(start, start + 600)
                    ]
                ),
            },
        )
        assert imported.status_code == 200
    history = client.get("/network/history", params={"limit": 1_000}).json()["events"]

    assert imported.json()["total"] == 1_000
    assert len(history) == 1_000
    assert history[0]["url"] == "https://bank.test/api/items/200"
    assert history[-1]["url"] == "https://bank.test/api/items/1199"


def test_android_mcp_network_event_ids_are_stable_and_never_reused() -> None:
    client = TestClient(app)
    client.delete("/network/history")

    first = client.post(
        "/network/events",
        json={"method": "GET", "url": "https://bank.test/api/first"},
    )
    client.delete("/network/history")
    second = client.post(
        "/network/events",
        json={"method": "GET", "url": "https://bank.test/api/second"},
    )
    history = client.get("/network/history").json()["events"]

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["event_id"] != second.json()["event_id"]
    assert history[0]["event_id"] == second.json()["event_id"]


def test_android_mcp_analyzes_apk_and_retains_reverse_report(tmp_path, monkeypatch) -> None:
    client = TestClient(app)
    monkeypatch.setattr(state, "artifact_root", tmp_path)
    apk = tmp_path / "lab.apk"
    with zipfile.ZipFile(apk, "w") as archive:
        archive.writestr("classes.dex", b"https://bank.test/api/transactions")

    cleared = client.delete("/reverse/reports", params={"assessment_id": "assessment-a"})
    analyzed = client.post(
        "/reverse/analyze",
        json={"assessment_id": "assessment-a", "apk_path": str(apk)},
    )
    reports = client.get("/reverse/reports", params={"assessment_id": "assessment-a"})

    assert cleared.status_code == 200
    assert analyzed.status_code == 200
    assert "https://bank.test/api/transactions" in analyzed.json()["endpoints"]
    assert reports.status_code == 200
    assert reports.json()["reports"][0]["apk_path"] == str(apk)


def test_android_mcp_reverse_analysis_stays_inside_artifact_root(tmp_path, monkeypatch) -> None:
    client = TestClient(app)
    artifact_root = tmp_path / "artifacts"
    artifact_root.mkdir()
    monkeypatch.setattr(state, "artifact_root", artifact_root)
    outside_apk = tmp_path / "outside.apk"
    with zipfile.ZipFile(outside_apk, "w") as archive:
        archive.writestr("classes.dex", b"https://outside.test/api")

    missing_assessment = client.post("/reverse/analyze", json={"apk_path": str(outside_apk)})
    outside = client.post(
        "/reverse/analyze",
        json={"assessment_id": "assessment-a", "apk_path": str(outside_apk)},
    )
    unc = client.post(
        "/reverse/analyze",
        json={"assessment_id": "assessment-a", "apk_path": r"\\server\share\remote.apk"},
    )

    assert missing_assessment.status_code == 422
    assert outside.status_code == 400
    assert "artifact root" in outside.json()["detail"]
    assert unc.status_code == 400
    assert "UNC" in unc.json()["detail"]


def test_android_mcp_limits_concurrent_reverse_analysis(tmp_path, monkeypatch) -> None:
    client = TestClient(app)
    monkeypatch.setattr(state, "artifact_root", tmp_path)
    apk = tmp_path / "lab.apk"
    with zipfile.ZipFile(apk, "w") as archive:
        archive.writestr("classes.dex", b"https://bank.test/api")

    assert state.reverse_analysis_slots.acquire(blocking=False)
    try:
        response = client.post(
            "/reverse/analyze",
            json={"assessment_id": "assessment-a", "apk_path": str(apk)},
        )
    finally:
        state.reverse_analysis_slots.release()

    assert response.status_code == 429
    assert "already running" in response.json()["detail"]


def test_android_mcp_isolates_and_bounds_reverse_reports(tmp_path, monkeypatch) -> None:
    client = TestClient(app)
    monkeypatch.setattr(state, "artifact_root", tmp_path)
    apk = tmp_path / "lab.apk"
    with zipfile.ZipFile(apk, "w") as archive:
        archive.writestr("classes.dex", b"https://bank.test/api")
    for assessment_id in ("assessment-a", "assessment-b"):
        client.delete("/reverse/reports", params={"assessment_id": assessment_id})

    first = client.post(
        "/reverse/analyze",
        json={"assessment_id": "assessment-a", "apk_path": str(apk)},
    )
    for _ in range(101):
        latest = client.post(
            "/reverse/analyze",
            json={"assessment_id": "assessment-b", "apk_path": str(apk)},
        )
        assert latest.status_code == 200

    reports_a = client.get(
        "/reverse/reports", params={"assessment_id": "assessment-a", "limit": 100}
    ).json()["reports"]
    reports_b = client.get(
        "/reverse/reports", params={"assessment_id": "assessment-b", "limit": 100}
    ).json()["reports"]
    cleared_b = client.delete("/reverse/reports", params={"assessment_id": "assessment-b"})
    remaining_a = client.get(
        "/reverse/reports", params={"assessment_id": "assessment-a", "limit": 100}
    ).json()["reports"]

    assert first.status_code == 200
    assert len(reports_a) == 1
    assert len(reports_b) == 100
    assert cleared_b.json()["removed"] == 100
    assert len(remaining_a) == 1


def test_android_mcp_exposes_mobile_tool_status(monkeypatch) -> None:
    monkeypatch.setattr(state.controller, "health", lambda: {"ok": True, "devices": []})
    client = TestClient(app)

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json()["ok"] is True
    assert set(response.json()["mobile_tools"]) == {
        "adb",
        "aapt",
        "apktool",
        "jadx",
        "frida",
        "frida-ps",
        "mitmproxy",
    }


def test_android_mcp_exposes_frida_template_and_lab_catalogs() -> None:
    client = TestClient(app)

    scripts = client.get("/frida/scripts")
    labs = client.get("/lab/profiles")

    assert scripts.status_code == 200
    assert scripts.json()["templates"][0]["id"] == "okhttp_request_observer"
    assert set(scripts.json()["tools"]) == {
        "adb",
        "aapt",
        "apktool",
        "jadx",
        "frida",
        "frida-ps",
        "mitmproxy",
    }
    assert labs.status_code == 200
    assert [profile["id"] for profile in labs.json()["profiles"]] == ["dvba", "bugbazaar"]


def test_adb_proxy_control_uses_android_global_http_proxy(monkeypatch) -> None:
    controller = AdbController(device_id="emulator-5554")
    calls: list[tuple[str, ...]] = []

    def fake_adb_shell(*args: str, timeout: int | None = None) -> CommandResult:
        calls.append(args)
        return CommandResult(argv=list(args), returncode=0, stdout="", stderr="")

    monkeypatch.setattr(controller, "_adb_shell", fake_adb_shell)

    assert controller.set_http_proxy("127.0.0.1", 8080) == {
        "status": "proxy_set",
        "host": "127.0.0.1",
        "port": 8080,
    }
    assert controller.clear_http_proxy() == {"status": "proxy_cleared"}
    assert calls == [
        ("settings", "put", "global", "http_proxy", "127.0.0.1:8080"),
        ("settings", "put", "global", "http_proxy", ":0"),
        ("settings", "delete", "global", "http_proxy"),
    ]


def test_adb_proxy_control_brackets_ipv6_hosts(monkeypatch) -> None:
    controller = AdbController()
    calls: list[tuple[str, ...]] = []

    def fake_adb_shell(*args: str, timeout: int | None = None) -> CommandResult:
        calls.append(args)
        return CommandResult(argv=list(args), returncode=0, stdout="", stderr="")

    monkeypatch.setattr(controller, "_adb_shell", fake_adb_shell)

    controller.set_http_proxy("2001:db8::1", 8080)

    assert calls == [("settings", "put", "global", "http_proxy", "[2001:db8::1]:8080")]


def test_android_mcp_exposes_validated_proxy_control(monkeypatch) -> None:
    calls: list[tuple[str, str, int] | tuple[str]] = []
    monkeypatch.setattr(
        state.controller,
        "set_http_proxy",
        lambda host, port: calls.append(("set", host, port)) or {"status": "proxy_set", "host": host, "port": port},
    )
    monkeypatch.setattr(
        state.controller,
        "clear_http_proxy",
        lambda: calls.append(("clear",)) or {"status": "proxy_cleared"},
    )
    client = TestClient(app)

    configured = client.post("/network/proxy/set", json={"host": "10.0.2.2", "port": 8080})
    normalized_hostname = client.post("/network/proxy/set", json={"host": "proxy.test.", "port": 8888})
    cleared = client.post("/network/proxy/clear")
    invalid_ports = [
        client.post("/network/proxy/set", json={"host": "10.0.2.2", "port": port})
        for port in (0, 65536)
    ]
    invalid_hosts = [
        client.post("/network/proxy/set", json={"host": host, "port": 8080})
        for host in (
            "   ",
            "10.0.2.2:8888",
            "http://proxy.test",
            "proxy.test/path",
            "proxy.test..",
            "999.999.999.999",
            "[proxy.test]",
        )
    ]

    assert configured.status_code == 200
    assert configured.json() == {"status": "proxy_set", "host": "10.0.2.2", "port": 8080}
    assert normalized_hostname.status_code == 200
    assert normalized_hostname.json() == {"status": "proxy_set", "host": "proxy.test", "port": 8888}
    assert cleared.status_code == 200
    assert cleared.json() == {"status": "proxy_cleared"}
    assert all(response.status_code == 422 for response in invalid_ports)
    assert all(response.status_code == 422 for response in invalid_hosts)
    assert calls == [("set", "10.0.2.2", 8080), ("set", "proxy.test", 8888), ("clear",)]


def test_android_mcp_isolates_external_frida_observations_by_assessment() -> None:
    client = TestClient(app)

    client.delete("/frida/observations", params={"assessment_id": "assessment-a"})
    client.delete("/frida/observations", params={"assessment_id": "assessment-b"})
    recorded_a = client.post(
        "/frida/observations",
        json={
            "assessment_id": "assessment-a",
            "package": "com.demo.bank",
            "script_id": "okhttp_request_observer",
            "event_type": "http_request",
            "summary": "Observed an authorized profile request",
            "details": {
                "url": "https://bank.test/api/profile",
                "request": {
                    "Authorization": "Bearer secret",
                    "X-Access-Token": "access-secret",
                    "password": "password-secret",
                    "accessToken": "camel-token",
                    "apiKey": "camel-key",
                },
            },
        },
    )
    recorded_b = client.post(
        "/frida/observations",
        json={
            "assessment_id": "assessment-b",
            "package": "com.demo.bank",
            "event_type": "activity",
            "summary": "Observed the authorized account activity",
        },
    )
    history_a = client.get("/frida/observations", params={"assessment_id": "assessment-a"})
    cleared_a = client.delete("/frida/observations", params={"assessment_id": "assessment-a"})
    remaining_a = client.get("/frida/observations", params={"assessment_id": "assessment-a"})
    remaining_b = client.get("/frida/observations", params={"assessment_id": "assessment-b"})

    assert recorded_a.status_code == 200
    assert recorded_b.status_code == 200
    assert history_a.status_code == 200
    observation = history_a.json()["observations"][0]
    assert observation["assessment_id"] == "assessment-a"
    assert observation["package"] == "com.demo.bank"
    assert observation["script_id"] == "okhttp_request_observer"
    assert observation["event_type"] == "http_request"
    assert observation["details"] == {
        "url": "https://bank.test/api/profile",
        "request": {
            "Authorization": "[REDACTED]",
            "X-Access-Token": "[REDACTED]",
            "password": "[REDACTED]",
            "accessToken": "[REDACTED]",
            "apiKey": "[REDACTED]",
        },
    }
    assert datetime.fromisoformat(observation["recorded_at"]).tzinfo is not None
    assert cleared_a.json()["removed"] == 1
    assert remaining_a.json() == {"observations": []}
    assert len(remaining_b.json()["observations"]) == 1
    client.delete("/frida/observations", params={"assessment_id": "assessment-b"})


def test_android_mcp_bounds_frida_observation_payload_and_history() -> None:
    client = TestClient(app)
    assessment_id = "bounded-assessment"
    stable_assessment_id = "stable-assessment"
    client.delete("/frida/observations", params={"assessment_id": assessment_id})
    client.delete("/frida/observations", params={"assessment_id": stable_assessment_id})
    stable = client.post(
        "/frida/observations",
        json={
            "assessment_id": stable_assessment_id,
            "package": "com.demo.bank",
            "event_type": "activity",
            "summary": "Stable observation",
        },
    )

    oversized = client.post(
        "/frida/observations",
        json={
            "assessment_id": assessment_id,
            "package": "com.demo.bank",
            "event_type": "runtime_value",
            "summary": "Oversized observation",
            "details": {"value": "x" * 70_000},
        },
    )
    for sequence in range(1_001):
        response = client.post(
            "/frida/observations",
            json={
                "assessment_id": assessment_id,
                "package": "com.demo.bank",
                "event_type": "runtime_value",
                "summary": f"Observation {sequence}",
                "details": {"sequence": sequence},
            },
        )
        assert response.status_code == 200
    history = client.get("/frida/observations", params={"assessment_id": assessment_id, "limit": 1_000})
    stable_history = client.get(
        "/frida/observations",
        params={"assessment_id": stable_assessment_id, "limit": 1_000},
    )

    assert stable.status_code == 200
    assert oversized.status_code == 422
    observations = history.json()["observations"]
    assert len(observations) == 1_000
    assert observations[0]["details"] == {"sequence": 1}
    assert observations[-1]["details"] == {"sequence": 1_000}
    assert len(stable_history.json()["observations"]) == 1
    client.delete("/frida/observations", params={"assessment_id": assessment_id})
    client.delete("/frida/observations", params={"assessment_id": stable_assessment_id})


def test_parse_uiautomator_xml_extracts_useful_nodes() -> None:
    xml = """<?xml version='1.0' encoding='UTF-8' standalone='yes' ?>
    <hierarchy rotation="0">
      <node text="" resource-id="" class="android.widget.FrameLayout" package="p" clickable="false" enabled="true" bounds="[0,0][100,100]">
        <node text="登录" resource-id="com.demo:id/login" class="android.widget.Button" package="p" clickable="true" enabled="true" bounds="[10,20][80,60]" />
        <node text="" content-desc="更多" resource-id="" class="android.widget.ImageButton" package="p" clickable="true" enabled="true" bounds="[80,20][100,60]" />
      </node>
    </hierarchy>
    """

    nodes = parse_uiautomator_xml(xml)

    assert nodes == [
        {
            "text": "登录",
            "resource_id": "com.demo:id/login",
            "content_desc": "",
            "class": "android.widget.Button",
            "package": "p",
            "clickable": True,
            "enabled": True,
            "bounds": "[10,20][80,60]",
        },
        {
            "text": "",
            "resource_id": "",
            "content_desc": "更多",
            "class": "android.widget.ImageButton",
            "package": "p",
            "clickable": True,
            "enabled": True,
            "bounds": "[80,20][100,60]",
        },
    ]


def test_parse_uiautomator_xml_returns_empty_on_invalid_xml() -> None:
    assert parse_uiautomator_xml("<bad") == []

