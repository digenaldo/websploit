# AGENTS.md

Guidance for AI coding agents working in this repository.

## What this repo is

WebSploit Labs is an **intentionally vulnerable** training environment by Omar Santos. It bundles classic OWASP apps (WebGoat, Juice Shop, DVWA), several CTF challenges, and a set of custom Flask-based labs that each demonstrate a specific web vulnerability class. Everything is orchestrated via Docker Compose on a single bridge network (`10.6.6.0/24`).

The intended deployment target is a Kali or Parrot VM (see `Vagrantfile` and `install.sh`). The host running these containers is expected to be isolated.

## Critical rule: this code is intentionally vulnerable

The custom labs under `additional-labs/` contain **deliberate vulnerabilities** (SQLi, XSS, SSRF, XXE, command injection, path traversal, SSTI, insecure deserialization, JWT flaws, prototype pollution, GraphQL introspection/IDOR, etc.). These vulnerabilities are the product. Do not "fix" them.

When working in this repo:

- **Do not remove or harden the intentional vulnerabilities** in any lab application code (the Python/JS/HTML inside `additional-labs/<lab>/`). The educational value depends on them being exploitable.
- **Do not** add input sanitization, parameterized queries, output encoding, secure XML parsing, JWT signature verification, etc. to the lab apps unless the user explicitly asks you to add a "secure mode" or a separate hardened endpoint.
- The workspace-level `codeguard-*` security rules describe best practices that **apply to tooling, infrastructure, CI, and any non-vulnerable code** (e.g., `install.sh`, `docker-compose.yml`, helper scripts, READMEs). Treat the lab application source files as out of scope for those rules unless the user says otherwise.
- If you spot a vulnerability in a lab and are unsure whether it is intentional, ask before changing it. Default assumption: it is intentional.
- Hardcoded weak credentials, default secrets, and insecure crypto inside lab apps are intentional teaching artifacts. The "no hardcoded credentials" rule still applies to anything outside the lab apps (install scripts, compose files, infra, READMEs).
- The same rules apply to the AI-track labs under `agentic-ai-labs/<lab>/`, with one exception: **`agentic-ai-labs/mind-core/` is shared infrastructure, not a lab.** It is not intentionally vulnerable; keep it hardened (pinned digest and hashes, non-root, read-only, bounded inputs) like any other tooling.

What you **should** improve when asked:

- `install.sh`, `containers.sh`, `vulnhub.sh`, `Vagrantfile`, `docker-compose.yml`, top-level `README.md`, lab `README.md` files (instructions, exercises, hints).
- Dockerfile hygiene (pinned base images, non-root users, healthchecks) **as long as** the vulnerabilities the lab is built around remain exploitable from outside the container.
- New labs, new exercises, new walkthroughs, fixing typos, improving documentation.

## Repo layout

```
websploit/
├── README.md                       # Top-level overview, container table, network diagram
├── docker-compose.yml              # Single source of truth for all containers + the websploit network
├── install.sh                      # Kali/Parrot installer (root); installs tools + brings up compose
├── containers.sh                   # Helper to print container info on the host
├── vulnhub.sh                      # Helper for VulnHub-style targets
├── Vagrantfile                     # Kali VM that curls install.sh from websploit.org
├── pyproject.toml / uv.lock        # Top-level Python project metadata (mostly placeholder; flask dep)
├── main.py                         # Placeholder entry point ("Hello from websploit!")
├── .python-version                 # pinned Python for uv
├── websploit-containers.drawio     # Network diagram source
├── .github/
│   ├── golden-stack/               # Guard: fingerprint of the default stack (no profile) + checker
│   └── workflows/ai-track.yml      # CI: compose config, golden-stack guard, multi-arch build, smoke test
├── agentic-ai-labs/                # Opt-in AI/LLM track (Compose profile "ai"), OWASP LLM Top 10 (2025)
│   ├── README.md                   # Track overview, reserved block, OWASP mapping
│   └── mind-core/                  → mind-core          (10.6.6.50, host port 5030)  # shared LLM backend, NOT a lab
└── additional-labs/                # Custom Flask labs, each built by docker-compose
    ├── README.md                   # Directory-name → container-name → vuln type mapping
    ├── Command_Injection/          → shell-inject       (10.6.6.34, host port 5002)
    ├── deserial-gate/              → deserial-gate      (10.6.6.42, host port 5022)
    ├── GraphQL/                    → graphql-galaxy     (10.6.6.44, host port 5023)
    ├── Multi-Vulnerability-Gauntlet/ → hydra-nexus      (10.6.6.30, host port 5010)
    ├── Path_Traversal/             → maze-walker        (10.6.6.35, host port 5003)
    ├── Prototype_Pollution/        → proto-pollute      (10.6.6.45, host port 5004)
    ├── render-reign/               → render-reign       (10.6.6.41, host port 5021)  # SSTI
    ├── SQLi/                       → sqli-breach        (10.6.6.33, host port 5001)
    ├── SSRF/                       → trojan-relay       (10.6.6.32, host port 5012)
    ├── token-tower/                → token-tower        (10.6.6.40, host port 5020)  # JWT
    ├── XSS/                        → phantom-script     (10.6.6.31, host port 5011)
    └── XXE/                        → entity-smuggler    (10.6.6.36, host port 5013)
```

OWASP/classic apps and CTFs (`webgoat`, `juice-shop`, `dvwa`, `galactic-archives`, `gravemind`, `y-wing`, `redis-rogue`) are **pulled as prebuilt images** (mostly under `santosomar/*` on Docker Hub) and have no source in this repo.

