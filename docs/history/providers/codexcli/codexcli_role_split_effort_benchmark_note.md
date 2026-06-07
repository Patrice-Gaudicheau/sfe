# CodexCLI Role-Split Effort Benchmark Note

This note records a CodexCLI DEV/Patch output-token benchmark run after the
role-aware provider split.

## Purpose

The benchmark checked whether explicit router/executor provider configuration
works for the CodexCLI output-token campaign, and whether CodexCLI executor
reasoning effort affects mechanical patch reliability on the medium DEV/Patch
fixture.

The target fixture was `medium_php_blog_escape` in the CodexCLI output-token
campaign. The task patches `public/index.php` so rendered post titles and bodies
use `htmlspecialchars`.

## Effective Config

The high-effort rerun used explicit role-aware provider configuration:

```env
SFE_PROVIDER=
SFE_PROVIDER_ROUTER=codexcli
SFE_PROVIDER_EXECUTOR=codexcli
SFE_CODEXCLI_ROUTER_MODEL=gpt-5.5
SFE_CODEXCLI_EXECUTOR_MODEL=gpt-5.4
SFE_CODEXCLI_SANDBOX=read-only
SFE_CODEXCLI_ROUTER_EFFORT=high
SFE_CODEXCLI_EXECUTOR_EFFORT=high
SFE_CODEXCLI_REASONING_EFFORT=
```

`SFE_PROVIDER` was unset, so the run did not depend on the legacy shared
provider fallback. The earlier comparison run used the same role/provider/model
setup but with `SFE_CODEXCLI_EXECUTOR_EFFORT=medium`.

This output-token benchmark records router configuration, but it does not make a
separate live router provider call. The selected-context and full-context
conditions are controlled by fixture file sets, and CodexCLI is called as the
patch executor.

No source code changes were made by the benchmark itself.

## Medium-Effort Result

The medium-effort role-split run used:

```env
SFE_CODEXCLI_ROUTER_EFFORT=high
SFE_CODEXCLI_EXECUTOR_EFFORT=medium
```

Across 3 repeats and 6 provider executions:

| Condition | Accepted | Applied | Tests passed | Input tokens | Output tokens | Total tokens |
| --- | ---: | ---: | ---: | --- | --- | --- |
| `selected_context_dev_patch` | 3/3 | 0/3 | 0/3 | 12492 each | 183, 181, 170; avg 178 | avg 12670 |
| `full_context_dev_patch` | 1/3 | 1/3 | 1/3 | 29197 each | 183, 186, 395; avg 254.7 | avg 29451.7 |

All token fields used `measured_provider_usage`.

Failure breakdown:

- `hunk_preimage_mismatch`: 3
- `impossible_hunk_accounting`: 2

The selected-context failures all targeted `public/index.php`. The selected
context contained the complete target file plus `content/posts.php`, so the
failure was not caused by missing selected context. CodexCLI followed the
diff-only instruction and produced mechanically close hunks, but the hunk start
line was approximate, causing SFE to reject physical application with
`hunk_preimage_mismatch`.

The full-context `impossible_hunk_accounting` failures were malformed diff
outputs: the declared hunk old/new counts were one line lower than the actual
hunk body counts. SFE rejected them during patch parsing.

## High-Effort Result

The high-effort rerun used:

```env
SFE_CODEXCLI_ROUTER_EFFORT=high
SFE_CODEXCLI_EXECUTOR_EFFORT=high
```

Across 3 repeats and 6 provider executions:

| Condition | Accepted | Applied | Tests passed | Input tokens | Output tokens | Total tokens |
| --- | ---: | ---: | ---: | --- | --- | --- |
| `selected_context_dev_patch` | 2/3 | 2/3 | 2/3 | 12492 each | 537, 539, 558; avg 544.7 | avg 13036.7 |
| `full_context_dev_patch` | 3/3 | 3/3 | 3/3 | 29197 each | 631, 546, 504; avg 560.3 | avg 29757.3 |

All token fields used `measured_provider_usage`.

Failure breakdown:

- `hunk_preimage_mismatch`: 0
- `impossible_hunk_accounting`: 1

The remaining failure was a selected-context malformed hunk:
`@@ -8,3 +8,3 @@` declared `3/3`, while SFE measured `4/4`.

## Comparison

High executor effort substantially improved patch reliability for this fixture:

- medium effort applied and passed: 1/6
- high effort applied and passed: 5/6
- medium effort had 3 `hunk_preimage_mismatch` failures and 2
  `impossible_hunk_accounting` failures
- high effort had 0 `hunk_preimage_mismatch` failures and 1
  `impossible_hunk_accounting` failure

Selected-context input reduction remained strong:

- selected-context input tokens: 12492
- full-context input tokens: 29197
- reduction: about 57.21%

High effort increased output tokens:

- medium selected-context average output tokens: 178
- high selected-context average output tokens: 544.7
- medium full-context average output tokens: 254.7
- high full-context average output tokens: 560.3

Compared with the older `campaign-d-sfe-gpt55-router-gpt54-medium` medium
fixture run, high effort improved overall application/test pass count from 3/6
to 5/6, while preserving the same selected-context input-token reduction
pattern.

## Takeaway

For CodexCLI DEV/Patch execution on this medium fixture,
`SFE_CODEXCLI_EXECUTOR_EFFORT=high` currently looks safer than `medium` for
mechanically valid patch generation. The improvement appears to address diff
mechanics rather than context selection: the selected context already contained
the complete target file.

Treat this as benchmark evidence, not a universal guarantee. CodexCLI still
returns text or diffs only, and SFE remains responsible for parsing, validating,
isolating, applying, or rejecting patches.
