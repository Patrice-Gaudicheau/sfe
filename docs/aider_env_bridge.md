# SFE .env To Aider Environment Bridge

This document describes the proposed bridge between SFE configuration and
Aider's runtime environment. The bridge is implemented for single-pass Aider
workspace writes on this branch. Multi-pass Aider execution and real
model-backed smoke testing remain deferred.

## Goals

- Keep Aider as the default single-pass `workspace_write` executor.
- Keep `SFE_WORKSPACE_WRITE_EXECUTOR=text` as the explicit legacy fallback.
- Let Aider receive only the provider settings it needs.
- Avoid passing the whole SFE `.env` to Aider.
- Never copy `.env` into an SFE worktree.
- Keep diagnostics bounded and secret-safe.

SFE should resolve the executor provider with the existing provider config
rules: `SFE_PROVIDER_EXECUTOR`, then `SFE_PROVIDER`, then the default
`openai`.

## Aider Expected Variables

Local Aider 0.86.2 exposes `--env-file`, `--model`, `--weak-model`,
`--timeout`, `--api-key`, `--set-env`, `--openai-api-base`, and Aider-prefixed
configuration variables such as `AIDER_MODEL`, `AIDER_WEAK_MODEL`,
`AIDER_TIMEOUT`, `AIDER_OPENAI_API_KEY`, and `AIDER_OPENAI_API_BASE`.

Provider-specific variables observed from local Aider/LiteLLM behavior:

| Provider | Aider/LiteLLM variables | Notes |
| --- | --- | --- |
| OpenAI | `OPENAI_API_KEY`, `OPENAI_API_BASE` | Aider also accepts `AIDER_OPENAI_API_KEY` and `AIDER_OPENAI_API_BASE`; CLI flags can set these too. |
| OpenAI-compatible | `OPENAI_API_KEY`, `OPENAI_API_BASE` | Use for compatible endpoints when the model name is known to work with Aider/LiteLLM. |
| Anthropic | `ANTHROPIC_API_KEY` | Aider supports `--anthropic-api-key`; model should be passed with `--model`. |
| Gemini | `GEMINI_API_KEY` | LiteLLM may also understand `GOOGLE_API_KEY`, but the bridge should prefer `GEMINI_API_KEY` for Aider. |
| OpenRouter | `OPENROUTER_API_KEY` | Usually paired with an `openrouter/...` model name. |
| DeepSeek | `DEEPSEEK_API_KEY` | Usually paired with a `deepseek/...` model name. |
| Alibaba/Qwen | `OPENAI_API_KEY`, `OPENAI_API_BASE` | Treat as OpenAI-compatible using `ALIBABA_API_KEY` and `ALIBABA_BASE_URL`; require explicit Aider model override unless proven safe. |
| Ollama/local | `OLLAMA_API_BASE` | Usually paired with an `ollama/...` model name; require explicit Aider model override unless proven safe. |

`OPENAI_BASE_URL` is an SFE variable. Aider/LiteLLM expect
`OPENAI_API_BASE`, so the bridge should translate when building the Aider
environment.

## Current SFE Variables

Relevant SFE configuration currently documented or used by provider code:

