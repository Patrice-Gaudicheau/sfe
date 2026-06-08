"""Optional live Ollama smoke test."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from providers.ollama import DEFAULT_MODEL, OllamaProvider, OllamaProviderError


PROMPT = "Return the word OK."


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--model",
        default=os.getenv("SFE_OLLAMA_MODEL") or DEFAULT_MODEL,
        help="Ollama model ID to use. Defaults to SFE_OLLAMA_MODEL, then qwen3.5:4b.",
    )
    parser.add_argument(
        "--base-url",
        default=os.getenv("SFE_OLLAMA_BASE_URL"),
        help="Ollama base URL. Defaults to SFE_OLLAMA_BASE_URL, then http://localhost:11434.",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=None,
        help="Request timeout in seconds. Defaults to SFE_OLLAMA_TIMEOUT_SECONDS, then 120.",
    )
    args = parser.parse_args()

    provider = OllamaProvider(base_url=args.base_url, timeout=args.timeout)
    try:
        response = provider.chat(
            [{"role": "user", "content": PROMPT}],
            model=args.model,
            max_tokens=8,
            temperature=0.0,
        )
    except OllamaProviderError as exc:
        print(f"error: {exc.error_category}: {exc}", file=sys.stderr)
        return 1

    text = response["choices"][0]["message"]["content"].strip()
    print(f"provider: ollama")
    print(f"base_url: {provider.base_url}")
    print(f"model: {args.model}")
    print(f"response text: {text}")
    return 0 if "OK" in text.upper() else 1


if __name__ == "__main__":
    raise SystemExit(main())
