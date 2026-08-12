from __future__ import annotations

import os
import re
import signal
import subprocess
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal
from xml.etree import ElementTree


ToolStatus = Literal["completed", "unavailable", "timeout", "failed"]
ANDROID_NAMESPACE = "http://schemas.android.com/apk/res/android"
JADX_RULES = (
    ("webview_javascript_enabled", re.compile(r"setJavaScriptEnabled\s*\(\s*true\s*\)"), "发现 WebView JavaScript 启用调用"),
    ("webview_file_access", re.compile(r"setAllowFileAccess(?:FromFileURLs|FromUniversalAccessFromFileURLs)?\s*\(\s*true\s*\)"), "发现 WebView 文件访问启用调用"),
    ("javascript_interface", re.compile(r"addJavascriptInterface\s*\("), "发现 WebView JavaScript Interface 注册调用"),
    ("permissive_hostname_verifier", re.compile(r"HostnameVerifier|setHostnameVerifier|hostnameVerifier\s*=.*->\s*true", re.IGNORECASE), "发现自定义或宽松 HostnameVerifier 线索"),
    ("custom_trust_manager", re.compile(r"X509TrustManager|checkServerTrusted\s*\("), "发现自定义 TrustManager 线索"),
    ("weak_cipher_mode", re.compile(r"(?:AES|DES|DESede)/ECB|MessageDigest\.getInstance\s*\(\s*[\"'](?:MD5|SHA-?1)[\"']", re.IGNORECASE), "发现弱密码学算法或模式线索"),
    ("logging_usage", re.compile(r"(?:android\.util\.)?Log\.(?:v|d|i|w|e)\s*\(|System\.(?:out|err)\.print"), "发现应用日志输出调用"),
    ("shared_preferences_usage", re.compile(r"getSharedPreferences\s*\(|SharedPreferences"), "发现 SharedPreferences 使用线索"),
    ("external_storage_usage", re.compile(r"getExternalStorage|Environment\.getExternalStorage"), "发现外部存储使用线索"),
    ("database_usage", re.compile(r"SQLiteDatabase|RoomDatabase|openOrCreateDatabase"), "发现本地数据库使用线索"),
    ("cleartext_http_endpoint", re.compile(r"http://[A-Za-z0-9._~:/?#\[\]@!$&'()*+,;=%-]+", re.IGNORECASE), "发现 HTTP 明文端点线索"),
    ("credential_indicator", re.compile(r"(?:api[_-]?key|secret|token|jwt|password|passwd)\s*=", re.IGNORECASE), "发现疑似硬编码凭据标识"),
)


@dataclass(frozen=True)
class ToolRun:
    status: ToolStatus
    stdout: str = ""
    reason: str | None = None


def run_tool(
    argv: list[str],
    *,
    cwd: Path,
    env: dict[str, str],
    timeout: int = 90,
    max_output_bytes: int = 262_144,
) -> ToolRun:
    if not argv or not argv[0]:
        raise ValueError("tool argv must not be empty")
    if timeout <= 0:
        raise ValueError("tool timeout must be positive")
    if max_output_bytes <= 0:
        raise ValueError("tool output budget must be positive")

    try:
        process = subprocess.Popen(
            argv,
            cwd=cwd,
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            start_new_session=True,
        )
    except FileNotFoundError:
        return ToolRun(status="unavailable", reason="tool is not installed")
    except OSError:
        return ToolRun(status="failed", reason="tool could not be started")

    exceeded = threading.Event()
    stdout_chunks: list[bytes] = []
    stderr_chunks: list[bytes] = []
    readers = [
        threading.Thread(
            target=_capture_stream,
            args=(process.stdout, stdout_chunks, max_output_bytes, process, exceeded),
            daemon=True,
        ),
        threading.Thread(
            target=_capture_stream,
            args=(process.stderr, stderr_chunks, max_output_bytes, process, exceeded),
            daemon=True,
        ),
    ]
    for reader in readers:
        reader.start()
    try:
        returncode = process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        _terminate_process_group(process)
        process.wait()
        for reader in readers:
            reader.join(timeout=1)
        return ToolRun(status="timeout", reason=f"tool timed out after {timeout} seconds")
    for reader in readers:
        reader.join(timeout=1)
    stdout = b"".join(stdout_chunks)[:max_output_bytes].decode("utf-8", errors="replace")
    if exceeded.is_set():
        return ToolRun(status="failed", stdout=stdout, reason="tool output exceeded byte budget")
    if returncode != 0:
        return ToolRun(status="failed", reason=f"tool exited with status {returncode}")
    return ToolRun(status="completed", stdout=stdout)


