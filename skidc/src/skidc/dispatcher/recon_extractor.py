"""RECON phase gate and potential-target extraction for real-website mode.

When bootstrap_enabled=False the scheduler uses this module to:
1. Check whether enough RECON data (port scan, subdomain, directory, asset) has
   been collected before allowing reason to proceed.
2. Parse RECON facts and extract potential sub-targets (subdomains, open
   services, URLs) written as facts with goal_type='potential_target'.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

from skidc.server.models import Fact

LOG = logging.getLogger(__name__)

# Keywords that indicate a fact belongs to a particular RECON category.
_CATEGORY_KEYWORDS: dict[str, tuple[str, ...]] = {
    "port_scan": ("port", "nmap", "naabu", "open port", "tcp", "service"),
    "subdomain": ("subdomain", "subfinder", "amass", "dns", "cname"),
    "directory": ("directory", "ffuf", "gobuster", "dirsearch", "path", "endpoint"),
    "asset": ("asset", "katana", "crawl", "url", "endpoint", "javascript", "js file"),
}


@dataclass(slots=True)
class ReconChecklist:
    """Tracks which RECON categories have been covered."""

    port_scan: bool = False
    subdomain: bool = False
    directory: bool = False
    asset: bool = False

    @property
    def complete(self) -> bool:
        return all((self.port_scan, self.subdomain, self.directory, self.asset))

    @property
    def missing(self) -> list[str]:
        return [name for name in _CATEGORY_KEYWORDS if not getattr(self, name)]


@dataclass(slots=True)
class PotentialTarget:
    description: str
    source: str  # which fact produced this target


def check_recon_status(facts: list[Fact]) -> ReconChecklist:
    """Scan all facts and return a checklist of covered RECON categories."""
    checklist = ReconChecklist()
    for fact in facts:
        desc_lower = fact.description.lower()
        for category, keywords in _CATEGORY_KEYWORDS.items():
            if any(kw in desc_lower for kw in keywords):
                setattr(checklist, category, True)
    return checklist


def extract_potential_targets(facts: list[Fact]) -> list[PotentialTarget]:
    """Parse RECON facts and extract potential sub-targets.

    Looks for:
    - Subdomains (e.g. ``admin.example.com``)
    - Open ports/services (e.g. ``80/tcp http``, ``443/tcp https``)
    - Interesting URLs/paths (e.g. ``/api/v1/admin``)
    """
    targets: list[PotentialTarget] = []
    seen: set[str] = set()

    for fact in facts:
        desc = fact.description

        # Subdomains: word.word.tld patterns (at least 3 parts)
        for match in re.finditer(r"\b([a-zA-Z0-9][-a-zA-Z0-9]*\.[a-zA-Z0-9][-a-zA-Z0-9]*\.[a-zA-Z]{2,})\b", desc):
            domain = match.group(1)
            if domain not in seen:
                seen.add(domain)
                targets.append(PotentialTarget(
                    description=f"Subdomain discovered: {domain}",
                    source=fact.id,
                ))

        # Open ports/services: patterns like "80/tcp", "443/tcp https", "22/ssh"
        for match in re.finditer(r"\b(\d{1,5})/(tcp|udp)\s*(\w+)?", desc):
            port = match.group(1)
            proto = match.group(2)
            service = match.group(3) or ""
            label = f"{port}/{proto}"
            if service:
                label += f" ({service})"
            if label not in seen:
                seen.add(label)
                targets.append(PotentialTarget(
                    description=f"Open port/service: {label}",
                    source=fact.id,
                ))

        # Interesting paths: /api/..., /admin, /login, etc.
        for match in re.finditer(r"(/(?:api|admin|login|dashboard|upload|backup|config|\.env|\.git|wp-|phpmyadmin)[^\s]*)", desc, re.IGNORECASE):
            path = match.group(1)
            if path not in seen:
                seen.add(path)
                targets.append(PotentialTarget(
                    description=f"Interesting path: {path}",
                    source=fact.id,
                ))

    return targets
