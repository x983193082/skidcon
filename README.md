<div align="center">

**[🇨🇳 中文](README.zh-CN.md)** | **[🇬🇧 English](README.md)**

# Skidc

### Multi-Agent Automated Penetration Testing Platform

*Define an **origin** and a **goal**. Skidc orchestrates LLM-powered agents*
*to autonomously plan, execute, and verify penetration testing workflows —*
*across Web, API, and Android targets.*

</div>

---

## What is Skidc?

Skidc is an automated penetration testing platform that uses multiple LLM-powered agents
to drive the full pentest lifecycle — from reconnaissance through exploitation — without
manual step-by-step scripting.

You describe **where you start** (a target IP, URL, APK, or domain) and **what success
looks like** (get a shell, capture the flag, find an IDOR). Skidc's dispatcher breaks the
problem into parallel exploration tasks, runs them inside isolated Docker containers, and
writes every confirmed finding back to a shared task graph that drives the next round of
reasoning.

### Core capabilities

| Capability | Description |
|------------|-------------|
| **Phased pentest with gate control** | RECON → Explore phase transition is driven by the project's `recon_profile`, so domain, IP, API, Android, and mixed targets can use different required evidence |
| **Android MCP Bridge** | 18 HTTP endpoints for mobile app control — UI interaction, screenshot, network capture — seamlessly integrated into the pentest workflow |
| **Fact–intent task graph** | Every confirmed finding (fact) and exploration direction (intent) is tracked, visualized, and used to drive the next reasoning cycle |
| **Attack path annotation** | Exploitation chains are automatically identified with severity assessment (critical / high / medium / low) |
| **Pluggable LLM backends** | Swap between DeepSeek, Qwen, Claude, or any compatible model — agent CLI and LLM are fully decoupled |
| **Two-phase conclude** | Timeouts don't lose work — the same agent session is resumed to harvest partial results |

---

## How it works

### Architecture

```
              ┌────────────────────────────────────┐
              │           Skidc Server             │   truth source:
              │   Facts + Intents + Hints + Paths  │   graph consistency only
              └─────────────────┬──────────────────┘
                                │  read / write protocol API
              ┌─────────────────┴──────────────────┐
              │             Dispatcher             │   sole protocol writer:
              │  schedule → claim lease → run →    │   leases, heartbeats, timeouts,
              │  parse → write back → cleanup      │   container lifecycle
              └──────────┬───────────────┬─────────┘
                         │               │
              ┌──────────┴─────┐  ┌──────┴───────────┐   one container per project;
              │ Worker (proj A)│  │ Worker (proj B)  │   agents exec inside it,
              │  claude→DeepSeek│  │  codex→Qwen      │   coordinate via the graph only
              └─────────────────┘  └──────────────────┘
```

**Server** (FastAPI + SQLite) keeps the task graph consistent and owns the intent-claim /
reason-lease state machine. **Dispatcher** is the only component that writes to the
protocol: it reads the graph, decides the task type per project, claims a lease, runs the
worker in that project's container, parses the structured JSON result, and writes it back.

### Three task types

All tasks are executed by the same universal worker inside a Docker container:

| Task | Trigger | What it does | Output |
|------|---------|-------------|--------|
| **Bootstrap** | Project is in its initial state | Try to solve the whole problem directly | Fact + possible Complete |
| **Reason** | New facts appeared, or no open intents | Read the full graph: goal met? what to explore next? | Complete / new Intents / no-op |
| **Explore** | An unclaimed open intent exists | Claim one intent, execute it, report findings | One Fact |

Both `bootstrap` and `explore` are **two-phase**: if the main attempt times out or returns
unparseable output, the dispatcher resumes the *same agent session* with a `conclude`
prompt — "stop working, just summarize what you confirmed" — so partial progress is
preserved instead of being thrown away.

### Phased pentest with RECON gate

When a project starts in `recon` phase (real-website mode), the dispatcher enforces a
profile-aware **gate check** before allowing the workflow to proceed to exploitation:

