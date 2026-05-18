# Proxy Structured Responses Builder Diagnostics Note

Date: 2026-05-18

This note records the current SFE Proxy milestone for CodexCLI-style
`/v1/responses` requests.

The controlled structured builder path is validated for a narrow fixture: it
can preserve the structured input list/dict envelope, preserve file-path task
items and the latest user task, insert selected context as a new user text item,
preserve `stream=true`, and forward mock SSE through `response.completed`.

Realistic CodexCLI requests that include more complex structured envelopes
still fall back with `unsafe_task_envelope`. That is safe behavior, not a
regression, and it should not be read as realistic CodexCLI context reduction
being solved.

The next implementation step is sanitized structural observation of real
CodexCLI request envelopes. Diagnostics should classify item topology only:
counts, role and part-type distributions, approximate text-size buckets,
protected/task/context-like flags, and candidate rejection reasons. They must
not log prompt content, file paths, request bodies, headers, API keys, hidden
reasoning, raw SSE payloads, tool payload content, or exact text snippets.
