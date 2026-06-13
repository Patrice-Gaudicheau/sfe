# SolarSystem3D

SolarSystem3D is a static Three.js browser app for exploring a simplified educational model of the solar system. The first screen is the simulator itself: a 3D scene with the Sun, all eight planets, Earth’s Moon, orbit paths, camera controls, labels, season presets, and a selected-body info panel.

## Run instructions

This app is fully static. It does not use a backend, package manager, bundler, build step, or database.

### Recommended method: small static server

Because the app uses browser ES module imports, some browsers block direct `file://` loading. The safest run method is:

```bash
cd app
python3 -m http.server 8000
```

Then open:

- `http://localhost:8000/`

### Direct open from disk

You can also try opening:

- `app/index.html`

If the 3D scene does not load because the browser blocks module imports from local disk, use the static-server method above.

## Dependency notes

The app uses pinned CDN browser imports:

- `https://unpkg.com/three@0.165.0/build/three.module.js`
- `https://unpkg.com/three@0.165.0/examples/jsm/controls/OrbitControls.js`

No external texture images, audio files, APIs, or other runtime dependencies are required.

## Project files

```text
app/
  index.html
  styles.css
  app.js
  README.md
```

## Feature list

The finished app includes:

- Simulator-first layout with the 3D scene visible on first load
- Sun, Mercury, Venus, Earth, Moon, Mars, Jupiter, Saturn, Uranus, and Neptune
- Procedural starfield background
- Visible orbit paths for every planet and for the Moon
- Procedural Canvas-generated textures for all required bodies
- Saturn ring system
- Earth axial tilt marker
- Play/pause simulation control
- Time speed slider with readable live output
- Live position mode plus season preset selection
- Spring equinox, summer solstice, autumn equinox, and winter solstice buttons
- Camera presets for:
  - overview
  - inner planets
  - Earth and Moon
  - outer planets
  - Sun view
- Click-to-focus body selection in the 3D scene
- Interactive body labels that can also focus a body
- Toggle for labels
- Toggle for orbit visibility
- Educational scale mode
- Realistic scale mode
- Selected-body information panel showing:
  - name
  - type
  - distance
  - orbital period
  - rotation period
  - short description
- Keyboard shortcuts for common review actions
- Touch-friendly controls and responsive layout behavior
- No music, no sound effects, no narration, and no generated audio

## Controls and interaction

### Scene navigation

OrbitControls provide:

- drag to orbit the camera
- scroll wheel or pinch to zoom
- pan to shift the view

### Camera presets

The view controls include predictable preset buttons:

- **Overview**
- **Inner planets**
- **Earth and Moon**
- **Outer planets**
- **Sun view**

These presets animate the camera toward reusable target-and-offset views. If you directly select a body, the app exits preset-follow mode and reframes the chosen body.

### Selection and focus

You can select a body by:

- clicking its 3D mesh
- clicking its visible label
- using the labels with keyboard focus when labels are visible

Selection updates the info panel and focus state. A **Refocus selected body** button is also provided for keyboard and touch users.

### Keyboard shortcuts

Supported shortcuts:

- `Space` — play/pause
- `L` — toggle labels
- `O` — toggle orbit guides
- `F` — refocus the selected body
- `ArrowUp` / `ArrowRight` — increase time speed
- `ArrowDown` / `ArrowLeft` — decrease time speed
- `1` — overview preset
- `2` — inner planets preset
- `3` — Earth and Moon preset
- `4` — outer planets preset
- `5` — Sun view preset

Shortcuts are intentionally suppressed while typing in normal form controls, except that the time-speed slider still supports arrow-key adjustment.

## Astronomy simplifications

This app is an educational approximation, not a precision ephemeris or scientific mission-planning tool.

Simplifications used here include:

- circular or near-circular visual orbit paths
- rounded orbital and rotation values
- a shared simplified orbital plane for readability
- educationally compressed distances in the default scale
- a realistic scale mode that still preserves minimum visible sizes for usability
- constant Earth axial tilt of about 23.5°
- simplified teaching positions for:
  - spring equinox
  - summer solstice
  - autumn equinox
  - winter solstice
- Earth season presets that emphasize tilt relative to sunlight rather than exact date calculations
- illustrative procedural surfaces instead of photorealistic maps

Important teaching note:

- **Seasons are caused by Earth’s axial tilt relative to sunlight, not by Earth being closer to or farther from the Sun.**

When a season preset is active, Earth is placed in a simplified teaching position. Other bodies continue using the simplified live animation model.

## Procedural texture notes

All body surfaces are generated in `app.js` with Canvas APIs and reused through texture caching.

Examples:

