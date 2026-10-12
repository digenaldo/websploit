"""Tests for mind-core (stdlib unittest; run inside the image so they use its pinned deps).

    docker run --rm -v "$PWD/tests:/app/tests:ro" mind-core python -m unittest discover -s tests -v
"""

import json
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import MAX_BODY_BYTES, RULES_DIR, create_app  # noqa: E402
from backends import Generator, load_backend  # noqa: E402
from backends.deterministic import DeterministicBackend, load_pack  # noqa: E402

PACK = {
    "rules": [
        {"id": "first", "match": ["alpha"], "reply": "first"},
        {"id": "second", "match": ["alpha", "BETA"], "reply": "second"},
        {"id": "anywhere", "match": ["hidden-trigger"], "scope": "all", "reply": "found it"},
        {"id": "echo", "match": ["echo"], "reply": "you said: {{input}} | sys: {{system}}"},
        {"id": "braces", "match": ["template"], "reply": "{{7*7}} and {not a placeholder}"},
        {"id": "long", "match": ["long"], "reply": "one two three four five"},
    ],
    "fallback": "no rule",
}


def msgs(*pairs):
    return [{"role": role, "content": content} for role, content in pairs]


def backend_with(pack, name="lab"):
    tmp = tempfile.TemporaryDirectory()
    Path(tmp.name, name + ".json").write_text(json.dumps(pack))
    backend = DeterministicBackend(rules_dir=tmp.name)
    tmp.cleanup()
    return backend


class FakeBackend:
    name = "fake"

    def __init__(self, delay=0.0, fail=False):
        self.delay, self.fail = delay, fail

    def generate(self, model, messages, max_tokens=None):
        time.sleep(self.delay)
        if self.fail:
            raise ConnectionError("model server down")
        return "fake reply", None, "stop"


class DeterministicEngineTest(unittest.TestCase):
    def setUp(self):
        self.backend = backend_with(PACK)

    def reply(self, *pairs, max_tokens=None):
        return self.backend.generate("lab", msgs(*pairs), max_tokens)

    def test_first_matching_rule_wins(self):
        self.assertEqual(self.reply(("user", "alpha beta")), ("first", "first", "stop"))

    def test_matching_is_case_insensitive(self):
        self.assertEqual(self.reply(("user", "only Beta here"))[1], "second")

    def test_default_scope_is_last_user_message(self):
        self.assertIsNone(self.reply(("user", "alpha"), ("user", "nothing"))[1])

    def test_scope_all_searches_the_whole_conversation(self):
        self.assertEqual(self.reply(("system", "hidden-trigger"), ("user", "nothing"))[1], "anywhere")

    def test_fallback_when_no_rule_matches(self):
        self.assertEqual(self.reply(("user", "zzz")), ("no rule", None, "stop"))

    def test_placeholders_are_filled_in_one_pass(self):
        text = self.reply(("system", "SECRET"), ("user", "echo {{system}}"))[0]
        self.assertEqual(text, "you said: echo {{system}} | sys: SECRET")

    def test_other_braces_are_left_alone(self):
        self.assertEqual(self.reply(("user", "template"))[0], "{{7*7}} and {not a placeholder}")

    def test_max_tokens_truncates_and_reports_length(self):
        self.assertEqual(self.reply(("user", "long"), max_tokens=2), ("one two", "long", "length"))
        self.assertEqual(self.reply(("user", "long"), max_tokens=5)[2], "stop")

    def test_invalid_packs_are_rejected(self):
        broken = [
            {"rules": []},
            {"rules": [{"id": "a", "match": [], "reply": "x"}], "fallback": "f"},
            {"rules": [{"id": "a", "match": ["k"], "reply": "x"}] * 2, "fallback": "f"},
            {"rules": [{"id": "a", "match": ["k"], "reply": "x", "scope": "sideways"}], "fallback": "f"},
        ]
        for pack in broken:
            with self.subTest(pack=pack), tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp, "bad.json")
                path.write_text(json.dumps(pack))
                with self.assertRaises(ValueError):
                    load_pack(path)

    def test_shipped_packs_load(self):
        self.assertIn("default", DeterministicBackend(rules_dir=RULES_DIR).models())

    def test_unknown_backend_is_rejected(self):
        with self.assertRaises(ValueError):
            load_backend("llama-cpp", RULES_DIR)


