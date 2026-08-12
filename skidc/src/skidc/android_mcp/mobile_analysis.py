from __future__ import annotations

import json
import os
import re
import shutil
import tempfile
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable
from xml.etree import ElementTree

from skidc.android_mcp.static_tools import (
    ToolRun,
    parse_aapt,
    parse_decoded_manifest,
    run_tool,
    scan_jadx_output,
)


URL_RE = re.compile(rb"https?://[A-Za-z0-9._~:/?#\[\]@!$&'()*+,;=%-]+")
PATH_RE = re.compile(
    rb"/(?:api|v[0-9]|auth|user|users|account|balance|transfer|transaction|login|signup)"
    rb"[A-Za-z0-9._~:/?#\[\]@!$&'()*+,;=%-]*"
)
SECRET_RE = re.compile(
    rb"(?i)(api[_-]?key|secret|token|jwt|password|passwd|bearer)"
    rb"[A-Za-z0-9._~:/?#\[\]@!$&'()*+,;=%-]{0,80}"
)
ALLOWED_ZIP_COMPRESSION = {zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED}


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


def tool_status() -> dict[str, bool]:
    return {
        "adb": shutil.which("adb") is not None,
        "aapt": shutil.which("aapt") is not None,
        "apktool": shutil.which("apktool") is not None,
        "jadx": shutil.which("jadx") is not None,
        "frida": shutil.which("frida") is not None,
        "frida-ps": shutil.which("frida-ps") is not None,
        "mitmproxy": shutil.which("mitmproxy") is not None,
    }


def analyze_apk(
    apk_path: Path,
    *,
    max_files: int = 400,
    max_entries: int = 2_000,
    max_apk_bytes: int = 128_000_000,
    max_bytes_per_file: int = 750_000,
    max_total_uncompressed_bytes: int = 128_000_000,
    max_compression_ratio: int = 200,
    max_match_bytes: int = 2_048,
    max_name_chars: int = 512,
    max_report_bytes: int = 1_000_000,
    enrich: bool = True,
    tool_executor: Callable[..., ToolRun] = run_tool,
) -> dict[str, Any]:
    if not apk_path.exists() or not apk_path.is_file():
        raise ValueError(f"apk not found: {apk_path}")
    if apk_path.suffix.lower() != ".apk":
        raise ValueError(f"expected an .apk file: {apk_path}")
    apk_size = apk_path.stat().st_size
    if apk_size > max_apk_bytes:
        raise ValueError(f"apk exceeds compressed byte budget of {max_apk_bytes}")

    urls: set[str] = set()
    paths: set[str] = set()
    secrets: set[str] = set()
    interesting_files: list[str] = []
    permissions: set[str] = set()
    manifest_text: str | None = None

    with zipfile.ZipFile(apk_path) as archive:
        entries = archive.infolist()
        if len(entries) > max_entries:
            raise ValueError(f"apk exceeds ZIP entry limit of {max_entries}")
        total_uncompressed = sum(entry.file_size for entry in entries)
        if total_uncompressed > max_total_uncompressed_bytes:
            raise ValueError(
                f"apk exceeds uncompressed byte budget of {max_total_uncompressed_bytes}"
            )
        for entry in entries:
            if entry.flag_bits & 0x1:
                raise ValueError("encrypted ZIP entries are not supported")
            if entry.compress_type not in ALLOWED_ZIP_COMPRESSION:
                raise ValueError(f"unsupported ZIP compression method: {entry.compress_type}")
            if entry.file_size and entry.file_size / max(1, entry.compress_size) > max_compression_ratio:
                raise ValueError(f"apk entry exceeds compression ratio limit of {max_compression_ratio}")

        for entry in entries:
            name = entry.filename
            lower = name.lower()
            if len(interesting_files) < 200 and (
                lower == "androidmanifest.xml"
                or lower.endswith((".dex", ".so", ".xml", ".json", ".properties"))
            ) and len(name) <= max_name_chars:
                interesting_files.append(name)

        for info in entries[:max_files]:
            name = info.filename
            if info.file_size > max_bytes_per_file:
                continue
            try:
                data = archive.read(name)
            except (KeyError, RuntimeError, zipfile.BadZipFile):
                continue

            if name.lower() == "androidmanifest.xml":
                decoded = _decode_text(data)
                if decoded and "<manifest" in decoded:
                    manifest_text = decoded
                    for permission in re.findall(r"android\.permission\.[A-Z0-9_]+", decoded):
                        if len(permission) <= max_name_chars:
                            permissions.add(permission)
                        if len(permissions) >= 200:
                            break

            _add_matches(urls, URL_RE, data, limit=200, max_match_bytes=max_match_bytes)
            _add_matches(paths, PATH_RE, data, limit=200, max_match_bytes=max_match_bytes)
            _add_matches(secrets, SECRET_RE, data, limit=100, max_match_bytes=max_match_bytes)

    report: dict[str, Any] = {
        "apk_path": str(apk_path),
        "size_bytes": apk_size,
        "analyzed_at": utc_now(),
        "tools": tool_status(),
        "manifest_decoded": manifest_text is not None,
        "permissions": sorted(permissions),
        "interesting_files": interesting_files[:200],
        "endpoints": sorted(urls)[:200],
        "endpoint_paths": sorted(paths)[:200],
        "secret_indicators": sorted(secrets)[:100],
        "notes": [
            "Pure ZIP/string analysis is always available.",
            "Static analysis results are investigation leads and require runtime confirmation.",
        ],
    }
    if enrich:
        enrichment = enrich_apk_analysis(apk_path, executor=tool_executor)
        aapt_permissions = enrichment.pop("aapt_permissions", [])
        report.update(enrichment)
        report["permissions"] = sorted(
            set(report["permissions"]) | set(aapt_permissions)
        )[:200]
    _trim_report_to_budget(report, max_report_bytes=max_report_bytes)
    return report


