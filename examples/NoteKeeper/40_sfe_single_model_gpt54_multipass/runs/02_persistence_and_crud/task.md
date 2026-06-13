# NoteKeeper SFE split-model benchmark task

Use the SFE-selected workspace context. The controlled workspace contains only the benchmark brief under `brief/`, task metadata under `tasks/`, and the current generated app under `app/`.

This scenario uses split OpenAI models: router/discovery/multipass planning use the stronger router model, while patch generation uses the executor model. Multipass is intentionally forced on for this scenario.

You are implementing the NoteKeeper static browser app. Edit only these workspace files:

- `app/index.html`
- `app/styles.css`
- `app/app.js`
- `app/README.md`

Do not create package files, server code, dependency manifests, external assets, screenshots, logs, or files outside `app/`. The final app must run by opening `index.html` directly after the runner copies the app files out of `app/`.

Consult these benchmark documents from selected context when available:

- `brief/prompt.md`
- `brief/acceptance_criteria.md`
- `brief/task_sequence.md`
- `tasks/02_persistence_and_crud.md`

## Current task

## 2. LocalStorage persistence and CRUD

Implement note creation, rendering, editing, deletion, and `localStorage` persistence for plain text notes. Use a NoteKeeper-specific storage key. Include safe startup behavior for missing or malformed stored data. Confirm notes survive a browser reload.
