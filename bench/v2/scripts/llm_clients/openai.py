"""OpenAI (GPT-4o) client adapter.

Live-mode requires `OPENAI_API_KEY` and the `openai` Python SDK.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Dict, Optional

from .mock import Completion


@dataclass
class _Config:
    api_key_env: str = "OPENAI_API_KEY"
    default_model: str = "gpt-4o-2024-08-06"
    max_tokens: int = 1024


class Client:
    name = "openai"
    env_var = "OPENAI_API_KEY"
    default_model = _Config.default_model

    def __init__(self) -> None:
        self.cfg = _Config()
        try:
            import openai  # noqa: F401  pyright: ignore[reportMissingImports]

            self._sdk_present = True
        except Exception:
            self._sdk_present = False

    @classmethod
    def available(cls) -> bool:
        if not os.environ.get(cls.env_var):
            return False
        try:
            import openai  # noqa: F401
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
        import openai  # type: ignore  # pyright: ignore[reportMissingImports]

        client = openai.OpenAI(api_key=os.environ[self.env_var])
        chosen_model = model or self.default_model
        kwargs: Dict[str, Any] = {
            "model": chosen_model,
            "temperature": temperature,
            "max_tokens": self.cfg.max_tokens,
            "messages": [{"role": "user", "content": prompt}],
        }
        if seed is not None:
            kwargs["seed"] = seed
        resp = client.chat.completions.create(**kwargs)
        choice = resp.choices[0]
        text = choice.message.content or ""
        raw = {
            "finish_reason": choice.finish_reason,
            "usage": resp.usage.model_dump() if getattr(resp, "usage", None) else None,
            "system_fingerprint": getattr(resp, "system_fingerprint", None),
        }
        return Completion(
            text=text,
            raw=raw,
            model=chosen_model,
            family="openai",
            finish_reason=choice.finish_reason or "stop",
        )
