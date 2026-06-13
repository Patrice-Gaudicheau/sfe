# SolarSystem3D

SolarSystem3D is a static Three.js educational solar system simulator. It opens directly into the 3D scene and includes the Sun, all eight planets, Earth's Moon, visible orbit paths, procedural textures, season presets, scale modes, labels, camera presets, click-to-focus selection, and a selected-body information panel.

This benchmark step finalizes responsive layout polish, reviews performance-minded implementation choices, and completes the README for manual review.

## Run instructions

Because `app.js` uses browser ES module imports for Three.js and OrbitControls, direct `file://` loading may be unreliable in some browsers.

Recommended run method:

```bash
cd app
python3 -m http.server 8000
```

Then open:

```text
http://localhost:8000/
```

Directly opening `index.html` may still work in some environments, but the simple static server is the documented fallback.

## Dependency note

This app uses pinned CDN imports:

- `https://cdn.jsdelivr.net/npm/three@0.160.0/build/three.module.js`
- `https://cdn.jsdelivr.net/npm/three@0.160.0/examples/jsm/controls/OrbitControls.js`

No package manager, bundler, build step, backend, or framework is required.

## Feature summary

- Static browser app with one main `requestAnimationFrame` loop
- First screen is the simulator itself
- Procedural star background generated in code
- Procedural Canvas textures for the Sun, all planets, and the Moon
- Sun, Mercury, Venus, Earth, Moon, Mars, Jupiter, Saturn, Uranus, and Neptune
- Correct planetary order from the Sun
- Saturn ring system
- Visible orbit paths for planets and Moon
- Orbit visibility toggle
- Body labels with label visibility toggle
- Play and pause controls
- Time speed slider
- Date input mapped to simplified educational season positions
- Spring equinox, summer solstice, autumn equinox, and winter solstice presets
- Earth axial tilt marker
- Educational scale mode and realistic scale mode
- OrbitControls camera rotation, zoom, and pan
- Camera presets for overview, inner planets, Earth and Moon, outer planets, and Sun view
- Click-to-focus body selection
- Selected-body info panel with name, type, distance, orbital period, rotation period, and description
- Keyboard shortcuts for core actions

## Body data model

Each body includes:

- Name
- Type
- Parent relationship where relevant
- Approximate distance text
- Approximate orbital period text
- Approximate rotation period text
- Short educational description
- Educational visual radius
- Realistic visual radius
- Educational orbit radius
- Realistic orbit radius
- Approximate orbital timing value in days
- Texture style parameters

The Moon is modeled as a child of Earth so it remains visually associated with Earth during orbit motion and season preset changes.

## Educational astronomy simplifications

This is an educational approximation, not a precision ephemeris or physics simulator.

Important simplifications:

- Planetary orbits are simplified as circular paths in a shared main plane
- Orbital periods are approximate and rounded for readability
- Body sizes and distances are remapped for usability
- Educational scale enlarges small worlds and compresses distances
- Realistic scale preserves relative spacing and sizes more strongly, while still keeping a minimum visible body size
- Earth's axial tilt is kept at about 23.5°
- Season presets place Earth at four representative orbital positions for Northern Hemisphere learning
- The date input maps to simplified seasonal categories rather than real ephemeris dates
- Seasons are explained as being caused by axial tilt relative to sunlight, not by Earth being much closer to or farther from the Sun

## Procedural texture approach

All body appearances are generated in-browser with Canvas APIs and reused through cached `THREE.CanvasTexture` objects.

Implemented styles include:

- **Sun**: warm gradient, layered bright streaks, granular variation
- **Mercury**: gray rocky mottled surface with crater-like markings
- **Venus**: pale yellow cloudy haze and swirl-like bands
- **Earth**: blue oceans, green-brown land-like regions, and white cloud-like detail
- **Moon**: gray cratered rocky surface
- **Mars**: red-orange dusty rocky surface with darker variation
- **Jupiter**: horizontal bands and a storm-like red spot
- **Saturn**: soft bands plus a separate procedural ring texture
- **Uranus**: cyan to blue-green ice giant appearance
- **Neptune**: deeper blue ice giant appearance with stronger shading

No external image textures are downloaded.

## Controls

### Main controls

- **Play**: resume animation
- **Pause**: pause simulation motion
- **Time speed**: adjust simulated days per second
- **Date / preset**: maps to simplified seasonal positions
- **Season preset buttons**:
  - Spring equinox
  - Summer solstice
  - Autumn equinox
  - Winter solstice
- **Camera preset buttons**:
  - Overview
  - Inner planets
  - Earth and Moon
  - Outer planets
  - Sun view
