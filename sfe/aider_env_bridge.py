"""Secret-safe bridge from SFE provider configuration to Aider environment."""

from __future__ import annotations

import os
import tempfile
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from sfe.provider_config import (
    CODEXCLI_SFE_PROVIDER,
    SFE_PROVIDER_ENV,
    SFE_PROVIDER_EXECUTOR_ENV,
    normalize_provider_name,
)


SFE_AIDER_PROVIDER_ENV = "SFE_AIDER_PROVIDER"
SFE_AIDER_MODEL_ENV = "SFE_AIDER_MODEL"
SFE_AIDER_WEAK_MODEL_ENV = "SFE_AIDER_WEAK_MODEL"
SFE_AIDER_TIMEOUT_SECONDS_ENV = "SFE_AIDER_TIMEOUT_SECONDS"


@dataclass(frozen=True)
class AiderEnvBridgeResult:
    provider_name: str
    aider_env: dict[str, str]
    selected_model: str | None
    selected_weak_model: str | None
    selected_timeout_seconds: float | None
    missing_variables: tuple[str, ...]
    error_category: str | None
    diagnostics: dict[str, object]

    @property
    def ok(self) -> bool:
        return self.error_category is None


class AiderEnvFileError(RuntimeError):
    def __init__(self, error_category: str) -> None:
        self.error_category = error_category
        super().__init__(error_category)


def resolve_aider_env_bridge(
    environ: Mapping[str, str] | None = None,
) -> AiderEnvBridgeResult:
    """Resolve a minimal Aider environment without mutating process globals."""

    env = os.environ if environ is None else environ
    provider_result = _resolve_aider_provider(env)
    if isinstance(provider_result, str):
        return _result(
            provider_name="invalid",
            aider_env={},
            selected_model=None,
            selected_weak_model=_env_value(env, SFE_AIDER_WEAK_MODEL_ENV),
            selected_timeout_seconds=None,
            missing_variables=(),
            error_category="unsupported_sfe_provider",
            diagnostics_extra={
                "provider_source_env_var": provider_result,
                "provider_source_value": _env_value(env, provider_result),
            },
        )
    provider_name, provider_diagnostics = provider_result

    timeout_result = _resolve_timeout(env)
    if isinstance(timeout_result, str):
        return _result(
            provider_name=provider_name,
            aider_env={},
            selected_model=None,
            selected_weak_model=_env_value(env, SFE_AIDER_WEAK_MODEL_ENV),
            selected_timeout_seconds=None,
            missing_variables=(),
            error_category=timeout_result,
            diagnostics_extra=provider_diagnostics,
        )

    selected_model = _resolve_model(provider_name, env)
    selected_weak_model = _env_value(env, SFE_AIDER_WEAK_MODEL_ENV)
    aider_env: dict[str, str] = {}
    missing: list[str] = []

    if provider_name == "openai":
        _require_env(env, "OPENAI_API_KEY", missing, aider_env, "OPENAI_API_KEY")
        _optional_env(
            env,
            "OPENAI_BASE_URL",
            aider_env,
            "OPENAI_API_BASE",
            "OPENAI_BASE_URL",
        )
        if selected_model is None:
            missing.extend((SFE_AIDER_MODEL_ENV, "SFE_OPENAI_EXECUTOR_MODEL"))
    elif provider_name == "openai-compatible":
        _require_env(env, "OPENAI_API_KEY", missing, aider_env, "OPENAI_API_KEY")
        _require_env(
            env,
            "OPENAI_BASE_URL",
            missing,
            aider_env,
            "OPENAI_API_BASE",
            "OPENAI_BASE_URL",
        )
        if _env_value(env, SFE_AIDER_MODEL_ENV) is None:
            missing.append(SFE_AIDER_MODEL_ENV)
    elif provider_name == "anthropic":
        _require_env(env, "ANTHROPIC_API_KEY", missing, aider_env, "ANTHROPIC_API_KEY")
        if selected_model is None:
            missing.extend((SFE_AIDER_MODEL_ENV, "SFE_ANTHROPIC_EXECUTOR_MODEL"))
    elif provider_name == "google":
        _require_env(env, "GOOGLE_API_KEY", missing, aider_env, "GEMINI_API_KEY")
        if selected_model is None:
            missing.extend((SFE_AIDER_MODEL_ENV, "SFE_GOOGLE_MODEL"))
    elif provider_name == "alibaba":
        _require_env(env, "ALIBABA_API_KEY", missing, aider_env, "OPENAI_API_KEY")
        _require_env(
            env,
            "ALIBABA_BASE_URL",
            missing,
            aider_env,
            "OPENAI_API_BASE",
            "OPENAI_BASE_URL",
        )
        if _env_value(env, SFE_AIDER_MODEL_ENV) is None:
            missing.append(SFE_AIDER_MODEL_ENV)
    elif provider_name == "lemonade":
        _require_lemonade_base_url(env, missing, aider_env)
        _optional_env(env, "SFE_LEMONADE_API_KEY", aider_env, "OPENAI_API_KEY")
        if _env_value(env, SFE_AIDER_MODEL_ENV) is None:
            missing.append(SFE_AIDER_MODEL_ENV)
    elif provider_name == "ollama":
        _require_env(env, "SFE_OLLAMA_BASE_URL", missing, aider_env, "OLLAMA_API_BASE")
        if _env_value(env, SFE_AIDER_MODEL_ENV) is None:
            missing.append(SFE_AIDER_MODEL_ENV)
    elif provider_name == "codexcli":
        return _result(
            provider_name=provider_name,
            aider_env={},
            selected_model=None,
            selected_weak_model=selected_weak_model,
            selected_timeout_seconds=timeout_result,
            missing_variables=(),
            error_category="unsupported_aider_provider",
            diagnostics_extra=provider_diagnostics,
        )
    else:
        return _result(
            provider_name=provider_name,
            aider_env={},
            selected_model=None,
            selected_weak_model=selected_weak_model,
            selected_timeout_seconds=timeout_result,
            missing_variables=(),
            error_category="unsupported_aider_provider",
            diagnostics_extra=provider_diagnostics,
        )

    missing_variables = _dedupe(missing)
    error_category = _error_category_for_missing(missing_variables)
    return _result(
        provider_name=provider_name,
        aider_env=aider_env,
        selected_model=selected_model,
        selected_weak_model=selected_weak_model,
        selected_timeout_seconds=timeout_result,
        missing_variables=missing_variables,
        error_category=error_category,
        diagnostics_extra=provider_diagnostics,
    )


