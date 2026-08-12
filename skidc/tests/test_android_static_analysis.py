from __future__ import annotations

import os
import sys
import zipfile
import json
from pathlib import Path

from skidc.android_mcp.static_tools import (
    ToolRun,
    parse_aapt,
    parse_decoded_manifest,
    run_tool,
    scan_jadx_output,
)
from skidc.android_mcp.mobile_analysis import analyze_apk


def test_run_tool_uses_private_environment_and_bounds_stdout(tmp_path) -> None:
    private_home = tmp_path / "home"
    private_home.mkdir()
    env = {**os.environ, "HOME": str(private_home), "STATIC_TEST_VALUE": "private"}

    result = run_tool(
        [
            sys.executable,
            "-c",
            "import os; print(os.environ['HOME']); print(os.environ['STATIC_TEST_VALUE'])",
        ],
        cwd=tmp_path,
        env=env,
        timeout=5,
        max_output_bytes=96,
    )

    assert result.status == "completed"
    assert str(private_home) in result.stdout
    assert "private" in result.stdout
    assert len(result.stdout.encode("utf-8")) <= 96
    assert result.reason is None


def test_run_tool_terminates_process_when_output_exceeds_budget(tmp_path) -> None:
    marker = tmp_path / "continued"

    result = run_tool(
        [
            sys.executable,
            "-c",
            "import pathlib,sys,time; sys.stdout.write('x'*4096); sys.stdout.flush(); time.sleep(1); pathlib.Path(sys.argv[1]).write_text('bad')",
            str(marker),
        ],
        cwd=tmp_path,
        env=dict(os.environ),
        timeout=5,
        max_output_bytes=128,
    )

    assert result.status == "failed"
    assert result.reason == "tool output exceeded byte budget"
    assert len(result.stdout.encode("utf-8")) <= 128
    assert not marker.exists()


def test_run_tool_maps_permission_error_to_isolated_failure(tmp_path, monkeypatch) -> None:
    def denied(*_args, **_kwargs):
        raise PermissionError("sensitive local path")

    monkeypatch.setattr("skidc.android_mcp.static_tools.subprocess.Popen", denied)

    result = run_tool(["jadx"], cwd=tmp_path, env=dict(os.environ))

    assert result.status == "failed"
    assert result.reason == "tool could not be started"
    assert "sensitive" not in repr(result)


def test_run_tool_maps_missing_failure_and_timeout_without_secret_stderr(tmp_path) -> None:
    missing = run_tool(
        ["definitely-not-a-real-skidc-tool"],
        cwd=tmp_path,
        env=dict(os.environ),
        timeout=1,
    )
    failed = run_tool(
        [sys.executable, "-c", "import sys; print('token=do-not-return', file=sys.stderr); raise SystemExit(7)"],
        cwd=tmp_path,
        env=dict(os.environ),
        timeout=1,
    )
    timed_out = run_tool(
        [sys.executable, "-c", "import time; time.sleep(5)"],
        cwd=tmp_path,
        env=dict(os.environ),
        timeout=1,
    )

    assert missing.status == "unavailable"
    assert missing.reason == "tool is not installed"
    assert failed.status == "failed"
    assert failed.reason == "tool exited with status 7"
    assert "do-not-return" not in failed.reason
    assert timed_out.status == "timeout"
    assert timed_out.reason == "tool timed out after 1 seconds"


def test_parse_aapt_returns_package_sdk_and_sorted_permissions() -> None:
    badging = """package: name='com.example.bank' versionCode='42' versionName='2.3.1'
sdkVersion:'23'
targetSdkVersion:'34'
application-label:'示例银行'
"""
    permissions = """package: com.example.bank
uses-permission: name='android.permission.INTERNET'
uses-permission: name='android.permission.CAMERA'
uses-permission: name='android.permission.INTERNET'
"""

    package, parsed_permissions = parse_aapt(badging, permissions)

    assert package == {
        "name": "com.example.bank",
        "version_code": "42",
        "version_name": "2.3.1",
        "min_sdk": "23",
        "target_sdk": "34",
        "application_label": "示例银行",
    }
    assert parsed_permissions == [
        "android.permission.CAMERA",
        "android.permission.INTERNET",
    ]