- **Show labels** checkbox
- **Show orbits** checkbox
- **Scale mode** selector:
  - Educational scale
  - Realistic scale

### Mouse and touch

- Drag to orbit camera
- Scroll or pinch to zoom
- Pan using OrbitControls-supported interaction
- Click or tap a visible body to select and focus it

### Keyboard shortcuts

- `Space`: play or pause
- `L`: toggle labels
- `O`: toggle orbits
- `1`: overview preset
- `2`: inner planets preset
- `3`: Earth and Moon preset
- `4`: outer planets preset
- `5`: Sun view preset
- `[` : decrease time speed
- `]` : increase time speed
- `Arrow Left`: step backward one day while paused
- `Arrow Right`: step forward one day while paused

## Accessibility notes

- The 3D scene is the first-screen primary content
- Controls use semantic `button`, `input`, `select`, `label`, `section`, and heading elements
- A skip link allows quick keyboard access to the controls and info panel
- Visible focus styles are included for keyboard users
- Control labels are visible and not hover-only
- Primary controls are reachable by keyboard tab order
- Selected body details are duplicated in a readable text panel, not only in floating scene labels
- Labels can be toggled off if they become visually dense
- Control sizing is touch-friendly on smaller screens
- No audio, music, sound effects, or narration are included

## Responsive layout notes

- On desktop, the scene remains the dominant visual surface with a right-hand control column
- On tablet and smaller widths, the layout stacks vertically so controls remain reachable without horizontal scrolling
- At narrow phone widths, grouped buttons wrap and eventually become single-column where needed
- Scene status chips are allowed to wrap rather than overflow
- The sidebar scrolls independently on larger screens to avoid covering the canvas

## Performance and implementation notes

- One main `requestAnimationFrame` loop drives rendering
- Stable textures are generated once and cached
- Stable sphere geometries are reused through a geometry cache
- Orbit geometries are cached by radius and segment count and reused when scale mode changes
- No textures, materials, or geometries are recreated every animation frame
- Star counts are bounded to moderate values
- Label elements are created once and only repositioned per frame
- Event listeners are registered once during startup
- Window resize updates renderer size and camera aspect ratio
- Simulation state changes are minimized when paused
- Geometry segment counts are moderate for typical laptop browsers

## Manual verification checklist

1. Start a static server from the `app/` directory with `python3 -m http.server 8000`.
2. Open `http://localhost:8000/`.
3. Confirm the simulator appears immediately without a landing page.
4. Confirm the Sun, all eight planets, and Earth's Moon are present.
5. Confirm each body has a visible texture-like procedural surface.
6. Confirm Saturn has visible rings.
7. Confirm orbit paths are visible for planets and the Moon.
8. Toggle **Show orbits** off and on and verify the paths hide and reappear.
9. Toggle **Show labels** off and on and verify labels hide and reappear.
10. Click **Pause** and verify orbital progression stops.
11. Click **Play** and verify motion resumes.
12. Move the time speed slider and verify motion speeds up or slows down.
13. Set time speed to `0` and verify the playback status reflects a paused state.
14. Click **Spring equinox** and verify Earth moves to a distinct simplified position.
15. Click **Summer solstice** and verify Earth moves to a different position from spring equinox.
16. Click **Autumn equinox** and **Winter solstice** and verify those also move Earth to distinct positions.
17. Confirm the season explanation states that seasons are caused by axial tilt, not distance from the Sun.
18. Focus on Earth and verify the axial tilt marker is visible.
19. Confirm the Moon remains associated with Earth after season changes.
20. Use **Overview**, **Inner planets**, **Earth and Moon**, **Outer planets**, and **Sun view** camera presets and confirm each gives a distinct helpful view.
21. Click several bodies such as Mars, Jupiter, the Moon, and the Sun and verify the selected-body info panel updates.
22. Confirm the info panel shows name, type, distance, orbital period, rotation period, and description.
23. Switch between **Educational scale** and **Realistic scale** and verify the scene updates coherently without duplicated bodies.
24. Use mouse or touch interaction to orbit, zoom, and pan the scene.
25. Use keyboard navigation to tab through the controls and verify visible focus indication.
26. Test keyboard shortcuts: `Space`, `L`, `O`, `1`-`5`, `[` , `]`, `Arrow Left`, and `Arrow Right`.
27. Check the layout around roughly 360px, 768px, and desktop widths and verify controls remain usable without horizontal scrolling.
28. Confirm no audio plays and no backend setup is required.

## Known non-goals

This app intentionally does not implement:

- Backend services
- User accounts or persistence
- External astronomy APIs
- Ephemeris-grade orbital calculations
- Asteroids, comets, Pluto, spacecraft, or exoplanets
- Audio or music
- Build tools or framework scaffolding
