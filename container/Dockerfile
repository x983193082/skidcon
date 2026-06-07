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
# The base image ships its apt sources in DEB822 format at
# /etc/apt/sources.list.d/kali.sources (current Kali) and may also have the
# legacy /etc/apt/sources.list (older pulls). Rewrite the URI to Aliyun's
# Kali mirror over http — keep it http so apt can run before ca-certificates
# is installed (HTTPS would fail certificate verification without it).
RUN find /etc/apt/sources.list.d/ -type f \( -name '*.list' -o -name '*.sources' \) -exec sed -i \
        -e 's|mirror\.wane\.kr|mirrors.aliyun.com|g' \
        -e 's|http://http\.kali\.org|http://mirrors.aliyun.com|g' \
        {} + \
    && [ -f /etc/apt/sources.list ] && sed -i \
        -e 's|mirror\.wane\.kr|mirrors.aliyun.com|g' \
        -e 's|http://http\.kali\.org|http://mirrors.aliyun.com|g' \
        /etc/apt/sources.list || true \
    && apt-get update \
    && apt-get install -y --no-install-recommends \
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

# Non-root user — Claude Code refuses to run with --dangerously-skip-permissions
# when executed as root. Mirror the setup in Cairn's container/Dockerfile.
RUN useradd -m -s /bin/bash kali && \
    echo "kali ALL=(ALL) NOPASSWD:ALL" >> /etc/sudoers
USER kali

# A writable workspace for agents to drop scan logs, payloads, proofs, etc.
RUN mkdir -p /home/kali/workspace
WORKDIR /home/kali/workspace

COPY --chown=kali:kali ./AGENTS.md /home/kali/workspace/AGENTS.md
COPY --chown=kali:kali ./AGENTS.md /home/kali/workspace/CLAUDE.md