def test_parse_aapt_bounds_fields_and_removes_control_characters() -> None:
    long_label = "A" * 700
    package, permissions = parse_aapt(
        "package: name='com.example\x00.bad' versionCode='1\x1b' versionName='2'\n"
        f"application-label:'{long_label}\tbad'\n",
        "uses-permission: name='android.permission.INTERNET\rBAD'\n",
    )

    assert package["name"] == "com.example.bad"
    assert package["version_code"] == "1"
    assert len(package["application_label"] or "") == 512
    assert all(ord(character) >= 32 for value in package.values() if value for character in value)
    assert permissions == ["android.permission.INTERNETBAD"]


def test_parse_decoded_manifest_extracts_security_flags_components_and_deep_links(tmp_path) -> None:
    manifest = tmp_path / "AndroidManifest.xml"
    manifest.write_text(
        """<?xml version="1.0" encoding="utf-8"?>
<manifest xmlns:android="http://schemas.android.com/apk/res/android" package="com.example.bank">
  <uses-permission android:name="android.permission.INTERNET" />
  <application android:debuggable="false" android:allowBackup="true"
      android:usesCleartextTraffic="false" android:networkSecurityConfig="@xml/network_security_config">
    <activity android:name=".ExportedActivity" android:exported="true" />
    <activity android:name=".DeepLinkActivity">
      <intent-filter>
        <action android:name="android.intent.action.VIEW" />
        <category android:name="android.intent.category.BROWSABLE" />
        <data android:scheme="https" android:host="bank.example" android:pathPrefix="/pay" />
        <data android:scheme="demo" android:host="open" />
      </intent-filter>
    </activity>
    <service android:name="com.example.bank.SyncService" android:exported="false" />
    <receiver android:name=".BootReceiver">
      <intent-filter><action android:name="android.intent.action.BOOT_COMPLETED" /></intent-filter>
    </receiver>
    <provider android:name=".LocalProvider" android:authorities="com.example.bank.local" />
  </application>
</manifest>
""",
        encoding="utf-8",
    )

    parsed = parse_decoded_manifest(manifest)

    assert parsed["application"] == {
        "debuggable": False,
        "allow_backup": True,
        "uses_cleartext_traffic": False,
        "network_security_config": "@xml/network_security_config",
    }
    assert parsed["exported_components"] == [
        {
            "kind": "activity",
            "name": "com.example.bank.DeepLinkActivity",
            "exported": True,
            "exported_source": "inferred_from_intent_filter",
            "actions": ["android.intent.action.VIEW"],
            "categories": ["android.intent.category.BROWSABLE"],
        },
        {
            "kind": "activity",
            "name": "com.example.bank.ExportedActivity",
            "exported": True,
            "exported_source": "explicit",
            "actions": [],
            "categories": [],
        },
        {
            "kind": "receiver",
            "name": "com.example.bank.BootReceiver",
            "exported": True,
            "exported_source": "inferred_from_intent_filter",
            "actions": ["android.intent.action.BOOT_COMPLETED"],
            "categories": [],
        },
    ]
    assert parsed["deep_links"] == [
        {"scheme": "demo", "host": "open", "path": None},
        {"scheme": "https", "host": "bank.example", "path": "/pay"},
    ]
    assert "com.example.bank.LocalProvider" not in str(parsed["exported_components"])