| RECON Category | Evidence Required |
|----------------|-------------------|
| Port scan | nmap / naabu results with open ports and services |
| Subdomain | subfinder / amass / DNS enumeration results |
| Directory | ffuf / gobuster / dirsearch path discovery |
| Asset | katana / crawler results with URLs and JS files |

Only the categories listed in the project's `recon_profile.required_categories` must be
covered before the system transitions from `recon` to `explore`. For example, a single-IP
assessment can disable subdomain enumeration, while an Android assessment can require
`android_app`, `android_ui`, and `mobile_api` instead of web categories. When the gate
passes, potential sub-targets (subdomains, open services, interesting paths) are extracted
and written to the graph as new facts without duplicating them after dispatcher restarts.

---

## The model is not hard-coded

A worker's **`type`** selects the *agent CLI loop*; the worker's **`env`** selects the
*actual LLM* behind it. They are decoupled, so you mix and match freely:

| Worker `type` | Agent CLI it drives | Endpoint it talks to (set via env) | Example model |
|---------------|---------------------|------------------------------------|---------------|
| `claudecode`  | `claude`            | `ANTHROPIC_BASE_URL` (Anthropic-compatible) | **DeepSeek** (`https://api.deepseek.com/anthropic`) |
| `codex`       | `codex`             | `CODEX_BASE_URL` (OpenAI/Responses-compatible) | **Qwen** (`https://dashscope.aliyuncs.com/compatible-mode/v1`) |
| `mock`        | a local script      | none — deterministic outcomes for testing | — |

```yaml
# Run DeepSeek through the Claude Code agent loop:
- name: "claudecode_deepseek"
  type: "claudecode"
  env:
    ANTHROPIC_MODEL: "deepseek-v4-flash"
    ANTHROPIC_BASE_URL: "https://api.deepseek.com/anthropic"
    ANTHROPIC_AUTH_TOKEN: "<YOUR_ANTHROPIC_AUTH_TOKEN>"

# Run Qwen through the Codex agent loop:
- name: "codex_qwen"
  type: "codex"
  env:
    CODEX_MODEL: "qwen3.7-plus"
    CODEX_BASE_URL: "https://dashscope.aliyuncs.com/compatible-mode/v1"
    OPENAI_API_KEY: "<YOUR_OPENAI_API_KEY>"
```

Swapping models is a config edit. Adding a new backend is one new driver file in
`workers/adapters/`.

---

## Android Docker Lab (WSL2)

Skidc includes an Android security-testing environment designed for a Docker Engine running
inside WSL2. The Android path does not replace the Web path: the same startup command runs
the Web Server and Dispatcher together with an isolated Emulator and authenticated Bridge,
and the project target type determines which prompt and tools a worker receives.

| Component | Purpose |
|-----------|---------|
| `skidc-server` | Dashboard, project API, Fact-Intent graph, evidence and reports |
| `skidc-dispatcher` | Selects the Android prompt group and schedules isolated workers |
| `android-emulator` | KVM-accelerated Android 11 test device |
| `android-bridge` | Authenticated ADB, observation and bounded APK-analysis API |

### Requirements

- WSL2 with Docker Engine and Docker Compose v2 available inside the distribution.
- `/dev/kvm` visible to WSL2; the Lab will not silently fall back to slow software emulation.
- At least 14 GiB memory visible inside WSL2 and 30 GiB free in Docker storage.
- Local ports `8000` and `8765` available. Port `8765` is bound to loopback only.
- An LLM provider key in the local `dispatch.yaml`. This file is ignored by Git; do not put
  the Android Bridge token in it because the Lab creates and mounts that token automatically.

### First startup

Run these commands in WSL2 from the repository root:

```bash
# 1. Create the local dispatcher configuration once, then replace the provider placeholder.
[ -e dispatch.yaml ] || cp dispatch_android.example.yaml dispatch.yaml
nano dispatch.yaml
# Because Dispatcher runs in Compose, set this field in dispatch.yaml:
# server: http://skidc-server:8000
# Then replace the selected worker's provider-key placeholder.

# 2. Verify WSL2, KVM, Docker, memory, disk and the Bridge port.
./scripts/android-lab.sh doctor

# 3. Build skidc-app, skidc-worker and skidc-android-bridge from the committed source tree.
./scripts/android-lab.sh build

# 4. Generate the local ADB key, Bridge bearer token and APK artifact directory.
./scripts/android-lab.sh init

# 5. Start Web Server, Dispatcher, Android Emulator and Android Bridge together.
./scripts/android-lab.sh up

# 6. Check until all four services report Up and both Android services report healthy.
./scripts/android-lab.sh status

# 7. Verify the server, authenticated Bridge, ADB, screenshot, UI tree and worker client.
./scripts/android-lab.sh smoke
```

The emulator image is downloaded on the first `up` and is large. If the registry connection
is unreliable, pull it explicitly and retry:

```bash
docker pull us-docker.pkg.dev/android-emulator-268719/images/30-google-x64-no-metrics:30.1.2
```

`smoke` does not wait for an emulator that is still booting. If `status` says `health: starting`,
wait for it to become `healthy` and run `smoke` again.

Normally the runtime root is the current checkout. When running the script from a Git worktree
but reusing `dispatch.yaml`, credentials, artifacts and containers owned by another checkout,
point it at that absolute WSL path before `init`, `up`, `status`, `smoke` and `down`:

```bash
export ANDROID_LAB_RUNTIME_ROOT=/mnt/d/path/to/skidcon-skidc
```

The script validates Compose ownership and refuses to reuse `skidc-server` or
`skidc-dispatcher` containers belonging to a different runtime root.

### Run an Android assessment

1. Copy an authorized APK into the runtime artifact directory:

   ```bash
   android_runtime_root=${ANDROID_LAB_RUNTIME_ROOT:-"$PWD"}
   cp /mnt/c/path/to/demo.apk "$android_runtime_root/datas/android-artifacts/demo.apk"
   ```

   This uses `./datas/android-artifacts/` when `ANDROID_LAB_RUNTIME_ROOT` is not set.

2. Open <http://127.0.0.1:8000>, click **New Project**, choose **Real Website mode**, then set
   **Target type** to **Android**. Android currently uses this guarded/RECON project form; it
   is routed by `recon_profile.target_type: android`, not by the Web target itself.
3. Enter an authorized target description. The APK path must be the path visible inside the
   Bridge container:

   ```text
   APK: /artifacts/demo.apk
   Package: com.example.demo
   Device: Docker Android Emulator
   Test accounts: user_a / user_b
   Authorization: only this APK, package, emulator and the stated accounts
   ```

4. Enter the assessment goal and create the project. The Dispatcher selects the Android
   prompt group, provisions the Bridge credential only inside that Android worker, and runs
   the Fact-Intent loop. Web, API and CTF projects continue to use the default prompt group
   and receive no Android Bridge credential.

The Android workflow combines bounded static analysis (`aapt`, `apktool`, `jadx`) with runtime
observation and controlled actions: install/start the app, inspect Activity and UI state,
capture screenshots and Logcat, operate controls, test mobile API behavior, independently
verify candidates, and write evidence-backed Facts. Static findings are leads and must be
confirmed with runtime evidence before they are treated as reproduced findings.

### Operations

| Command | Effect |
|---------|--------|
| `./scripts/android-lab.sh doctor` | Read-only host prerequisite checks |
| `./scripts/android-lab.sh build` | Rebuild app, worker and Bridge images |
| `./scripts/android-lab.sh init` | Create missing local credentials and artifact directories |
| `./scripts/android-lab.sh up` | Start Web, Dispatcher, Emulator and Bridge |
| `./scripts/android-lab.sh status` | Show the four service states and health |
| `./scripts/android-lab.sh smoke` | Exercise the authenticated end-to-end control path |
| `./scripts/android-lab.sh down` | Stop this Lab while preserving bind-mounted project data |

