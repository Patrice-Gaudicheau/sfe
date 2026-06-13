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