class GeneratorFallbackTest(unittest.TestCase):
    def setUp(self):
        self.fallback = backend_with(PACK)

    def test_healthy_backend_answers(self):
        reply = Generator(FakeBackend(), self.fallback, timeout=1).generate("lab", msgs(("user", "alpha")))
        self.assertEqual((reply.text, reply.backend, reply.fallback), ("fake reply", "fake", False))

    def test_slow_backend_falls_back_instead_of_hanging(self):
        generator = Generator(FakeBackend(delay=5), self.fallback, timeout=0.2)
        started = time.monotonic()
        reply = generator.generate("lab", msgs(("user", "alpha")))
        self.assertLess(time.monotonic() - started, 2)
        self.assertEqual((reply.text, reply.backend, reply.fallback), ("first", "deterministic", True))

    def test_failing_backend_falls_back(self):
        reply = Generator(FakeBackend(fail=True), self.fallback, timeout=1).generate("lab", msgs(("user", "x")))
        self.assertEqual((reply.text, reply.fallback), ("no rule", True))


class HttpContractTest(unittest.TestCase):
    def setUp(self):
        backend = DeterministicBackend(rules_dir=RULES_DIR)
        self.client = create_app(Generator(backend, backend, timeout=1)).test_client()

    def chat(self, **body):
        return self.client.post("/v1/chat/completions", json=body)

    def test_health(self):
        response = self.client.get("/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json["status"], "ok")
        self.assertEqual(response.json["backend"], "deterministic")

    def test_models_lists_rule_packs(self):
        ids = [m["id"] for m in self.client.get("/v1/models").json["data"]]
        self.assertIn("default", ids)

    def test_chat_completion_shape(self):
        response = self.chat(model="default", messages=[{"role": "user", "content": "ping"}])
        self.assertEqual(response.status_code, 200)
        body = response.json
        self.assertEqual(body["object"], "chat.completion")
        self.assertEqual(body["model"], "default")
        self.assertEqual(body["choices"][0]["message"], {"role": "assistant", "content": "pong"})
        self.assertEqual(body["choices"][0]["finish_reason"], "stop")
        self.assertEqual(body["usage"]["total_tokens"], 2)
        self.assertEqual(body["mind_core"], {"backend": "deterministic", "rule": "ping", "fallback": False})

    def test_same_request_same_answer(self):
        request = {"messages": [{"role": "user", "content": "hello"}]}
        first, second = self.chat(**request).json, self.chat(**request).json
        self.assertEqual(first["id"], second["id"])
        self.assertEqual(first["choices"], second["choices"])

    def test_model_defaults_to_default_pack(self):
        self.assertEqual(self.chat(messages=[{"role": "user", "content": "ping"}]).json["model"], "default")

    def test_content_parts_are_accepted(self):
        content = [{"type": "text", "text": "repeat after me: hi"}, {"type": "image_url", "image_url": {}}]
        reply = self.chat(messages=[{"role": "user", "content": content}]).json
        self.assertEqual(reply["choices"][0]["message"]["content"], "You said: repeat after me: hi")

    def test_unknown_model_is_404(self):
        response = self.chat(model="gpt-9", messages=[{"role": "user", "content": "x"}])
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json["error"]["code"], "model_not_found")

    def test_bad_requests_are_400(self):
        user = [{"role": "user", "content": "x"}]
        cases = {
            "stream": {"messages": user, "stream": True},
            "no messages": {"messages": []},
            "bad role": {"messages": [{"role": "root", "content": "x"}]},
            "bad content": {"messages": [{"role": "user", "content": 42}]},
            "bad max_tokens": {"messages": user, "max_tokens": 0},
            "bool max_tokens": {"messages": user, "max_tokens": True},
            "too many messages": {"messages": user * 65},
        }
        for name, body in cases.items():
            with self.subTest(name):
                response = self.chat(**body)
                self.assertEqual(response.status_code, 400)
                self.assertIn("message", response.json["error"])

    def test_non_json_body_is_400(self):
        response = self.client.post("/v1/chat/completions", data="not json", content_type="text/plain")
        self.assertEqual(response.status_code, 400)

    def test_oversized_body_is_413(self):
        content = "x" * MAX_BODY_BYTES
        response = self.chat(messages=[{"role": "user", "content": content}])
        self.assertEqual(response.status_code, 413)
        self.assertIn("error", response.json)

    def test_unknown_route_returns_json_error(self):
        response = self.client.get("/admin")
        self.assertEqual(response.status_code, 404)
        self.assertIn("error", response.json)


if __name__ == "__main__":
    unittest.main()
