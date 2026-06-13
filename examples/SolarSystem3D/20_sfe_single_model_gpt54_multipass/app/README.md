# SolarSystem3D

SolarSystem3D is a static Three.js educational solar system simulator. The current milestone establishes the simulator-first layout, a reusable solar-system body dataset for the Sun, eight planets, and Earth's Moon, a procedural texture pipeline built with Canvas APIs, and a preview scene that already consumes those shared data structures.

## Run

This app uses a pinned browser ES module import for Three.js:

- `https://unpkg.com/three@0.165.0/build/three.module.js`

Directly opening `index.html` with `file://` may work in some browsers, but browser module loading rules can block or behave inconsistently for local files. The recommended fallback is a tiny static server:

```bash
cd app
python3 -m http.server 8000
```

Then open:

- `http://localhost:8000/`

## Current milestone contents

- Primary first-screen simulator layout
- Responsive scene and sidebar structure
- Semantic button, range, date, checkbox, and select placeholders
- Selected-body information panel seeded with data-pipeline status copy
- Solar system dataset for:
  - Sun
  - Mercury
  - Venus
  - Earth
  - Moon
  - Mars
  - Jupiter
  - Saturn
  - Uranus
  - Neptune
- Per-body metadata including type, parent relationship, approximate distance, orbital period, rotation period, description, render radius, orbit radius, and texture style parameters
- Reusable procedural texture helpers for:
  - noise layers
  - crater fields
  - speckles
  - clouded swirl bands
  - gas-giant bands
  - polar caps
  - haze
  - Saturn-style ring texture generation
- Baseline Three.js renderer, camera, lighting, resize handling, and animated preview scene wired to the shared data model
- Procedural star field generated in JavaScript without external images

## Accessibility notes

- Controls use semantic HTML elements and visible text labels.
- Keyboard focus states are styled for buttons, inputs, and selects.
- A skip link jumps directly to the controls panel.
- The canvas is labeled for assistive technologies, though the 3D scene is still an interactive visual experience and will need additional descriptive updates in later tasks.

## Current simplifications

- This milestone focuses on the data model and procedural texture foundation first.
- The preview scene already exercises the shared textures and body records, but later tasks will complete the full interaction model, camera controls, labels, full orbit system behavior, season presets, and selected-body inspection workflow.
- Textures are generated entirely in-browser with Canvas APIs. No external planet texture images are used.
