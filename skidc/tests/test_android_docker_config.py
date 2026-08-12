from __future__ import annotations

import os
from pathlib import Path
import subprocess

import pytest
import yaml


REPO_ROOT = Path(__file__).resolve().parents[2]
BRIDGE_DIR = REPO_ROOT / "container" / "android-bridge"
COMPOSE_FILE = REPO_ROOT / "docker-compose.yaml"
ANDROID_COMPOSE_FILE = REPO_ROOT / "docker-compose.android.yaml"
ANDROID_LAB_SCRIPT = REPO_ROOT / "scripts" / "android-lab.sh"
ANDROID_MCP_CLIENT = REPO_ROOT / "container" / "android-mcp"


def _compose_config() -> dict:
    return yaml.safe_load(COMPOSE_FILE.read_text(encoding="utf-8"))


def _android_compose_config() -> dict:
    return yaml.safe_load(ANDROID_COMPOSE_FILE.read_text(encoding="utf-8"))


def test_android_prompts_use_only_the_authenticated_worker_client() -> None:
    prompts_dir = REPO_ROOT / "skidc/src/skidc/dispatcher/prompts/android"
    prompts = {
        path.name: path.read_text(encoding="utf-8")
        for path in prompts_dir.glob("*.md")
    }

    for name in ("bootstrap.md", "reason.md", "explore.md", "verify.md"):
        assert "android-mcp" in prompts[name]
        assert "curl" not in prompts[name]
        assert "Authorization" not in prompts[name]
        assert "Bearer" not in prompts[name]
        assert "$ANDROID_MCP_URL" not in prompts[name]


def test_android_compose_overlay_shares_secret_only_with_android_lab_services() -> None:
    base = _compose_config()
    overlay = _android_compose_config()

    assert "secrets" not in base
    assert "secrets" not in base["services"]["skidc-dispatcher"]
    assert "secrets" not in base["services"]["android-bridge"]
    assert overlay["secrets"]["android_mcp_token"] == {
        "file": "./datas/android-lab/secrets/android_mcp_token"
    }
    assert overlay["services"]["skidc-dispatcher"]["secrets"] == ["android_mcp_token"]
    assert overlay["services"]["android-bridge"]["secrets"] == ["android_mcp_token"]


def _write_executable(path: Path, body: str) -> None:
    path.write_text(body, encoding="utf-8")
    path.chmod(0o755)


def test_android_mcp_client_reads_bearer_token_from_file_without_leaking_it(tmp_path: Path) -> None:
    token = "bridge-token-that-must-not-leak"
    token_file = tmp_path / "token"
    token_file.write_text(token + "\n", encoding="utf-8")
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    argv_log = tmp_path / "argv.log"
    config_log = tmp_path / "config.log"
    _write_executable(
        fake_bin / "curl",
        "#!/bin/sh\n"
        "set -eu\n"
        "printf '%s\\n' \"$*\" > \"$ARGV_LOG\"\n"
        "cat > \"$CONFIG_LOG\"\n"
        "printf '%s\\n' '{\"ready\":true}'\n",
    )
    env = {
        **os.environ,
        "PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}",
        "ANDROID_MCP_URL": "http://127.0.0.1:8765",
        "ANDROID_MCP_TOKEN_FILE": str(token_file),
        "ARGV_LOG": str(argv_log),
        "CONFIG_LOG": str(config_log),
    }

    result = subprocess.run(
        ["sh", str(ANDROID_MCP_CLIENT), "GET", "/health/ready"],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == '{"ready":true}'
    assert "--config -" in argv_log.read_text(encoding="utf-8")
    assert token not in argv_log.read_text(encoding="utf-8")
    assert token not in result.stdout
    assert token not in result.stderr
    assert config_log.read_text(encoding="utf-8").strip() == (
        f'header = "Authorization: Bearer {token}"'
    )


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("TRACE", "/health/ready"),
        ("GET", "health/ready"),
        ("GET", "//outside"),
        ("GET", "/health/ready\nInjected: value"),
        ("GET", "/health/ready\tbad"),
    ],
)
def test_android_mcp_client_rejects_unsafe_requests(
    tmp_path: Path,
    method: str,
    path: str,
) -> None:
    token_file = tmp_path / "token"
    token_file.write_text("token\n", encoding="utf-8")
    env = {
        **os.environ,
        "ANDROID_MCP_URL": "http://127.0.0.1:8765",
        "ANDROID_MCP_TOKEN_FILE": str(token_file),
    }

    result = subprocess.run(
        ["sh", str(ANDROID_MCP_CLIENT), method, path],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )

    assert result.returncode != 0
    assert "token" not in result.stderr


