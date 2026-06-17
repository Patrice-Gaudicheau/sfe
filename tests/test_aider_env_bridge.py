"""Tests for the SFE-to-Aider environment bridge."""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

from sfe.aider_env_bridge import (
    resolve_aider_env_bridge,
    write_temporary_aider_env_file,
)


def test_openai_maps_base_url_to_openai_api_base() -> None:
    result = resolve_aider_env_bridge(
        {
            "SFE_PROVIDER": "openai",
            "OPENAI_API_KEY": "fixture-openai-key",
            "OPENAI_BASE_URL": "https://example.test/v1",
            "SFE_OPENAI_EXECUTOR_MODEL": "gpt-fixture",
        }
    )

    assert result.ok
    assert result.provider_name == "openai"
    assert result.aider_env == {
        "OPENAI_API_KEY": "fixture-openai-key",
        "OPENAI_API_BASE": "https://example.test/v1",
        "OPENAI_BASE_URL": "https://example.test/v1",
    }
    assert result.selected_model == "gpt-fixture"
    assert result.diagnostics["aider_env_variable_names"] == (
        "OPENAI_API_BASE",
        "OPENAI_API_KEY",
        "OPENAI_BASE_URL",
    )


def test_openai_missing_key_fails_with_variable_name_only() -> None:
    result = resolve_aider_env_bridge(
        {
            "SFE_PROVIDER": "openai",
            "SFE_OPENAI_EXECUTOR_MODEL": "gpt-fixture",
        }
    )

    assert not result.ok
    assert result.error_category == "missing_aider_environment"
    assert result.missing_variables == ("OPENAI_API_KEY",)
    assert "fixture-openai-key" not in repr(result.diagnostics)


def test_aider_model_overrides_provider_model() -> None:
    result = resolve_aider_env_bridge(
        {
            "SFE_PROVIDER": "openai",
            "SFE_PROVIDER_EXECUTOR": "anthropic",
            "OPENAI_API_KEY": "fixture-openai-key",
            "ANTHROPIC_API_KEY": "fixture-anthropic-key",
            "SFE_AIDER_MODEL": "aider/main-model",
            "SFE_OPENAI_EXECUTOR_MODEL": "provider-model",
            "SFE_ANTHROPIC_EXECUTOR_MODEL": "anthropic-provider-model",
            "SFE_OPENAI_ROUTER_MODEL": "expensive-router-model",
        }
    )

    assert result.ok
    assert result.provider_name == "anthropic"
    assert result.selected_model == "aider/main-model"


def test_codexcli_executor_provider_does_not_select_aider_provider() -> None:
    result = resolve_aider_env_bridge(
        {
            "SFE_PROVIDER_EXECUTOR": "codexcli",
            "SFE_AIDER_MODEL": "gpt-5.4-mini",
            "SFE_OPENAI_EXECUTOR_MODEL": "gpt-5.4-mini",
            "SFE_CODEXCLI_EXECUTOR_MODEL": "gpt-5.4",
            "OPENAI_API_KEY": "fixture-openai-key",
        }
    )

    assert result.ok
    assert result.provider_name == "openai"
    assert result.selected_model == "gpt-5.4-mini"
    assert result.aider_env == {"OPENAI_API_KEY": "fixture-openai-key"}
    assert result.diagnostics["provider_source_env_var"] == "default"
    assert result.diagnostics["provider_source_value"] == "openai"
    assert result.diagnostics["ignored_provider_env_var"] == "SFE_PROVIDER_EXECUTOR"
    assert result.diagnostics["ignored_provider_value"] == "codexcli"


def test_codexcli_shared_provider_does_not_select_aider_provider() -> None:
    result = resolve_aider_env_bridge(
        {
            "SFE_PROVIDER": "codexcli",
            "SFE_PROVIDER_EXECUTOR": "codexcli",
            "SFE_AIDER_MODEL": "gpt-5.4-mini",
            "OPENAI_API_KEY": "fixture-openai-key",
        }
    )

    assert result.ok
    assert result.provider_name == "openai"
    assert result.selected_model == "gpt-5.4-mini"
    assert result.diagnostics["ignored_provider_env_var"] == "SFE_PROVIDER_EXECUTOR"
    assert result.diagnostics["ignored_provider_value"] == "codexcli"


def test_provider_specific_model_fallbacks() -> None:
    openai = resolve_aider_env_bridge(
        {
            "SFE_PROVIDER": "openai",
            "OPENAI_API_KEY": "fixture-openai-key",
            "SFE_OPENAI_EXECUTOR_MODEL": "openai-model",
        }
    )
    anthropic = resolve_aider_env_bridge(
        {
            "SFE_PROVIDER": "anthropic",
            "ANTHROPIC_API_KEY": "fixture-anthropic-key",
            "SFE_ANTHROPIC_EXECUTOR_MODEL": "claude-fixture",
        }
    )
    google = resolve_aider_env_bridge(
        {
            "SFE_PROVIDER": "google",
            "GOOGLE_API_KEY": "fixture-google-key",
            "SFE_GOOGLE_MODEL": "gemini-fixture",
        }
    )

    assert openai.selected_model == "openai-model"
    assert anthropic.selected_model == "claude-fixture"
    assert google.selected_model == "gemini-fixture"


