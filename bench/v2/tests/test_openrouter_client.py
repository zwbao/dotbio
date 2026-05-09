"""Pytest tests for the OpenRouter LLM client.

These tests use a mocked HTTP session so they never touch the network.
Coverage:

1. ``available()`` returns False without ``OPENROUTER_API_KEY`` and
   True when it is set
2. ``complete()`` parses the OpenAI-compatible payload and surfaces
   the OpenRouter ``usage`` block (including cost) in ``Completion.raw``
3. Retry/backoff path: a single 429 followed by a 200 is transparent
4. Hard 4xx (e.g. 404 model-not-found) raises a clear error and the
   client returns a ``finish_reason='error'`` Completion that the
   harness can record without crashing
"""

from __future__ import annotations

import json
from typing import Any, Dict, List
from unittest import mock

import pytest

from bench.v2.scripts.llm_clients import openrouter as orc


class _FakeResp:
    def __init__(self, status: int, body: Any, headers: Dict[str, str] | None = None):
        self.status_code = status
        self._body = body
        self.headers = headers or {}
        self.text = json.dumps(body) if not isinstance(body, str) else body

    def json(self) -> Any:
        if isinstance(self._body, str):
            raise ValueError("not json")
        return self._body


class _FakeSession:
    """Minimal stand-in for requests.Session that returns canned responses."""

    def __init__(self, sequence: List[_FakeResp]):
        self._sequence = list(sequence)
        self.calls: List[Dict[str, Any]] = []

    def post(self, url: str, *, headers: Dict[str, str], data: str, timeout: float):
        self.calls.append(
            {"url": url, "headers": headers, "data": json.loads(data), "timeout": timeout}
        )
        if not self._sequence:
            raise AssertionError("no more canned responses")
        return self._sequence.pop(0)

    def get(self, url: str, *, headers: Dict[str, str], timeout: float):  # pragma: no cover
        self.calls.append({"url": url, "method": "GET", "timeout": timeout})
        if not self._sequence:
            raise AssertionError("no more canned responses")
        return self._sequence.pop(0)


# ---------------------------------------------------------------------------
# 1. availability gate
# ---------------------------------------------------------------------------


def test_available_requires_api_key(monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    assert orc.Client.available() is False
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-v1-fake")
    # `requests` is a hard dep of the test env; if it weren't, this would be False.
    assert orc.Client.available() is True


# ---------------------------------------------------------------------------
# 2. happy-path complete() round-trips usage block + cost
# ---------------------------------------------------------------------------


def test_complete_parses_usage_and_cost(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-v1-fake")
    body = {
        "id": "gen-abc123",
        "model": "anthropic/claude-sonnet-4.6",
        "provider": "Anthropic",
        "choices": [
            {
                "finish_reason": "stop",
                "message": {
                    "role": "assistant",
                    "content": '{"verdict": "depends", "phenotype": "IM"}',
                },
            }
        ],
        "usage": {
            "prompt_tokens": 1234,
            "completion_tokens": 56,
            "total_tokens": 1290,
            "cost": 0.0042,
        },
    }
    sess = _FakeSession([_FakeResp(200, body)])
    client = orc.Client(session=sess, sleep=lambda _s: None)

    comp = client.complete(
        "test prompt",
        format_id="C",
        question_id="q01",
        replicate_idx=0,
        temperature=0.7,
        model="anthropic/claude-sonnet-4.6",
    )
    assert comp.text.startswith('{"verdict"')
    assert comp.model == "anthropic/claude-sonnet-4.6"
    assert comp.family == "openrouter"
    assert comp.finish_reason == "stop"
    assert comp.raw["id"] == "gen-abc123"
    assert comp.raw["usage"]["cost"] == pytest.approx(0.0042)
    assert comp.raw["usage"]["total_tokens"] == 1290
    # Body shape: model/messages/usage{include:true} present.
    sent = sess.calls[0]["data"]
    assert sent["model"] == "anthropic/claude-sonnet-4.6"
    assert sent["messages"][0]["content"] == "test prompt"
    assert sent["usage"] == {"include": True}


# ---------------------------------------------------------------------------
# 3. retry on 429 then 200
# ---------------------------------------------------------------------------


def test_retry_on_429_then_succeeds(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-v1-fake")
    ok_body = {
        "id": "gen-2",
        "model": "openai/gpt-5-mini",
        "choices": [
            {"finish_reason": "stop", "message": {"role": "assistant", "content": "ok"}}
        ],
        "usage": {"prompt_tokens": 10, "completion_tokens": 1, "total_tokens": 11, "cost": 0.0001},
    }
    sess = _FakeSession(
        [
            _FakeResp(429, {"error": "rate limited"}, headers={"Retry-After": "0"}),
            _FakeResp(200, ok_body),
        ]
    )
    sleeps: List[float] = []
    client = orc.Client(session=sess, sleep=lambda s: sleeps.append(s))
    comp = client.complete(
        "p",
        format_id="A1",
        question_id="q01",
        replicate_idx=0,
        model="openai/gpt-5-mini",
    )
    assert comp.text == "ok"
    assert comp.finish_reason == "stop"
    assert len(sess.calls) == 2  # one 429, one 200
    assert len(sleeps) == 1  # one backoff slept


# ---------------------------------------------------------------------------
# 4. hard 404 (model-not-found) is recorded, not raised through the harness
# ---------------------------------------------------------------------------


def test_hard_404_returns_error_completion(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-v1-fake")
    sess = _FakeSession(
        [_FakeResp(404, {"error": {"message": "no such model", "code": 404}})]
    )
    client = orc.Client(session=sess, sleep=lambda _s: None)
    comp = client.complete(
        "p",
        format_id="A1",
        question_id="q01",
        replicate_idx=0,
        model="bogus/nonexistent-model",
    )
    assert comp.text == ""
    assert comp.finish_reason == "error"
    assert "404" in comp.raw["error"]
    assert comp.model == "bogus/nonexistent-model"


# ---------------------------------------------------------------------------
# 5. exhausted retries surface a clear error completion
# ---------------------------------------------------------------------------


def test_5xx_exhausts_retries(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-v1-fake")
    cfg = orc._Config(max_retries=2, backoff_base_s=0.0)
    sess = _FakeSession(
        [_FakeResp(503, {"error": "upstream"}) for _ in range(cfg.max_retries + 1)]
    )
    client = orc.Client(cfg=cfg, session=sess, sleep=lambda _s: None)
    comp = client.complete(
        "p",
        format_id="A1",
        question_id="q01",
        replicate_idx=0,
        model="anthropic/claude-sonnet-4.6",
    )
    assert comp.finish_reason == "error"
    assert "503" in comp.raw["error"] or "exhausted" in comp.raw["error"].lower()
    assert len(sess.calls) == cfg.max_retries + 1