Use `build` again after pulling source changes that affect an image. Use `up` after a normal
shutdown; `init` is idempotent and does not overwrite an existing complete key/token set.

### Endpoint overview

| Area | Endpoints |
|------|-----------|
| Device status | `GET /health`, `GET /devices` |
| App lifecycle | `POST /app/install`, `/app/start`, `/app/stop`, `/app/clear` |
| Input control | `POST /input/tap`, `/input/text`, `/input/swipe`, `/input/back`, `/input/home`, `/input/key` |
| Observation | `GET /observe/ui`, `/observe/activity`, `/observe/screenshot`, `POST /observe/logcat` |
| Network capture | `GET /network/history`, `POST /network/events`, `DELETE /network/history` |
| APK static analysis | `POST /reverse/analyze`, `GET /reverse/reports`, `DELETE /reverse/reports` |

`/reverse/analyze` keeps the bounded ZIP/string baseline and invokes the Bridge image's
`aapt`, `apktool`, and `jadx` tools in an ephemeral workspace. The response reports
`analysis_level`, per-tool `tool_runs`, package/SDK metadata, decoded Manifest security
settings and exported components, Deep Links, and bounded `code_findings` with relative
`evidence_ref` locations. Tool failures are isolated, and static findings remain leads that
must be confirmed through runtime evidence.

### Configuring for Android targets

Use `dispatch_android.example.yaml`, or add these settings to the existing `dispatch.yaml`:

```yaml
runtime:
  prompt_group: "default"
  target_prompt_groups:
    android: "android"

android_bridge:
  url: "http://127.0.0.1:8765"
  token_file: "/run/secrets/android_mcp_token"
  worker_token_file: "/run/skidc/android-mcp-token"
  readiness_timeout: 15
```

Never put the token value in `dispatch.yaml`, prompts, or worker environment values.
`android-lab.sh` loads `docker-compose.android.yaml`, which mounts the same read-only
secret into the Dispatcher and Bridge. The Dispatcher provisions a mode-`0600` file
only inside Android project workers.

Current boundary: `/network/history` stores events imported by an external proxy/add-on; the
Lab does not yet start mitmproxy, install its CA, or bypass certificate pinning automatically.
Likewise, Frida endpoints expose script metadata and store externally produced observations;
they do not automatically start Frida Server or inject a process.

See [ANDROID_MCP.md](ANDROID_MCP.md) for the full bridge documentation.

---

## Project layout

```
skidc\
├─ skidc\                         # the Python package (uv project)
│  ├─ src\skidc\
│  │  ├─ server\                  # FastAPI + SQLite task graph
│  │  │  ├─ db.py  models.py  services.py  app.py
│  │  │  ├─ routers\             # projects, intents, hints, settings, export
│  │  │  └─ static\index.html    # live graph dashboard (zero-dependency)
│  │  ├─ dispatcher\
│  │  │  ├─ config.py            # dispatch.yaml schema + model-swap env wiring
│  │  │  ├─ contracts.py         # strict JSON output validation
│  │  │  ├─ scheduler\loop.py    # the control plane / decision tree
│  │  │  ├─ tasks\               # bootstrap / reason / explore (+ conclude)
│  │  │  ├─ workers\             # driver abstraction
│  │  │  │  └─ adapters\         #   claudecode, codex, mock
│  │  │  ├─ runtime\             # docker exec, heartbeat lease, cancellation
│  │  │  ├─ recon_extractor.py   # RECON gate check + sub-target extraction
│  │  │  └─ prompts\             # default\ (offensive) + android\ (mobile) + mock\
│  │  ├─ android_mcp\            # Android MCP Bridge (FastAPI + ADB)
│  │  └─ cli.py                  # `skidc serve` / `skidc dispatch` / `skidc android-mcp`
│  └─ tests\                     # run with no Docker and no LLM
├─ container\                    # Kali worker image (Dockerfile + AGENTS.md)
├─ benchmark\                    # XBOW benchmark harness
├─ dispatch.example.yaml         # Web/API pentest template
├─ dispatch_android.example.yaml # Android pentest template
├─ dispatch_mock.yaml            # mock-only setup for local testing
├─ Dockerfile                    # builds skidc-app (server + dispatcher image)
├─ docker-compose.yaml
├─ ANDROID_MCP.md                # Android Bridge usage guide
└─ README.md
```