def test_scan_jadx_output_returns_relative_redacted_security_leads(tmp_path) -> None:
    source = tmp_path / "sources" / "com" / "example" / "MainActivity.java"
    source.parent.mkdir(parents=True)
    source.write_text(
        """webView.getSettings().setJavaScriptEnabled(true);
hostnameVerifier = (hostname, session) -> true;
Cipher.getInstance("AES/ECB/PKCS5Padding");
getSharedPreferences("auth", 0);
String endpoint = "http://api.example.test/v1/login";
String api_token = "sk-live-super-secret-value";
""",
        encoding="utf-8",
    )
    outside = tmp_path.parent / "outside-secret.java"
    outside.write_text('String password = "must-not-be-read";', encoding="utf-8")
    symlink = tmp_path / "sources" / "outside.java"
    try:
        symlink.symlink_to(outside)
    except OSError:
        pass

    findings = scan_jadx_output(tmp_path)

    by_kind = {finding["kind"]: finding for finding in findings}
    assert {
        "webview_javascript_enabled",
        "permissive_hostname_verifier",
        "weak_cipher_mode",
        "shared_preferences_usage",
        "cleartext_http_endpoint",
        "credential_indicator",
    } <= set(by_kind)
    assert by_kind["webview_javascript_enabled"]["evidence_ref"] == "sources/com/example/MainActivity.java:1"
    assert all(finding["confidence"] == "lead" for finding in findings)
    serialized = repr(findings)
    assert "sk-live-super-secret-value" not in serialized
    assert "must-not-be-read" not in serialized
    assert str(tmp_path) not in serialized


def test_scan_jadx_output_enforces_file_byte_and_finding_budgets(tmp_path) -> None:
    for index in range(4):
        (tmp_path / f"Source{index}.java").write_text(
            "webView.getSettings().setJavaScriptEnabled(true);\n" * 4,
            encoding="utf-8",
        )

    findings = scan_jadx_output(
        tmp_path,
        max_files=2,
        max_total_bytes=512,
        max_file_bytes=256,
        max_findings=1,
    )

    assert len(findings) == 1
    assert findings[0]["evidence_ref"] == "Source0.java:1"


def test_scan_jadx_output_limits_enumerated_entries(tmp_path) -> None:
    for index in range(20):
        (tmp_path / f"Source{index:02}.java").write_text(
            "webView.getSettings().setJavaScriptEnabled(true);",
            encoding="utf-8",
        )

    findings = scan_jadx_output(tmp_path, max_entries=3, max_findings=20)

    assert len(findings) <= 3


def test_analyze_apk_enriches_baseline_with_all_static_tools_and_cleans_workspace(tmp_path) -> None:
    apk = tmp_path / "bank.apk"
    with zipfile.ZipFile(apk, "w") as archive:
        archive.writestr("classes.dex", b"https://baseline.example/api/login")

    calls: list[tuple[list[str], Path, dict[str, str]]] = []

    def fake_executor(
        argv: list[str],
        *,
        cwd: Path,
        env: dict[str, str],
        timeout: int = 90,
        max_output_bytes: int = 262_144,
    ) -> ToolRun:
        calls.append((argv, cwd, env))
        assert timeout == 90
        assert max_output_bytes == 262_144
        if argv[:3] == ["aapt", "dump", "badging"]:
            return ToolRun(
                "completed",
                "package: name='com.example.bank' versionCode='7' versionName='1.4'\n"
                "sdkVersion:'23'\ntargetSdkVersion:'34'\napplication-label:'Bank'\n",
            )
        if argv[:3] == ["aapt", "dump", "permissions"]:
            return ToolRun("completed", "uses-permission: name='android.permission.INTERNET'\n")
        if argv[0] == "apktool":
            output = Path(argv[argv.index("--output") + 1])
            output.mkdir(parents=True)
            (output / "AndroidManifest.xml").write_text(
                """<manifest xmlns:android="http://schemas.android.com/apk/res/android" package="com.example.bank">
<application android:allowBackup="true"><activity android:name=".MainActivity" android:exported="true" /></application>
</manifest>""",
                encoding="utf-8",
            )
            return ToolRun("completed")
        if argv[0] == "jadx":
            output = Path(argv[argv.index("--output-dir") + 1])
            source = output / "sources" / "com" / "example" / "MainActivity.java"
            source.parent.mkdir(parents=True)
            source.write_text("webView.getSettings().setJavaScriptEnabled(true);", encoding="utf-8")
            return ToolRun("completed")
        raise AssertionError(f"unexpected command: {argv}")

    report = analyze_apk(apk, tool_executor=fake_executor)

    assert report["analysis_level"] == "tool_enriched"
    assert report["tool_runs"] == {
        "aapt": {"status": "completed", "reason": None},
        "apktool": {"status": "completed", "reason": None},
        "jadx": {"status": "completed", "reason": None},
    }
    assert report["package"] == {
        "name": "com.example.bank",
        "version_code": "7",
        "version_name": "1.4",
        "min_sdk": "23",
        "target_sdk": "34",
        "application_label": "Bank",
    }
    assert report["permissions"] == ["android.permission.INTERNET"]
    assert report["manifest"]["application"]["allow_backup"] is True
    assert report["manifest"]["exported_components"][0]["name"] == "com.example.bank.MainActivity"
    assert report["code_findings"][0]["kind"] == "webview_javascript_enabled"
    assert "https://baseline.example/api/login" in report["endpoints"]
    assert [call[0][0] for call in calls] == ["aapt", "aapt", "apktool", "jadx"]
    workspace = calls[0][1]
    assert all(call[1] == workspace for call in calls)
    assert all(call[2]["HOME"].startswith(str(workspace)) for call in calls)
    assert not workspace.exists()
    assert "skidc-static-" not in repr(report)