| Area | SFE variables |
| --- | --- |
| Provider selection | `SFE_PROVIDER`, `SFE_PROVIDER_ROUTER`, `SFE_PROVIDER_DISCOVERY`, `SFE_PROVIDER_EXECUTOR` |
| Workspace writer | `SFE_WORKSPACE_WRITE_EXECUTOR` |
| OpenAI | `OPENAI_API_KEY`, `OPENAI_BASE_URL`, `SFE_OPENAI_EXECUTOR_MODEL` |
| Anthropic | `ANTHROPIC_API_KEY`, `ANTHROPIC_BASE_URL`, `ANTHROPIC_VERSION`, `SFE_ANTHROPIC_EXECUTOR_MODEL` |
| Google/Gemini | `GOOGLE_API_KEY`, `SFE_GOOGLE_BASE_URL`, `SFE_GOOGLE_MODEL` |
| Alibaba/Qwen | `ALIBABA_API_KEY`, `ALIBABA_BASE_URL`, `SFE_ALIBABA_EXECUTOR_MODEL`, `SFE_ALIBABA_DISABLE_THINKING` |
| Lemonade | `SFE_LEMONADE_BASE_URL`, `SFE_LEMONADE_API_KEY`, `SFE_LEMONADE_EXECUTOR_MODEL`, `SFE_EXECUTOR_MODEL` |
| Ollama | `SFE_OLLAMA_BASE_URL`, `SFE_OLLAMA_MODEL`, `SFE_OLLAMA_EXECUTOR_MODEL`, `SFE_OLLAMA_TIMEOUT_SECONDS`, `SFE_OLLAMA_THINK` |
| Codex CLI | `SFE_CODEXCLI_EXECUTOR_MODEL`, `SFE_CODEXCLI_EXECUTOR_EFFORT`, `SFE_CODEXCLI_REASONING_EFFORT` |

The real `.env` should not be inspected for this design pass. Versioned source
and `.env.example` are sufficient to define the bridge.

## Proposed Bridge

Add a small SFE-owned helper in a later implementation phase that builds an
Aider execution environment from already-loaded SFE configuration. The helper
should return structured data, not mutate process-global state directly.

Recommended behavior:

- Resolve the SFE executor provider using existing provider config helpers.
- Build a minimal key/value mapping for Aider.
- Include only variables required by the resolved provider.
- Create a temporary env file outside the source checkout and outside the SFE
  worktree.
- Restrict permissions when the platform allows it.
- Pass the file to Aider with `--env-file`.
- Delete the temporary env file after Aider exits.
- Redact the env-file path in diagnostics as `<aider-env-file>`.
- Never serialize env values or env-file contents.
- Run Aider with a controlled subprocess environment rather than inheriting
  the whole SFE process environment.

Initial mapping:

| SFE executor provider | Required source values | Aider env output | Model policy |
| --- | --- | --- | --- |
| `openai` | `OPENAI_API_KEY`, optional `OPENAI_BASE_URL` | `OPENAI_API_KEY`, `OPENAI_API_BASE` | `SFE_AIDER_MODEL`, else `SFE_OPENAI_EXECUTOR_MODEL` if accepted. |
| `openai-compatible` | `OPENAI_API_KEY`, `OPENAI_BASE_URL` | `OPENAI_API_KEY`, `OPENAI_API_BASE` | Prefer `SFE_AIDER_MODEL`; do not guess if model name is ambiguous. |
| `anthropic` | `ANTHROPIC_API_KEY` | `ANTHROPIC_API_KEY` | `SFE_AIDER_MODEL`, else `SFE_ANTHROPIC_EXECUTOR_MODEL` if accepted. |
| `google` | `GOOGLE_API_KEY` | `GEMINI_API_KEY` | `SFE_AIDER_MODEL`, else `SFE_GOOGLE_MODEL` if accepted. |
| `alibaba` | `ALIBABA_API_KEY`, `ALIBABA_BASE_URL` | `OPENAI_API_KEY`, `OPENAI_API_BASE` | Require `SFE_AIDER_MODEL` unless a tested mapping exists. |
| `lemonade` | `SFE_LEMONADE_BASE_URL`, optional `SFE_LEMONADE_API_KEY` | `OPENAI_API_BASE`, optional `OPENAI_API_KEY` | Require `SFE_AIDER_MODEL`. |
| `ollama` | `SFE_OLLAMA_BASE_URL` | `OLLAMA_API_BASE` | Require `SFE_AIDER_MODEL`. |
| `codexcli` | local Codex CLI auth | none | Not supported by Aider bridge; fail closed or require separate Aider provider config. |

Missing required provider values should fail closed with a structured issue that
lists only missing variable names. There must be no silent fallback from Aider
to text transport.

## Model Mapping Policy

Add these future SFE configuration variables:

- `SFE_AIDER_MODEL`: explicit Aider main model override.
- `SFE_AIDER_WEAK_MODEL`: optional Aider weak model override.
- `SFE_AIDER_ENV_FILE`: optional explicit env file override for advanced users.
- `SFE_AIDER_TIMEOUT_SECONDS`: optional timeout passed to Aider.

Avoid `SFE_AIDER_EXTRA_ARGS` for now. It is too easy to bypass SFE's safety
model with arbitrary Aider flags. If an escape hatch is needed later, prefer a
validated allow-list of specific settings.

Default model selection:

1. Use `SFE_AIDER_MODEL` when set.
2. For OpenAI, Anthropic, and Gemini, consider the provider-specific SFE
   executor model only if it is known to be valid for Aider/LiteLLM.
3. For Alibaba/Qwen, Lemonade, Ollama, and other OpenAI-compatible endpoints,
   require `SFE_AIDER_MODEL` until tested mappings exist.
4. If no safe model can be selected, fail closed with a diagnostic such as
   `missing_aider_model`.

The bridge should pass the selected model with Aider's `--model` flag rather
than relying on ambient `AIDER_MODEL`, so the invocation remains explicit and
diagnosable.

## Security Model

The bridge must treat all provider values as secrets unless they are explicitly
known to be safe names. It may list variable names, provider names, selected
model names, and missing variable names. It must not include secret values,
full env-file contents, API keys, bearer tokens, or raw `.env` content in any
TUI/MCP output, test fixture, log, or exception string.

Diagnostics may include:

- executor provider;
- selected Aider model name;
- names of variables written to the temporary env file;
- names of missing variables;
- sanitized command with `--message-file <message-file>` and
  `--env-file <aider-env-file>`;
- return code, elapsed time, stdout/stderr lengths, and short bounded previews.
- timeout category and duration when configured.

Diagnostics must not include:

- env values;
- `.env` contents;
- temporary env-file contents;
- prompt contents;
- API keys or tokens;
- unbounded Aider output.

## Implementation Phases

### Phase A: Documentation

- Add this design note.
- Keep runtime behavior unchanged.
- Do not inspect the real `.env`.
- Do not run a real Aider/model smoke test.

### Phase B: Pure Bridge Helper

- Add a testable helper that accepts an environment mapping and returns an Aider
  env mapping plus CLI options such as `--model`, `--weak-model`, and
  `--timeout`.
- Unit test provider mappings, missing variables, model override precedence,
  and redaction behavior.
- Do not wire it into `AiderFilesystemExecutor` yet.

### Phase C: Runtime Wiring

- Wire the helper into `AiderFilesystemExecutor`.
- Write the minimal temporary env file outside the worktree.
- Pass `--env-file <tempfile>` to Aider.
- Pass `--model`, optional `--weak-model`, and optional `--timeout`.
- Close stdin and apply the configured timeout to the Aider subprocess.
- Keep Aider input/chat history files outside the worktree and delete them with
  the temporary execution files.
- Redact env-file paths and values in diagnostics.
- Preserve Aider as the default single-pass writer and text as explicit
  fallback only.

### Phase D: Bounded Real Smoke

- Run a real single-pass smoke only when safe model credentials/configuration
  are available.
- Use a disposable source repo and an SFE-controlled worktree.
- Confirm promoted output appears only in the selected destination.
- Do not print secrets.

### Phase E: Multi-Pass Later

- Keep multi-pass text-backed until the bridge and single-pass behavior are
  stable.
- Reuse the same bridge for each later Aider pass.
- Keep each later multi-pass Aider call small and batch-specific; SFE remains
  the context router and planner.

## Open Questions

- Which Aider model names should be considered known-safe aliases for SFE's
  current default OpenAI, Anthropic, and Gemini model names?
- Should SFE allow `SFE_AIDER_ENV_FILE` to point to a user-managed file even
  though it cannot validate secret contents?
- Should Aider support for `openai-compatible` endpoints require explicit
  `SFE_AIDER_MODEL` in all cases?
- Should SFE expose an allow-listed future variable for model settings files or
  aliases, such as `AIDER_MODEL_SETTINGS_FILE`, or keep those outside v1?
