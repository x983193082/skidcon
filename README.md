<div align="center">

# Skidc

### A blackboard state-space search engine that orchestrates pluggable coding-agent backends

*Give it an **origin** and a **goal**. It searches for a path through an unknown state space —*
*using whatever LLM you point it at (DeepSeek, Qwen, …) behind whatever agent CLI you prefer.*

</div>

---

## What is Skidc?

Many hard problems share one shape — a **directed search through a near-infinite state space**:

- **Origin**: known (a target IP, a starting position, a set of facts)
- **Goal**: defined (get a shell, capture the flag, prove a property)
- **Path**: unknown

Penetration testing is the canonical example, and Skidc's reference prompts + worker
container are built for authorized offensive security / CTF work. But the engine itself has
**no roles, no fixed workflow, and no domain assumptions**. Swap the prompt group and the
worker image and the same machine does vulnerability research, CTF solving, or any other
"clear start, clear success condition, unknown middle" problem.

Skidc is built on a **blackboard architecture** with an explicit fact–intent graph. Three
primitives are all it needs:

| Concept | Meaning |
|---------|---------|
| **Fact** | A confirmed, objective finding written to the board |
| **Intent** | A declared direction of exploration, not yet executed |
| **Hint** | Human judgment injected at any time; absorbed by agents on the next read |

The graph grows from `origin` toward `goal`. Every new Fact is a stepping stone; every
Intent is a step into the unknown. Workers run an observe→orient→decide→act loop over the
**shared board only** (stigmergy) — no direct agent-to-agent messaging, no information silos,
no predefined job descriptions. Tasks are generated at runtime from the graph's current state.

