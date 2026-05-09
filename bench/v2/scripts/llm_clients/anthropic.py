"""Anthropic (Claude) client adapter.

Live-mode requires `ANTHROPIC_API_KEY` and the `anthropic` Python SDK.
When either is missing, `available()` returns False and the harness
falls back to the mock client. We intentionally do NOT pip-install
anthropic at import time; the SDK is a lazy/optional dependency.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Dict, Optional

from .mock import Completion


@dataclass
class _Config:
    api_key_env: str = "ANTHROPIC_API_KEY"
    default_model: str = "claude-3-5-sonnet-20241022"
    max_tokens: int = 1024


class Client:
    name = "anthropic"
    env_var = "ANTHROPIC_API_KEY"
    default_model = _Config.default_model

    def __init__(self) -> None:
        self.cfg = _Config()
        # Lazy import — only required when the client is actually live.
        try:
            import anthropic  # noqa: F401  pyright: ignore[reportMissingImports]

            self._sdk_present = True
        except Exception:
            self._sdk_present = False

    @classmethod
    def available(cls) -> bool:
        if not os.environ.get(cls.env_var):
            return False
        try:
            import anthropic  # noqa: F401
        except Exception:
            return False
        return True

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
        # Live path. Kept compact; round-1 expects this to be reached
        # only when keys + SDK are both present.
        import anthropic  # type: ignore  # pyright: ignore[reportMissingImports]

        client = anthropic.Anthropic(api_key=os.environ[self.env_var])
        chosen_model = model or self.default_model
        msg = client.messages.create(
            model=chosen_model,
            max_tokens=self.cfg.max_tokens,
            temperature=temperature,
            messages=[{"role": "user", "content": prompt}],
        )
        text = "".join(
            block.text for block in msg.content if getattr(block, "type", None) == "text"
        )
        raw: Dict[str, Any] = {
            "stop_reason": getattr(msg, "stop_reason", None),
            "usage": getattr(msg, "usage", None).__dict__
            if getattr(msg, "usage", None)
            else None,
        }
        return Completion(
            text=text,
            raw=raw,
            model=chosen_model,
            family="claude",
            finish_reason=getattr(msg, "stop_reason", "stop") or "stop",
        )