## Container conventions

- Network: every service joins the `websploit` bridge network with subnet `10.6.6.0/24`, gateway `10.6.6.1`, and a static `ipv4_address`.
- Naming: each service sets an explicit `container_name` (the codename, e.g., `phantom-script`).
- Restart policy: `restart: unless-stopped`.
- Custom labs use `build: ./additional-labs/<dir>` and expose ports on the host.
- Prebuilt amd64 images set `platform: linux/amd64` (important for Apple Silicon hosts).
- Host port → container port mapping is intentional and documented in `README.md`. Do not change a port without also updating the top-level README, `additional-labs/README.md`, and the lab's own README.
- Opt-in services carry a Compose profile (`profiles: ["ai"]` for the AI track) and never start with a plain `docker compose up -d`. The default stack is pinned by `.github/golden-stack/golden-stack.txt`; CI fails if it drifts.

When adding a new lab:

1. Create `additional-labs/<NewLab>/` with a `Dockerfile`, app source, `requirements.txt`, and a `README.md` (objective, vulnerable endpoints, exploitation hints, learning objectives).
2. Add a service block in `docker-compose.yml` following the existing pattern (build path, container_name, static IP in `10.6.6.0/24`, host port mapping, `restart: unless-stopped`).
3. Pick the next free static IP and a non-conflicting host port; update both READMEs and the network diagram.
4. Keep the lab app intentionally vulnerable to its target class; document the intended exploit path in the lab README.

When adding an **AI-track** lab (opt-in, mapped to the OWASP LLM Top 10 2025), the steps above change as follows:

1. Create `agentic-ai-labs/<lab>/` (not `additional-labs/`) with a `Dockerfile` (pinned base image, native `linux/amd64` and `linux/arm64`), a pinned `requirements.txt`, the app, and a `README.md` (objective, vulnerable endpoints, walkthrough, learning objectives, isolation disclaimer).
2. Use the IP and host port already reserved for the lab in `agentic-ai-labs/README.md` (`10.6.6.50`–`10.6.6.59`, ports `5030`–`5039`). Don't take addresses from `.46`–`.49`, which are kept free as a buffer.
3. The service block uses `build: ./agentic-ai-labs/<lab>`, `profiles: ["ai"]`, `restart: unless-stopped`, a `healthcheck`, `mem_limit`, `cpus`, and `depends_on: { mind-core: { condition: service_healthy } }`. Agent/tool labs that must not reach the internet also join `websploit-isolated` (`10.7.7.0/24`, `internal: true`).
4. Talk to the model only through `mind-core` (`http://10.6.6.50:5030/v1/chat/completions`), with a timeout. Ship the lab's deterministic rule pack as `agentic-ai-labs/mind-core/rules/<lab>.json`, so every flag can be captured offline with no GPU, API key, or model weights.
5. Don't modify existing labs; reach them over the network only. Leave `install.sh` and `generate_checksum.yml` alone.
6. Update the top-level `README.md`, `agentic-ai-labs/README.md`, and `websploit-containers.drawio` together, and extend the smoke test in `.github/workflows/ai-track.yml` to capture the lab's flags over HTTP.
7. Run `python3 .github/golden-stack/check.py` and confirm the only fixture change is the `profile ai adds:` line. Any other diff means the default stack changed.

## How to run things

From the repo root:

```bash
docker compose up -d --build      # build custom labs + start everything
docker compose ps                 # list containers
docker compose logs -f <name>     # tail a service
docker compose build --no-cache <name>
docker compose down               # stop everything
docker compose --profile ai up -d --build   # also start the opt-in AI track
python3 .github/golden-stack/check.py       # prove the default stack did not change
```

The `install.sh` script is meant to be run as root on Kali/Parrot. It installs system tooling, clones companion repos into `/root/`, and runs `docker-compose -f docker-compose.yml up -d`. Don't run it on your dev machine.

## Python tooling

- `pyproject.toml` declares Python `>=3.13` and `flask>=3.1.2`. `uv.lock` is checked in, suggesting `uv` for environment management at the top level. Individual labs have their own `requirements.txt` and Python versions baked into their Dockerfiles — treat each lab as its own self-contained environment.
- The top-level `main.py` is a placeholder; the real "apps" are the per-lab Flask apps under `additional-labs/`.

## Documentation conventions

- Top-level `README.md` and `additional-labs/README.md` both contain the network topology diagram and a container table. **Keep them in sync** when you add, rename, renumber, or remove a container.
- Lab READMEs follow a rough pattern: overview, vulnerable endpoints/parameters, step-by-step exploitation, learning objectives, and sometimes hints. Match that style for new labs.
- The `websploit-containers.drawio` source diagram should ideally be updated alongside topology changes (optional if the user doesn't ask).

## Style and small things

- Bash scripts use `set -e` / `set -u` (see `install.sh`); preserve that. They are interactive and assume root and a Debian-family distro (`apt`, `lsb_release`).
- Markdown tables in READMEs are aligned by content, not by spaces — don't over-format.
- Two header URLs appear repeatedly: `https://websploit.org` and `https://github.com/The-Art-of-Hacking/websploit`. Use them consistently.
- Author/credit line: "Omar Santos" / "@santosomar".

## Disclaimer to repeat in user-facing changes

These containers are intentionally vulnerable and must only run in isolated, non-production environments. Any new lab README should carry a short version of this warning.