- **Sun**: warm gradients, glow-like variation, hot cellular detail
- **Mercury / rocky planets**: mottled rocky tones and crater fields
- **Venus**: pale clouded rocky appearance with haze
- **Earth**: ocean-like, land-like, cloud-like, and polar detail
- **Moon**: cratered gray surface with maria-like regions
- **Mars**: reddish surface, darker regions, dust-like variation, polar caps
- **Jupiter**: horizontal bands and a storm-like mark
- **Saturn**: banded atmosphere and visible rings
- **Uranus**: blue-green ice giant styling
- **Neptune**: deeper blue ice giant styling with storm-like variation

No external image textures are downloaded.

## Accessibility notes

The app is designed to be reviewable and usable with common browser accessibility expectations.

Included accessibility-oriented behavior:

- semantic `button`, `input`, `select`, `label`, `section`, `main`, and `aside` elements
- visible focus states
- labeled controls
- keyboard-reachable core controls
- keyboard-reachable visible labels
- hidden labels removed from the tab order when labels are toggled off
- no hover-only primary actions
- touch-friendly minimum control sizing
- scene interaction guidance in the UI and screen-reader-only helper text
- controls remain available without drag-and-drop
- no audio content

Responsive polish notes:

- the 3D scene remains the main first-screen surface
- controls stack cleanly at phone and tablet widths
- the layout avoids horizontal scrolling at common small widths
- sidebar cards wrap below the scene on narrower viewports instead of permanently covering it
- labels are constrained and reduced on smaller screens to limit clutter

## Performance notes

The implementation includes a lightweight performance pass appropriate for a static browser benchmark.

Current decisions:

- one main `requestAnimationFrame` loop
- simulation updates only advance while play is active and time speed is above zero
- stable textures are generated once and reused from a cache
- stable meshes, materials, labels, and orbit lines are reused rather than recreated per frame
- moderate sphere geometry counts:
  - Sun uses 48 x 48 segments
  - planets and Moon use 28 x 28 segments
- bounded starfield count
- bounded label count
- no listener creation inside the animation loop
- resize handling updates camera aspect ratio and renderer size
- camera focus uses interpolation instead of rebuilding scene resources
- scale mode changes update existing transforms in place
- renderer pixel ratio is capped to reduce unnecessary high-DPI cost

Paused-state behavior:

- when paused, simulation day advancement stops
- camera controls, focus interpolation, labels, and rendering still continue so the scene remains inspectable

## Manual verification steps

1. Run the app with `python3 -m http.server 8000` from `app/`.
2. Open `http://localhost:8000/`.
3. Confirm the simulator is the first visible screen.
4. Confirm the Sun, all eight planets, and Earth’s Moon are present.
5. Confirm each body has a visible texture-like procedural surface.
6. Confirm Saturn has rings.
7. Confirm orbit paths are visible for planets and the Moon.
8. Toggle orbit visibility off and back on.
9. Toggle labels off and back on.
10. Confirm hidden labels are not keyboard focusable while labels are off.
11. Drag, zoom, and pan in the scene to verify OrbitControls behavior.
12. Use camera presets:
    - Overview
    - Inner planets
    - Earth and Moon
    - Outer planets
    - Sun view
13. Confirm the preset framing remains coherent after switching scale mode.
14. Click the Sun, Earth, Moon, and at least one outer planet to verify selection and focus.
15. Confirm the selected-body panel updates with:
    - name
    - type
    - distance
    - orbital period
    - rotation period
    - short description
16. Confirm the Moon distance text identifies Earth as the parent body.
17. Use the play/pause button and confirm orbital motion stops and resumes.
18. Move the time-speed slider and confirm the live speed output changes.
19. Confirm paused mode does not stop inspection, labels, or camera movement.
20. Select each season preset:
    - spring equinox
    - summer solstice
    - autumn equinox
    - winter solstice
21. Confirm Earth moves to distinct simplified positions.
22. Focus Earth and confirm the axial tilt marker is visible in closer views.
23. Confirm the season explanation states that tilt, not distance, causes seasons.
24. Switch between educational and realistic scale and confirm the scene updates coherently without duplicates.
25. Tab through controls and confirm visible focus outlines appear.
26. Test keyboard shortcuts:
    - `Space`
    - `L`
    - `O`
    - `F`
    - `ArrowUp` / `ArrowRight`
    - `ArrowDown` / `ArrowLeft`
    - `1` through `5`
27. Check the layout around roughly:
    - 360px width
    - 768px width
    - desktop width
28. Confirm there is no horizontal scrolling caused by the controls or labels.
29. Confirm the scene is still visible on first load at those sizes.
30. Confirm no music, sound effects, narration, or audio controls are present.

## Reviewer summary

- Static app only
- No backend
- No build step
- No package manager
- No external planet textures
- Pinned Three.js CDN imports
- Educational simplifications are documented
- Responsive behavior, accessibility notes, and manual verification steps are included
