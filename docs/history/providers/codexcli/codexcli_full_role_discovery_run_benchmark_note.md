# CodexCLI Full-Role Discovery Run Benchmark Note

This note records a real SFE `/run` benchmark after CodexCLI discovery routing
was added.

## Purpose

The benchmark checked whether a full CodexCLI role setup can run the normal
SFE `/run` path end to end, and whether using CodexCLI for discovery produces
token-output or patch-reliability gains on the medium DEV/Patch fixture.

The target fixture was `medium_php_blog_escape`. The task patches
`public/index.php` so rendered post titles and bodies use `htmlspecialchars`.

## Why Not The Output-Token Benchmark

`runtime/run_codexcli_output_token_benchmark.py` was inspected before live
calls. It is not a live CodexCLI discovery benchmark:

- it does not call the execution-mode router live;
- it does not call the discovery router live;
- it records router configuration only;
- it calls CodexCLI as the patch executor against preselected fixture context.

Because of that, a real `/run` harness was used instead.

## Effective Config

```env
SFE_PROVIDER=
SFE_PROVIDER_ROUTER=codexcli
SFE_PROVIDER_DISCOVERY=codexcli
SFE_PROVIDER_EXECUTOR=codexcli

SFE_CODEXCLI_ROUTER_MODEL=gpt-5.5
SFE_CODEXCLI_DISCOVERY_MODEL=gpt-5.5
SFE_CODEXCLI_EXECUTOR_MODEL=gpt-5.4

SFE_CODEXCLI_ROUTER_EFFORT=high
SFE_CODEXCLI_DISCOVERY_EFFORT=high
SFE_CODEXCLI_EXECUTOR_EFFORT=high

SFE_CODEXCLI_REASONING_EFFORT=
SFE_CODEXCLI_SANDBOX=
```

`SFE_PROVIDER` was unset, so the run did not use the legacy shared provider
fallback. `SFE_CODEXCLI_REASONING_EFFORT` was unset, so the role-specific effort
variables controlled the calls. `SFE_CODEXCLI_SANDBOX` was unset, and the
effective CodexCLI default was `read-only`.

## Harness

The benchmark used fresh copies of the `medium_php_blog_escape` fixture and ran
the normal SFE `RunPipeline` path with live CodexCLI calls for all three roles:

- execution-mode router;
- discovery router;
- patch executor.

The harness recorded provider usage at the CodexCLI adapter boundary. Token
usage came from `measured_provider_usage` for all live CodexCLI calls.

No source code changes were made by the benchmark itself.

## Reports

```text
/home/patrice/Projets/00_Tests/SFE-playground/codexcli-full-role-run-campaign/reports/full-codexcli-discovery-gpt55-gpt54-high-run-1-20260608T061407Z
/home/patrice/Projets/00_Tests/SFE-playground/codexcli-full-role-run-campaign/reports/full-codexcli-discovery-gpt55-gpt54-high-run-2-20260608T061906Z
/home/patrice/Projets/00_Tests/SFE-playground/codexcli-full-role-run-campaign/reports/full-codexcli-discovery-gpt55-gpt54-high-run-3-20260608T062330Z
```

Aggregate report:

```text
/home/patrice/Projets/00_Tests/SFE-playground/codexcli-full-role-run-campaign/reports/full-codexcli-discovery-gpt55-gpt54-high-aggregate-20260608T062803Z.json
```

## Per-Run Results

| Run | Discovery files | Selected tokens | Status | Patch | Issue |
| --- | --- | ---: | --- | --- | --- |
| 1 | `public/index.php`, `content/posts.php`, `includes/format.php` | 468 | failed | not applied | `impossible_hunk_accounting` |
| 2 | `public/index.php`, `content/posts.php` | 173 | completed | applied/promoted | none |
| 3 | `public/index.php`, `content/posts.php` | 173 | failed | not applied | `impossible_hunk_accounting` |

Patch reliability:

- executor returned patch text: 3/3;
- SFE accepted, applied, and promoted: 1/3;
- `hunk_preimage_mismatch`: 0;
- `impossible_hunk_accounting`: 2.

CodexCLI discovery selected relevant files every time. It did not fail JSON
parsing or local path validation. The failures were patch diff mechanics, not
missing selected context.

## Token Usage

Average measured token usage across three repeats:

| Role | Input tokens | Output tokens | Total tokens |
| --- | ---: | ---: | ---: |
| execution-mode router | 13381 | 63.0 | 13444.0 |
| discovery router | 14230 | 141.3 | 14371.3 |
| patch executor | 12412.7 | 615.3 | 13028.0 |
| end to end | | | 40843.3 |

The real `/run` selected-token reduction was reported as `0.0%` because
discovery had already narrowed the workspace and the local selector kept all
discovered files. Compared with the full fixture context, runs 2 and 3 loaded
the same 173-token selected pair used by earlier selected-context benchmarks,
but that is a fixture comparison rather than the `/run` audit metric.

## Comparison

Previous high-effort output-token benchmark, selected-context patch executor:

```text
applied/tests passed: 2/3
avg input: 12492
avg output: 544.7
avg total: 13036.7
```

New real full-CodexCLI `/run`, patch executor only:

```text
applied/promoted: 1/3
avg input: 12412.7
avg output: 615.3
avg total: 13028.0
```

Executor-only total tokens were roughly flat, output tokens increased, and
patch reliability was worse in this 3-run sample. End-to-end token cost was
much higher because the real `/run` path added live execution-mode router and
discovery calls.

The comparison is not like-for-like: the older output-token benchmark measures
controlled executor prompts, while this run measures the normal `/run` path
with separate live router and discovery calls.

## Takeaway

CodexCLI discovery is technically viable on this fixture: it selected relevant
files, returned parseable JSON, and passed local path validation. However, this
sample did not show an end-to-end token gain, and the current bottleneck remains
mechanically valid patch diff generation, especially `impossible_hunk_accounting`.

Treat this as a small 3-run benchmark sample, not a definitive provider ranking
or a broad reliability guarantee.