@contextmanager
def write_temporary_aider_env_file(
    aider_env: Mapping[str, str],
    *,
    forbidden_roots: Sequence[Path] = (),
) -> Iterator[Path]:
    """Write a minimal Aider env file outside forbidden roots and delete it."""

    with tempfile.TemporaryDirectory(prefix="sfe-aider-env-") as temp_dir:
        env_path = Path(temp_dir) / "aider.env"
        _ensure_outside_forbidden_roots(env_path, forbidden_roots)
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        fd = os.open(env_path, flags, 0o600)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                fd = -1
                for key in sorted(aider_env):
                    handle.write(f"{key}={_quote_env_value(aider_env[key])}\n")
            yield env_path
        finally:
            if fd != -1:
                os.close(fd)


def _resolve_model(provider_name: str, env: Mapping[str, str]) -> str | None:
    explicit = _env_value(env, SFE_AIDER_MODEL_ENV)
    if explicit is not None:
        return explicit
    if provider_name == "openai":
        return _env_value(env, "SFE_OPENAI_EXECUTOR_MODEL")
    if provider_name == "anthropic":
        return _env_value(env, "SFE_ANTHROPIC_EXECUTOR_MODEL")
    if provider_name == "google":
        return _env_value(env, "SFE_GOOGLE_MODEL")
    return None


def _resolve_aider_provider(
    env: Mapping[str, str],
) -> tuple[str, dict[str, object]] | str:
    explicit_aider_provider = _env_value(env, SFE_AIDER_PROVIDER_ENV)
    if explicit_aider_provider is not None:
        try:
            provider = normalize_provider_name(explicit_aider_provider)
        except ValueError:
            return SFE_AIDER_PROVIDER_ENV
        return provider, {
            "provider_source_env_var": SFE_AIDER_PROVIDER_ENV,
            "provider_source_value": explicit_aider_provider,
        }

    executor_provider = _env_value(env, SFE_PROVIDER_EXECUTOR_ENV)
    if executor_provider is not None:
        try:
            provider = normalize_provider_name(executor_provider)
        except ValueError:
            return SFE_PROVIDER_EXECUTOR_ENV
        if provider != CODEXCLI_SFE_PROVIDER:
            return provider, {
                "provider_source_env_var": SFE_PROVIDER_EXECUTOR_ENV,
                "provider_source_value": executor_provider,
            }
        fallback_result = _resolve_non_codexcli_aider_fallback(env)
        if isinstance(fallback_result, str):
            return fallback_result
        provider, diagnostics = fallback_result
        diagnostics.update(
            {
                "ignored_provider_env_var": SFE_PROVIDER_EXECUTOR_ENV,
                "ignored_provider_value": executor_provider,
            }
        )
        return provider, diagnostics

    return _resolve_non_codexcli_aider_fallback(env)


def _resolve_non_codexcli_aider_fallback(
    env: Mapping[str, str],
) -> tuple[str, dict[str, object]] | str:
    shared_provider = _env_value(env, SFE_PROVIDER_ENV)
    if shared_provider is not None:
        try:
            provider = normalize_provider_name(shared_provider)
        except ValueError:
            return SFE_PROVIDER_ENV
        if provider != CODEXCLI_SFE_PROVIDER:
            return provider, {
                "provider_source_env_var": SFE_PROVIDER_ENV,
                "provider_source_value": shared_provider,
            }
        return "openai", {
            "provider_source_env_var": "default",
            "provider_source_value": "openai",
            "ignored_provider_env_var": SFE_PROVIDER_ENV,
            "ignored_provider_value": shared_provider,
        }
    return "openai", {
        "provider_source_env_var": "default",
        "provider_source_value": "openai",
    }


