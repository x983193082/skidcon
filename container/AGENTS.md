# Worker environment

Autonomous agent in a Skidc worker container. One task at a time (bootstrap, reason, or explore). Return a single raw JSON object.

## Container

Kali-based. Workspace: `/home/kali/workspace`. Save scan output, logs, payloads here — reference paths from `description`, never paste blobs into JSON. Network access to the target in Origin/Graph.

## Preinstalled tools

- **Network:** `nmap`, `naabu`, `ncat`
- **Web:** `nuclei` (templates: `/home/kali/.local/nuclei-templates/`), `nikto`, `sqlmap`, `dalfox`, `dirsearch`, `katana`
- **Directory:** `ffuf`, `gobuster`, `dirb`, `wfuzz`. Wordlists at `/usr/share/seclists/Discovery/Web-Content/` (`common.txt`, `directory-list-2.3-medium.txt`, `raft-large-directories.txt`)
- **Exploitation:** `hydra`, `pwntools` (import `pwn`), `pwncat`, `chisel`, `ysoserial`, `jwt_tool`, `jdwp-shellifier`
- **Search:** `rg` (ripgrep), `fd`, `gitleaks`
- **Browser:** `chromium` + `puppeteer-core` (CDP). Start: `chrome-start`, read port: `cat /home/kali/chrome-profile/cdp-port`
- **AD/cloud:** `bloodyAD`, `coercer`, `enum4linux-ng`, `netexec`, `kerbrute`, `cloudfox`, `adb`
- **Other:** `tmux`, `jq`, `yq`, `curl`, `wget`, `sshpass`, `sudo` (passwordless)

## Knowledge bases (offline)

Reference corpora at `/home/kali/knowledges/`. Search with `rg`:
- `PayloadsAllTheThings/` — payloads + bypasses per vuln class
- `hacktricks/` — pentest methodology
- `Awesome-POC/` — CVE exploitation notes
- `InternalAllTheThings/` — AD + lateral movement
- `wooyun-legacy/` — business-logic case archive
- `owasp-bla-top10/` — OWASP Top 10 for Business Logic Abuse
- `vulnerability-Checklist/` — per-class test checklists
- `hack-skills/` — agent-oriented pentest skill library

## Browser CDP

```bash
chrome-start
PORT=$(cat /home/kali/chrome-profile/cdp-port)
node -e '
const puppeteer = require("puppeteer-core");
const fs = require("fs");
(async () => {
  const port = fs.readFileSync("/home/kali/chrome-profile/cdp-port", "utf8").trim();
  const { webSocketDebuggerUrl } = await (await fetch(`http://127.0.0.1:${port}/json/version`)).json();
  const browser = await puppeteer.connect({ browserWSEndpoint: webSocketDebuggerUrl });
  const page = await browser.newPage();
  await page.goto("http://TARGET_URL", { waitUntil: "networkidle2" });
  console.log(await page.content());
  await browser.disconnect();
})();
'
```

## Output

- Return exactly one raw JSON object matching the task prompt contract. No prose around it.
- Report objective, confirmed facts. Negative results are valid. Never fabricate findings.
- Never emit a refusal as a `description`.
