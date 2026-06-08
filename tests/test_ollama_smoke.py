"""Opt-in live smoke test for a local Ollama server."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from providers.ollama import DEFAULT_MODEL, OllamaProvider


@pytest.mark.skipif(
    os.getenv("SFE_OLLAMA_LIVE_SMOKE") != "1",
    reason="set SFE_OLLAMA_LIVE_SMOKE=1 to run the live Ollama smoke test",
)
def test_live_ollama_returns_text() -> None:
    model = os.getenv("SFE_OLLAMA_MODEL") or DEFAULT_MODEL
    provider = OllamaProvider()

    response = provider.chat(
        [{"role": "user", "content": "Return the word OK."}],
        model=model,
        max_tokens=8,
        temperature=0.0,
    )

    assert "OK" in response["choices"][0]["message"]["content"].strip().upper()
