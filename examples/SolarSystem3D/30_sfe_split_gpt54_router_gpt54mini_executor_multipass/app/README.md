# SolarSystem3D

Static Three.js solar system simulator for the SolarSystem3D benchmark.

## Run

This version uses browser ES module imports from a pinned Three.js CDN, so it is best opened through a simple static server:

```bash
cd app
python3 -m http.server 8000
```

Then open `http://localhost:8000/`.

## Features

- Sun, eight planets, and Earth's Moon are rendered in order.
- Procedural Canvas textures are generated in-app for each required body style.
- Visible orbit paths, Saturn's rings, labels, click-to-focus, camera presets, and OrbitControls are included.
- Play/pause, time speed, label/orbit toggles, and spring equinox / summer solstice / autumn equinox / winter solstice controls are included.
- Educational scale mode and a realistic scale mode are both available.
- Earth's axial tilt is shown with a visible marker.
- The Moon remains visually associated with Earth when season presets change.

## Simplifications

- Orbits and season positions are educational approximations, not precision ephemerides.
- Bodies use circular paths in a shared plane for readability.
- Seasons are described correctly as a result of Earth's axial tilt relative to sunlight.
- Realistic scale mode preserves size and distance relationships more strongly while keeping bodies minimally visible.
- Season presets place Earth at simplified orbital positions for comparison rather than computed calendar dates.

## Accessibility notes

- Primary controls use semantic buttons and inputs with accessible names.
- Keyboard focus is visible via CSS.
- Buttons and range controls are sized for touch use where practical.
- Labels and orbits can be toggled to reduce visual clutter.
- Core controls are keyboard reachable, and Space / L / O / R shortcuts are supported.
- Camera presets are also reachable with number keys 1–5, and S cycles season presets.
- The selected-body panel updates when a body is clicked or selected through camera focus.

## Manual checks

- Verify the Sun, eight planets, Saturn's rings, and Earth's Moon are visible.
- Confirm play/pause, time speed, orbit toggles, labels, scale mode, camera presets, and click-to-focus work.
- Use the season buttons to compare spring equinox and summer solstice positions, then autumn equinox and winter solstice.
