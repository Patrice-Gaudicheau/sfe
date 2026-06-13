# NoteKeeper SFE split-model benchmark task

Use the SFE-selected workspace context. The controlled workspace contains only the benchmark brief under `brief/`, task metadata under `tasks/`, and the current generated app under `app/`.

This scenario uses split OpenAI models: router/discovery/multipass planning use the stronger router model, while patch generation uses the executor model. Multipass is intentionally set to auto.

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
- `tasks/03_labels_search_archive.md`

## Current task

## 3. Labels, search, and archive

Add labels or categories, display labels on note cards, implement search across title, body, checklist text when present, and labels, and add archive and restore behavior. Active notes and archived notes should be separated by the view controls. Add empty states for no notes and no filtered results.