def test_openai_executor_provider_model_is_used_without_aider_override() -> None:
    result = resolve_aider_env_bridge(
        {
            "SFE_PROVIDER": "anthropic",
            "SFE_PROVIDER_EXECUTOR": "openai",
            "OPENAI_API_KEY": "fixture-openai-key",
            "ANTHROPIC_API_KEY": "fixture-anthropic-key",
            "SFE_OPENAI_EXECUTOR_MODEL": "openai-executor-model",
            "SFE_ANTHROPIC_EXECUTOR_MODEL": "anthropic-executor-model",
            "SFE_OPENAI_ROUTER_MODEL": "openai-router-model",
        }
    )

    assert result.ok
    assert result.provider_name == "openai"
    assert result.selected_model == "openai-executor-model"


def test_router_model_is_never_used_as_aider_fallback() -> None:
    result = resolve_aider_env_bridge(
        {
            "SFE_PROVIDER": "openai",
            "OPENAI_API_KEY": "fixture-openai-key",
            "SFE_OPENAI_ROUTER_MODEL": "expensive-router-model",
            "SFE_ROUTER_MODEL": "another-router-model",
        }
    )

    assert not result.ok
    assert result.error_category == "missing_aider_model"
    assert result.selected_model is None
    assert result.missing_variables == (
        "SFE_AIDER_MODEL",
        "SFE_OPENAI_EXECUTOR_MODEL",
    )
    assert "expensive-router-model" not in repr(result.diagnostics)
    assert "another-router-model" not in repr(result.diagnostics)


def test_only_router_model_for_explicit_provider_fails_closed() -> None:
    result = resolve_aider_env_bridge(
        {
            "SFE_PROVIDER_EXECUTOR": "google",
            "GOOGLE_API_KEY": "fixture-google-key",
            "SFE_GOOGLE_ROUTER_MODEL": "gemini-router-model",
        }
    )

    assert not result.ok
    assert result.provider_name == "google"
    assert result.error_category == "missing_aider_model"
    assert result.selected_model is None
    assert result.missing_variables == ("SFE_AIDER_MODEL", "SFE_GOOGLE_MODEL")


def test_google_maps_google_api_key_to_gemini_api_key() -> None:
    result = resolve_aider_env_bridge(
        {
            "SFE_PROVIDER": "google",
            "GOOGLE_API_KEY": "fixture-google-key",
            "SFE_GOOGLE_MODEL": "gemini-fixture",
        }
    )

    assert result.ok
    assert result.aider_env == {"GEMINI_API_KEY": "fixture-google-key"}


def test_openai_compatible_requires_explicit_aider_model() -> None:
    result = resolve_aider_env_bridge(
        {
            "SFE_PROVIDER": "openai-compatible",
            "OPENAI_API_KEY": "fixture-compatible-key",
            "OPENAI_BASE_URL": "https://compatible.example/v1",
            "SFE_OPENAI_EXECUTOR_MODEL": "provider-model",
        }
    )

    assert not result.ok
    assert result.error_category == "missing_aider_model"
    assert result.missing_variables == ("SFE_AIDER_MODEL",)


def test_alibaba_lemonade_and_ollama_require_explicit_aider_model() -> None:
    alibaba = resolve_aider_env_bridge(
        {
            "SFE_PROVIDER": "alibaba",
            "ALIBABA_API_KEY": "fixture-alibaba-key",
            "ALIBABA_BASE_URL": "https://dashscope.example/v1",
        }
    )
    lemonade = resolve_aider_env_bridge(
        {
            "SFE_PROVIDER": "lemonade",
            "SFE_LEMONADE_BASE_URL": "http://127.0.0.1:13305",
        }
    )
    ollama = resolve_aider_env_bridge(
        {
            "SFE_PROVIDER": "ollama",
            "SFE_OLLAMA_BASE_URL": "http://localhost:11434",
        }
    )

    assert alibaba.error_category == "missing_aider_model"
    assert lemonade.error_category == "missing_aider_model"
    assert ollama.error_category == "missing_aider_model"


