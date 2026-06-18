# FAQ

## Is SFE a replacement for Aider?

No. Aider is the default writer for normal file-editing runs. SFE routes the
task, selects context, isolates the workspace, and then delegates writing.

## Can I use SFE without Aider?

Yes for read-only usage, provider experiments, and some legacy/debug paths. For
normal `workspace_write` runs, install Aider. `make install` can offer to run
`pipx install aider-chat` after confirmation, and `make doctor` reports whether
Aider is available.

## Does SFE push changes?

No. SFE prepares and promotes local file changes. You decide when to commit and
push.

## Does SFE commit changes?

Successful workspace-write promotions may create a local source-repository
commit named `SFE workspace_write promotion` in current runtime behavior. It
does not push.

## Is the worktree a security sandbox?

No. It is a review and isolation boundary for Git changes. Do not treat it as a
host security boundary.

## Why keep benchmarks in the repo?

They are useful regression and measurement tools. The public docs summarize the
results conservatively instead of presenting long tables as universal proof.

## Was SFE built with AI assistance?

Yes, much of the implementation was written during AI-assisted coding sessions
under maintainer direction. That is a transparency note, not a quality claim.