def parse_aapt(badging: str, permissions: str) -> tuple[dict[str, str | None], list[str]]:
    package: dict[str, str | None] = {
        "name": None,
        "version_code": None,
        "version_name": None,
        "min_sdk": None,
        "target_sdk": None,
        "application_label": None,
    }
    package_line = re.search(r"^package:\s+name='([^']*)'\s+versionCode='([^']*)'\s+versionName='([^']*)'", badging, re.MULTILINE)
    if package_line:
        package["name"], package["version_code"], package["version_name"] = (
            _bounded_text(value) for value in package_line.groups()
        )

    known_fields = {
        "sdkVersion": "min_sdk",
        "targetSdkVersion": "target_sdk",
        "application-label": "application_label",
    }
    for prefix, field in known_fields.items():
        match = re.search(rf"^{re.escape(prefix)}:'([^']*)'", badging, re.MULTILINE)
        if match:
            package[field] = _bounded_text(match.group(1))

    parsed_permissions = {
        _bounded_text(match.group(1))
        for match in re.finditer(r"^uses-permission:\s+name='([^']+)'", permissions, re.MULTILINE)
        if len(match.group(1)) <= 512
    }
    return package, sorted(parsed_permissions)


def parse_decoded_manifest(path: Path) -> dict[str, Any]:
    root = ElementTree.parse(path).getroot()
    package_name = root.attrib.get("package", "")
    application = root.find("application")
    if application is None:
        return {"application": _empty_application(), "exported_components": [], "deep_links": []}

    application_result = {
        "debuggable": _android_bool(application, "debuggable"),
        "allow_backup": _android_bool(application, "allowBackup"),
        "uses_cleartext_traffic": _android_bool(application, "usesCleartextTraffic"),
        "network_security_config": _android_attr(application, "networkSecurityConfig"),
    }
    exported_components: list[dict[str, Any]] = []
    deep_links: list[dict[str, str | None]] = []
    inferable = {"activity", "activity-alias", "service", "receiver"}

    for element in application:
        kind = _local_name(element.tag)
        if kind not in inferable | {"provider"}:
            continue
        raw_name = _android_attr(element, "name")
        if not raw_name:
            continue
        filters = [child for child in element if _local_name(child.tag) == "intent-filter"]
        explicit = _android_bool(element, "exported")
        exported = explicit is True or (explicit is None and kind in inferable and bool(filters))
        if exported:
            actions = sorted(
                {
                    value
                    for intent_filter in filters
                    for child in intent_filter
                    if _local_name(child.tag) == "action"
                    if (value := _android_attr(child, "name"))
                }
            )[:100]
            categories = sorted(
                {
                    value
                    for intent_filter in filters
                    for child in intent_filter
                    if _local_name(child.tag) == "category"
                    if (value := _android_attr(child, "name"))
                }
            )[:100]
            exported_components.append(
                {
                    "kind": kind,
                    "name": _component_name(package_name, raw_name),
                    "exported": True,
                    "exported_source": "explicit" if explicit is True else "inferred_from_intent_filter",
                    "actions": actions,
                    "categories": categories,
                }
            )
        for intent_filter in filters:
            for child in intent_filter:
                if _local_name(child.tag) != "data":
                    continue
                scheme = _android_attr(child, "scheme")
                if not scheme:
                    continue
                deep_links.append(
                    {
                        "scheme": scheme,
                        "host": _android_attr(child, "host"),
                        "path": (
                            _android_attr(child, "path")
                            or _android_attr(child, "pathPrefix")
                            or _android_attr(child, "pathPattern")
                        ),
                    }
                )

    exported_components.sort(key=lambda item: (item["kind"], item["name"]))
    unique_links = {
        (item["scheme"], item["host"], item["path"]): item
        for item in deep_links
    }
    return {
        "application": application_result,
        "exported_components": exported_components[:200],
        "deep_links": [unique_links[key] for key in sorted(unique_links, key=lambda value: tuple(part or "" for part in value))][:200],
    }


