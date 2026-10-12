"""Deterministic rules engine: canned and templated replies, no model.

Rule packs are JSON files in the rules directory, and a pack's file name
(without .json) is the model id a caller asks for. A pack looks like:

    {
      "description": "what this pack is for",
      "rules": [
        {"id": "ping", "match": ["ping"], "reply": "pong"},
        {"id": "echo", "match": ["repeat after me"], "scope": "all", "reply": "{{input}}"}
      ],
      "fallback": "reply when no rule matches"
    }

Rules are tried in order and the first match wins. A rule matches when any of
its "match" keywords occurs, case-insensitively, in the last user message, or
anywhere in the conversation with "scope": "all". Matching is plain substring
search, never a regex, so a crafted prompt cannot cause catastrophic
backtracking. A reply may use {{input}} (the last user message) and {{system}}
(the system messages); nothing else in a reply is interpreted.
"""

import json
import re
from pathlib import Path

SCOPES = ("last_user", "all")
PLACEHOLDER = re.compile(r"\{\{(input|system)\}\}")


def load_pack(path):
    def require(ok, problem):
        if not ok:
            raise ValueError("%s: %s" % (path, problem))

    pack = json.loads(Path(path).read_text(encoding="utf-8"))
    require(isinstance(pack, dict), "a pack must be a JSON object")
    require(isinstance(pack.get("fallback"), str), '"fallback" must be a string')
    rules = pack.get("rules")
    require(isinstance(rules, list), '"rules" must be a list')

    seen = set()
    for index, rule in enumerate(rules):
        where = "rule #%d" % index
        require(isinstance(rule, dict), "%s must be an object" % where)
        require(isinstance(rule.get("id"), str) and rule["id"], "%s needs a string id" % where)
        require(rule["id"] not in seen, "duplicate rule id %r" % rule["id"])
        seen.add(rule["id"])
        match = rule.get("match")
        require(isinstance(match, list) and match
                and all(isinstance(k, str) and k for k in match),
                "rule %r needs a non-empty list of non-empty match keywords" % rule["id"])
        require(isinstance(rule.get("reply"), str), "rule %r needs a string reply" % rule["id"])
        require(rule.get("scope", "last_user") in SCOPES,
                "rule %r has scope %r (expected one of %s)" % (rule["id"], rule.get("scope"), SCOPES))
        rule["match"] = [k.casefold() for k in match]
    return pack


def truncate(text, max_tokens):
    """Cap a reply at max_tokens, counting whitespace-separated words as tokens."""
    words = text.split()
    if max_tokens is None or len(words) <= max_tokens:
        return text, "stop"
    return " ".join(words[:max_tokens]), "length"


class DeterministicBackend:
    name = "deterministic"

    def __init__(self, rules_dir):
        self.packs = {path.stem: load_pack(path) for path in sorted(Path(rules_dir).glob("*.json"))}
        if not self.packs:
            raise ValueError("no rule packs (*.json) found in %s" % rules_dir)

    def models(self):
        return sorted(self.packs)

    def generate(self, model, messages, max_tokens=None):
        """Return (text, rule id or None, finish_reason) for already-validated messages."""
        pack = self.packs[model]
        user = next((m["content"] for m in reversed(messages) if m["role"] == "user"), "")
        system = "\n".join(m["content"] for m in messages if m["role"] == "system")
        haystacks = {
            "last_user": user.casefold(),
            "all": "\n".join(m["content"] for m in messages).casefold(),
        }

        rule_id, reply = None, pack["fallback"]
        for rule in pack["rules"]:
            haystack = haystacks[rule.get("scope", "last_user")]
            if any(keyword in haystack for keyword in rule["match"]):
                rule_id, reply = rule["id"], rule["reply"]
                break

        # One pass over the author's template: substituted text is never re-scanned,
        # so a user who types "{{system}}" cannot pull the system prompt into an echo.
        values = {"input": user, "system": system}
        text = PLACEHOLDER.sub(lambda m: values[m.group(1)], reply)
        text, finish_reason = truncate(text, max_tokens)
        return text, rule_id, finish_reason