def enrich_apk_analysis(
    apk_path: Path,
    *,
    executor: Callable[..., ToolRun] = run_tool,
    timeout: int = 90,
) -> dict[str, Any]:
    empty_manifest = {
        "application": {
            "debuggable": None,
            "allow_backup": None,
            "uses_cleartext_traffic": None,
            "network_security_config": None,
        },
        "exported_components": [],
        "deep_links": [],
    }
    package: dict[str, str | None] = {
        "name": None,
        "version_code": None,
        "version_name": None,
        "min_sdk": None,
        "target_sdk": None,
        "application_label": None,
    }
    manifest = empty_manifest
    code_findings: list[dict[str, str]] = []
    aapt_permissions: list[str] = []

    with tempfile.TemporaryDirectory(prefix="skidc-static-") as workspace_text:
        workspace = Path(workspace_text)
        home = workspace / "home"
        apktool_output = workspace / "apktool"
        jadx_output = workspace / "jadx"
        home.mkdir(mode=0o700)
        env = {
            **os.environ,
            "HOME": str(home),
            "TMPDIR": str(workspace),
            "JAVA_TOOL_OPTIONS": "-Xmx512m -Djava.io.tmpdir=" + str(workspace),
        }
        run_options = {
            "cwd": workspace,
            "env": env,
            "timeout": timeout,
            "max_output_bytes": 262_144,
        }
        badging = executor(["aapt", "dump", "badging", str(apk_path)], **run_options)
        permissions = executor(["aapt", "dump", "permissions", str(apk_path)], **run_options)
        apktool = executor(
            [
                "apktool",
                "d",
                "--force",
                "--no-src",
                "--output",
                str(apktool_output),
                str(apk_path),
            ],
            **run_options,
        )
        jadx = executor(
            ["jadx", "--output-dir", str(jadx_output), "--no-res", str(apk_path)],
            **run_options,
        )

        if badging.status == "completed" or permissions.status == "completed":
            package, aapt_permissions = parse_aapt(
                badging.stdout if badging.status == "completed" else "",
                permissions.stdout if permissions.status == "completed" else "",
            )
        if apktool.status == "completed":
            decoded_manifest = apktool_output / "AndroidManifest.xml"
            if (
                decoded_manifest.is_file()
                and not decoded_manifest.is_symlink()
                and decoded_manifest.stat().st_size <= 2_000_000
            ):
                try:
                    manifest = parse_decoded_manifest(decoded_manifest)
                except (OSError, ElementTree.ParseError):
                    manifest = empty_manifest
        if jadx.status == "completed":
            code_findings = scan_jadx_output(jadx_output)

        aapt_status = _combine_aapt_runs(badging, permissions)
        tool_runs = {
            "aapt": _tool_run_summary(aapt_status),
            "apktool": _tool_run_summary(apktool),
            "jadx": _tool_run_summary(jadx),
        }
        enriched = any(item["status"] == "completed" for item in tool_runs.values())
        return {
            "analysis_level": "tool_enriched" if enriched else "heuristic_only",
            "tool_runs": tool_runs,
            "package": package,
            "manifest": manifest,
            "code_findings": code_findings,
            "aapt_permissions": aapt_permissions,
        }


