"""Unit tests for shared SFE provider configuration helpers."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from sfe.provider_config import (
    normalize_provider_name,
    resolve_sfe_provider,
    resolve_sfe_provider_with_legacy_fallback,
)


def test_unset_sfe_provider_returns_default() -> None:
    assert resolve_sfe_provider({}, default="openai") == "openai"


def test_blank_sfe_provider_returns_default() -> None:
    assert resolve_sfe_provider({"SFE_PROVIDER": "  "}, default="lemonade") == "lemonade"


@pytest.mark.parametrize(
    ("provider", "expected"),
    (
        ("openai", "openai"),
        ("lemonade", "lemonade"),
        ("alibaba", "alibaba"),
        ("anthropic", "anthropic"),
        ("google", "google"),
        ("openai-compatible", "openai-compatible"),
    ),
)
def test_sfe_provider_canonical_values(provider: str, expected: str) -> None:
    assert resolve_sfe_provider({"SFE_PROVIDER": provider}) == expected


def test_provider_normalizes_whitespace_and_case() -> None:
    assert normalize_provider_name("  LeMoNaDe  ") == "lemonade"


def test_openai_api_alias_normalizes_to_openai() -> None:
    assert normalize_provider_name("openai-api") == "openai"
    assert resolve_sfe_provider({"SFE_PROVIDER": "OPENAI-API"}) == "openai"


def test_alibaba_api_alias_normalizes_to_alibaba() -> None:
    assert normalize_provider_name("alibaba-api") == "alibaba"
    assert resolve_sfe_provider({"SFE_PROVIDER": "ALIBABA-API"}) == "alibaba"


def test_gemini_alias_normalizes_to_google() -> None:
    assert normalize_provider_name("gemini") == "google"
    assert resolve_sfe_provider({"SFE_PROVIDER": "GEMINI"}) == "google"


def test_unknown_provider_raises_clear_error() -> None:
    with pytest.raises(ValueError, match="Unsupported SFE provider"):
        resolve_sfe_provider({"SFE_PROVIDER": "unknown-provider"})


def test_codexcli_is_not_a_shared_sfe_provider_yet() -> None:
    with pytest.raises(ValueError, match="Unsupported SFE provider"):
        resolve_sfe_provider({"SFE_PROVIDER": "openai-codexcli"})


def test_default_is_normalized_and_validated() -> None:
    assert resolve_sfe_provider({}, default="OPENAI-API") == "openai"
    with pytest.raises(ValueError, match="Unsupported SFE provider"):
        resolve_sfe_provider({}, default="invalid-default")


def test_sfe_provider_takes_precedence_over_legacy_provider() -> None:
    environ = {
        "SFE_PROVIDER": "anthropic",
        "SFE_PROXY_PROVIDER": "lemonade",
    }

    assert resolve_sfe_provider_with_legacy_fallback(environ) == "anthropic"


def test_legacy_provider_fallback_used_when_sfe_provider_unset() -> None:
    environ = {"SFE_PROXY_PROVIDER": "lemonade"}

    assert resolve_sfe_provider_with_legacy_fallback(environ) == "lemonade"


def test_legacy_provider_fallback_ignores_blank_sfe_provider() -> None:
    environ = {
        "SFE_PROVIDER": "",
        "SFE_PROXY_PROVIDER": "alibaba-api",
    }

    assert resolve_sfe_provider_with_legacy_fallback(environ) == "alibaba"


def test_legacy_provider_default_used_when_both_unset() -> None:
    assert resolve_sfe_provider_with_legacy_fallback({}) == "openai-compatible"


def test_custom_legacy_env_var_is_supported_without_wiring_behavior() -> None:
    environ = {"OLD_PROVIDER": "openai-api"}

    assert (
        resolve_sfe_provider_with_legacy_fallback(
            environ,
            legacy_env_var="OLD_PROVIDER",
            default="lemonade",
        )
        == "openai"
    )


def test_no_env_loading_required(tmp_path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("SFE_PROVIDER=anthropic\n", encoding="utf-8")

    assert resolve_sfe_provider({}, default="openai") == "openai"
