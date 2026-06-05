# CodexCLI Raw Envelope Smoke Note

This note records tiny raw CodexCLI smoke tests used to isolate the base token
envelope around `codex exec`. These were not SFE benchmark runs and should not
be compared as task-quality measurements.

## Purpose

The CodexCLI `openai-codexcli` path is an agentic provider path, not a thin
OpenAI API transport. SFE sends a prompt to `codex exec --json`, and CodexCLI
wraps that prompt in its own exec-agent runtime context. That context can
include agent framing, sandbox/tool instructions, user configuration, rules,
plugins, apps, skills, hooks, connector metadata, and other Codex runtime
surfaces.

This matters for token accounting. SFE selected-context prompts can become much
smaller than full-context prompts, but CodexCLI's fixed envelope can hide much
of that reduction in reported input-token metrics.

## Raw Smoke Setup

All smokes used the trivial prompt:

```bash
printf 'Return exactly: ok\n'
```

The baseline command shape was:

```bash
codex exec --json --model gpt-5.4 \
  --sandbox read-only --skip-git-repo-check --ephemeral
```

The more constrained variants added `--ignore-user-config`, `--ignore-rules`,
and then feature disables for plugin, app, tool, and hook surfaces.

## Results

| Command shape | Returned text | Input tokens | Output tokens | Interpretation |
| --- | --- | ---: | ---: | --- |
| Default plus `--ephemeral` | `ok` | `11,189` | `22` | Full CodexCLI exec-agent envelope. |
| Add `--ignore-user-config --ignore-rules` | `ok` | `9,256` | `5` | User config/rules removed about `1,933` input tokens. |
| Add plugin/app/tool/hook feature disables | `ok` | `8,045` | `16` | Feature disables removed another `1,211` input tokens. |

The final constrained command disabled:

```bash
--disable plugins --disable plugin_sharing --disable apps \
--disable browser_use --disable browser_use_external \
--disable computer_use --disable image_generation \
--disable multi_agent --disable tool_suggest \
--disable workspace_dependencies --disable hooks
```

Total measured reduction from default to the constrained command was `3,144`
input tokens, about `28.1%`.

## Interpretation

The feature and config disables materially reduce CodexCLI overhead, but they do
not eliminate it. Even the constrained smoke still reported about `8k` input
tokens for a trivial prompt. That remaining floor is consistent with intrinsic
CodexCLI exec-agent framing rather than SFE prompt content.

This supports the current interpretation of the large/contextual CodexCLI
results: SFE context reduction is real, and router quality can remain high, but
CodexCLI's fixed envelope can dominate one-shot token accounting. CodexCLI
should therefore be treated as a provider-specific agentic transport, not as a
direct apples-to-apples token comparison against the direct OpenAI API path.

## Benchmark Guidance

For CodexCLI benchmarks:

- report CodexCLI results as provider-specific observations;
- keep executor-only and router-inclusive token metrics separate;
- avoid presenting CodexCLI token reductions as equivalent to direct OpenAI API
  token reductions;
- do not try to turn CodexCLI into an OpenAI API equivalent;
- treat CodexCLI as a functional benchmark-local provider, not as a clean
  token-efficiency baseline.

A CodexCLI minimal-envelope mode was considered, but it is not planned for now.
The constrained smoke removed several thousand fixed input tokens, but the
remaining about `8k` token floor is still too large to solve the token-parity
problem. Such a mode could also be misleading or dangerous because disabling
plugins, apps, tools, and hooks changes CodexCLI's normal agent environment.

The safer position is to document CodexCLI as an agentic provider with a large
fixed envelope. CodexCLI remains useful for functional benchmark-local
validation, but it should not be used as the clean token-efficiency baseline for
SFE versus direct OpenAI API comparisons.