def scan_jadx_output(
    root: Path,
    *,
    max_files: int = 2_000,
    max_total_bytes: int = 67_108_864,
    max_file_bytes: int = 1_048_576,
    max_findings: int = 200,
    max_entries: int = 10_000,
) -> list[dict[str, str]]:
    if min(max_files, max_total_bytes, max_file_bytes, max_findings, max_entries) <= 0:
        return []
    resolved_root = root.resolve()
    findings: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    total_bytes = 0
    files_read = 0

    for path in _bounded_paths(resolved_root, max_entries=max_entries):
        if files_read >= max_files or len(findings) >= max_findings:
            break
        if path.is_symlink() or not path.is_file():
            continue
        resolved = path.resolve()
        try:
            relative = resolved.relative_to(resolved_root)
        except ValueError:
            continue
        size = path.stat().st_size
        if size > max_file_bytes or total_bytes + size > max_total_bytes:
            continue
        data = path.read_bytes()
        total_bytes += len(data)
        files_read += 1
        text = data.decode("utf-8", errors="replace")
        for line_number, line in enumerate(text.splitlines(), start=1):
            for kind, pattern, summary in JADX_RULES:
                if not pattern.search(line):
                    continue
                evidence_ref = f"{relative.as_posix()}:{line_number}"
                identity = (kind, evidence_ref)
                if identity in seen:
                    continue
                seen.add(identity)
                findings.append(
                    {
                        "kind": kind,
                        "evidence_ref": evidence_ref[:768],
                        "summary": summary[:300],
                        "confidence": "lead",
                    }
                )
                if len(findings) >= max_findings:
                    break
            if len(findings) >= max_findings:
                break
    return findings


def _terminate_process_group(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is not None:
        return
    if os.name == "posix":
        try:
            os.killpg(process.pid, signal.SIGKILL)
            return
        except ProcessLookupError:
            return
    process.kill()


def _capture_stream(
    stream: Any,
    chunks: list[bytes],
    budget: int,
    process: subprocess.Popen[bytes],
    exceeded: threading.Event,
) -> None:
    captured = 0
    while True:
        chunk = stream.read(min(65_536, budget + 1))
        if not chunk:
            return
        remaining = budget - captured
        if remaining > 0:
            chunks.append(chunk[:remaining])
            captured += min(len(chunk), remaining)
        if len(chunk) > remaining:
            exceeded.set()
            _terminate_process_group(process)
            return


def _bounded_paths(root: Path, *, max_entries: int) -> list[Path]:
    discovered: list[Path] = []
    pending = [root]
    entries_seen = 0
    while pending and entries_seen < max_entries:
        directory = pending.pop()
        children: list[Path] = []
        try:
            with os.scandir(directory) as iterator:
                for entry in iterator:
                    if entries_seen >= max_entries:
                        break
                    entries_seen += 1
                    children.append(Path(entry.path))
        except OSError:
            continue
        children.sort(key=lambda item: item.name)
        subdirectories: list[Path] = []
        for child in children:
            if child.is_symlink():
                continue
            try:
                if child.is_dir():
                    subdirectories.append(child)
                elif child.is_file():
                    discovered.append(child)
            except OSError:
                continue
        pending.extend(reversed(subdirectories))
    discovered.sort(key=lambda item: item.relative_to(root).as_posix())
    return discovered


def _bounded_text(value: str, *, limit: int = 512) -> str:
    return "".join(character for character in value if ord(character) >= 32 and ord(character) != 127)[:limit]


def _android_attr(element: ElementTree.Element, name: str) -> str | None:
    value = element.attrib.get(f"{{{ANDROID_NAMESPACE}}}{name}")
    if value is None:
        return None
    value = value.strip()
    return value[:512] if value else None


def _android_bool(element: ElementTree.Element, name: str) -> bool | None:
    value = _android_attr(element, name)
    if value == "true":
        return True
    if value == "false":
        return False
    return None


def _component_name(package_name: str, value: str) -> str:
    if value.startswith("."):
        return f"{package_name}{value}"
    if "." not in value and package_name:
        return f"{package_name}.{value}"
    return value


def _local_name(value: str) -> str:
    return value.rsplit("}", 1)[-1]


def _empty_application() -> dict[str, bool | str | None]:
    return {
        "debuggable": None,
        "allow_backup": None,
        "uses_cleartext_traffic": None,
        "network_security_config": None,
    }
