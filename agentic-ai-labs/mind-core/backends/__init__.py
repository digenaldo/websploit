"""Pluggable text-generation backends for mind-core.

A backend turns an OpenAI-style message list into reply text for a named
model. Phase 0 ships only the deterministic rules engine. Later tiers (a local
GGUF runtime, an optional external provider) register in BACKENDS and are
selected with MIND_CORE_BACKEND, so lab apps never change.

Every request goes through Generator, which bounds the backend with a timeout
and answers from the deterministic engine if the backend is slow, down, or
raises. A lab calling mind-core therefore always gets an answer, never a hang.
"""

import logging
from collections import namedtuple
from concurrent.futures import ThreadPoolExecutor

from .deterministic import DeterministicBackend

log = logging.getLogger("mind-core")

# text: reply content; rule: id of the rule that produced it (None = pack fallback);
# finish_reason: "stop" or "length"; backend: name of the backend that answered;
# fallback: True when the deterministic engine answered for a failed backend.
Reply = namedtuple("Reply", "text rule finish_reason backend fallback")

BACKENDS = {
    DeterministicBackend.name: DeterministicBackend,
}


def load_backend(name, rules_dir):
    try:
        backend_cls = BACKENDS[name]
    except KeyError:
        raise ValueError("unknown MIND_CORE_BACKEND %r (available: %s)"
                         % (name, ", ".join(sorted(BACKENDS)))) from None
    return backend_cls(rules_dir=rules_dir)


class Generator:
    """Run the configured backend with a timeout and a deterministic fallback."""

    def __init__(self, backend, fallback, timeout, workers=4):
        self.backend = backend
        self.fallback = fallback
        self.timeout = timeout
        self._pool = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="backend")

    def models(self):
        return self.fallback.models()

    def generate(self, model, messages, max_tokens=None):
        future = self._pool.submit(self.backend.generate, model, messages, max_tokens)
        try:
            text, rule, finish_reason = future.result(timeout=self.timeout)
            return Reply(text, rule, finish_reason, self.backend.name, False)
        except Exception as exc:  # includes TimeoutError: never let a backend hang a lab
            future.cancel()
            log.warning("backend %s failed for model %s (%s); answering deterministically",
                        self.backend.name, model, type(exc).__name__)
            text, rule, finish_reason = self.fallback.generate(model, messages, max_tokens)
            return Reply(text, rule, finish_reason, self.fallback.name, True)
