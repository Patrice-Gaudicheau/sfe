# SolarSystem3D SFE split-model benchmark task

Use the SFE-selected workspace context. The controlled workspace contains only the benchmark brief under `brief/`, task metadata under `tasks/`, and the current generated app under `app/`.

This scenario uses split OpenAI models: router/discovery/multipass planning use the stronger router model, while patch generation uses the executor model. Multipass is intentionally set to auto.

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
- `tasks/02_data_and_textures.md`

## Current task

## 2. Solar system data model and procedural texture pipeline

Create a clear data model for the Sun, eight planets, and Earth's Moon. Include body type, approximate distance, orbital period, rotation period, description, visual radius, orbit radius, parent relationship where needed, and texture style parameters.

Implement reusable procedural Canvas texture generation for the required body styles: Sun, rocky planets, Earth, Moon, Mars, Jupiter, Saturn, Uranus, Neptune, and general bands/noise/crater effects. Do not use external image texture files.
