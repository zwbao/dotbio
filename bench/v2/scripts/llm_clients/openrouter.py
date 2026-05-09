"""OpenRouter client adapter (round-2).

OpenRouter exposes a unified, OpenAI-compatible chat-completions API at
``https://openrouter.ai/api/v1/chat/completions``. A single API key
(``OPENROUTER_API_KEY``) buys access to dozens of model providers via
slugs like ``anthropic/claude-sonnet-4.6`` or ``openai/gpt-5-mini``.

This adapter:

- talks to OpenRouter via plain ``requests`` (no SDK dependency)
- returns the same ``Completion`` shape as the other clients
- exposes the OpenRouter ``usage`` block (prompt/completion tokens AND
  the per-call cost OpenRouter computes when you append
  ``usage={"include": true}`` to the body) so the harness can enforce a
  hard cost cap
- retries on 429 / 5xx with exponential backoff
- never crashes the harness on a single-call failure: returns a
  ``Completion`` with empty text and ``finish_reason='error'`` plus the
  raw error in ``raw['error']``
"""

from __future__ import annotations

import json
import os
import random
import time
from dataclasses import dataclass
from typing import Any, Callable, Dict, Optional

from .mock import Completion


@dataclass
class _Config:
    api_key_env: str = "OPENROUTER_API_KEY"
    base_url: str = "https://openrouter.ai/api/v1"
    default_model: str = "anthropic/claude-3.5-sonnet"
    max_tokens: int = 1024
    request_timeout_s: float = 120.0
    max_retries: int = 4
    backoff_base_s: float = 1.5
    # Optional headers OpenRouter recommends for analytics; empty by default.
    http_referer: Optional[str] = None
    x_title: Optional[str] = "dotbio-bench-v2"


