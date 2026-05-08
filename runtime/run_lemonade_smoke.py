"""Run one Lemonade chat completion and log it as an experiment."""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from providers.lemonade import LemonadeProvider
from runtime.logger import log_run
from runtime.metrics import estimated_token_usage


PROMPT = "Classify this task in one word: write a short article about spatial cognition."
DEFAULT_MODEL = "user.Qwen3.5-4B-GGUF"


def main() -> None:
    model = os.getenv("SFE_LEMONADE_MODEL") or DEFAULT_MODEL
    provider = LemonadeProvider()
    messages = [{"role": "user", "content": PROMPT}]

    started = time.perf_counter()
    response = provider.chat(messages, model=model, max_tokens=64, temperature=0.0)
    latency_ms = int((time.perf_counter() - started) * 1000)

    response_text = _extract_response_text(response)
    token_usage = _extract_token_usage(response, PROMPT, response_text)

    run_id = log_run(
        {
            "task_type": "review",
            "mode": "spatial",
            "provider": "lemonade",
            "model": model,
            "input_tokens": token_usage["input_tokens"],
            "output_tokens": token_usage["output_tokens"],
            "total_tokens": token_usage["total_tokens"],
            "latency_ms": latency_ms,
            "success": bool(response_text.strip()),
            "notes": "lemonade smoke run",
        }
    )

    print(f"model: {model}")
    print(f"response text: {response_text}")
    print(f"token usage: {token_usage}")
    print(f"run_id: {run_id}")
    print(f"latency_ms: {latency_ms}")


def _extract_response_text(response: dict) -> str:
    choices = response.get("choices", [])
    if not choices:
        return ""

    first_choice = choices[0]
    if not isinstance(first_choice, dict):
        return ""

    message = first_choice.get("message", {})
    if isinstance(message, dict) and message.get("content") is not None:
        content = str(message["content"]).strip()
        if content:
            return content

    if isinstance(message, dict) and message.get("reasoning_content") is not None:
        return str(message["reasoning_content"]).strip()

    if first_choice.get("text") is not None:
        return str(first_choice["text"]).strip()

    return ""


def _extract_token_usage(response: dict, prompt: str, response_text: str) -> dict:
    usage = response.get("usage", {})
    if isinstance(usage, dict):
        prompt_tokens = usage.get("prompt_tokens")
        completion_tokens = usage.get("completion_tokens")
        total_tokens = usage.get("total_tokens")

        if prompt_tokens is not None and completion_tokens is not None:
            input_tokens = int(prompt_tokens)
            output_tokens = int(completion_tokens)
            if total_tokens is None:
                total_tokens = input_tokens + output_tokens

            return {
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "total_tokens": int(total_tokens),
            }

    return estimated_token_usage(prompt, response_text)


if __name__ == "__main__":
    main()
