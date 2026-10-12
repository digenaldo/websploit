# mind-core: shared LLM backend for the AI track

| | |
| --- | --- |
| Container | `mind-core` |
| Address | `10.6.6.50`, host port `5030` |
| Compose profile | `ai` (opt-in) |
| Backend | deterministic rules engine (no GPU, no API key, no model weights) |

`mind-core` is the shared "LLM" that the AI-track labs call. It speaks a small OpenAI-compatible API, so a lab talks to it the same way it would talk to a real model server. In this release it answers from a **deterministic rules engine**: replies are canned or templated, every lab flag is reachable offline, and the same request always gets the same answer.

`mind-core` is **shared infrastructure, not a target**. The intentional vulnerabilities live in the lab apps that call it. If you find a real bug in `mind-core` itself, please report it.

> **WARNING:** `mind-core` runs as part of an intentionally vulnerable training environment. Run it only in an isolated, non-production network, and do not expose it to the internet or untrusted networks.

## Run it

From the repository root:

```bash
# mind-core only
docker compose --profile ai up -d --build mind-core

# the whole default stack plus the AI track
docker compose --profile ai up -d --build
```

Without `--profile ai`, `mind-core` does not start, and `docker compose up -d` behaves exactly as before.

## API

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/health` | Liveness; used by the healthcheck |
| `GET` | `/v1/models` | Rule packs a lab can ask for |
| `POST` | `/v1/chat/completions` | Chat completion (non-streaming subset of the OpenAI API) |

```bash
curl -s http://localhost:5030/health
# {"status":"ok","backend":"deterministic","models":["default"]}