class Client:
    """OpenRouter chat-completions adapter.

    The class-level ``available()`` only requires ``OPENROUTER_API_KEY``
    to be set; we deliberately do not require the ``openai`` SDK because
    OpenRouter's API is a plain JSON HTTP endpoint and the harness has
    ``requests`` as its only HTTP dependency.
    """

    name = "openrouter"
    env_var = "OPENROUTER_API_KEY"
    default_model = _Config.default_model

    def __init__(
        self,
        *,
        cfg: Optional[_Config] = None,
        session: Any = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.cfg = cfg or _Config()
        self._sleep = sleep
        # Lazy-import requests so importing this module never crashes the
        # harness — the SDK check happens in ``available()`` instead.
        if session is not None:
            self._session = session
        else:
            try:
                import requests  # noqa: F401  pyright: ignore[reportMissingImports]

                self._session = requests.Session()
            except Exception:
                self._session = None

    # ------------------------------------------------------------------
    # Availability
    # ------------------------------------------------------------------
    @classmethod
    def available(cls) -> bool:
        if not os.environ.get(cls.env_var):
            return False
        try:
            import requests  # noqa: F401
        except Exception:
            return False
        return True

    # ------------------------------------------------------------------
    # HTTP plumbing
    # ------------------------------------------------------------------
    def _headers(self) -> Dict[str, str]:
        h = {
            "Authorization": f"Bearer {os.environ[self.cfg.api_key_env]}",
            "Content-Type": "application/json",
        }
        if self.cfg.http_referer:
            h["HTTP-Referer"] = self.cfg.http_referer
        if self.cfg.x_title:
            h["X-Title"] = self.cfg.x_title
        return h

    def _post(self, path: str, body: Dict[str, Any]) -> Dict[str, Any]:
        """POST with exponential-backoff retry on 429 and 5xx."""
        if self._session is None:  # pragma: no cover - defensive
            raise RuntimeError(
                "OpenRouter client requires the `requests` library; install it."
            )
        url = f"{self.cfg.base_url.rstrip('/')}{path}"
        last_exc: Optional[Exception] = None
        last_status: Optional[int] = None
        last_text: Optional[str] = None
        for attempt in range(self.cfg.max_retries + 1):
            try:
                resp = self._session.post(
                    url,
                    headers=self._headers(),
                    data=json.dumps(body),
                    timeout=self.cfg.request_timeout_s,
                )
            except Exception as exc:  # network error
                last_exc = exc
                if attempt < self.cfg.max_retries:
                    self._sleep(self._backoff(attempt))
                    continue
                raise
            status = resp.status_code
            last_status = status
            try:
                last_text = resp.text
            except Exception:
                last_text = None
            if status == 200:
                try:
                    return resp.json()
                except ValueError as exc:
                    raise RuntimeError(
                        f"OpenRouter 200 but non-JSON body: {last_text!r}"
                    ) from exc
            if status in (429,) or 500 <= status < 600:
                if attempt < self.cfg.max_retries:
                    self._sleep(self._backoff(attempt, retry_after_header=resp.headers.get("Retry-After")))
                    continue
            # 4xx other than 429 -> raise immediately with body for debugging.
            raise RuntimeError(
                f"OpenRouter HTTP {status} on {path}: {last_text!r}"
            )
        # Exhausted retries without 200 — synthesise a clear error.
        raise RuntimeError(
            f"OpenRouter exhausted retries ({self.cfg.max_retries+1}). "
            f"last_status={last_status}, last_exc={last_exc}, body={last_text!r}"
        )

    def _backoff(self, attempt: int, *, retry_after_header: Optional[str] = None) -> float:
        if retry_after_header:
            try:
                return float(retry_after_header)
            except ValueError:
                pass
        # Exponential with jitter: base * 2**attempt +/- 25%
        base = self.cfg.backoff_base_s * (2 ** attempt)
        return base * (1.0 + random.uniform(-0.25, 0.25))

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def list_models(self) -> Dict[str, Any]:
        """Return the parsed ``GET /models`` payload from OpenRouter."""
        if self._session is None:  # pragma: no cover - defensive
            raise RuntimeError("requests library required")
        url = f"{self.cfg.base_url.rstrip('/')}/models"
        resp = self._session.get(url, headers=self._headers(), timeout=30)
        if resp.status_code != 200:
            raise RuntimeError(
                f"OpenRouter /models HTTP {resp.status_code}: {resp.text[:200]!r}"
            )
        return resp.json()

    def complete(
        self,
        prompt: str,
        *,
        format_id: str,
        question_id: str,
        replicate_idx: int = 0,
        temperature: float = 0.7,
        seed: Optional[int] = None,
        model: Optional[str] = None,
    ) -> Completion:
        """Send one chat-completion request and return a Completion.

        The returned ``raw`` dict carries the OpenRouter ``usage`` block
        verbatim (prompt_tokens, completion_tokens, total_tokens, cost
        if available). Cost is the dollar amount OpenRouter charged for
        this single call when you pass ``usage={"include": true}`` in
        the request body. The harness sums this to enforce the cap.
        """
        chosen_model = model or self.default_model
        body: Dict[str, Any] = {
            "model": chosen_model,
            "temperature": temperature,
            "max_tokens": self.cfg.max_tokens,
            "messages": [{"role": "user", "content": prompt}],
            # Asks OpenRouter to embed `usage.cost` in the response.
            "usage": {"include": True},
        }
        if seed is not None:
            body["seed"] = seed

        try:
            data = self._post("/chat/completions", body)
        except Exception as exc:
            return Completion(
                text="",
                raw={"error": str(exc), "model": chosen_model},
                model=chosen_model,
                family="openrouter",
                finish_reason="error",
            )

        choices = data.get("choices") or []
        if not choices:
            return Completion(
                text="",
                raw={"error": "no choices in response", "data": data},
                model=chosen_model,
                family="openrouter",
                finish_reason="error",
            )
        choice = choices[0]
        msg = choice.get("message") or {}
        text = msg.get("content") or ""
        finish_reason = choice.get("finish_reason") or "stop"
        usage = data.get("usage") or {}
        raw: Dict[str, Any] = {
            "id": data.get("id"),
            "model_returned": data.get("model"),
            "provider": data.get("provider"),
            "finish_reason": finish_reason,
            "usage": usage,
        }
        return Completion(
            text=text,
            raw=raw,
            model=chosen_model,
            family="openrouter",
            finish_reason=finish_reason or "stop",
        )


__all__ = ["Client"]