def test_android_mcp_client_accepts_bodyless_delete(tmp_path: Path) -> None:
    token_file = tmp_path / "token"
    token_file.write_text("token\n", encoding="utf-8")
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    argv_log = tmp_path / "argv.log"
    _write_executable(
        fake_bin / "curl",
        "#!/bin/sh\nprintf '%s\\n' \"$*\" > \"$ARGV_LOG\"\ncat >/dev/null\n",
    )
    env = {
        **os.environ,
        "PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}",
        "ANDROID_MCP_URL": "http://127.0.0.1:8765",
        "ANDROID_MCP_TOKEN_FILE": str(token_file),
        "ARGV_LOG": str(argv_log),
    }

    result = subprocess.run(
        ["sh", str(ANDROID_MCP_CLIENT), "DELETE", "/network/history"],
        cwd=REPO_ROOT, env=env, capture_output=True, text=True, check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "--request DELETE" in argv_log.read_text(encoding="utf-8")


def _doctor_environment(tmp_path: Path, *, port_busy: bool = False) -> dict[str, str]:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    meminfo = tmp_path / "meminfo"
    meminfo.write_text("MemTotal:       16777216 kB\n", encoding="utf-8")

    _write_executable(
        fake_bin / "uname",
        "#!/bin/sh\nprintf '%s\\n' '5.15.0-microsoft-standard-WSL2'\n",
    )
    _write_executable(
        fake_bin / "docker",
        "#!/bin/sh\n"
        "if [ \"${1:-}\" = info ]; then\n"
        "  if [ \"${2:-}\" = --format ]; then printf '%s\\n' \"$FAKE_DOCKER_ROOT\"; fi\n"
        "  exit 0\n"
        "fi\n"
        "if [ \"${1:-}\" = compose ] && [ \"${2:-}\" = version ]; then exit 0; fi\n"
        "exit 1\n",
    )
    ss_output = "LISTEN 0 128 127.0.0.1:8765 0.0.0.0:*" if port_busy else ""
    _write_executable(
        fake_bin / "ss",
        f"#!/bin/sh\nprintf '%s\\n' '{ss_output}'\n",
    )

    return {
        **os.environ,
        "PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}",
        "FAKE_DOCKER_ROOT": str(tmp_path),
        "ANDROID_LAB_KVM_PATH": "/dev/null",
        "ANDROID_LAB_MEMINFO_FILE": str(meminfo),
        "ANDROID_LAB_MIN_DISK_KIB": "1",
    }


def _run_android_lab(env: dict[str, str], *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["sh", str(ANDROID_LAB_SCRIPT), *args],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )


def _task_environment(
    tmp_path: Path,
    *,
    bridge_image_available: bool = True,
) -> dict[str, str]:
    env = _doctor_environment(tmp_path)
    fake_bin = tmp_path / "bin"
    docker_log = tmp_path / "docker.log"
    docker_log.touch()
    runtime_root = tmp_path / "runtime"
    runtime_root.mkdir()
    (runtime_root / "dispatch.yaml").write_text("workers: []\n", encoding="utf-8")
    _write_executable(
        fake_bin / "docker",
        "#!/bin/sh\n"
        "set -eu\n"
        "printf 'call\\t%s\\n' \"$*\" >> \"$FAKE_DOCKER_LOG\"\n"
        "if [ \"${1:-}\" = info ]; then\n"
        "  if [ \"${2:-}\" = --format ]; then printf '%s\\n' \"$FAKE_DOCKER_ROOT\"; fi\n"
        "  exit 0\n"
        "fi\n"
        "if [ \"${1:-}\" = compose ] && [ \"${2:-}\" = version ]; then exit 0; fi\n"
        "if [ \"${1:-}\" = image ] && [ \"${2:-}\" = inspect ]; then\n"
        "  [ \"$FAKE_BRIDGE_IMAGE_AVAILABLE\" = 1 ]\n"
        "  exit\n"
        "fi\n"
        "if [ \"${1:-}\" = inspect ]; then\n"
        "  [ \"$FAKE_CONTAINER_EXISTS\" = 1 ] || exit 1\n"
        "  printf '%s\\n' \"$FAKE_CONTAINER_PROJECT\"\n"
        "  exit 0\n"
        "fi\n"
        "if [ \"${1:-}\" = build ]; then\n"
        "  context=\n"
        "  for argument do context=$argument; done\n"
        "  [ -f \"$context/Dockerfile\" ]\n"
        "  case \" $* \" in\n"
        "    *' skidc-worker:latest '*) : ;;\n"
        "    *) [ -f \"$context/container/android-bridge/Dockerfile\" ] ;;\n"
        "  esac\n"
        "  [ ! -e \"$context/.pytest_cache\" ]\n"
        "  [ ! -e \"$context/datas\" ]\n"
        "  printf 'build-context\\t%s\\n' \"$context\" >> \"$FAKE_DOCKER_LOG\"\n"
        "  exit 0\n"
        "fi\n"
        "if [ \"${1:-}\" = run ]; then\n"
        "  case \" $* \" in\n"
        "    *' --entrypoint adb '*)\n"
        "      mount=\n"
        "      while [ \"$#\" -gt 0 ]; do\n"
        "        if [ \"$1\" = -v ]; then mount=$2; shift 2; else shift; fi\n"
        "      done\n"
        "      key_dir=${mount%:/keys}\n"
        "      printf '%s\\n' \"$FAKE_ADB_PRIVATE_KEY\" > \"$key_dir/adbkey\"\n"
        "      printf '%s\\n' \"$FAKE_ADB_PUBLIC_KEY\" > \"$key_dir/adbkey.pub\"\n"
        "      exit 0\n"
        "      ;;\n"
        "    *' skidc-worker:latest android-mcp GET /health/ready '*) exit 0 ;;\n"
        "  esac\n"
        "  exit 1\n"
        "fi\n"
        "if [ \"${1:-}\" = compose ]; then\n"
        "  case \" $* \" in\n"
        "    *' up '*) [ \"${ANDROID_ADBKEY:-}\" = \"$FAKE_ADB_PRIVATE_KEY\" ] ;;\n"
        "  esac\n"
        "  exit 0\n"
        "fi\n"
        "exit 1\n",
    )
    _write_executable(
        fake_bin / "openssl",
        "#!/bin/sh\n"
        "set -eu\n"
        "[ \"${1:-}\" = rand ] && [ \"${2:-}\" = -hex ] && [ \"${3:-}\" = 32 ]\n"
        "printf '%s\\n' \"$FAKE_ANDROID_MCP_TOKEN\"\n",
    )
    curl_log = tmp_path / "curl.log"
    curl_log.touch()
    _write_executable(
        fake_bin / "curl",
        "#!/bin/sh\n"
        "set -eu\n"
        "expected_token=$(cat \"$FAKE_SMOKE_TOKEN_FILE\")\n"
        "if env | grep -F \"$expected_token\" >/dev/null 2>&1; then\n"
        "  exit 89\n"
        "fi\n"
        "[ \"${1:-}\" = --disable ] || exit 91\n"
        "printf 'call\\t%s\\n' \"$*\" >> \"$FAKE_CURL_LOG\"\n"
        "case \" $* \" in\n"
        "  *' --config - '*)\n"
        "    auth_config=$(cat)\n"
        "    expected_config=\"header = \\\"Authorization: Bearer $expected_token\\\"\"\n"
        "    [ \"$auth_config\" = \"$expected_config\" ] || exit 90\n"
        "    printf 'auth\\tok\\n' >> \"$FAKE_CURL_LOG\"\n"
        "    ;;\n"
        "esac\n"
        "url=\n"
        "for argument do\n"
        "  case $argument in http://*|https://*) url=$argument ;; esac\n"
        "done\n"
        "if [ -n \"${FAKE_CURL_FAIL_PATTERN:-}\" ]; then\n"
        "  case $url in\n"
        "    *\"$FAKE_CURL_FAIL_PATTERN\"*)\n"
        "      printf '%s\\n' \"$FAKE_CURL_ERROR\" >&2\n"
        "      exit 22\n"
        "      ;;\n"
        "  esac\n"
        "fi\n"
        "exit 0\n",
    )
    return {
        **env,
        "ANDROID_LAB_RUNTIME_ROOT": str(runtime_root),
        "ANDROID_LAB_DATA_DIR": str(runtime_root / "datas/android-lab"),
        "ANDROID_LAB_ARTIFACT_DIR": str(runtime_root / "datas/android-artifacts"),
        "FAKE_DOCKER_LOG": str(docker_log),
        "FAKE_BRIDGE_IMAGE_AVAILABLE": "1" if bridge_image_available else "0",
        "FAKE_CONTAINER_EXISTS": "0",
        "FAKE_CONTAINER_PROJECT": "runtime",
        "FAKE_CURL_LOG": str(curl_log),
        "FAKE_CURL_FAIL_PATTERN": "",
        "FAKE_CURL_ERROR": "simulated curl failure",
        "FAKE_SMOKE_TOKEN_FILE": str(
            runtime_root / "datas/android-lab/secrets/android_mcp_token"
        ),
        "FAKE_ANDROID_MCP_TOKEN": "a" * 64,
        "FAKE_ADB_PRIVATE_KEY": "private-adb-key",
        "FAKE_ADB_PUBLIC_KEY": "public-adb-key",
    }


def _write_task_credentials(
    env: dict[str, str],
    *,
    token: bool = True,
    adb_key: bool = True,
) -> None:
    data_dir = Path(env["ANDROID_LAB_DATA_DIR"])
    if token:
        token_file = data_dir / "secrets/android_mcp_token"
        token_file.parent.mkdir(parents=True, exist_ok=True)
        token_file.write_text("test-token\n", encoding="utf-8")
    if adb_key:
        private_key = data_dir / "adb/adbkey"
        private_key.parent.mkdir(parents=True, exist_ok=True)
        private_key.write_text(env["FAKE_ADB_PRIVATE_KEY"] + "\n", encoding="utf-8")


def test_android_bridge_dockerfile_has_a_bounded_non_root_runtime() -> None:
    dockerfile_path = BRIDGE_DIR / "Dockerfile"
    assert dockerfile_path.is_file()

    dockerfile = dockerfile_path.read_text(encoding="utf-8")
    normalized = dockerfile.casefold()
    assert "from skidc-app:latest" in normalized
    assert "copy ./skidc /skidc" in normalized
    assert "user skidc-android" in normalized
    assert "healthcheck" in normalized
    assert "/health/ready" in dockerfile
    assert "/run/secrets/android_mcp_token" in dockerfile
    assert "/artifacts" in dockerfile
    assert "entrypoint" in normalized
    assert "sed -i 's/\\r$//' /usr/local/bin/android-bridge-entrypoint" in dockerfile
    assert "privileged" not in normalized
    assert "/var/run/docker.sock" not in dockerfile


def test_android_bridge_tool_versions_are_pinned() -> None:
    versions_path = BRIDGE_DIR / "tool-versions.env"
    assert versions_path.is_file()

    versions = dict(
        line.split("=", 1)
        for line in versions_path.read_text(encoding="utf-8").splitlines()
        if line and not line.startswith("#")
    )
    assert versions == {
        "JADX_VERSION": "1.5.5",
        "APKTOOL_VERSION": "3.0.3",
        "FRIDA_VERSION": "17.9.11",
    }


def test_android_bridge_entrypoint_rejects_missing_token_before_adb(tmp_path) -> None:
    entrypoint = BRIDGE_DIR / "entrypoint.sh"
    assert entrypoint.is_file()
    env = {
        **os.environ,
        "ANDROID_MCP_TOKEN_FILE": str(tmp_path / "missing-token"),
        "ADB_VENDOR_KEYS": str(tmp_path / "missing-adb-keys"),
    }

    result = subprocess.run(
        ["sh", str(entrypoint)],
        env=env,
        capture_output=True,
        text=True,
        timeout=5,
        check=False,
    )

    assert result.returncode != 0
    assert "Android Bridge token file is missing or unreadable" in result.stderr


def test_android_bridge_entrypoint_rejects_missing_adb_key(tmp_path) -> None:
    entrypoint = BRIDGE_DIR / "entrypoint.sh"
    token_file = tmp_path / "android-mcp-token"
    token_file.write_text("test-token", encoding="utf-8")
    env = {
        **os.environ,
        "ANDROID_MCP_TOKEN_FILE": str(token_file),
        "ADB_VENDOR_KEYS": str(tmp_path / "missing-adb-keys"),
    }

    result = subprocess.run(
        ["sh", str(entrypoint)],
        env=env,
        capture_output=True,
        text=True,
        timeout=5,
        check=False,
    )

    assert result.returncode != 0
    assert "ADB private key is missing or unreadable" in result.stderr


def test_android_profile_does_not_change_default_compose_services() -> None:
    services = _compose_config()["services"]
    default_services = {name for name, service in services.items() if not service.get("profiles")}

    assert default_services == {"skidc-server", "skidc-dispatcher"}
    assert services["android-emulator"]["profiles"] == ["android"]
    assert services["android-bridge"]["profiles"] == ["android"]


def test_android_emulator_is_kvm_bounded_and_does_not_publish_adb() -> None:
    emulator = _compose_config()["services"]["android-emulator"]

    assert emulator["image"] == (
        "us-docker.pkg.dev/android-emulator-268719/images/"
        "30-google-x64-no-metrics:30.1.2"
    )
    assert emulator["devices"] == ["/dev/kvm:/dev/kvm"]
    assert "ports" not in emulator
    assert emulator["environment"]["ADBKEY"] == "${ANDROID_ADBKEY:-}"
    assert emulator["mem_limit"] == "5g"
    assert emulator["cpus"] == 4
    assert emulator["shm_size"] == "2gb"
    assert emulator["networks"] == ["android-lab"]
    assert emulator.get("privileged") is not True


def test_android_bridge_is_loopback_only_read_only_and_resource_bounded() -> None:
    bridge = _compose_config()["services"]["android-bridge"]

    assert bridge["image"] == "skidc-android-bridge:latest"
    assert bridge["ports"] == ["127.0.0.1:8765:8765"]
    assert bridge["volumes"] == [
        "./datas/android-artifacts:/artifacts:ro",
        "./datas/android-lab/adb:/var/lib/skidc/android-adb:ro",
    ]
    assert "secrets" not in bridge
    assert bridge["environment"] == {
        "ANDROID_EMULATOR_SERIAL": "android-emulator:5555",
        "ADB_VENDOR_KEYS": "/var/lib/skidc/android-adb",
    }
    assert bridge["depends_on"] == {
        "android-emulator": {"condition": "service_started"}
    }
    assert bridge["read_only"] is True
    assert bridge["mem_limit"] == "1536m"
    assert bridge["cpus"] == 2
    assert bridge["pids_limit"] == 256
    assert bridge["networks"] == ["android-lab"]
    assert bridge.get("privileged") is not True
    assert all("docker.sock" not in volume for volume in bridge["volumes"])


def test_android_compose_secret_and_network_are_declared() -> None:
    compose = _compose_config()
    android_compose = _android_compose_config()

    assert "secrets" not in compose
    assert android_compose["secrets"]["android_mcp_token"] == {
        "file": "./datas/android-lab/secrets/android_mcp_token"
    }
    assert compose["networks"]["android-lab"] == {"driver": "bridge"}


def test_android_lab_doctor_accepts_a_ready_wsl_host(tmp_path) -> None:
    result = _run_android_lab(_doctor_environment(tmp_path), "doctor")

    assert result.returncode == 0, result.stderr
    assert "PASS WSL 2 environment" in result.stdout
    assert "PASS KVM device" in result.stdout
    assert "PASS Docker daemon" in result.stdout
    assert "PASS Docker Compose" in result.stdout
    assert "PASS visible memory" in result.stdout
    assert "PASS Docker storage" in result.stdout
    assert "PASS Bridge port 8765" in result.stdout


def test_android_lab_doctor_rejects_missing_kvm_but_checks_other_gates(tmp_path) -> None:
    env = _doctor_environment(tmp_path)
    env["ANDROID_LAB_KVM_PATH"] = str(tmp_path / "missing-kvm")

    result = _run_android_lab(env, "doctor")

    assert result.returncode != 0
    assert "FAIL KVM device" in result.stdout
    assert "PASS Docker daemon" in result.stdout
    assert "PASS Docker Compose" in result.stdout


def test_android_lab_doctor_rejects_an_occupied_bridge_port(tmp_path) -> None:
    result = _run_android_lab(
        _doctor_environment(tmp_path, port_busy=True),
        "doctor",
    )

    assert result.returncode != 0
    assert "FAIL Bridge port 8765" in result.stdout


def test_android_lab_build_uses_clean_committed_contexts_for_all_images(
    tmp_path,
) -> None:
    env = _task_environment(tmp_path)

    result = _run_android_lab(env, "build")

    assert result.returncode == 0, result.stderr
    log_lines = Path(env["FAKE_DOCKER_LOG"]).read_text(encoding="utf-8").splitlines()
    build_calls = [line for line in log_lines if line.startswith("call\tbuild ")]
    contexts = [
        Path(line.removeprefix("build-context\t"))
        for line in log_lines
        if line.startswith("build-context\t")
    ]
    assert len(build_calls) == 3
    assert "--pull=false -t skidc-app:latest" in build_calls[0]
    assert "--pull=false -t skidc-worker:latest" in build_calls[1]
    assert "--pull=false -t skidc-android-bridge:latest" in build_calls[2]
    assert build_calls[0].endswith(f"{contexts[0] / 'Dockerfile'} {contexts[0]}")
    assert build_calls[1].endswith(
        f"{contexts[0] / 'container/Dockerfile'} {contexts[0] / 'container'}"
    )
    assert build_calls[2].endswith(
        f"{contexts[2] / 'container/android-bridge/Dockerfile'} {contexts[2]}"
    )
    assert contexts[0] / "container" == contexts[1]
    assert contexts[0] == contexts[2]
    assert not contexts[0].exists()


def test_readmes_configure_dispatcher_to_reach_server_over_compose_network() -> None:
    for readme_name in ("README.md", "README.zh-CN.md"):
        readme = (REPO_ROOT / readme_name).read_text(encoding="utf-8")

        assert "server: http://skidc-server:8000" in readme


def test_android_lab_init_creates_credentials_once_without_printing_them(
    tmp_path,
) -> None:
    env = _task_environment(tmp_path)

    first = _run_android_lab(env, "init")

    assert first.returncode == 0, first.stderr
    data_dir = Path(env["ANDROID_LAB_DATA_DIR"])
    artifact_dir = Path(env["ANDROID_LAB_ARTIFACT_DIR"])
    token_file = data_dir / "secrets/android_mcp_token"
    private_key = data_dir / "adb/adbkey"
    public_key = data_dir / "adb/adbkey.pub"
    assert token_file.read_text(encoding="utf-8").strip() == "a" * 64
    assert private_key.read_text(encoding="utf-8").strip() == "private-adb-key"
    assert public_key.read_text(encoding="utf-8").strip() == "public-adb-key"
    assert token_file.stat().st_mode & 0o777 == 0o600
    assert private_key.stat().st_mode & 0o777 == 0o600
    assert public_key.stat().st_mode & 0o777 == 0o600
    assert data_dir.stat().st_mode & 0o777 == 0o700
    assert (data_dir / "adb").stat().st_mode & 0o777 == 0o700
    assert (data_dir / "secrets").stat().st_mode & 0o777 == 0o700
    assert artifact_dir.stat().st_mode & 0o777 == 0o700
    combined_output = first.stdout + first.stderr
    assert "a" * 64 not in combined_output
    assert "private-adb-key" not in combined_output

    env["FAKE_ANDROID_MCP_TOKEN"] = "b" * 64
    env["FAKE_ADB_PRIVATE_KEY"] = "replacement-private-key"
    second = _run_android_lab(env, "init")

    assert second.returncode == 0, second.stderr
    assert token_file.read_text(encoding="utf-8").strip() == "a" * 64
    assert private_key.read_text(encoding="utf-8").strip() == "private-adb-key"
    docker_log = Path(env["FAKE_DOCKER_LOG"]).read_text(encoding="utf-8")
    assert docker_log.count("call\trun ") == 1


def test_android_lab_init_requires_bridge_image_before_writing_credentials(
    tmp_path,
) -> None:
    env = _task_environment(tmp_path, bridge_image_available=False)

    result = _run_android_lab(env, "init")

    assert result.returncode != 0
    assert "run ./scripts/android-lab.sh build first" in result.stderr
    data_dir = Path(env["ANDROID_LAB_DATA_DIR"])
    assert not (data_dir / "secrets/android_mcp_token").exists()
    assert not (data_dir / "adb/adbkey").exists()


def test_android_lab_init_rejects_an_incomplete_existing_adb_pair(tmp_path) -> None:
    env = _task_environment(tmp_path)
    adb_dir = Path(env["ANDROID_LAB_DATA_DIR"]) / "adb"
    adb_dir.mkdir(parents=True)
    private_key = adb_dir / "adbkey"
    private_key.write_text("keep-this-key\n", encoding="utf-8")

    result = _run_android_lab(env, "init")

    assert result.returncode != 0
    assert "ADB keypair is incomplete" in result.stderr
    assert private_key.read_text(encoding="utf-8") == "keep-this-key\n"
    assert not (adb_dir / "adbkey.pub").exists()
    docker_log = Path(env["FAKE_DOCKER_LOG"]).read_text(encoding="utf-8")
    assert "call\trun " not in docker_log


def test_android_lab_runtime_root_defaults_credentials_and_artifacts(tmp_path) -> None:
    env = _task_environment(tmp_path)
    env.pop("ANDROID_LAB_DATA_DIR")
    env.pop("ANDROID_LAB_ARTIFACT_DIR")

    result = _run_android_lab(env, "init")

    assert result.returncode == 0, result.stderr
    runtime_root = Path(env["ANDROID_LAB_RUNTIME_ROOT"])
    assert (runtime_root / "datas/android-lab/adb/adbkey").is_file()
    assert (runtime_root / "datas/android-lab/adb/adbkey.pub").is_file()
    assert (runtime_root / "datas/android-lab/secrets/android_mcp_token").is_file()
    assert (runtime_root / "datas/android-artifacts").is_dir()


@pytest.mark.parametrize(
    ("case", "expected_error"),
    [
        ("relative", "Android Lab runtime root must be an absolute path"),
        ("missing", "Android Lab runtime root does not exist"),
        ("no_dispatch", "dispatch.yaml is missing or unreadable"),
    ],
)
def test_android_lab_runtime_root_rejects_invalid_runtime_before_writes(
    tmp_path,
    case,
    expected_error,
) -> None:
    case_dir = tmp_path / case
    case_dir.mkdir()
    env = _task_environment(case_dir)
    env.pop("ANDROID_LAB_DATA_DIR")
    env.pop("ANDROID_LAB_ARTIFACT_DIR")
    if case == "relative":
        env["ANDROID_LAB_RUNTIME_ROOT"] = "relative-runtime"
    elif case == "missing":
        env["ANDROID_LAB_RUNTIME_ROOT"] = str(case_dir / "missing-runtime")
    else:
        runtime_root = case_dir / "runtime-without-dispatch"
        runtime_root.mkdir()
        env["ANDROID_LAB_RUNTIME_ROOT"] = str(runtime_root)

    result = _run_android_lab(env, "init")

    assert result.returncode != 0
    assert expected_error in result.stderr
    docker_log = Path(env["FAKE_DOCKER_LOG"]).read_text(encoding="utf-8")
    assert docker_log == ""


def test_android_lab_unified_up_starts_web_and_android_services(tmp_path) -> None:
    env = _task_environment(tmp_path)
    _write_task_credentials(env)
    env["FAKE_CONTAINER_EXISTS"] = "1"

    result = _run_android_lab(env, "up")

    assert result.returncode == 0, result.stderr
    docker_log = Path(env["FAKE_DOCKER_LOG"]).read_text(encoding="utf-8")
    runtime_root = Path(env["ANDROID_LAB_RUNTIME_ROOT"])
    assert (
        f"call\tcompose --project-directory {runtime_root} --project-name runtime "
        f"-f {COMPOSE_FILE} -f {ANDROID_COMPOSE_FILE} --profile android up -d "
        "skidc-server skidc-dispatcher "
        "android-emulator android-bridge"
    ) in docker_log
    assert env["FAKE_ADB_PRIVATE_KEY"] not in result.stdout + result.stderr


@pytest.mark.parametrize(
    ("missing", "expected_error"),
    [
        ("token", "Android MCP token is missing or empty"),
        ("adb_key", "ADB private key is missing or empty"),
        ("image", "Android Bridge image is unavailable"),
    ],
)
def test_android_lab_lifecycle_up_rejects_missing_prerequisites(
    tmp_path,
    missing,
    expected_error,
) -> None:
    case_dir = tmp_path / missing
    case_dir.mkdir()
    env = _task_environment(
        case_dir,
        bridge_image_available=missing != "image",
    )
    _write_task_credentials(
        env,
        token=missing != "token",
        adb_key=missing != "adb_key",
    )

    result = _run_android_lab(env, "up")

    assert result.returncode != 0
    assert expected_error in result.stderr
    docker_log = Path(env["FAKE_DOCKER_LOG"]).read_text(encoding="utf-8")
    assert " --profile android up " not in docker_log


def test_android_lab_lifecycle_rejects_foreign_compose_container(tmp_path) -> None:
    env = _task_environment(tmp_path)
    _write_task_credentials(env)
    env["FAKE_CONTAINER_EXISTS"] = "1"
    env["FAKE_CONTAINER_PROJECT"] = "other-project"

    result = _run_android_lab(env, "up")

    assert result.returncode != 0
    assert "skidc-server belongs to Compose project other-project" in result.stderr
    assert "requested project is runtime" in result.stderr
    docker_log = Path(env["FAKE_DOCKER_LOG"]).read_text(encoding="utf-8")
    assert " --profile android up " not in docker_log


def test_android_lab_lifecycle_down_keeps_persistent_data(tmp_path) -> None:
    env = _task_environment(tmp_path)

    result = _run_android_lab(env, "down")

    assert result.returncode == 0, result.stderr
    docker_log = Path(env["FAKE_DOCKER_LOG"]).read_text(encoding="utf-8")
    runtime_root = Path(env["ANDROID_LAB_RUNTIME_ROOT"])
    assert (
        f"call\tcompose --project-directory {runtime_root} --project-name runtime "
        f"-f {COMPOSE_FILE} -f {ANDROID_COMPOSE_FILE} --profile android down\n"
    ) in docker_log
    assert " -v" not in docker_log


def test_android_lab_lifecycle_status_lists_all_services(tmp_path) -> None:
    env = _task_environment(tmp_path)

    result = _run_android_lab(env, "status")

    assert result.returncode == 0, result.stderr
    docker_log = Path(env["FAKE_DOCKER_LOG"]).read_text(encoding="utf-8")
    runtime_root = Path(env["ANDROID_LAB_RUNTIME_ROOT"])
    assert (
        f"call\tcompose --project-directory {runtime_root} --project-name runtime "
        f"-f {COMPOSE_FILE} -f {ANDROID_COMPOSE_FILE} --profile android ps "
        "skidc-server skidc-dispatcher "
        "android-emulator android-bridge"
    ) in docker_log


def test_android_lab_smoke_checks_all_required_web_and_android_paths(tmp_path) -> None:
    env = _task_environment(tmp_path)
    _write_task_credentials(env)

    result = _run_android_lab(env, "smoke")

    assert result.returncode == 0, result.stderr
    expected_checks = [
        "Web Server health",
        "Android Bridge readiness",
        "ADB device listing",
        "Android screenshot",
        "Android UI tree",
        "Android HOME key",
        "Android worker client",
    ]
    for check_name in expected_checks:
        assert f"PASS {check_name}" in result.stdout
    curl_log = Path(env["FAKE_CURL_LOG"]).read_text(encoding="utf-8")
    call_lines = [line for line in curl_log.splitlines() if line.startswith("call\t")]
    assert call_lines == [
        "call\t--disable --fail --silent --show-error --max-time 15 "
        "--output /dev/null --request GET http://127.0.0.1:8000/projects",
        "call\t--disable --config - --fail --silent --show-error --max-time 15 "
        "--output /dev/null --request GET http://127.0.0.1:8765/health/ready",
        "call\t--disable --config - --fail --silent --show-error --max-time 15 "
        "--output /dev/null --request GET http://127.0.0.1:8765/devices",
        "call\t--disable --config - --fail --silent --show-error --max-time 15 "
        "--output /dev/null --request GET http://127.0.0.1:8765/observe/screenshot",
        "call\t--disable --config - --fail --silent --show-error --max-time 15 "
        "--output /dev/null --request GET http://127.0.0.1:8765/observe/ui",
        "call\t--disable --config - --fail --silent --show-error --max-time 15 "
        "--output /dev/null --request POST http://127.0.0.1:8765/input/home",
    ]
    assert curl_log.count("auth\tok") == 5
    assert " -H " not in curl_log
    assert "test-token" not in curl_log
    assert "test-token" not in result.stdout + result.stderr


def test_android_lab_smoke_applies_configured_timeout_to_every_check(tmp_path) -> None:
    env = _task_environment(tmp_path)
    _write_task_credentials(env)
    env["ANDROID_LAB_SMOKE_TIMEOUT_SECONDS"] = "3"

    result = _run_android_lab(env, "smoke")

    assert result.returncode == 0, result.stderr
    call_lines = [
        line
        for line in Path(env["FAKE_CURL_LOG"]).read_text(encoding="utf-8").splitlines()
        if line.startswith("call\t")
    ]
    assert len(call_lines) == 6
    assert all(" --max-time 3 " in line for line in call_lines)


@pytest.mark.parametrize(
    ("failure_path", "failed_check"),
    [
        ("/projects", "Web Server health"),
        ("/health/ready", "Android Bridge readiness"),
        ("/devices", "ADB device listing"),
        ("/observe/screenshot", "Android screenshot"),
        ("/observe/ui", "Android UI tree"),
        ("/input/home", "Android HOME key"),
    ],
)
def test_android_lab_smoke_fails_boundedly_but_attempts_every_check(
    tmp_path,
    failure_path,
    failed_check,
) -> None:
    env = _task_environment(tmp_path)
    _write_task_credentials(env)
    env["FAKE_CURL_FAIL_PATTERN"] = failure_path
    env["FAKE_CURL_ERROR"] = "x" * 5000

    result = _run_android_lab(env, "smoke")

    assert result.returncode != 0
    assert f"FAIL {failed_check}" in result.stdout
    curl_log = Path(env["FAKE_CURL_LOG"]).read_text(encoding="utf-8")
    assert curl_log.count("call\t") == 6
    assert len(result.stdout + result.stderr) < 1024
    assert "test-token" not in result.stdout + result.stderr


def test_android_lab_rejects_unknown_commands_with_usage(tmp_path) -> None:
    result = _run_android_lab(_doctor_environment(tmp_path), "unknown")

    assert result.returncode == 2
    assert "Usage: android-lab.sh" in result.stderr


def test_android_lab_script_uses_lf_line_endings() -> None:
    assert b"\r\n" not in ANDROID_LAB_SCRIPT.read_bytes()


def _git_index_mode(relative_path: str) -> str:
    env = dict(os.environ)
    git_dir = REPO_ROOT / ".git"
    if git_dir.is_file():
        location = git_dir.read_text(encoding="utf-8").strip().removeprefix("gitdir: ")
        normalized = location.replace("\\", "/")
        if os.name != "nt" and len(normalized) >= 3 and normalized[1:3] == ":/":
            normalized = f"/mnt/{normalized[0].lower()}/{normalized[3:]}"
        env["GIT_DIR"] = normalized
        env["GIT_WORK_TREE"] = str(REPO_ROOT)

    result = subprocess.run(
        ["git", "ls-files", "--stage", "--", relative_path],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=5,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    return result.stdout.split(maxsplit=1)[0]


def test_android_lab_script_is_committed_executable() -> None:
    assert _git_index_mode("scripts/android-lab.sh") == "100755"