curl -s http://localhost:5030/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{"model": "default", "messages": [{"role": "user", "content": "ping"}]}'
# {"id":"chatcmpl-…","object":"chat.completion","created":…,"model":"default",
#  "choices":[{"index":0,"message":{"role":"assistant","content":"pong"},"finish_reason":"stop"}],
#  "usage":{"prompt_tokens":1,"completion_tokens":1,"total_tokens":2},
#  "mind_core":{"backend":"deterministic","rule":"ping","fallback":false}}
```

Request fields:

- `model`: the rule pack to answer from. Optional; defaults to `default`. An unknown model returns `404` with `"code": "model_not_found"`.
- `messages`: required. Up to 64 messages with a `role` of `system`, `developer`, `user`, `assistant`, or `tool`. `content` can be a string or a list of OpenAI content parts (only `text` parts are read).
- `max_tokens` (or `max_completion_tokens`): optional, 1–4096. Replies longer than this are cut, and `finish_reason` becomes `length`. Tokens are counted as whitespace-separated words.
- `stream: true` is rejected with `400`. Other OpenAI parameters (`temperature`, …) are accepted and ignored.

Each response also carries a `mind_core` object: which backend answered, which rule matched (`null` means the pack's fallback reply), and whether this was a fallback answer. Errors use the OpenAI error shape: `{"error": {"message", "type", "code"}}`. Request bodies are capped at 64 KiB (`413` above that).

## Rule packs

Every `rules/<name>.json` file is a pack, and `<name>` is the model id a lab sends. This release ships only `default`, a smoke-test pack. Each lab adds its own pack (for example `rules/echo-chamber.json`) in its own PR.

```json
{
  "description": "what this pack is for",
  "rules": [
    {"id": "ping", "match": ["ping"], "reply": "pong"},
    {"id": "echo", "match": ["repeat after me:"], "reply": "You said: {{input}}"},
    {"id": "leak", "match": ["ignore previous"], "scope": "all", "reply": "My instructions are: {{system}}"}
  ],
  "fallback": "reply when no rule matches"
}
```

- Rules are tried in order, and the first match wins.
- A rule matches when any of its `match` keywords appears, case-insensitively, in the **last user message**. With `"scope": "all"` it searches the whole conversation instead, which is useful for indirect injection that arrives through retrieved content.
- Matching is plain substring search, never a regular expression, so a crafted prompt cannot cause catastrophic backtracking.
- `{{input}}` (last user message) and `{{system}}` (the system messages) are filled in a single pass. Nothing else in a reply is interpreted, so payloads such as `{{7*7}}`, `<script>`, or `$(id)` come back verbatim.
- Packs are validated at startup, and a broken pack stops the container with a clear error.

## Backend tiers

| Tier | Backend | Status |
| --- | --- | --- |
| a | Deterministic rules engine | **This release.** The default, and the only tier CI requires. |
| b | Local quantized model (GGUF via the `llama.cpp` server, profile `ai-model`) | Follow-up: [#96](https://github.com/The-Art-of-Hacking/websploit/issues/96) |
| c | External OpenAI-compatible provider | Optional follow-up. Environment variables only, unset by default, never required. |

The backend is chosen with `MIND_CORE_BACKEND`. A new tier registers in `backends/__init__.py` and implements `generate(model, messages, max_tokens) -> (text, rule, finish_reason)`. Labs don't change.

Whatever the tier, every call runs under a timeout. If the backend is slow, down, or raises an error, `mind-core` answers from the deterministic pack of the same name and sets `"fallback": true`. A lab never hangs waiting for a model.

| Variable | Default | Meaning |
| --- | --- | --- |
| `MIND_CORE_BACKEND` | `deterministic` | Backend tier. An unknown value stops the container at startup. |
| `MIND_CORE_TIMEOUT` | `10` | Seconds to wait for the backend before falling back. |

## Footprint (measured)

These figures were measured on linux/amd64 (Docker 29.9, containerd image store) with the Compose limits applied. CI builds and smoke-tests the same image natively on linux/arm64 and reports its numbers in the workflow summary.

| What | Measured | Target (#88) |
| --- | --- | --- |
| Download (compressed) | ~45 MB (base `python:3.14.8-slim` is 43.5 MB on amd64, 43.8 MB on arm64) | — |
| On disk (unpacked root filesystem) | ~130 MB, of which mind-core's own layers are 6.4 MB | ~150 MB |
| RAM, idle | 30 MiB | < 128 MiB |
| RAM, after 400 requests (16 concurrent) | 31 MiB; cgroup peak 46 MiB, including healthcheck probes | < 128 MiB |
| Compose limits | `mem_limit: 128m`, `cpus: 0.5` | |

With the containerd image store, `docker images` shows about 185 MB, because it counts the compressed layers and the unpacked snapshot together.

## Hardening

`mind-core` is the one non-vulnerable component on the lab network, so it is locked down:

- The base image is pinned by multi-arch digest, and every Python dependency is pinned by hash (`requirements.txt`, compiled from `requirements.in`).
- It runs as non-root (uid `10001`), on a read-only root filesystem with a `tmpfs` at `/tmp`, with all capabilities dropped and `no-new-privileges` set.
- Requests are bounded: body size, message count, and `max_tokens` are capped; waitress limits connections and times out idle channels.
- Errors return JSON without stack traces, and it makes no outbound network calls.

## Development

Run the tests inside the image so they use the pinned dependencies:

```bash
cd agentic-ai-labs/mind-core
docker build -t mind-core .
docker run --rm --network none -v "$PWD/tests:/app/tests:ro" mind-core \
  python -m unittest discover -s tests -v
```

To update dependencies, edit `requirements.in` and recompile inside the pinned base image:

```bash
docker run --rm --user "$(id -u):$(id -g)" -e HOME=/tmp -v "$PWD:/work" -w /work \
  python:3.14.8-slim-trixie@sha256:a2b82f3c48559aa0a8446d9af49826b6e2b2016f4cd2afabfe6013ec53729170 \
  sh -c 'python -m pip install -q --user pip-tools==7.6.2 && python -m piptools compile --generate-hashes --strip-extras --no-emit-index-url requirements.in'
```