---

## Getting started

### Prerequisites

- **OS**: Windows 10/11 with WSL2, macOS, or Linux
- **Docker Engine + Docker Compose v2**. Docker Desktop is optional; the Android Docker Lab
  described above is designed for Docker Engine running directly inside WSL2.
- **Python >= 3.12** and [uv](https://docs.astral.sh/uv/) — only needed for `uv run skidc serve / dispatch`; **not needed if you only use Docker Compose**
- For the Android Lab: KVM, at least **14 GiB WSL-visible memory**, and **30 GiB free Docker storage**

### Path A — Web/API/CTF with Docker Compose (no Python needed)

```powershell
# 1. Build the worker image (Kali + claude-code + codex). ~5-15 min, ~4.6 GB.
docker build -t skidc-worker:latest -f container/Dockerfile container

# 2. Create your dispatcher config from the template, then fill in LLM keys.
copy dispatch.example.yaml dispatch.yaml
notepad dispatch.yaml                  # set server: http://skidc-server:8000 and fill in the provider key

# 3. Build the app image and start everything.
docker compose up -d --build
```

`dispatch.yaml` is ignored by git and is meant to stay local. If a real provider key was
ever committed or shared, rotate it in the provider console; replacing it with a placeholder
in this repository does not invalidate the old key.

`docker compose up -d --build` will:
- build `skidc-app` (the server + dispatcher image) from the root `Dockerfile`
- start `skidc-server` (port 8000) and `skidc-dispatcher`
- mount `datas/skidc/` to `/root/.local/share/skidc/` inside the server
  (this is where the SQLite db lives; survives restarts)

To verify:

```powershell
docker ps --filter "name=skidc" --format "table {{.Names}}\t{{.Status}}"
# Expect: skidc-server (healthy), skidc-dispatcher (Up)

curl http://127.0.0.1:8000/projects
# Expect: [] (empty project list)
```

Open http://127.0.0.1:8000 to see the dashboard.

To start Web and Android capabilities together, use the complete
[Android Docker Lab](#android-docker-lab-wsl2) procedure instead.

### Path B — `uv` directly (development; bypasses Docker for the app, still uses Docker for workers)

```powershell
# terminal 1: start the server
cd skidc
uv sync
uv run skidc serve --host 0.0.0.0

# terminal 2: start the dispatcher
cp dispatch.example.yaml dispatch.yaml
notepad dispatch.yaml
cd skidc
uv run skidc dispatch --config ..\dispatch.yaml

# Validate only your worker LLM configs (one ping per worker) and exit:
uv run skidc dispatch --config ..\dispatch.yaml --startup-healthcheck-only
```

### Path C — Tests only (no Docker, no LLM)

```powershell
cd skidc
uv sync --group dev
uv run --group dev pytest
```

Drives the **entire pipeline** — server protocol, scheduler decision tree, all three
task types, the two-phase conclude fallback, and the model-swap drivers — in-process
using the `mock` worker.

---

## Daily use

### Start a project

1. Open http://127.0.0.1:8000 in a browser.
2. Click **New Project**, fill in:
   - **Origin**: target IP / URL / domain / APK path
   - **Goal**: success condition (e.g. `get the root shell`, `find IDOR vulnerabilities`)
   - **Hints** (optional): things you already know (open ports, banners, credentials)
3. Submit. The dispatcher picks a worker, spawns a container, and starts the pentest loop.

For real websites, define the safety boundary at project creation time. The UI exposes
these fields, and the same structure can be sent to the API:

```json
{
  "title": "authorized web assessment",
  "origin": "https://app.example.test",
  "goal": "find authorization flaws within the agreed scope",
  "mode": "real_website",
  "bootstrap_enabled": false,
  "scope_policy": {
    "allowed_targets": ["app.example.test", "api.example.test"],
    "blocked_targets": ["admin.example.test"],
    "allowed_ports": [80, 443],
    "blocked_ports": [22],
    "allowed_paths": ["/app/"],
    "blocked_paths": ["/private/"],
    "support_ports": [3306],
    "allow_subdomains": false,
    "allow_domain_scan": false,
    "rate_limits": {},
    "passive_only": false
  },
  "recon_profile": {
    "target_type": "domain",
    "required_categories": ["port_scan", "subdomain", "directory", "asset"],
    "optional_categories": [],
    "disabled_categories": []
  }
}
```

The dispatcher injects this policy into worker prompts and performs basic structured
intent checks before dispatch, so obvious out-of-scope targets, blocked ports, and
passive-only violations are skipped instead of being executed.

### Watch progress

| What you want to see | Where to look |
|----------------------|---------------|
| The fact/intent graph growing | Dashboard (auto-refreshes) |
| What the agent is currently running | `docker exec <worker-container> ps aux` |
| Why a task was cancelled | `docker logs skidc-dispatcher --tail 100` |
| Which LLM call failed | `docker logs skidc-dispatch-proj_xxx` |

### Stop the system

```powershell
# Graceful stop (data preserved)
docker compose down

# Force stop (loses in-flight tasks)
docker compose down -v
```

### Restart after shutdown

```powershell
docker compose up -d
```

No rebuild needed — images are cached. Dashboard is ready in ~10 seconds.

---

## Swap the LLM brain

The agent CLI loop and the LLM behind it are decoupled. To switch:

1. Edit `dispatch.yaml`. The `env:` block of each worker is the only place to touch.
2. Common swaps:

| Want | Worker `type` | Required env |
|------|---------------|--------------|
| DeepSeek (Claude Code loop) | `claudecode` | `ANTHROPIC_BASE_URL`, `ANTHROPIC_MODEL`, `ANTHROPIC_AUTH_TOKEN` |
| Qwen (Codex loop) | `codex` | `CODEX_BASE_URL`, `CODEX_MODEL`, `OPENAI_API_KEY` |
| Anthropic Claude (real) | `claudecode` | `ANTHROPIC_BASE_URL=https://api.anthropic.com`, `ANTHROPIC_MODEL=claude-sonnet-4-5`, `ANTHROPIC_AUTH_TOKEN=<YOUR_ANTHROPIC_AUTH_TOKEN>` |

3. Restart the dispatcher — no rebuild required:

```powershell
docker compose restart skidc-dispatcher
```

---

## Troubleshooting

### Worker container exits with code 137

Exit code 137 = SIGKILL = OOM killer. Fix: hard-cap the worker container's memory in
`dispatch.yaml`:

```yaml
container:
  image: "skidc-worker:latest"
  network_mode: "host"
  completed_action: "remove"
  mem_limit: "3g"
```

### `docker exec` fails with "cannot be used with root/sudo privileges"

Claude Code refuses `--dangerously-skip-permissions` when running as root. Confirm
`container/Dockerfile` contains:

```dockerfile
RUN useradd -m -s /bin/bash kali && \
    echo "kali ALL=(ALL) NOPASSWD:ALL" >> /etc/sudoers
USER kali
```

### ghcr.io times out / 404

Common in CN networks. Use a Docker Hub base image instead:

```dockerfile
FROM python:3.13-slim-bookworm
RUN pip install uv
```

### Kali apt mirror fails (403)

Replace `mirror.wane.kr` with `mirrors.aliyun.com` in `container/Dockerfile`.

---

## Responsible use

Skidc targets authorized penetration-testing / CTF / security-assessment environments.
Use it **only** where you have explicit permission to operate. Unauthorized security
testing may be illegal and harmful. You are solely responsible for how you use this project.