def _resolve_timeout(env: Mapping[str, str]) -> float | None | str:
    raw = _env_value(env, SFE_AIDER_TIMEOUT_SECONDS_ENV)
    if raw is None:
        return None
    try:
        timeout = float(raw)
    except ValueError:
        return "invalid_aider_timeout"
    if timeout <= 0:
        return "invalid_aider_timeout"
    return timeout


def _require_env(
    env: Mapping[str, str],
    source_name: str,
    missing: list[str],
    aider_env: dict[str, str],
    target_name: str,
    *additional_target_names: str,
) -> None:
    value = _env_value(env, source_name)
    if value is None:
        missing.append(source_name)
        return
    aider_env[target_name] = value
    for additional_target_name in additional_target_names:
        aider_env[additional_target_name] = value


def _optional_env(
    env: Mapping[str, str],
    source_name: str,
    aider_env: dict[str, str],
    target_name: str,
    *additional_target_names: str,
) -> None:
    value = _env_value(env, source_name)
    if value is not None:
        aider_env[target_name] = value
        for additional_target_name in additional_target_names:
            aider_env[additional_target_name] = value


def _require_lemonade_base_url(
    env: Mapping[str, str],
    missing: list[str],
    aider_env: dict[str, str],
) -> None:
    value = _env_value(env, "SFE_LEMONADE_BASE_URL")
    if value is None:
        missing.append("SFE_LEMONADE_BASE_URL")
        return
    normalized = _ensure_openai_v1_base_url(value)
    aider_env["OPENAI_API_BASE"] = normalized
    aider_env["OPENAI_BASE_URL"] = normalized


def _ensure_openai_v1_base_url(value: str) -> str:
    stripped = value.rstrip("/")
    return stripped if stripped.endswith("/v1") else f"{stripped}/v1"


def _result(
    *,
    provider_name: str,
    aider_env: dict[str, str],
    selected_model: str | None,
    selected_weak_model: str | None,
    selected_timeout_seconds: float | None,
    missing_variables: tuple[str, ...],
    error_category: str | None,
    diagnostics_extra: Mapping[str, object] | None = None,
) -> AiderEnvBridgeResult:
    diagnostics = {
        "provider_name": provider_name,
        "aider_env_variable_names": tuple(sorted(aider_env)),
        "selected_model": selected_model,
        "selected_weak_model": selected_weak_model,
        "selected_timeout_seconds": selected_timeout_seconds,
        "missing_variables": missing_variables,
        "error_category": error_category,
    }
    if diagnostics_extra is not None:
        diagnostics.update(dict(diagnostics_extra))
    return AiderEnvBridgeResult(
        provider_name=provider_name,
        aider_env=dict(aider_env),
        selected_model=selected_model,
        selected_weak_model=selected_weak_model,
        selected_timeout_seconds=selected_timeout_seconds,
        missing_variables=missing_variables,
        error_category=error_category,
        diagnostics=diagnostics,
    )


def _error_category_for_missing(missing_variables: tuple[str, ...]) -> str | None:
    if not missing_variables:
        return None
    model_variable_names = {
        SFE_AIDER_MODEL_ENV,
        "SFE_OPENAI_EXECUTOR_MODEL",
        "SFE_ANTHROPIC_EXECUTOR_MODEL",
        "SFE_GOOGLE_MODEL",
    }
    only_model_missing = all(name in model_variable_names for name in missing_variables)
    if only_model_missing:
        return "missing_aider_model"
    if SFE_AIDER_MODEL_ENV in missing_variables:
        return "missing_aider_configuration"
    return "missing_aider_environment"


def _env_value(env: Mapping[str, str], name: str) -> str | None:
    value = env.get(name)
    if value is None or value.strip() == "":
        return None
    return value.strip()


def _dedupe(values: list[str]) -> tuple[str, ...]:
    seen: set[str] = set()
    deduped: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        deduped.append(value)
    return tuple(deduped)


def _ensure_outside_forbidden_roots(path: Path, roots: Sequence[Path]) -> None:
    resolved_path = path.resolve()
    for root in roots:
        resolved_root = root.resolve()
        try:
            resolved_path.relative_to(resolved_root)
        except ValueError:
            continue
        raise AiderEnvFileError("aider_env_file_inside_forbidden_root")


def _quote_env_value(value: str) -> str:
    escaped = (
        value.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("$", "\\$")
        .replace("`", "\\`")
        .replace("\n", "\\n")
    )
    return f'"{escaped}"'
