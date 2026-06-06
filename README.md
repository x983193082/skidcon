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

> This is a from-scratch reimplementation inspired by the architecture of
> [Cairn](https://github.com/oritera/Cairn). It keeps the clever core — blackboard graph,
> three runtime-generated task types, the driver abstraction, the server/dispatcher split,
> lease-based claiming, and two-phase conclude — and rebuilds it lean and Windows-friendly.

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

## Project layout

```
D:\skidc\
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
├─ dispatch.example.yaml         # DeepSeek + Qwen wired in
├─ dispatch_mock.yaml            # mock-only, for local observation
├─ Dockerfile  docker-compose.yaml
└─ README.md
```

---

## Getting started

### Prerequisites
- Python ≥ 3.12 and [uv](https://docs.astral.sh/uv/) (already used here)
- Docker (for real runs — one worker container per project)

### Run the tests (no Docker, no LLM required)

```bash
cd skidc
uv run --group dev pytest
```

This drives the **entire pipeline** — server protocol, scheduler decision tree, all three
task types, the two-phase conclude fallback, and the model-swap drivers — in-process using
the `mock` worker. It is the fastest way to understand the system.

### Run the server + dashboard

```bash
cd skidc
uv run skidc serve            # http://127.0.0.1:8000  (dashboard at /)
```

Create a project (origin + goal), add hints, and watch the fact/intent graph grow live.

### Run the dispatcher

```bash
cp dispatch.example.yaml dispatch.yaml     # then fill in your DeepSeek / Qwen keys
cd skidc
uv run skidc dispatch --config ../dispatch.yaml

# Validate only your worker LLM configs (one ping per worker) and exit:
uv run skidc dispatch --config ../dispatch.yaml --startup-healthcheck-only
```

### Docker Compose (server + dispatcher)

```bash
docker build -t skidc-worker:latest -f container/Dockerfile container   # the worker image
cp dispatch.example.yaml dispatch.yaml                                  # fill in keys
docker compose up --build
```

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