> Skidc is a Windows-friendly, self-contained implementation sharing the same core architecture
> as [Cairn](https://github.com/oritera/Cairn) — blackboard graph, three runtime-generated
> task types, the driver abstraction, the server/dispatcher split, lease-based claiming, and
> two-phase conclude. The two projects are independent; the prompt set, the worker container,
> and the default LLM choices differ.

---

## How it works

Three task types, all executed by the same universal worker:

| Task | Trigger | What it does | Output |
|------|---------|-------------|--------|
| **Bootstrap** | Project is in its initial state | Try to solve the whole problem directly | Fact + possible Complete |
| **Reason** | New facts/hints appeared, or no open intents | Read the full graph: goal met? what to explore next? | Complete / new Intents / no-op |
| **Explore** | An unclaimed open intent exists | Claim one intent, execute it, report findings | One Fact |

Both `bootstrap` and `explore` are **two-phase**: if the main attempt times out or returns
unparseable output, the dispatcher resumes the *same agent session* with a `conclude` prompt
that says "stop working, just summarize what you confirmed" — so partial progress still lands
on the board instead of being thrown away.

```
              ┌────────────────────────────────────┐
              │            Skidc Server            │   truth source:
              │     Facts + Intents + Hints        │   graph consistency only
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
              │  claude→DeepSeek│  │  codex→Qwen      │   coordinate via the board only
              └─────────────────┘  └──────────────────┘
```

**Server** keeps the graph consistent and owns the intent-claim / reason-lease state
machine (claim → heartbeat → expire). **Dispatcher** is the only component that writes the
protocol: it reads the graph, decides the task type per project, claims a lease, runs the
worker in that project's container, parses the structured JSON result, and writes it back.

---

## The headline trick: the model is not hard-coded

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
    ANTHROPIC_MODEL: "deepseek-chat"
    ANTHROPIC_BASE_URL: "https://api.deepseek.com/anthropic"
    ANTHROPIC_AUTH_TOKEN: "sk-deepseek-xxx"

# Run Qwen through the Codex agent loop:
- name: "codex_qwen"
  type: "codex"
  env:
    CODEX_MODEL: "qwen3-max"
    CODEX_BASE_URL: "https://dashscope.aliyuncs.com/compatible-mode/v1"
    OPENAI_API_KEY: "sk-qwen-xxx"
```

Swapping models is a config edit. Adding a new backend (a different CLI, a different wire
protocol) is one new driver file in `workers/adapters/`.

---

## Project layout

```
skidc\
├─ skidc\                         # the Python package (uv project)
│  ├─ src\skidc\
│  │  ├─ server\                  # FastAPI + SQLite blackboard
│  │  │  ├─ db.py  models.py  services.py  app.py
│  │  │  ├─ routers\             # projects, intents, hints, settings, export
│  │  │  └─ static\index.html    # live graph dashboard (zero-dependency)
│  │  ├─ dispatcher\
│  │  │  ├─ config.py            # dispatch.yaml schema + model-swap env wiring
│  │  │  ├─ contracts.py         # strict JSON output validation
│  │  │  ├─ scheduler\loop.py    # the control plane / decision tree
│  │  │  ├─ tasks\               # bootstrap / reason / explore (+ conclude)
│  │  │  ├─ workers\             # driver abstraction
│  │  │  │  └─ adapters\         #   claudecode→DeepSeek, codex→Qwen, mock
│  │  │  ├─ runtime\             # docker exec, heartbeat lease, cancellation
│  │  │  └─ prompts\             # default\ (offensive) + mock\ (structured)
│  │  └─ cli.py                  # `skidc serve` / `skidc dispatch`
│  └─ tests\                     # 27 tests, run with no Docker and no LLM
├─ container\                    # Kali worker image (Dockerfile + AGENTS.md)
│                                 # user: kali, workspace: /home/kali/workspace
├─ dispatch.example.yaml         # template — copy to dispatch.yaml and fill in keys
├─ dispatch.yaml                 # your real config (gitignored)
├─ dispatch_mock.yaml            # mock-only setup, for local observation / tests
├─ Dockerfile                    # builds skidc-app (server + dispatcher image)
├─ docker-compose.yaml
└─ README.md
```

---

## Getting started

### Prerequisites

- **OS**: Windows 10/11 (WSL2 backend), macOS, or Linux
- **Docker Desktop** ≥ 4.10 (uses WSL2 on Windows; bind mount `C:\` works)
- **Python ≥ 3.12** and [uv](https://docs.astral.sh/uv/) — only needed for `uv run skidc serve / dispatch`; **not needed if you only use Docker Compose**
- For Windows: at least **8 GB free on C:** (WSL2 stores Docker's ext4.vhdx there)

### Path A — Docker Compose (recommended; no Python needed)

```powershell
# From D:\skidc in PowerShell

# 1. Build the worker image (Kali + claude-code + codex). ~5-15 min, ~4.6 GB.
docker build -t skidc-worker:latest -f container/Dockerfile container

# 2. Create your dispatcher config from the template, then fill in LLM keys.
copy dispatch.example.yaml dispatch.yaml
notepad dispatch.yaml                  # fill in ANTHROPIC_AUTH_TOKEN / OPENAI_API_KEY

# 3. Build the app image and start everything.
docker compose up -d --build
```

`docker compose up -d --build` will:
- build `skidc-app` (the server + dispatcher image) from the root `Dockerfile`
- start `skidc-server` (port 8000) and `skidc-dispatcher`
- mount `D:\skidc\datas\skidc\` to `/root/.local/share/skidc/` inside the server
  (this is where the SQLite db lives; survives restarts)

To verify:

```powershell
docker ps --filter "name=skidc" --format "table {{.Names}}\t{{.Status}}"
# Expect: skidc-server (healthy), skidc-dispatcher (Up)

curl http://127.0.0.1:8000/api/projects
# Expect: [] (empty project list)
```

Open http://127.0.0.1:8000 to see the dashboard.

### Path B — `uv` directly (development; bypasses Docker for the app, still uses Docker for workers)

```powershell
# terminal 1: start the server
cd D:\skidc\skidc
uv sync
uv run skidc serve --host 0.0.0.0

# terminal 2: start the dispatcher
# (first time: copy dispatch.example.yaml to dispatch.yaml and fill in keys)
cp D:\skidc\dispatch.example.yaml D:\skidc\dispatch.yaml
notepad D:\skidc\dispatch.yaml
cd D:\skidc\skidc
uv run skidc dispatch --config ..\dispatch.yaml

# Validate only your worker LLM configs (one ping per worker) and exit:
uv run skidc dispatch --config ..\dispatch.yaml --startup-healthcheck-only
```

### Path C — Tests only (no Docker, no LLM)

```powershell
cd D:\skidc\skidc
uv sync --group dev
uv run --group dev pytest
```

Drives the **entire pipeline** — server protocol, scheduler decision tree, all three
task types, the two-phase conclude fallback, and the model-swap drivers — in-process using
the `mock` worker. It is the fastest way to understand the system.

---

## Daily use

### Start a project

1. Open http://127.0.0.1:8000 in a browser.
2. Click **New Project**, fill in:
   - **Origin**: target IP / URL / domain (e.g. `192.168.198.130`)
   - **Goal**: success condition (e.g. `get the root shell`, `capture the flag`)
   - **Hints** (optional): things you already know (open ports, banners, credentials)
3. Submit. The dispatcher picks a worker, spawns a container, and starts the OODA loop.

### Watch progress

| What you want to see | Where to look |
|----------------------|---------------|
| The fact/intent graph growing | Dashboard (auto-refreshes) |
| What Claude/Codex is currently running | `docker exec <worker-container> ps aux` |
| Why a task was cancelled | `docker logs skidc-dispatcher --tail 100` |
| Which LLM call failed | `docker logs skidc-dispatch-proj_xxx` |

Find the active worker container for a project:

```powershell
docker ps --filter "name=skidc-dispatch-proj_" --format "{{.Names}}"
```

### Stop the system

```powershell
# Graceful stop (data preserved)
cd D:\skidc
docker compose down

# Force stop (loses in-flight tasks)
docker compose down -v
```

### Periodic cleanup

Worker containers accumulate as `Exited (137)` or `Exited (0)` residues. Clean them:

```powershell
docker container prune -f
```

This frees disk inside WSL2. For C: drive reclamation, see the **Disk usage** section below.

### Restart after shutdown

```powershell
cd D:\skidc
docker compose up -d
```

No rebuild needed — images are cached. Dashboard is ready in ~10 seconds.

---

## Disk usage & C: pressure

Docker Desktop on Windows stores images and container layers in a WSL2 virtual disk:

```
C:\Users\<you>\AppData\Local\Docker\wsl\disk\docker_data.vhdx
```

`docker container prune` only frees space **inside** that vhdx; the file does **not**
shrink automatically, so `C:` may show no change.

To actually reclaim C: space:

```powershell
# 1. Quit Docker Desktop (right-click tray icon -> Quit)
# 2. wsl --shutdown
# 3. diskpart
#    select vdisk file="C:\Users\HUAWEI\AppData\Local\Docker\wsl\disk\docker_data.vhdx"
#    compact vdisk
#    exit
# 4. Restart Docker Desktop
```

> `Optimize-VHD` (the Hyper-V cmdlet) is **not available** in stock Windows + Docker
> Desktop (no Hyper-V module). `diskpart` always works.

Check how much space is recoverable before/after:

```powershell
wsl df -h /
```

---

## Swap the LLM brain

The whole point of the driver abstraction is that the agent CLI loop and the LLM behind
it are decoupled. To switch brains:

1. Edit `dispatch.yaml`. The `env:` block of each worker is the only place to touch.
2. Common swaps:

| Want | Worker `type` | Required env |
|------|---------------|--------------|
| DeepSeek (Claude Code loop) | `claudecode` | `ANTHROPIC_BASE_URL`, `ANTHROPIC_MODEL`, `ANTHROPIC_AUTH_TOKEN` |
| Qwen (Codex loop) | `codex` | `CODEX_BASE_URL`, `CODEX_MODEL`, `OPENAI_API_KEY` |
| Anthropic Claude (real) | `claudecode` | `ANTHROPIC_BASE_URL=https://api.anthropic.com`, `ANTHROPIC_MODEL=claude-sonnet-4-5`, `ANTHROPIC_AUTH_TOKEN=sk-ant-...` |

3. Restart the dispatcher — no rebuild required, env is read at task launch time:

```powershell
docker compose restart skidc-dispatcher
```

> **Note**: `claudecode` and `codex` workers have different loop semantics. The same
> prompt is fed to either, but `claudecode` auto-loads `CLAUDE.md` / `AGENTS.md` from
> the workspace; `codex` does not.

---

## Troubleshooting

### Worker container exits with code 137

Exit code 137 = SIGKILL = OOM killer. Symptom: a project gets its first fact but stays
stuck; `docker ps -a` shows `Exited (137)` for the worker container.

Causes (in order of likelihood):

1. nmap `-p-` with `--min-rate=1000` opens thousands of TCP sockets concurrently
2. DeepSeek / Qwen long-lived HTTP connections accumulate buffer memory
3. WSL2 cgroup memory accounting double-counts forked subprocesses

**Fix**: hard-cap the worker container's memory. Edit `dispatch.yaml`:

```yaml
container:
  image: "skidc-worker:latest"
  network_mode: "host"
  completed_action: "remove"     # auto-clean finished projects
  mem_limit: "3g"                # add this
```

Then update `skidc/src/skidc/dispatcher/runtime/containers.py:55-63` to pass
`mem_limit=self._config.mem_limit` to `containers.run(...)`, and add the field to
`ContainerConfig` in `skidc/src/skidc/dispatcher/config.py:151`.

Restart the dispatcher:

```powershell
docker compose restart skidc-dispatcher
```

### `docker exec` fails with "cannot be used with root/sudo privileges"

Claude Code refuses `--dangerously-skip-permissions` when running as root.

**Fix**: confirm `container/Dockerfile` contains:

```dockerfile
RUN useradd -m -s /bin/bash kali && \
    echo "kali ALL=(ALL) NOPASSWD:ALL" >> /etc/sudoers
USER kali
```

### ghcr.io times out / 404

Common in CN networks. Fix: use a Docker Hub base image instead of the ghcr.io one.
Edit the root `Dockerfile`:

```dockerfile
# FROM ghcr.io/astral-sh/uv:python3.13-trixie   # replace this
FROM python:3.13-slim-bookworm                    # with this
RUN pip install uv
```

Also add registry mirrors in `%USERPROFILE%\.docker\daemon.json`:

```json
{
  "registry-mirrors": [
    "https://1ms.run",
    "https://docker.m.daocloud.io"
  ]
}
```

Then **fully quit and reopen** Docker Desktop (a service restart is not enough).

### Kali apt mirror fails (403 on mirror.wane.kr)

Kali changed default mirrors. In `container/Dockerfile`, replace `mirror.wane.kr`
with `mirrors.aliyun.com` (http, not https, to avoid ca-cert bootstrap deadlock).

### Dispatcher logs: "cancelling running task for inactive project"

The project's `status` is no longer `active` on the server. Either the user manually
stopped it, or the bootstrap task did not write a fact within `tasks.bootstrap.timeout`
and the server marked the project as no longer actively making progress.

---

## Design notes worth stealing

- **One writer.** Agents never call the protocol API, never claim, never heartbeat. The
  dispatcher is the sole writer, which makes the whole system reason about as a single state
  machine instead of N racing clients.
- **Leases, not locks.** A claim is a lease kept alive by a heartbeat thread; if a worker
  dies, the server expires the lease and the intent becomes claimable again. No stuck work.
- **Stigmergy beats messaging.** Workers coordinate only by reading/writing the board. Add a
  worker, add a model, add a whole project — nothing else needs to know.
- **Two-phase harvest.** Timeouts don't mean lost work: resume the same session and ask for a
  summary. Cheap, and it dramatically improves yield on long explorations.
- **Graph-as-file injection.** Large graph snapshots are written into the container as a file
  and referenced from the prompt, dodging argv length limits.
- **A real mock backend.** The `mock` driver makes the success/failure/timeout/rejection
  paths testable deterministically — which is why the suite runs anywhere in seconds.

---

## Responsible use

Skidc's reference configuration targets authorized penetration-testing / CTF environments.
Use it **only** where you have explicit permission to operate. Unauthorized security testing
may be illegal and harmful. You are solely responsible for how you use this project.
