"""Run one tiny OpenAI Responses API smoke test."""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from providers.openai_api import MissingOpenAIAPIKeyError, OpenAIAPIProvider
from sfe.env import load_repo_env


PROMPT = "Reply with OK."
# The Responses API rejected lower values for the configured smoke-test model.
MAX_OUTPUT_TOKENS = 16


def main() -> int:
    load_repo_env()
    args = _parse_args()
    model = args.model or os.getenv("SFE_OPENAI_EXECUTOR_MODEL")
    if not model:
        print("success: false")
        print("error: SFE_OPENAI_EXECUTOR_MODEL is required unless --model is provided")
        return 2

    provider = OpenAIAPIProvider()
    messages = [{"role": "user", "content": PROMPT}]

    started = time.perf_counter()
    try:
        response = provider.chat(
            messages,
            model=model,
            max_tokens=MAX_OUTPUT_TOKENS,
            temperature=None,
        )
    except MissingOpenAIAPIKeyError:
        print("success: false")
        print("model:", model)
        print("error: OPENAI_API_KEY is required")
        return 2
    except Exception as exc:
        latency_ms = int((time.perf_counter() - started) * 1000)
        print("success: false")
        print("model:", model)
        print("error:", _safe_error_message(exc))
        print("latency_ms:", latency_ms)
        return 1

    latency_ms = int((time.perf_counter() - started) * 1000)
    response_text = _extract_response_text(response)
    usage = _extract_usage(response)
    success = bool(response_text.strip())

    print("success:", str(success).lower())
    print("model:", model)
    print("response_text_length:", len(response_text))
    if response_text.strip() == "OK":
        print("response_text: OK")
    print("input_tokens:", _format_optional_int(usage.get("input_tokens")))
    print("output_tokens:", _format_optional_int(usage.get("output_tokens")))
    print("total_tokens:", _format_optional_int(usage.get("total_tokens")))
    print("latency_ms:", latency_ms)
    return 0 if success else 1


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run one tiny OpenAI API smoke test without logging prompts or secrets."
    )
    parser.add_argument(
        "--model",
        help="OpenAI model ID to use. Defaults to SFE_OPENAI_EXECUTOR_MODEL.",
    )
    return parser.parse_args()


def _extract_response_text(response: dict[str, Any]) -> str:
    choices = response.get("choices", [])
    if not isinstance(choices, list) or not choices:
        return ""
    first_choice = choices[0]
    if not isinstance(first_choice, dict):
        return ""
    message = first_choice.get("message", {})
    if isinstance(message, dict) and message.get("content") is not None:
        return str(message["content"]).strip()
    if first_choice.get("text") is not None:
        return str(first_choice["text"]).strip()
    return ""


def _extract_usage(response: dict[str, Any]) -> dict[str, int | None]:
    usage = response.get("usage", {})
    if not isinstance(usage, dict):
        usage = {}
    input_tokens = _optional_int(usage.get("prompt_tokens"))
    output_tokens = _optional_int(usage.get("completion_tokens"))
    total_tokens = _optional_int(usage.get("total_tokens"))
    if total_tokens is None and input_tokens is not None and output_tokens is not None:
        total_tokens = input_tokens + output_tokens
    return {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": total_tokens,
    }


def _optional_int(value: object) -> int | None:
    if value is None:
        return None
    return int(value)


def _format_optional_int(value: int | None) -> str:
    return "n/a" if value is None else str(value)


def _safe_error_message(exc: Exception) -> str:
    message = str(exc).strip()
    if not message:
        return exc.__class__.__name__
    api_key = os.getenv("OPENAI_API_KEY")
    if api_key:
        message = message.replace(api_key, "[REDACTED]")
    return message


if __name__ == "__main__":
    raise SystemExit(main())
