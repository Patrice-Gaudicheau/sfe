# CodexCLI With OpenAI Discovery TUI Run Note

This note records one successful manual `sfe-tui` `/run` test using CodexCLI
for execution-mode routing and patch execution, with OpenAI used for workspace
discovery.

## Purpose

The test checked the mixed-provider path after the discovery provider split:
CodexCLI should be able to route `/run` into `workspace_write` and produce a
DEV/Patch proposal, while a discovery-supported provider selects workspace
context.

The manual workspace was:

```text
~/Projets/00_Tests/SFE-playground/test_01
```

The task modified a small PHP mini blog so user-controlled post fields are
escaped before rendering in `public/index.php`.

## Effective Config

```env
SFE_PROVIDER_ROUTER=codexcli
SFE_PROVIDER_DISCOVERY=openai
SFE_PROVIDER_EXECUTOR=codexcli
SFE_CODEXCLI_ROUTER_MODEL="gpt-5.5"
SFE_CODEXCLI_EXECUTOR_MODEL="gpt-5.5"
SFE_CODEXCLI_SANDBOX=read-only
SFE_CODEXCLI_ROUTER_EFFORT="high"
SFE_CODEXCLI_EXECUTOR_EFFORT="high"
```

`SFE_PROVIDER_DISCOVERY=openai` was used because CodexCLI discovery routing is
not currently implemented. CodexCLI can handle execution-mode routing and patch
execution, but discovery still needs a provider supported by the discovery
router factory.

## Status Display

The TUI `/status` output correctly showed all provider roles:

```text
router provider: codexcli
discovery provider: openai
executor provider: codexcli
```

This confirmed that the displayed values came from the effective role-aware
provider configuration, not only from the legacy shared provider value.

## Run Result

The `/run` flow reached the intended DEV/Patch path:

```text
SFE: execution mode selected: workspace_write
SFE: context candidates inspected: 3
SFE: relevant context selected: 3 files
SFE: patch validation completed
SFE: promotion completed
```

The run completed successfully:

```text
status: completed
promoted files: public/index.php
modified relative paths: public/index.php
```

The promoted patch added a local escaping helper:

```php
function e($value): string
{
    return htmlspecialchars((string) $value, ENT_QUOTES, 'UTF-8');
}
```

and replaced raw post output with escaped output:

```php
<?= e($post['title']) ?>
<?= e($post['author']) ?>
<?= e($post['body']) ?>
```

`content/posts.php` was not edited.

## Manual Validation

Manual validation after promotion passed:

```bash
php -l public/index.php
php -l content/posts.php
php -l tests/render_smoke.php
php tests/render_smoke.php
```

Results:

```text
No syntax errors detected in public/index.php
No syntax errors detected in content/posts.php
No syntax errors detected in tests/render_smoke.php
OK
```

## Takeaway

For this small DEV/Patch task, the mixed provider path worked:

- CodexCLI handled `/run` execution-mode routing.
- OpenAI handled workspace discovery.
- CodexCLI produced a valid patch proposal.
- SFE validated, isolated, applied, and promoted the patch.

This supports the practical configuration:

```env
SFE_PROVIDER_ROUTER=codexcli
SFE_PROVIDER_DISCOVERY=openai
SFE_PROVIDER_EXECUTOR=codexcli
```

OpenAI discovery remains useful because CodexCLI discovery routing is not
implemented yet. This is one successful manual test on a small fixture, not a broad reliability guarantee.