def _combine_aapt_runs(badging: ToolRun, permissions: ToolRun) -> ToolRun:
    if badging.status == "completed" and permissions.status == "completed":
        return ToolRun(status="completed")
    if badging.status == "completed" or permissions.status == "completed":
        return ToolRun(status="completed", reason="AAPT returned partial structured output")
    for status in ("timeout", "failed", "unavailable"):
        for result in (badging, permissions):
            if result.status == status:
                return ToolRun(status=result.status, reason=result.reason)
    return ToolRun(status="failed", reason="AAPT analysis failed")


def _tool_run_summary(result: ToolRun) -> dict[str, str | None]:
    return {"status": result.status, "reason": result.reason}


def _trim_report_to_budget(report: dict[str, Any], *, max_report_bytes: int) -> None:
    def size() -> int:
        return len(json.dumps(report, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))

    if size() <= max_report_bytes:
        return
    report["notes"].append("Report collections were deterministically trimmed to the byte budget.")
    collection_paths = (
        ("code_findings",),
        ("manifest", "deep_links"),
        ("manifest", "exported_components"),
        ("endpoints",),
        ("endpoint_paths",),
        ("secret_indicators",),
        ("interesting_files",),
        ("permissions",),
    )
    while size() > max_report_bytes:
        changed = False
        for path in collection_paths:
            value: Any = report
            for part in path:
                value = value.get(part, [])
            if isinstance(value, list) and value:
                value.pop()
                changed = True
                if size() <= max_report_bytes:
                    return
        if not changed:
            raise ValueError(f"apk analysis exceeds report byte budget of {max_report_bytes}")


def parse_network_import(content: str) -> list[dict[str, Any]]:
    text = content.strip()
    if not text:
        return []

    try:
        parsed: Any = json.loads(text)
    except json.JSONDecodeError:
        events = []
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            item = json.loads(line)
            if not isinstance(item, dict):
                raise ValueError(f"network JSONL event at index {len(events)} must be an object")
            events.append(_normalise_network_event(item))
        return events

    if isinstance(parsed, list):
        return _normalise_network_events(parsed)
    if isinstance(parsed, dict):
        if isinstance(parsed.get("events"), list):
            return _normalise_network_events(parsed["events"])
        if isinstance(parsed.get("flows"), list):
            return _normalise_network_events(parsed["flows"])
        return [_normalise_network_event(parsed)]
    raise ValueError("network import must be a JSON object, JSON array, or JSONL content")


