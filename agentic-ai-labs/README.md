# WebSploit AI Track (agentic-ai-labs)

An **opt-in** track of AI/LLM application-security labs, mapped to the [OWASP Top 10 for LLM Applications (2025)](https://genai.owasp.org/llm-top-10/). The track ties the LLM-specific entry point to vulnerability classes WebSploit already teaches. For example, improper output handling ends up as XSS, SQL injection, or command injection, and excessive agency ends up as SSRF into the `10.6.6.0/24` targets.

Everything runs locally with **no GPU, no API key, and no internet access** after the images are built. Labs answer from a deterministic backend, so every flag can be captured offline, the same way every time, on both `linux/amd64` and `linux/arm64`.

> **WARNING**: These labs are **intentionally vulnerable**. They are **NOT malware or malicious**. They are only for educational purposes.
> - Do **NOT** expose these containers to the public internet or untrusted networks.
> - Run them only in a safe, isolated environment.
> - Use them for educational and authorized testing purposes only.

## Opting in

The track is behind the Compose profile `ai`. Without it, `docker compose up -d` (and `install.sh`) starts exactly the same containers as before.

```bash
# The default WebSploit stack plus the AI track
docker compose --profile ai up -d --build

# Only the AI track's shared backend
docker compose --profile ai up -d --build mind-core

# Or enable the profile for every command in this shell
export COMPOSE_PROFILES=ai
docker compose up -d --build
```

Once the AI containers are running, a plain `docker compose up -d` leaves them alone, and a plain `docker compose down` stops and removes them along with the rest of the stack.

## Containers

| Container | IP Address | Port | Role | Status |
|-----------|------------|------|------|--------|
| **mind-core** | 10.6.6.50 | 5030 | Shared LLM backend (deterministic) | Available |
| **oracle-booth** | 10.6.6.51 | 5031 | Support RAG chatbot: prompt injection, sensitive data and system-prompt leakage | Planned ([#91](https://github.com/The-Art-of-Hacking/websploit/issues/91)) |
| **marionette** | 10.6.6.52 | 5032 | Tool-using copilot: excessive agency, SSRF pivot | Planned ([#92](https://github.com/The-Art-of-Hacking/websploit/issues/92)) |
| **tainted-well** | 10.6.6.53 | 5033 | Ingestion + vector index: supply chain, poisoning, embeddings | Planned ([#93](https://github.com/The-Art-of-Hacking/websploit/issues/93)) |
| **echo-chamber** | 10.6.6.54 | 5034 | AI ops panel: improper output handling into web, SQL, and shell sinks | Planned ([#90](https://github.com/The-Art-of-Hacking/websploit/issues/90)) |
| **false-prophet** | 10.6.6.55 | 5035 | Answer generator: misinformation | Planned ([#94](https://github.com/The-Art-of-Hacking/websploit/issues/94)) |
| **token-famine** | 10.6.6.56 | 5036 | Metered chat endpoint: unbounded consumption | Planned ([#95](https://github.com/The-Art-of-Hacking/websploit/issues/95)) |

`mind-core` is shared infrastructure, **not** a target. The intentional vulnerabilities live in the lab apps. See [`mind-core/README.md`](mind-core/README.md) for its API, rule packs, and measured footprint.

### Reserved addresses

- `10.6.6.50`–`10.6.6.59` and host ports `5030`–`5039` belong to this track. `.57`–`.59` and `5037`–`5039` are spare.
- `10.6.6.46`–`10.6.6.49` stay unused as a buffer above the classic labs, which end at `10.6.6.45`.
- `websploit-isolated` (`10.7.7.0/24`, `internal: true`, no internet egress) is defined in `docker-compose.yml` for agent/tool labs. Compose only creates a network once a service joins it, and nothing does yet; `marionette` will be the first to join.

```
┌─────────────────────────────────────────────────────────────┐
│           WebSploit Network (10.6.6.0/24)                   │
├─────────────────────────────────────────────────────────────┤
│  Default stack (unchanged): 10.6.6.11 – 10.6.6.45           │
│                                                             │
│  AI track (opt-in, --profile ai):                           │
│  ├── mind-core        10.6.6.50  :5030  shared backend      │
│  └── 10.6.6.51–.59    :5031–5039        reserved for labs   │
└─────────────────────────────────────────────────────────────┘
┌─────────────────────────────────────────────────────────────┐
│  websploit-isolated (10.7.7.0/24, internal, no egress)      │
│  Defined; created when the first agent/tool lab joins it    │
└─────────────────────────────────────────────────────────────┘
```

## Backend tiers

| Tier | Backend | Status |
|------|---------|--------|
| a | Deterministic rules engine in `mind-core`: canned and templated replies | **Available.** The default; every flag is designed to be capturable with it. |
| b | Local quantized model: one small GGUF served by `llama.cpp`, CPU-only, profile `ai-model` | Follow-up ([#96](https://github.com/The-Art-of-Hacking/websploit/issues/96)) |
| c | External OpenAI-compatible provider, bring your own key | Optional follow-up. Environment variables only, unset by default, never required. |

Labs only ever talk to `mind-core` (an OpenAI-compatible API on `http://10.6.6.50:5030`). Adding a tier changes `mind-core`, not the labs. If a model is slow or down, `mind-core` answers from the lab's deterministic rule pack instead of hanging.

## OWASP Top 10 for LLM Applications (2025)

| Item | Lab(s) |
|------|--------|
| LLM01 Prompt Injection | oracle-booth, marionette |
| LLM02 Sensitive Information Disclosure | oracle-booth |
| LLM03 Supply Chain | tainted-well |
| LLM04 Data and Model Poisoning | tainted-well |
| LLM05 Improper Output Handling | echo-chamber |
| LLM06 Excessive Agency | marionette |
| LLM07 System Prompt Leakage | oracle-booth |
| LLM08 Vector and Embedding Weaknesses | tainted-well |
| LLM09 Misinformation | false-prophet |
| LLM10 Unbounded Consumption | token-famine |

**`marionette` is the track's agentic exercise.** A copilot with too much agency is driven, through indirect prompt injection, into tool calls that pivot across the lab network. It also maps to ASI01 (Agent Goal Hijack) in the [OWASP Top 10 for Agentic Applications](https://genai.owasp.org/).

## Adding a lab

Each lab lands in its own PR under `agentic-ai-labs/<lab>/`. Follow the AI-track checklist in [`AGENTS.md`](../AGENTS.md).

## Requirements

- Docker with Compose v2 (`docker compose`, or the `docker-compose` v2 binary that Kali/Parrot install).
- Fits the documented 8 GB RAM floor: `mind-core` idles around 30 MiB and is capped at 128 MiB.