def test_alibaba_maps_to_openai_compatible_when_model_is_explicit() -> None:
    result = resolve_aider_env_bridge(
        {
            "SFE_PROVIDER": "alibaba",
            "ALIBABA_API_KEY": "fixture-alibaba-key",
            "ALIBABA_BASE_URL": "https://dashscope.example/v1",
            "SFE_AIDER_MODEL": "openai/qwen-fixture",
        }
    )

    assert result.ok
    assert result.aider_env == {
        "OPENAI_API_KEY": "fixture-alibaba-key",
        "OPENAI_API_BASE": "https://dashscope.example/v1",
        "OPENAI_BASE_URL": "https://dashscope.example/v1",
    }
    assert result.selected_model == "openai/qwen-fixture"


def test_lemonade_maps_base_url_to_both_openai_base_conventions() -> None:
    result = resolve_aider_env_bridge(
        {
            "SFE_PROVIDER": "lemonade",
            "SFE_LEMONADE_API_KEY": "fixture-lemonade-key",
            "SFE_LEMONADE_BASE_URL": "http://127.0.0.1:13305",
            "SFE_AIDER_MODEL": "openai/phi-fixture",
        }
    )

    assert result.ok
    assert result.aider_env == {
        "OPENAI_API_KEY": "fixture-lemonade-key",
        "OPENAI_API_BASE": "http://127.0.0.1:13305/v1",
        "OPENAI_BASE_URL": "http://127.0.0.1:13305/v1",
    }
    assert result.selected_model == "openai/phi-fixture"


def test_explicit_codexcli_aider_provider_is_unsupported_with_source() -> None:
    result = resolve_aider_env_bridge({"SFE_AIDER_PROVIDER": "codexcli"})

    assert not result.ok
    assert result.error_category == "unsupported_aider_provider"
    assert result.aider_env == {}
    assert result.diagnostics["provider_source_env_var"] == "SFE_AIDER_PROVIDER"
    assert result.diagnostics["provider_source_value"] == "codexcli"


def test_timeout_parsing_accepts_positive_and_rejects_invalid() -> None:
    valid = resolve_aider_env_bridge(
        {
            "SFE_PROVIDER": "google",
            "GOOGLE_API_KEY": "fixture-google-key",
            "SFE_GOOGLE_MODEL": "gemini-fixture",
            "SFE_AIDER_TIMEOUT_SECONDS": "12.5",
        }
    )
    invalid = resolve_aider_env_bridge(
        {
            "SFE_PROVIDER": "google",
            "GOOGLE_API_KEY": "fixture-google-key",
            "SFE_GOOGLE_MODEL": "gemini-fixture",
            "SFE_AIDER_TIMEOUT_SECONDS": "0",
        }
    )

    assert valid.ok
    assert valid.selected_timeout_seconds == 12.5
    assert invalid.error_category == "invalid_aider_timeout"


def test_resolver_does_not_mutate_process_environment() -> None:
    with patch.dict(os.environ, {}, clear=True):
        result = resolve_aider_env_bridge(
            {
                "SFE_PROVIDER": "openai",
                "OPENAI_API_KEY": "fixture-openai-key",
                "SFE_OPENAI_EXECUTOR_MODEL": "gpt-fixture",
            }
        )

    assert result.ok
    assert "OPENAI_API_KEY" not in os.environ


def test_diagnostics_do_not_contain_provider_values() -> None:
    result = resolve_aider_env_bridge(
        {
            "SFE_PROVIDER": "openai",
            "OPENAI_API_KEY": "fixture-value-that-must-not-leak",
            "OPENAI_BASE_URL": "https://base-value-that-must-not-leak.test/v1",
            "SFE_OPENAI_EXECUTOR_MODEL": "gpt-fixture",
        }
    )

    diagnostics = repr(result.diagnostics)
    assert "fixture-value-that-must-not-leak" not in diagnostics
    assert "base-value-that-must-not-leak" not in diagnostics
    assert "OPENAI_API_KEY" in diagnostics
    assert "OPENAI_API_BASE" in diagnostics
    assert "OPENAI_BASE_URL" in diagnostics


def test_temporary_env_file_contains_only_expected_keys_and_is_deleted(
    tmp_path: Path,
) -> None:
    env_path_after_exit: Path
    with write_temporary_aider_env_file(
        {
            "OPENAI_API_KEY": "fixture-openai-key",
            "OPENAI_API_BASE": "https://example.test/v1",
            "OPENAI_BASE_URL": "https://example.test/v1",
        },
        forbidden_roots=(tmp_path,),
    ) as env_path:
        env_path_after_exit = env_path
        assert env_path.exists()
        assert not env_path.is_relative_to(tmp_path)
        text = env_path.read_text(encoding="utf-8")
        assert 'OPENAI_API_KEY="fixture-openai-key"' in text
        assert 'OPENAI_API_BASE="https://example.test/v1"' in text
        assert 'OPENAI_BASE_URL="https://example.test/v1"' in text
        assert "SFE_PROVIDER" not in text

    assert not env_path_after_exit.exists()