def lab_profiles() -> list[dict[str, Any]]:
    return [
        {
            "id": "dvba",
            "name": "Damn Vulnerable Bank",
            "source": "https://github.com/rewanthtammana/Damn-Vulnerable-Bank",
            "target_type": "android_app_plus_backend",
            "recommended_for": ["API inventory", "auth/session testing", "IDOR", "storage/logcat leakage"],
            "expected_output": [
                "Install and operate the vulnerable banking APK",
                "Capture login, profile, balance, transfer, beneficiary, and transaction traffic",
                "Correlate two-account actions with API requests",
                "Produce evidence-backed mobile API findings",
            ],
        },
        {
            "id": "bugbazaar",
            "name": "BugBazaar",
            "source": "https://github.com/payatu/BugBazaar",
            "target_type": "android_native_vulnerability_lab",
            "recommended_for": ["WebView", "deep link", "IPC", "storage", "runtime instrumentation"],
            "expected_output": [
                "Navigate native Android vulnerability modules",
                "Collect UI, logcat, static reverse, and Frida observations",
                "Produce Android-native vulnerability evidence",
            ],
        },
    ]


def frida_script_templates() -> list[dict[str, str]]:
    return [
        {
            "id": "okhttp_request_observer",
            "name": "OkHttp request observer",
            "purpose": "Record URLs, headers, and request metadata observed inside the app runtime.",
        },
        {
            "id": "retrofit_endpoint_observer",
            "name": "Retrofit endpoint observer",
            "purpose": "Record Retrofit interface methods and generated endpoint paths.",
        },
        {
            "id": "ssl_pinning_observer",
            "name": "SSL pinning observer",
            "purpose": "Identify certificate pinning checks during authorized lab testing.",
        },
        {
            "id": "token_source_observer",
            "name": "Token source observer",
            "purpose": "Trace where authorization tokens are read or written at runtime.",
        },
    ]


def _normalise_network_event(item: dict[str, Any]) -> dict[str, Any]:
    request = item.get("request") if isinstance(item.get("request"), dict) else {}
    response = item.get("response") if isinstance(item.get("response"), dict) else {}
    url = item.get("url") or request.get("url") or item.get("pretty_url")
    if not url:
        raise ValueError("network event is missing url")
    return {
        "method": item.get("method") or request.get("method"),
        "url": str(url),
        "status_code": item.get("status_code") or response.get("status_code") or response.get("status"),
        "request_headers": _string_map(item.get("request_headers") or request.get("headers") or {}),
        "response_headers": _string_map(item.get("response_headers") or response.get("headers") or {}),
        "request_body_preview": item.get("request_body_preview") or request.get("body") or request.get("content"),
        "response_body_preview": item.get("response_body_preview") or response.get("body") or response.get("content"),
        "note": item.get("note") or item.get("source"),
        "imported_at": utc_now(),
    }


def _normalise_network_events(items: list[Any]) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            raise ValueError(f"network event at index {index} must be an object")
        events.append(_normalise_network_event(item))
    return events


def _string_map(value: Any) -> dict[str, str]:
    if not isinstance(value, dict):
        return {}
    return {str(key): str(item) for key, item in value.items()}


def _decode_match(value: bytes) -> str:
    return value.decode("utf-8", errors="ignore").strip("\x00\r\n\t ")


def _add_matches(
    target: set[str],
    pattern: re.Pattern[bytes],
    data: bytes,
    *,
    limit: int,
    max_match_bytes: int,
) -> None:
    if len(target) >= limit:
        return
    for match in pattern.finditer(data):
        value = match.group(0)
        if len(value) > max_match_bytes:
            continue
        target.add(_decode_match(value))
        if len(target) >= limit:
            return


def _decode_text(value: bytes) -> str | None:
    for encoding in ("utf-8", "utf-16", "latin1"):
        try:
            return value.decode(encoding)
        except UnicodeDecodeError:
            continue
    return None