def test_analyze_apk_preserves_partial_results_when_jadx_times_out(tmp_path) -> None:
    apk = tmp_path / "partial.apk"
    with zipfile.ZipFile(apk, "w") as archive:
        archive.writestr("classes.dex", b"/api/profile")

    def partial_executor(
        argv: list[str],
        *,
        cwd: Path,
        env: dict[str, str],
        timeout: int = 90,
        max_output_bytes: int = 262_144,
    ) -> ToolRun:
        if argv[:3] == ["aapt", "dump", "badging"]:
            return ToolRun("completed", "package: name='com.example.partial' versionCode='1' versionName='1'\n")
        if argv[:3] == ["aapt", "dump", "permissions"]:
            return ToolRun("completed", "")
        if argv[0] == "apktool":
            return ToolRun("failed", reason="tool exited with status 1")
        return ToolRun("timeout", reason="tool timed out after 90 seconds")

    report = analyze_apk(apk, tool_executor=partial_executor)

    assert report["analysis_level"] == "tool_enriched"
    assert report["package"]["name"] == "com.example.partial"
    assert report["tool_runs"]["apktool"] == {
        "status": "failed",
        "reason": "tool exited with status 1",
    }
    assert report["tool_runs"]["jadx"] == {
        "status": "timeout",
        "reason": "tool timed out after 90 seconds",
    }
    assert report["manifest"]["exported_components"] == []
    assert report["code_findings"] == []
    assert "/api/profile" in report["endpoint_paths"]


def test_analyze_apk_deterministically_trims_oversized_report(tmp_path) -> None:
    apk = tmp_path / "large-report.apk"
    payload = b"\x00".join(
        f"https://api.example.test/api/resource/{index}/{'x' * 400}".encode()
        for index in range(80)
    )
    with zipfile.ZipFile(apk, "w") as archive:
        archive.writestr("classes.dex", payload)

    def unavailable(*_args, **_kwargs) -> ToolRun:
        return ToolRun("unavailable", reason="tool is not installed")

    report = analyze_apk(apk, tool_executor=unavailable, max_report_bytes=4_096)

    assert len(json.dumps(report, ensure_ascii=False, separators=(",", ":")).encode("utf-8")) <= 4_096
    assert "Report collections were deterministically trimmed to the byte budget." in report["notes"]
    assert report["analysis_level"] == "heuristic_only"
