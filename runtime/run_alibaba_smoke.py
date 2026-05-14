"""Run one tiny Alibaba Model Studio Chat Completions smoke test."""

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

from providers.alibaba import (
    DEFAULT_EXECUTOR_MODEL,
    DEFAULT_ROUTER_MODEL,
    AlibabaAPIProvider,
    MissingAlibabaAPIKeyError,
)
from sfe.env import load_repo_env


PROMPT = "Reply with exactly: ALIBABA_OK"
MAX_OUTPUT_TOKENS = 16


def main() -> int:
    load_repo_env()
    args = _parse_args()
    models = [args.model] if args.model else [DEFAULT_ROUTER_MODEL, DEFAULT_EXECUTOR_MODEL]
    provider = AlibabaAPIProvider()
    messages = [{"role": "user", "content": PROMPT}]

    last_error = ""
    for model in models:
        started = time.perf_counter()
        try:
            response = provider.chat(
                messages,
                model=model,
                max_tokens=MAX_OUTPUT_TOKENS,
                temperature=0.0,
            )
        except MissingAlibabaAPIKeyError:
            print("success: false")
            print("error: ALIBABA_API_KEY is required")
            return 2
        except Exception as exc:
            latency_ms = int((time.perf_counter() - started) * 1000)
            last_error = _safe_error_message(exc)
            print("model_attempt:", model)
            print("success: false")
            print("error:", last_error)
            print("latency_ms:", latency_ms)
            continue

        latency_ms = int((time.perf_counter() - started) * 1000)
        response_text = _extract_response_text(response)
        usage = _extract_usage(response)
        success = response_text.strip() == "ALIBABA_OK"

        print("success:", str(success).lower())
        print("model:", model)
        print("response_text:", response_text[:80])
        print("prompt_tokens:", _format_optional_int(usage.get("prompt_tokens")))
        print("completion_tokens:", _format_optional_int(usage.get("completion_tokens")))
        print("reasoning_tokens:", _format_optional_int(usage.get("reasoning_tokens")))
        print("total_tokens:", _format_optional_int(usage.get("total_tokens")))
        print("disable_thinking:", str(provider.disable_thinking).lower())
        print("latency_ms:", latency_ms)
        return 0 if success else 1

    print("success: false")
    print("error:", last_error or "all Alibaba model attempts failed")
    return 1


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run one tiny Alibaba Model Studio smoke test without logging secrets."
    )
    parser.add_argument(
        "--model",
        help=(
            "Alibaba model ID to use. Defaults to qwen3.6-flash, then "
            "qwen3.6-plus fallback."
        ),
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
    return {
        "prompt_tokens": _optional_int(usage.get("prompt_tokens")),
        "completion_tokens": _optional_int(usage.get("completion_tokens")),
        "reasoning_tokens": _optional_int(usage.get("reasoning_tokens")),
        "total_tokens": _optional_int(usage.get("total_tokens")),
    }


def _optional_int(value: object) -> int | None:
    if value is None:
        return None
    return int(value)


def _format_optional_int(value: int | None) -> str:
    return "n/a" if value is None else str(value)


def _safe_error_message(exc: Exception) -> str:
    message = str(exc).strip() or exc.__class__.__name__
    api_key = os.getenv("ALIBABA_API_KEY")
    if api_key:
        message = message.replace(api_key, "[REDACTED]")
    return message


if __name__ == "__main__":
    raise SystemExit(main())
