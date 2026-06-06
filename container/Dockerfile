# Skidc worker container — the per-project execution environment.
#
# The dispatcher execs agent CLIs (claude / codex) INSIDE this container. For
# penetration-testing / CTF work this is a Kali base with common offensive tooling.
# For a different domain (data analysis, proving, scraping), swap this image and the
# prompt group — the engine itself has zero domain assumptions.
#
# Build:  docker build -t skidc-worker:latest -f container/Dockerfile container
# Then reference it as container.image in dispatch.yaml.

FROM kalilinux/kali-rolling:latest

ENV DEBIAN_FRONTEND=noninteractive
ENV TZ=UTC
ENV PYTHONUNBUFFERED=1

# Core CLI utilities + a headless offensive toolset. Trim or extend to taste.
RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates curl wget git jq yq ripgrep fd-find \
        python3 python3-pip nodejs npm \
        nmap ncat netcat-traditional dnsutils iputils-ping \
        sqlmap nikto hydra seclists \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Agent CLIs. The dispatcher's `claudecode` driver calls `claude`, `codex` calls `codex`.
# Pin versions you have validated. (These talk to DeepSeek / Qwen via env at runtime.)
RUN npm install -g @anthropic-ai/claude-code @openai/codex \
    && npm cache clean --force

# A writable workspace for agents to drop scan logs, payloads, proofs, etc.
RUN mkdir -p /root/workspace
WORKDIR /root/workspace

COPY ./AGENTS.md /root/workspace/AGENTS.md
COPY ./AGENTS.md /root/workspace/CLAUDE.md
