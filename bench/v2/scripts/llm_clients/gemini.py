"""Google Gemini client adapter.

Live-mode requires `GEMINI_API_KEY` and the `google-generativeai` SDK.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Dict, Optional

from .mock import Completion


@dataclass
class _Config:
    api_key_env: str = "GEMINI_API_KEY"
    default_model: str = "gemini-1.5-pro"
    max_output_tokens: int = 1024


class Client:
    name = "gemini"
    env_var = "GEMINI_API_KEY"
    default_model = _Config.default_model

    def __init__(self) -> None:
        self.cfg = _Config()
        try:
            import google.generativeai  # noqa: F401  pyright: ignore[reportMissingImports]

            self._sdk_present = True
        except Exception:
            self._sdk_present = False

    @classmethod
    def available(cls) -> bool:
        if not os.environ.get(cls.env_var):
            return False
        try:
            import google.generativeai  # noqa: F401
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
        import google.generativeai as genai  # type: ignore  # pyright: ignore[reportMissingImports]

        genai.configure(api_key=os.environ[self.env_var])
        chosen_model = model or self.default_model
        gen_cfg = {
            "temperature": temperature,
            "max_output_tokens": self.cfg.max_output_tokens,
        }
        m = genai.GenerativeModel(chosen_model, generation_config=gen_cfg)
        resp = m.generate_content(prompt)
        text = getattr(resp, "text", "") or ""
        raw: Dict[str, Any] = {
            "candidates": [
                {"finish_reason": getattr(c, "finish_reason", None)}
                for c in getattr(resp, "candidates", []) or []
            ],
            "usage_metadata": getattr(resp, "usage_metadata", None).__dict__
            if getattr(resp, "usage_metadata", None)
            else None,
        }
        return Completion(
            text=text,
            raw=raw,
            model=chosen_model,
            family="gemini",
            finish_reason="stop",
        )
