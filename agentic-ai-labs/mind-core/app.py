"""mind-core: shared LLM backend for the WebSploit AI track.

Serves a small OpenAI-compatible API over a pluggable backend:

    GET  /health                liveness for the Compose healthcheck
    GET  /v1/models             rule packs a lab can ask for
    POST /v1/chat/completions   non-streaming chat completion

Phase 0 ships only the deterministic rules engine, so every lab flag stays
reachable offline with no GPU, no API key, and no model weights.

mind-core is shared infrastructure and is NOT an intentionally vulnerable lab:
the intentional vulnerabilities live in the lab apps that call it.
"""

import hashlib
import json
import logging
import os
import time
from pathlib import Path

from flask import Flask, jsonify, request
from waitress import serve
from werkzeug.exceptions import HTTPException

from backends import Generator, load_backend
from backends.deterministic import DeterministicBackend

PORT = 5030
MAX_BODY_BYTES = 64 * 1024
MAX_MESSAGES = 64
MAX_TOKENS_LIMIT = 4096
DEFAULT_MODEL = "default"
ROLES = ("system", "developer", "user", "assistant", "tool")
RULES_DIR = Path(__file__).resolve().parent / "rules"

log = logging.getLogger("mind-core")


class BadRequest(Exception):
    def __init__(self, message, status=400, code=None):
        super().__init__(message)
        self.status = status
        self.code = code


def error(status, message, code=None):
    kind = "invalid_request_error" if status < 500 else "server_error"
    return jsonify(error={"message": message, "type": kind, "code": code}), status


def message_text(content):
    if content is None:  # e.g. an assistant turn that only carried tool calls
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):  # OpenAI content parts; only text parts matter here
        return "\n".join(part["text"] for part in content
                         if isinstance(part, dict) and part.get("type") == "text"
                         and isinstance(part.get("text"), str))
    raise BadRequest("message content must be a string or a list of content parts")


def parse_chat_request(body, models):
    if not isinstance(body, dict):
        raise BadRequest("request body must be a JSON object")
    if body.get("stream"):
        raise BadRequest("streaming is not supported; send \"stream\": false")

    model = body.get("model") or DEFAULT_MODEL
    if not isinstance(model, str):
        raise BadRequest("\"model\" must be a string")
    if model not in models:
        raise BadRequest("model %r not found (available: %s)" % (model, ", ".join(models)),
                         status=404, code="model_not_found")

    raw_messages = body.get("messages")
    if not isinstance(raw_messages, list) or not raw_messages:
        raise BadRequest("\"messages\" must be a non-empty list")
    if len(raw_messages) > MAX_MESSAGES:
        raise BadRequest("too many messages (max %d)" % MAX_MESSAGES)
    messages = []
    for message in raw_messages:
        if not isinstance(message, dict) or message.get("role") not in ROLES:
            raise BadRequest("each message needs a role (one of %s)" % ", ".join(ROLES))
        messages.append({"role": message["role"], "content": message_text(message.get("content"))})

    max_tokens = body.get("max_completion_tokens", body.get("max_tokens"))
    if max_tokens is not None and (isinstance(max_tokens, bool) or not isinstance(max_tokens, int)
                                   or not 1 <= max_tokens <= MAX_TOKENS_LIMIT):
        raise BadRequest("max_tokens must be an integer between 1 and %d" % MAX_TOKENS_LIMIT)

    return model, messages, max_tokens


def create_app(generator):
    app = Flask(__name__)
    app.config["MAX_CONTENT_LENGTH"] = MAX_BODY_BYTES
    app.json.sort_keys = False

    @app.get("/health")
    def health():
        return jsonify(status="ok", backend=generator.backend.name, models=generator.models())

    @app.get("/v1/models")
    def list_models():
        return jsonify(object="list", data=[
            {"id": model, "object": "model", "created": 0, "owned_by": "mind-core"}
            for model in generator.models()
        ])

    @app.post("/v1/chat/completions")
    def chat_completions():
        try:
            model, messages, max_tokens = parse_chat_request(
                request.get_json(silent=True), generator.models())
        except BadRequest as exc:
            return error(exc.status, str(exc), exc.code)

        reply = generator.generate(model, messages, max_tokens)
        prompt_tokens = sum(len(m["content"].split()) for m in messages)
        completion_tokens = len(reply.text.split())
        digest = hashlib.sha256(json.dumps([model, messages, max_tokens]).encode()).hexdigest()
        return jsonify(
            id="chatcmpl-" + digest[:24],
            object="chat.completion",
            created=int(time.time()),
            model=model,
            choices=[{
                "index": 0,
                "message": {"role": "assistant", "content": reply.text},
                "finish_reason": reply.finish_reason,
            }],
            usage={
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "total_tokens": prompt_tokens + completion_tokens,
            },
            mind_core={"backend": reply.backend, "rule": reply.rule, "fallback": reply.fallback},
        )

    @app.errorhandler(HTTPException)
    def http_error(exc):
        return error(exc.code, exc.description)

    @app.errorhandler(Exception)
    def unexpected_error(exc):
        log.exception("unhandled error")
        return error(500, "internal error")

    return app


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    backend_name = os.environ.get("MIND_CORE_BACKEND", DeterministicBackend.name)
    timeout = float(os.environ.get("MIND_CORE_TIMEOUT", "10"))

    fallback = DeterministicBackend(rules_dir=RULES_DIR)
    backend = fallback if backend_name == fallback.name else load_backend(backend_name, RULES_DIR)
    generator = Generator(backend, fallback, timeout)

    log.info("mind-core listening on :%d (backend=%s, timeout=%ss, models=%s)",
             PORT, backend.name, timeout, ",".join(generator.models()))
    serve(create_app(generator), host="0.0.0.0", port=PORT, threads=4,
          max_request_body_size=MAX_BODY_BYTES, connection_limit=64,
          channel_timeout=30, ident="mind-core")


if __name__ == "__main__":
    main()
