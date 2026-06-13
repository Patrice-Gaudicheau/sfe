# NoteKeeper SFE Comparative Run - 2026-06-13

This note records the benchmark-local NoteKeeper comparison after the workspace
write and multipass reliability pass. It is an observation note, not a broad
provider ranking.

## Result Summary

- Scenario 20, single-model no-multipass, produced a usable app after tasks 1-4
  but failed strict script validation at `05_responsive_polish` with a patch
  mismatch.
- Scenario 30, split router/executor, produced a usable app after tasks 1-4 but
  failed strict script validation at `05_responsive_polish` with a patch
  mismatch.
- Scenario 40, single-model multipass forced on, passed strict script validation
  through `05_responsive_polish`.

Manual inspection found the generated NoteKeeper app usable: it creates notes,
persists them in `localStorage`, displays them, and exposes edit, pin, archive,
and delete controls.

## Reliability Notes

The original scenario 40 task 2 failure was fixed by ensuring existing editable
app files are selected into executor context when later tasks modify the app.
Executor context now labels selected blocks with their `source_ref`, so the model
can distinguish `app/index.html`, `app/app.js`, `app/styles.css`, and
`app/README.md` from brief text.

The remaining scenario 20 and 30 strict failures are late responsive-polish patch
mismatches. They are not absence-of-app failures: both runs had already produced
usable app files after task 4.

No new LLM repair or reviewer layer was added. The LLM-reviewed full-file
replacement fallback remains opt-in, and the hard safety boundary remains the
workspace/worktree plus blocked internal directories.

## Token And Cost Interpretation

This NoteKeeper run does not support presenting SFE as a token-saving system.
The benchmark is small, and its baseline context is not large enough to amortize
SFE orchestration overhead.

Observed token-volume results:

- Scenario 20 increased total tokens by `+28.5%` through tasks 1-4.
- Scenario 30 increased total tokens by `+22.3%` through tasks 1-4.
- Scenario 40 completed strict validation, but increased full-run total tokens
  by `+323.7%`.

Multipass improved reliability in this benchmark: scenario 40 was the only SFE
scenario to pass strict validation through `05_responsive_polish`. It was also
much more expensive in token volume because planning and multiple executor
passes added substantial overhead.

The stronger supported claim is cost-control architecture, not raw token
reduction. Scenario 30 used split models:

- Baseline tasks 1-4 used `54,581` tokens on `gpt-5.4`.
- Scenario 30 tasks 1-4 used `10,784` tokens on `gpt-5.4`.
- Scenario 30 tasks 1-4 used `55,961` executor tokens on `gpt-5.4-mini`.

So total token volume increased, but expensive-model exposure dropped sharply.
That can matter for dollar cost when the executor model is much cheaper, even
though it is not a token-saving result.

A larger benchmark with much more irrelevant or weakly relevant context is
needed before making strong token-saving claims for SFE.
