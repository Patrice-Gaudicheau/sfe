# SolarSystem3D SFE single-model multipass benchmark task

Use the SFE-selected workspace context. The controlled workspace contains only the benchmark brief under `brief/`, task metadata under `tasks/`, and the current generated app under `app/`.

This scenario uses one OpenAI model for router, discovery, multipass planning, and patch generation. Multipass is intentionally forced on.

You are implementing the SolarSystem3D static Three.js browser app. Edit only these workspace files:

- `app/index.html`
- `app/styles.css`
- `app/app.js`
- `app/README.md`

Do not create package files, server code, backend code, screenshots, logs, or files outside `app/`. Do not add external texture images or audio. A pinned browser Three.js CDN import is allowed, and a documented simple static-server fallback is allowed if browser module restrictions require it.

Consult these benchmark documents from selected context when available:

- `brief/prompt.md`
- `brief/acceptance_criteria.md`
- `brief/task_sequence.md`
- `tasks/08_responsive_performance_readme.md`

## Current task

## 8. Responsive polish, performance review, and README

Polish phone, tablet, and desktop layouts. Verify controls do not overlap important scene content at common sizes. Review geometry counts, animation behavior, texture reuse, event listeners, resize handling, and paused-state behavior. Finalize `app/README.md` with run instructions, dependency notes, feature list, astronomy simplifications, accessibility notes, performance notes, and manual verification steps.
