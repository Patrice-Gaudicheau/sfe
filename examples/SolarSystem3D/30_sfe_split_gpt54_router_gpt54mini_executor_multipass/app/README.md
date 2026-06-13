# SolarSystem3D

Static Three.js educational solar system simulator with procedural textures and a selectable information panel.

## Run

This app uses browser ES modules with pinned Three.js CDN imports, so opening `index.html` directly from `file://` may be blocked in some browsers.

Recommended:

```bash
cd app
python3 -m http.server 8000
```

Then open `http://localhost:8000/`.

If your browser permits module loading from local files, you can open `index.html` directly.

## Features

- Sun, eight planets, and Earth's Moon.
- Procedural Canvas textures for the Sun, rocky planets, Earth, Moon, Mars, Jupiter, Saturn, Uranus, and Neptune.
- Visible orbit paths for the planets and Moon.
- Saturn ring mesh.
- Play/pause and time-speed controls.
- Season presets for spring equinox, summer solstice, autumn equinox, and winter solstice.
- Camera presets for overview, inner planets, Earth and Moon, outer planets, and Sun view.
- Click-to-focus selection with a live selected-body panel.
- Label and orbit visibility toggles.
- Educational scale and realistic scale modes.
- Procedural starfield background.

## Notes

- Three.js and OrbitControls are loaded from pinned CDN URLs.
- The app is static and does not require a backend, bundler, or package manager.
- The simulation is an educational approximation, not a precision ephemeris.
- Season positions are simplified simplified orbital positions used to explain Earth's axial tilt relative to sunlight.

## Accessibility

- Core controls use semantic buttons, range inputs, and selects with visible labels.
- Visible focus states are provided in CSS.
- The layout is responsive for desktop, tablet, and mobile widths.
- Clicked bodies update the selected-body panel, and labels can be toggled for readability.
