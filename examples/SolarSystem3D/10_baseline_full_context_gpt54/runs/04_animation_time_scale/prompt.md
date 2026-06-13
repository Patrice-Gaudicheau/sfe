# SolarSystem3D full-context baseline task

You are executing one task in an eight-step benchmark. This is the baseline run: use the full context below. Do not use SFE routing, discovery, or context reduction.

Return only strict JSON with this exact shape:

```json
{
  "files": [
    {"path": "index.html", "content": "..."},
    {"path": "styles.css", "content": "..."},
    {"path": "app.js", "content": "..."},
    {"path": "README.md", "content": "..."}
  ],
  "notes": "optional short implementation notes"
}
```

Rules for your response:
- Return JSON only, with no markdown fences or explanatory text.
- Include exactly the four required files.
- Use only these paths: index.html, styles.css, app.js, README.md.
- Provide complete replacement contents for every file on every task.
- Do not include package files, server code, backend code, or extra files.
- The app should remain static. A pinned browser Three.js CDN import is allowed, and a documented simple static-server fallback is allowed if browser module restrictions require it.

## Product brief

# SolarSystem3D product request

Build a static Three.js solar system simulator called SolarSystem3D. The finished app should be an educational 3D visualization that someone can open from a local folder, or run with a very small static server if browser module restrictions make direct `file://` loading unreliable. It must not require a backend, database, account system, package manager, bundler, build step, server framework, analytics, external API, generated audio, or music.

The first screen should be the simulator itself, not a landing page. The user should immediately see a starry 3D scene with the Sun, all eight planets, Earth's Moon, visible orbit paths, and usable controls. The product should feel like a focused learning tool: clear, technical, calm, and easy to inspect. Avoid a marketing-style hero page, decorative card-heavy layout, or a page that hides the actual 3D visualization below explanatory text.

## Expected runtime files

Create the generated app under the scenario's `app/` directory. The expected static structure is:

```text
app/
  index.html
  styles.css
  app.js
  README.md
```

The implementation may add `app/vendor/` only if it vendors Three.js or browser control helpers locally. If it uses CDN URLs for Three.js, the URLs must be pinned to an explicit version and documented in `app/README.md`. Do not add a package manifest, build config, server source, compiled bundle pipeline, or framework scaffolding.

## Three.js and static execution assumptions

Use Three.js for the 3D scene. It is acceptable to use a pinned browser CDN URL for Three.js and `OrbitControls`, or to vendor a small documented copy in `app/vendor/`. The benchmark should not depend on external planet texture images. If ES modules prevent direct local-file execution in a browser, document the static-server fallback:

```bash
cd app
python3 -m http.server 8000
```

The generated app should then run at `http://localhost:8000/`. No application backend is allowed; this fallback is only for serving static files.

## Core visualization requirements

- Render the Sun.
- Render all eight planets in the correct order from the Sun: Mercury, Venus, Earth, Mars, Jupiter, Saturn, Uranus, Neptune.
- Render Earth's Moon orbiting Earth.
- Use visible planet-like textures for the Sun, planets, and Moon.
- Generate textures procedurally inside the app with Canvas APIs. Do not depend on external image texture downloads.
- Generate a starry background procedurally or with Three.js geometry/materials. Do not use external starfield images.
- Show visible orbital paths for every planet and for the Moon.
- Support free 3D camera navigation around the scene.
- Allow clicking or otherwise selecting a body to focus the camera and update information.
- Include labels for bodies and allow labels to be toggled.
- Include a toggle for orbit visibility.
- Include both an educational scale mode and a realistic scale mode.
- Include an info panel for the selected body.
- Include clear controls for simulation time.
- Include no music, no sound effects, and no generated audio.

## Functional controls

Provide at least these controls in the UI:

- Play and pause simulation.
- Time speed slider or equivalent numeric control.
- Date selector or season preset controls.
- Buttons for spring equinox, summer solstice, autumn equinox, and winter solstice.
- Camera presets: overview, inner planets, Earth and Moon, outer planets, and Sun view.
- Planet label visibility toggle.
- Orbit visibility toggle.
- Scale mode switch for educational scale and realistic scale.
- Focus behavior when a planet, Moon, or Sun is selected.

Use the astronomy wording "spring equinox". Do not call it "spring solstice".

## Earth seasons and astronomy simplification rules

The app is an educational approximation, not an ephemeris-grade astronomy tool. It should communicate simplifications honestly in the UI or README.

Use these rules unless a more accurate implementation remains simple and static:

- Treat orbits as circular or nearly circular paths in a shared orbital plane, except where a small visual tilt helps readability.
- Use approximate relative orbital periods, not precision ephemerides.
- Use approximate body radii and distances, then map them through scale modes so the visualization remains usable.
- In educational scale mode, enlarge small planets and compress orbital distances enough for all bodies to be inspectable.
- In realistic scale mode, preserve relative distance and size relationships more strongly, while still allowing a minimum visible size so small bodies do not disappear.
- Use a constant Earth axial tilt of about 23.5 degrees.
- Show Earth's tilted axis with a visible line or marker.
- For season presets, place Earth at four simplified orbital positions representing Northern Hemisphere spring equinox, summer solstice, autumn equinox, and winter solstice.
- Include a short explanation that seasons are caused by Earth's axial tilt relative to sunlight, not by Earth being closer to or farther from the Sun.
- The spring equinox and autumn equinox should show the Earth axis neither leaning strongly toward nor away from the Sun.
- The summer solstice should show the Northern Hemisphere tilted toward the Sun.
- The winter solstice should show the Northern Hemisphere tilted away from the Sun.
- The Moon should orbit Earth visually and remain associated with Earth when Earth position changes.

The app should make it possible to view Earth's position at the spring equinox and summer solstice specifically. The autumn equinox and winter solstice are also required presets for comparison.

## Body data requirements

For each body, include enough data to drive rendering and the info panel:

- Name.
- Type, such as star, rocky planet, gas giant, ice giant, or moon.
- Approximate distance from the Sun. For the Moon, show distance from Earth and identify Earth as its parent.
- Approximate orbital period.
- Approximate rotation period.
- Short educational description.
- Visual radius value for rendering.
- Orbit radius or parent orbit radius for rendering.
- Procedural texture style parameters.

The values may be rounded and educational. They should be plausible and internally consistent, not random.

## Visual requirements

The scene should clearly read as a solar system. The user should be able to distinguish the Sun, rocky inner planets, gas giants, ice giants, Saturn's rings, Earth's Moon, orbit paths, and labels.

Procedural texture expectations:

- The Sun should appear bright and active, with warm layered color or noise.
- Mercury should appear gray and cratered or mottled.
- Venus should appear pale yellow or clouded.
- Earth should include blue ocean-like regions, green/brown land-like regions, and white cloud-like detail.
- The Moon should appear gray and cratered or mottled.
- Mars should appear red/orange with darker surface variation.
- Jupiter should show horizontal bands and a storm-like mark.
- Saturn should show bands and a visible ring system.
- Uranus should appear cyan or blue-green.
- Neptune should appear deeper blue.

The background should be dark enough for orbits and labels to be legible. Avoid relying on a single flat color theme for all UI. Controls must not overlap the canvas in ways that hide core content on common desktop and mobile viewport sizes.

## Interaction and navigation

Camera navigation should support mouse or trackpad rotation, zoom, and pan through `OrbitControls` or equivalent Three.js controls. Keyboard controls should support practical actions such as play/pause, stepping or changing speed, toggling labels/orbits, and focusing a selected body where reasonable. Touch interaction should remain usable on common mobile and tablet sizes.

Clicking a body should select it, update the info panel, and move or animate the camera focus toward that body. Camera preset buttons should provide predictable views: full overview, inner planets, Earth and Moon, outer planets, and Sun view.

## Layout, accessibility, and reviewability

The layout must be responsive at phone, tablet, and desktop widths. The 3D canvas should remain the primary surface. Controls should be visible, reachable, and not hover-only. Use semantic HTML for buttons, sliders, labels, and panels. Form controls must have visible labels or accessible names. Focus states should be visible. The app should be usable with keyboard navigation for core controls even if 3D camera movement is easier with a pointer.

Use clear JavaScript with readable data structures and functions. Since this is a benchmark project, reviewability matters more than cleverness. Avoid minified source, hidden generated code, framework boilerplate, and unnecessary abstraction layers.

## Performance constraints

The app should run acceptably on a typical laptop browser. Keep geometry counts reasonable:

- Use moderate segment counts for spheres instead of extremely dense meshes.
- Avoid creating new textures, geometries, or materials every animation frame.
- Use one `requestAnimationFrame` loop and pause expensive simulation updates when the simulation is paused.
- Reuse generated procedural textures.
- Keep star counts and label counts reasonable.
- Avoid unbounded event listener creation during re-renders.
- Handle window resize without breaking camera aspect ratio or renderer size.

## Non-goals

Do not implement:

- Backend services.
- User accounts.
- Persistence or saving custom scenarios.
- Real-time NASA, JPL, or external astronomy API calls.
- Precision ephemeris calculations.
- Spacecraft trajectories.
- Comets, asteroids, Pluto, dwarf planets, or exoplanets.
- Music, sound effects, narration, generated audio, or audio controls.
- VR or AR modes.
- Build tools, package managers, transpilers, test runners, or framework scaffolds.
- External image textures.

## Manual testing expectations

After implementation, a reviewer should be able to verify the app manually by opening the static app or serving it with `python3 -m http.server`. The README should explain the chosen run method, any Three.js dependency choice, feature list, simplifications, and manual test steps.

Manual checks should include:

- The Sun, eight planets, and Earth's Moon are visible.
- Every body has a visible texture or texture-like procedural surface.
- Saturn has rings.
- Planet and Moon orbits are visible and toggleable.
- Play/pause and time speed controls affect animation.
- Spring equinox and summer solstice controls move Earth to distinct explained positions.
- Autumn equinox and winter solstice controls also work.
- Earth's axial tilt marker is visible in Earth-focused views.
- Camera presets work.
- Click-to-focus works for several bodies.
- The info panel updates for selected bodies.
- Labels can be toggled.
- Scale mode can be changed.
- The layout remains usable around 360px, 768px, and desktop widths.
- Keyboard focus is visible and core controls are keyboard reachable.
- No audio plays.



## Acceptance criteria

# SolarSystem3D acceptance criteria

## Project shape

- For the baseline scenario, the generated app must live in `examples/SolarSystem3D/10_baseline_full_context_gpt54/app/`.
- For the SFE single-model multipass scenario, the generated app must live in `examples/SolarSystem3D/20_sfe_single_model_gpt54_multipass/app/`.
- For the SFE split-model multipass scenario, the generated app must live in `examples/SolarSystem3D/30_sfe_split_gpt54_router_gpt54mini_executor_multipass/app/`.
- Each scenario app folder must include `index.html`, `styles.css`, `app.js`, and `README.md`.
- The app is static. It has no backend, server framework, package manager, bundler, transpiler, database, account system, or analytics.
- If browser module restrictions prevent direct `file://` use, the app runs with a simple static server such as `python3 -m http.server`.
- Three.js dependency usage is pinned and documented. Vendored copies, if any, are placed under `app/vendor/`.
- No generated app output should be stored outside the scenario's `app/` directory.

## Required solar system content

- The Sun is present and visually distinct.
- Mercury, Venus, Earth, Mars, Jupiter, Saturn, Uranus, and Neptune are present.
- The planets are arranged in the correct order from the Sun.
- Earth's Moon is present and visually associated with Earth.
- The Moon orbits Earth or visibly moves with Earth as a moon.
- Saturn has a visible ring system.
- Pluto is not required.
- Comets, asteroids, spacecraft, dwarf planets, and exoplanets are not required.

## Procedural textures and background

- Every required body has a visible texture or texture-like procedural surface.
- Textures are generated in the app with Canvas APIs or equivalent procedural code.
- The app does not depend on external image texture downloads.
- The Sun uses warm layered color, noise, or similar visual treatment.
- Earth includes visible ocean-like, land-like, and cloud-like regions.
- Jupiter includes visible banding and a storm-like feature.
- Saturn includes visible banding or surface variation plus rings.
- Rocky planets and the Moon have mottled, cratered, or surface-varied appearances.
- Uranus and Neptune are visually distinguishable from each other.
- The starry background is generated procedurally or with Three.js objects/materials, not by downloading an external image.

## Orbits, motion, and scale

- Planet orbit paths are visible.
- The Moon orbit path is visible or clearly represented.
- Orbit visibility can be toggled.
- The simulation can be played and paused.
- Time speed can be changed with a slider, numeric control, or equivalent UI.
- Bodies orbit or otherwise animate according to the simulation state.
- Bodies rotate or show some rotation behavior where practical.
- Educational scale mode is available and makes all bodies inspectable.
- Realistic scale mode is available and better preserves relative distance/size relationships while remaining usable.
- Scale mode changes update the scene coherently without duplicating bodies or breaking camera controls.

## Earth seasons

- The UI includes a spring equinox control.
- The UI includes a summer solstice control.
- The UI includes an autumn equinox control.
- The UI includes a winter solstice control.
- The app uses the phrase "spring equinox" and does not use "spring solstice".
- Spring equinox and summer solstice place Earth in distinct simplified orbital positions.
- Autumn equinox and winter solstice also place Earth in distinct simplified orbital positions.
- Earth's axial tilt is visualized with a line, marker, or equivalent clear cue.
- The season explanation states that Earth's seasons are caused by axial tilt relative to sunlight, not by changing distance from the Sun.
- The README or UI states that season positions are simplified educational approximations, not precision ephemerides.

## Camera, selection, labels, and info panel

- The user can freely navigate the 3D scene with mouse or trackpad controls.
- Touch navigation remains practical where supported by the browser/control library.
- Camera preset controls exist for overview, inner planets, Earth and Moon, outer planets, and Sun view.
- Clicking or selecting a body focuses or moves the camera target to that body.
- Body labels are available.
- Labels can be toggled.
- The selected-body panel shows the selected body's name.
- The selected-body panel shows type.
- The selected-body panel shows approximate distance from the Sun, or Moon distance from Earth with Earth identified as parent.
- The selected-body panel shows approximate orbital period.
- The selected-body panel shows approximate rotation period.
- The selected-body panel shows a short description.

## Layout and responsiveness

- The 3D canvas is the primary first-screen surface.
- The app does not present a marketing landing page before the simulator.
- Controls remain usable at approximately 360px wide without horizontal scrolling.
- The layout is usable around tablet widths such as approximately 768px.
- Desktop layout leaves enough room to inspect the scene and operate controls.
- Controls and labels do not visibly overlap each other in an incoherent way.
- UI panels do not permanently hide essential scene content at common viewport sizes.
- Text inside controls remains readable and does not overflow its container.

## Accessibility and input

- Primary controls are semantic `button`, `input`, `select`, or equivalent accessible elements.
- Form controls have visible labels or accessible names.
- Keyboard focus is visible.
- Core controls can be reached and activated by keyboard.
- The app does not require drag and drop.
- The app does not rely on hover-only controls.
- No music, sound effects, narration, generated audio, or audio controls are present.
- `app/README.md` includes accessibility notes for controls and labels.

## Performance and code reviewability

- The app uses one main `requestAnimationFrame` loop.
- Stable textures, materials, and geometries are reused instead of recreated every frame.
- Geometry segment counts are reasonable for a browser benchmark.
- Star count and label count are bounded.
- Event listeners are not repeatedly added during animation or render updates.
- Window resize updates renderer size and camera aspect ratio.
- Pausing the simulation stops or minimizes simulation state changes.
- JavaScript and CSS are readable and not minified.
- Source code avoids unnecessary abstraction and hidden generated code.
- `app/README.md` includes manual verification steps and known simplifications.



## Full task sequence

# SolarSystem3D task sequence

Use the same task sequence for every benchmark scenario. Each task should build on the previous task without changing the product brief or acceptance criteria.

This sequence is intentionally longer and more interdependent than NoteKeeper. Later tasks depend on earlier data modeling, rendering, texture generation, camera behavior, and astronomy simplification choices.

## 1. Static scaffold and Three.js scene shell

Create the initial static app files under the scenario's `app/` directory: `index.html`, `styles.css`, `app.js`, and `README.md`. Establish the SolarSystem3D app shell, full-screen 3D canvas, primary control areas, selected-body panel placeholder, responsive layout, and baseline Three.js scene with camera, renderer, lighting, resize handling, and a procedural star background.

Document whether the app opens directly from `index.html` or requires a simple static server because of browser module loading rules.

## 2. Solar system data model and procedural texture pipeline

Create a clear data model for the Sun, eight planets, and Earth's Moon. Include body type, approximate distance, orbital period, rotation period, description, visual radius, orbit radius, parent relationship where needed, and texture style parameters.

Implement reusable procedural Canvas texture generation for the required body styles: Sun, rocky planets, Earth, Moon, Mars, Jupiter, Saturn, Uranus, Neptune, and general bands/noise/crater effects. Do not use external image texture files.

## 3. Bodies, educational scale, rings, and orbit paths

Render the Sun, all eight planets, Earth's Moon, Saturn's rings, and visible orbit paths. Use educational scale mode as the initial default so every body is inspectable. Ensure body order, relative placement, and labels or placeholders are coherent. Add Moon orbit around Earth.

## 4. Animation, time controls, and realistic scale mode

Implement simulation play/pause, time speed control, body orbital motion, body rotation, and a realistic scale mode toggle. Keep the animation loop efficient and avoid recreating stable scene resources per frame. The realistic scale mode should better preserve relative size/distance relationships while keeping bodies minimally visible and navigable.

## 5. Earth seasons, axial tilt, and date or season presets

Add spring equinox, summer solstice, autumn equinox, and winter solstice controls. Use the wording "spring equinox". Do not use "spring solstice".

Implement an Earth axial tilt marker and an explanation of why seasons occur. Earth should move to distinct simplified positions for each preset, with summer solstice visibly different from spring equinox. The Moon should remain visually associated with Earth after season preset changes.

## 6. Camera navigation, presets, labels, and click focus

Add free camera navigation with OrbitControls or equivalent. Implement camera preset buttons for overview, inner planets, Earth and Moon, outer planets, and Sun view. Add body labels with a toggle. Implement selecting a body by clicking it, updating the selected-body panel, and focusing the camera on the selected body.

## 7. Info panel, toggles, keyboard support, and accessibility pass

Complete the selected-body info panel with name, type, approximate distance, orbital period, rotation period, and description. Add orbit visibility and label visibility toggles if not already complete. Add practical keyboard shortcuts or keyboard-operable controls for core actions, visible focus states, accessible control names, and touch-friendly sizing where practical.

## 8. Responsive polish, performance review, and README

Polish phone, tablet, and desktop layouts. Verify controls do not overlap important scene content at common sizes. Review geometry counts, animation behavior, texture reuse, event listeners, resize handling, and paused-state behavior. Finalize `app/README.md` with run instructions, dependency notes, feature list, astronomy simplifications, accessibility notes, performance notes, and manual verification steps.



## Current task

## 4. Animation, time controls, and realistic scale mode

Implement simulation play/pause, time speed control, body orbital motion, body rotation, and a realistic scale mode toggle. Keep the animation loop efficient and avoid recreating stable scene resources per frame. The realistic scale mode should better preserve relative size/distance relationships while keeping bodies minimally visible and navigable.

## Current generated app files

### index.html

```text
<!DOCTYPE html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>SolarSystem3D</title>
    <link rel="stylesheet" href="styles.css" />
  </head>
  <body>
    <div class="app-shell">
      <header class="topbar" aria-label="Application header">
        <div>
          <h1>SolarSystem3D</h1>
          <p class="subtitle">Educational scale orbital layout with procedural planets, Moon, rings, and orbit paths</p>
        </div>
        <div class="status-badge" id="status-badge" aria-live="polite">Task 3: bodies, orbits, Moon, and Saturn rings</div>
      </header>

      <main class="layout">
        <section class="viewer-panel" aria-label="3D solar system viewer">
          <div id="scene-container" class="scene-container">
            <canvas id="scene-canvas" aria-label="3D solar system canvas"></canvas>
            <div class="scene-overlay">
              <div class="overlay-chip">Educational scale mode</div>
              <div class="overlay-chip">Visible orbit paths</div>
              <div class="overlay-chip">Procedural textures</div>
              <div class="overlay-chip">Moon orbit around Earth</div>
            </div>
          </div>
        </section>

        <aside class="sidebar" aria-label="Controls and selected body information">
          <section class="panel controls-panel">
            <h2>Controls</h2>
            <div class="control-grid">
              <button type="button" disabled aria-disabled="true">Play</button>
              <button type="button" disabled aria-disabled="true">Pause</button>

              <label class="control-block" for="speedRange">
                <span>Time speed</span>
                <input id="speedRange" type="range" min="0" max="100" value="25" disabled />
              </label>

              <label class="control-block" for="dateInput">
                <span>Date / preset</span>
                <input id="dateInput" type="date" disabled />
              </label>
            </div>

            <div class="button-group" aria-label="Season presets">
              <button type="button" disabled aria-disabled="true">Spring equinox</button>
              <button type="button" disabled aria-disabled="true">Summer solstice</button>
              <button type="button" disabled aria-disabled="true">Autumn equinox</button>
              <button type="button" disabled aria-disabled="true">Winter solstice</button>
            </div>

            <div class="button-group" aria-label="Camera presets">
              <button type="button" disabled aria-disabled="true">Overview</button>
              <button type="button" disabled aria-disabled="true">Inner planets</button>
              <button type="button" disabled aria-disabled="true">Earth and Moon</button>
              <button type="button" disabled aria-disabled="true">Outer planets</button>
              <button type="button" disabled aria-disabled="true">Sun view</button>
            </div>

            <div class="toggle-list">
              <label><input type="checkbox" checked disabled /> Show labels</label>
              <label><input type="checkbox" checked disabled /> Show orbits</label>
              <label><input type="checkbox" checked disabled /> Educational scale</label>
            </div>
          </section>

          <section class="panel info-panel" aria-live="polite">
            <h2>Selected body</h2>
            <dl>
              <div>
                <dt>Name</dt>
                <dd id="selected-name">Earth</dd>
              </div>
              <div>
                <dt>Type</dt>
                <dd id="selected-type">Rocky planet</dd>
              </div>
              <div>
                <dt>Distance</dt>
                <dd id="selected-distance">149.6 million km from the Sun</dd>
              </div>
              <div>
                <dt>Orbital period</dt>
                <dd id="selected-orbit">365 days</dd>
              </div>
              <div>
                <dt>Rotation period</dt>
                <dd id="selected-rotation">24 hours</dd>
              </div>
              <div>
                <dt>Description</dt>
                <dd id="selected-description">Earth is shown in the educational orbital layout with its Moon and a visible orbit path. Seasons and camera focus controls are added in later tasks.</dd>
              </div>
            </dl>
          </section>

          <section class="panel notes-panel">
            <h2>Current baseline</h2>
            <p>
              This step replaces the texture preview cluster with a full educational-scale solar system layout.
            </p>
            <p>
              The scene now includes the Sun, all eight planets in order, Earth’s Moon orbiting Earth, Saturn’s rings, and visible orbit paths for planets and the Moon.
            </p>
          </section>

          <section class="panel data-panel">
            <h2>Body data model</h2>
            <div id="body-summary" class="body-summary" aria-live="polite"></div>
          </section>
        </aside>
      </main>
    </div>

    <script type="module" src="app.js"></script>
  </body>
</html>

```

### styles.css

```text
:root {
  --bg: #07111f;
  --bg-panel: rgba(9, 18, 32, 0.88);
  --bg-panel-strong: rgba(10, 22, 40, 0.96);
  --line: rgba(145, 178, 219, 0.24);
  --text: #ecf4ff;
  --muted: #a6bad6;
  --accent: #62b0ff;
  --accent-2: #ffd36d;
  --shadow: 0 18px 48px rgba(0, 0, 0, 0.35);
  --radius: 16px;
}

* {
  box-sizing: border-box;
}

html,
body {
  margin: 0;
  min-height: 100%;
  background: radial-gradient(circle at top, #11213b 0%, #07111f 40%, #030813 100%);
  color: var(--text);
  font-family: Inter, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
}

body {
  min-height: 100vh;
}

button,
input,
select {
  font: inherit;
}

button:focus-visible,
input:focus-visible,
select:focus-visible {
  outline: 2px solid var(--accent-2);
  outline-offset: 2px;
}

.app-shell {
  min-height: 100vh;
  display: grid;
  grid-template-rows: auto 1fr;
  gap: 12px;
  padding: 12px;
}

.topbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding: 14px 16px;
  background: var(--bg-panel);
  border: 1px solid var(--line);
  border-radius: var(--radius);
  box-shadow: var(--shadow);
  backdrop-filter: blur(10px);
}

.topbar h1 {
  margin: 0;
  font-size: 1.35rem;
}

.subtitle {
  margin: 4px 0 0;
  color: var(--muted);
  font-size: 0.95rem;
}

.status-badge {
  padding: 8px 12px;
  border-radius: 999px;
  border: 1px solid rgba(98, 176, 255, 0.45);
  background: rgba(98, 176, 255, 0.12);
  color: #cfe6ff;
  white-space: nowrap;
}

.layout {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 340px;
  gap: 12px;
  min-height: 0;
}

.viewer-panel,
.sidebar {
  min-height: 0;
}

.scene-container {
  position: relative;
  min-height: 68vh;
  height: 100%;
  border-radius: var(--radius);
  overflow: hidden;
  border: 1px solid var(--line);
  background: #020814;
  box-shadow: var(--shadow);
}

#scene-canvas {
  display: block;
  width: 100%;
  height: 100%;
}

.scene-overlay {
  position: absolute;
  left: 12px;
  bottom: 12px;
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  pointer-events: none;
}

.overlay-chip {
  padding: 6px 10px;
  border-radius: 999px;
  background: rgba(3, 10, 23, 0.72);
  border: 1px solid rgba(255, 255, 255, 0.12);
  color: var(--muted);
  font-size: 0.85rem;
}

.sidebar {
  display: grid;
  gap: 12px;
  align-content: start;
}

.panel {
  background: var(--bg-panel-strong);
  border: 1px solid var(--line);
  border-radius: var(--radius);
  padding: 14px;
  box-shadow: var(--shadow);
  backdrop-filter: blur(10px);
}

.panel h2 {
  margin-top: 0;
  margin-bottom: 12px;
  font-size: 1rem;
}

.control-grid {
  display: grid;
  gap: 10px;
}

.control-block {
  display: grid;
  gap: 6px;
  color: var(--muted);
}

.button-group {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 12px;
}

button,
input[type="date"],
input[type="range"] {
  width: 100%;
}

button {
  padding: 10px 12px;
  border-radius: 10px;
  border: 1px solid rgba(255, 255, 255, 0.12);
  background: rgba(255, 255, 255, 0.06);
  color: var(--text);
}

button[disabled],
input[disabled] {
  opacity: 0.65;
  cursor: not-allowed;
}

.toggle-list {
  margin-top: 12px;
  display: grid;
  gap: 8px;
  color: var(--muted);
}

.info-panel dl {
  margin: 0;
  display: grid;
  gap: 10px;
}

.info-panel dl > div {
  display: grid;
  gap: 2px;
}

dt {
  color: var(--muted);
  font-size: 0.84rem;
}

dd {
  margin: 0;
}

.notes-panel p {
  margin: 0 0 10px;
  color: var(--muted);
  line-height: 1.5;
}

.notes-panel p:last-child {
  margin-bottom: 0;
}

.body-summary {
  display: grid;
  gap: 8px;
  max-height: 260px;
  overflow: auto;
}

.body-chip {
  display: grid;
  gap: 4px;
  padding: 10px;
  border-radius: 12px;
  border: 1px solid rgba(255, 255, 255, 0.1);
  background: rgba(255, 255, 255, 0.04);
}

.body-chip strong {
  font-size: 0.96rem;
}

.body-chip span {
  color: var(--muted);
  font-size: 0.85rem;
  line-height: 1.35;
}

@media (max-width: 980px) {
  .layout {
    grid-template-columns: 1fr;
  }

  .scene-container {
    min-height: 56vh;
  }
}

@media (max-width: 600px) {
  .app-shell {
    padding: 8px;
  }

  .topbar {
    flex-direction: column;
    align-items: flex-start;
  }

  .status-badge {
    white-space: normal;
  }

  .scene-container {
    min-height: 48vh;
  }
}

```

### app.js

```text
import * as THREE from 'https://cdn.jsdelivr.net/npm/three@0.160.0/build/three.module.js';

const canvas = document.getElementById('scene-canvas');
const container = document.getElementById('scene-container');
const bodySummary = document.getElementById('body-summary');

const renderer = new THREE.WebGLRenderer({
  canvas,
  antialias: true,
  alpha: false
});
renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
renderer.setSize(container.clientWidth, container.clientHeight, false);
renderer.outputColorSpace = THREE.SRGBColorSpace;

const scene = new THREE.Scene();
scene.background = new THREE.Color(0x020814);
scene.fog = new THREE.FogExp2(0x020814, 0.00075);

const camera = new THREE.PerspectiveCamera(
  50,
  container.clientWidth / container.clientHeight,
  0.1,
  4000
);
camera.position.set(0, 160, 235);
camera.lookAt(0, 0, 0);

const ambientLight = new THREE.AmbientLight(0x8fa8c9, 0.9);
scene.add(ambientLight);

const sunLight = new THREE.PointLight(0xffddaa, 2.6, 0, 2);
sunLight.position.set(0, 0, 0);
scene.add(sunLight);

const rimLight = new THREE.DirectionalLight(0x7aa2ff, 0.55);
rimLight.position.set(-120, 90, 60);
scene.add(rimLight);

const textureCache = new Map();
const ringTextureCache = new Map();
const sphereGeometryCache = new Map();

const solarSystemBodies = [
  {
    name: 'Sun',
    type: 'Star',
    parent: null,
    distanceText: '0 km from the Sun',
    orbitalPeriodText: 'Not orbiting the Sun',
    rotationPeriodText: 'About 27 days',
    description:
      'The Sun is the central star of the solar system and the source of the light and heat that drive planetary illumination and seasons.',
    visualRadius: 10,
    orbitRadius: 0,
    orbitDays: 0,
    rotationHours: 648,
    initialAngle: 0,
    textureStyle: {
      kind: 'sun',
      base: '#ffb347',
      highlight: '#fff1b5',
      deep: '#ff6a00'
    }
  },
  {
    name: 'Mercury',
    type: 'Rocky planet',
    parent: 'Sun',
    distanceText: '57.9 million km from the Sun',
    orbitalPeriodText: '88 days',
    rotationPeriodText: '59 days',
    description:
      'Mercury is a small rocky world with a heavily cratered appearance and extreme day-night temperature contrasts.',
    visualRadius: 1.5,
    orbitRadius: 16,
    orbitDays: 88,
    rotationHours: 1416,
    initialAngle: 0.2,
    textureStyle: {
      kind: 'rocky',
      base: '#a7a7a7',
      dark: '#6d6d6d',
      light: '#d7d7d7',
      crater: '#565656'
    }
  },
  {
    name: 'Venus',
    type: 'Rocky planet',
    parent: 'Sun',
    distanceText: '108.2 million km from the Sun',
    orbitalPeriodText: '225 days',
    rotationPeriodText: '243 days retrograde',
    description:
      'Venus is wrapped in thick clouds, giving it a pale yellow appearance and a bright, hazy surface style in simplified educational views.',
    visualRadius: 2.2,
    orbitRadius: 23,
    orbitDays: 225,
    rotationHours: -5832,
    initialAngle: 1.1,
    textureStyle: {
      kind: 'cloudy',
      base: '#d7c27c',
      band: '#efe1a3',
      swirl: '#c7ab63',
      haze: '#fff1c8'
    }
  },
  {
    name: 'Earth',
    type: 'Rocky planet',
    parent: 'Sun',
    distanceText: '149.6 million km from the Sun',
    orbitalPeriodText: '365 days',
    rotationPeriodText: '24 hours',
    description:
      'Earth is shown with blue oceans, green-brown land, and white cloud detail. Seasons are caused by axial tilt, not by changing distance from the Sun.',
    visualRadius: 2.4,
    orbitRadius: 31,
    orbitDays: 365,
    rotationHours: 24,
    initialAngle: 2.1,
    textureStyle: {
      kind: 'earth',
      ocean: '#2876c8',
      shallow: '#4ca0ff',
      land: '#4f8f3c',
      dryLand: '#9c7a43',
      cloud: '#ffffff'
    }
  },
  {
    name: 'Moon',
    type: 'Moon',
    parent: 'Earth',
    distanceText: '384,400 km from Earth',
    orbitalPeriodText: '27.3 days around Earth',
    rotationPeriodText: '27.3 days',
    description:
      'Earth\'s Moon is a rocky satellite with a gray cratered surface and a synchronous rotation in this simplified model.',
    visualRadius: 0.7,
    orbitRadius: 4.2,
    orbitDays: 27.3,
    rotationHours: 655.2,
    initialAngle: 0.8,
    textureStyle: {
      kind: 'moon',
      base: '#b5b5b5',
      dark: '#818181',
      light: '#d9d9d9',
      crater: '#707070'
    }
  },
  {
    name: 'Mars',
    type: 'Rocky planet',
    parent: 'Sun',
    distanceText: '227.9 million km from the Sun',
    orbitalPeriodText: '687 days',
    rotationPeriodText: '24.6 hours',
    description:
      'Mars is a smaller rocky world with red-orange coloration, darker surface regions, and dusty variation.',
    visualRadius: 1.9,
    orbitRadius: 40,
    orbitDays: 687,
    rotationHours: 24.6,
    initialAngle: 0.65,
    textureStyle: {
      kind: 'mars',
      base: '#c65d2e',
      dark: '#7a3318',
      light: '#de8b54',
      dust: '#e7b17c'
    }
  },
  {
    name: 'Jupiter',
    type: 'Gas giant',
    parent: 'Sun',
    distanceText: '778.6 million km from the Sun',
    orbitalPeriodText: '11.9 years',
    rotationPeriodText: '9.9 hours',
    description:
      'Jupiter is the largest planet, represented with layered cloud bands and a storm-like great red spot.',
    visualRadius: 5.6,
    orbitRadius: 56,
    orbitDays: 4333,
    rotationHours: 9.9,
    initialAngle: 3.25,
    textureStyle: {
      kind: 'jupiter',
      light: '#dfc29a',
      bandA: '#b98558',
      bandB: '#f1d7b4',
      storm: '#c96d4e'
    }
  },
  {
    name: 'Saturn',
    type: 'Gas giant',
    parent: 'Sun',
    distanceText: '1.43 billion km from the Sun',
    orbitalPeriodText: '29.5 years',
    rotationPeriodText: '10.7 hours',
    description:
      'Saturn is shown with gentle atmospheric bands and a visible ring system in the educational orbital scene.',
    visualRadius: 4.9,
    orbitRadius: 74,
    orbitDays: 10759,
    rotationHours: 10.7,
    initialAngle: 4.1,
    textureStyle: {
      kind: 'saturn',
      light: '#e2cf9f',
      bandA: '#b59a63',
      bandB: '#f0e2ba',
      ring: '#d7c59b'
    }
  },
  {
    name: 'Uranus',
    type: 'Ice giant',
    parent: 'Sun',
    distanceText: '2.87 billion km from the Sun',
    orbitalPeriodText: '84 years',
    rotationPeriodText: '17.2 hours retrograde',
    description:
      'Uranus is an ice giant with a smooth cyan to blue-green appearance in this procedural texture set.',
    visualRadius: 3.4,
    orbitRadius: 92,
    orbitDays: 30687,
    rotationHours: -17.2,
    initialAngle: 5.0,
    textureStyle: {
      kind: 'uranus',
      base: '#8ce4dd',
      shade: '#67c9c3',
      highlight: '#b9f8f3'
    }
  },
  {
    name: 'Neptune',
    type: 'Ice giant',
    parent: 'Sun',
    distanceText: '4.50 billion km from the Sun',
    orbitalPeriodText: '164.8 years',
    rotationPeriodText: '16.1 hours',
    description:
      'Neptune is rendered as a deeper blue ice giant with soft banding so it remains distinguishable from Uranus.',
    visualRadius: 3.3,
    orbitRadius: 110,
    orbitDays: 60190,
    rotationHours: 16.1,
    initialAngle: 2.7,
    textureStyle: {
      kind: 'neptune',
      base: '#2f63d8',
      shade: '#2249a8',
      highlight: '#5a90ff'
    }
  }
];

function createNoise(random, amount = 1) {
  return (random() - 0.5) * amount;
}

function hashSeed(text) {
  let seed = 2166136261;
  for (let i = 0; i < text.length; i += 1) {
    seed ^= text.charCodeAt(i);
    seed = Math.imul(seed, 16777619);
  }
  return seed >>> 0;
}

function createSeededRandom(seedValue) {
  let seed = seedValue >>> 0;
  return function random() {
    seed = (1664525 * seed + 1013904223) >>> 0;
    return seed / 4294967296;
  };
}

function canvasTexture(size = 512) {
  const canvasEl = document.createElement('canvas');
  canvasEl.width = size;
  canvasEl.height = size;
  const ctx = canvasEl.getContext('2d');
  return { canvas: canvasEl, ctx, size };
}

function drawNoiseOverlay(ctx, size, random, count, alphaRange, colorFn) {
  for (let i = 0; i < count; i += 1) {
    const x = random() * size;
    const y = random() * size;
    const radius = random() * size * 0.04 + 1;
    ctx.globalAlpha = alphaRange[0] + random() * (alphaRange[1] - alphaRange[0]);
    ctx.fillStyle = colorFn(random, i);
    ctx.beginPath();
    ctx.arc(x, y, radius, 0, Math.PI * 2);
    ctx.fill();
  }
  ctx.globalAlpha = 1;
}

function drawBands(ctx, size, colors, wobble = 10) {
  for (let y = 0; y < size; y += 8) {
    const color = colors[Math.floor((y / 8) % colors.length)];
    ctx.fillStyle = color;
    const offset = Math.sin(y * 0.05) * wobble;
    ctx.fillRect(offset, y, size, 10);
  }
}

function drawCraterField(ctx, size, random, count, lightColor, shadowColor) {
  for (let i = 0; i < count; i += 1) {
    const x = random() * size;
    const y = random() * size;
    const radius = random() * size * 0.035 + 3;

    ctx.globalAlpha = 0.28;
    ctx.fillStyle = shadowColor;
    ctx.beginPath();
    ctx.arc(x + radius * 0.12, y + radius * 0.12, radius, 0, Math.PI * 2);
    ctx.fill();

    ctx.globalAlpha = 0.18;
    ctx.strokeStyle = lightColor;
    ctx.lineWidth = Math.max(1, radius * 0.08);
    ctx.beginPath();
    ctx.arc(x - radius * 0.08, y - radius * 0.08, radius * 0.82, 0, Math.PI * 2);
    ctx.stroke();
  }
  ctx.globalAlpha = 1;
}

function applySphereShading(ctx, size, edgeAlpha = 0.32) {
  const gradient = ctx.createRadialGradient(size * 0.35, size * 0.3, size * 0.08, size * 0.5, size * 0.5, size * 0.52);
  gradient.addColorStop(0, 'rgba(255,255,255,0.28)');
  gradient.addColorStop(0.5, 'rgba(255,255,255,0.04)');
  gradient.addColorStop(1, `rgba(0,0,0,${edgeAlpha})`);
  ctx.fillStyle = gradient;
  ctx.fillRect(0, 0, size, size);
}

function makeSunTexture(style, random) {
  const { canvas, ctx, size } = canvasTexture(768);
  const gradient = ctx.createRadialGradient(size * 0.42, size * 0.42, size * 0.04, size * 0.5, size * 0.5, size * 0.5);
  gradient.addColorStop(0, style.highlight);
  gradient.addColorStop(0.45, style.base);
  gradient.addColorStop(1, style.deep);
  ctx.fillStyle = gradient;
  ctx.fillRect(0, 0, size, size);

  for (let i = 0; i < 140; i += 1) {
    const y = (i / 140) * size;
    ctx.globalAlpha = 0.1 + random() * 0.12;
    ctx.fillStyle = random() > 0.5 ? 'rgba(255,220,120,0.9)' : 'rgba(255,120,20,0.9)';
    ctx.fillRect(0, y + createNoise(random, 12), size, 4 + random() * 10);
  }
  ctx.globalAlpha = 1;

  drawNoiseOverlay(ctx, size, random, 1000, [0.05, 0.16], () => 'rgba(255,240,160,1)');
  applySphereShading(ctx, size, 0.16);

  const texture = new THREE.CanvasTexture(canvas);
  texture.colorSpace = THREE.SRGBColorSpace;
  return texture;
}

function makeRockyTexture(style, random) {
  const { canvas, ctx, size } = canvasTexture();
  const base = ctx.createLinearGradient(0, 0, size, size);
  base.addColorStop(0, style.light);
  base.addColorStop(0.45, style.base);
  base.addColorStop(1, style.dark);
  ctx.fillStyle = base;
  ctx.fillRect(0, 0, size, size);

  drawNoiseOverlay(ctx, size, random, 1500, [0.06, 0.18], () => (random() > 0.45 ? style.dark : style.light));
  drawCraterField(ctx, size, random, 130, 'rgba(255,255,255,0.45)', style.crater);
  applySphereShading(ctx, size);

  const texture = new THREE.CanvasTexture(canvas);
  texture.colorSpace = THREE.SRGBColorSpace;
  return texture;
}

function makeCloudyTexture(style, random) {
  const { canvas, ctx, size } = canvasTexture();
  const base = ctx.createLinearGradient(0, 0, size, size);
  base.addColorStop(0, style.haze);
  base.addColorStop(0.5, style.base);
  base.addColorStop(1, style.swirl);
  ctx.fillStyle = base;
  ctx.fillRect(0, 0, size, size);

  for (let i = 0; i < 30; i += 1) {
    ctx.globalAlpha = 0.15 + random() * 0.15;
    ctx.fillStyle = i % 2 === 0 ? style.band : style.haze;
    ctx.beginPath();
    const y = (i / 30) * size + createNoise(random, 18);
    ctx.ellipse(size * 0.5, y, size * (0.3 + random() * 0.25), 12 + random() * 18, random(), 0, Math.PI * 2);
    ctx.fill();
  }
  ctx.globalAlpha = 1;
  drawNoiseOverlay(ctx, size, random, 800, [0.04, 0.12], () => style.swirl);
  applySphereShading(ctx, size, 0.22);

  const texture = new THREE.CanvasTexture(canvas);
  texture.colorSpace = THREE.SRGBColorSpace;
  return texture;
}

function makeEarthTexture(style, random) {
  const { canvas, ctx, size } = canvasTexture(768);
  const ocean = ctx.createLinearGradient(0, 0, size, size);
  ocean.addColorStop(0, style.shallow);
  ocean.addColorStop(0.45, style.ocean);
  ocean.addColorStop(1, '#173d85');
  ctx.fillStyle = ocean;
  ctx.fillRect(0, 0, size, size);

  for (let i = 0; i < 18; i += 1) {
    const x = random() * size;
    const y = random() * size;
    const rx = 40 + random() * 120;
    const ry = 20 + random() * 70;
    ctx.globalAlpha = 0.9;
    ctx.fillStyle = random() > 0.35 ? style.land : style.dryLand;
    ctx.beginPath();
    ctx.ellipse(x, y, rx, ry, random() * Math.PI, 0, Math.PI * 2);
    ctx.fill();
  }

  for (let i = 0; i < 22; i += 1) {
    const x = random() * size;
    const y = random() * size;
    const rx = 35 + random() * 90;
    const ry = 10 + random() * 30;
    ctx.globalAlpha = 0.22 + random() * 0.18;
    ctx.fillStyle = style.cloud;
    ctx.beginPath();
    ctx.ellipse(x, y, rx, ry, random() * Math.PI, 0, Math.PI * 2);
    ctx.fill();
  }

  ctx.globalAlpha = 1;
  drawNoiseOverlay(ctx, size, random, 900, [0.04, 0.1], () => 'rgba(255,255,255,0.9)');
  applySphereShading(ctx, size, 0.28);

  const texture = new THREE.CanvasTexture(canvas);
  texture.colorSpace = THREE.SRGBColorSpace;
  return texture;
}

function makeMarsTexture(style, random) {
  const { canvas, ctx, size } = canvasTexture();
  const base = ctx.createLinearGradient(0, 0, size, size);
  base.addColorStop(0, style.light);
  base.addColorStop(0.55, style.base);
  base.addColorStop(1, style.dark);
  ctx.fillStyle = base;
  ctx.fillRect(0, 0, size, size);

  drawNoiseOverlay(ctx, size, random, 1200, [0.06, 0.16], () => (random() > 0.5 ? style.dark : style.dust));
  for (let i = 0; i < 18; i += 1) {
    ctx.globalAlpha = 0.12 + random() * 0.12;
    ctx.fillStyle = style.dust;
    ctx.beginPath();
    ctx.ellipse(random() * size, random() * size, 50 + random() * 90, 18 + random() * 45, random(), 0, Math.PI * 2);
    ctx.fill();
  }
  ctx.globalAlpha = 1;
  applySphereShading(ctx, size, 0.3);

  const texture = new THREE.CanvasTexture(canvas);
  texture.colorSpace = THREE.SRGBColorSpace;
  return texture;
}

function makeJupiterTexture(style, random) {
  const { canvas, ctx, size } = canvasTexture(768);
  drawBands(ctx, size, [style.bandB, style.light, style.bandA, style.bandB, '#e8d7bf', '#c89b73'], 20);

  for (let i = 0; i < 140; i += 1) {
    ctx.globalAlpha = 0.04 + random() * 0.08;
    ctx.fillStyle = random() > 0.5 ? 'rgba(255,255,255,0.7)' : 'rgba(120,70,40,0.7)';
    ctx.fillRect(0, random() * size, size, 2 + random() * 5);
  }

  ctx.globalAlpha = 0.95;
  ctx.fillStyle = style.storm;
  ctx.beginPath();
  ctx.ellipse(size * 0.7, size * 0.6, size * 0.11, size * 0.07, -0.2, 0, Math.PI * 2);
  ctx.fill();
  ctx.globalAlpha = 1;

  applySphereShading(ctx, size, 0.24);

  const texture = new THREE.CanvasTexture(canvas);
  texture.colorSpace = THREE.SRGBColorSpace;
  return texture;
}

function makeSaturnTexture(style, random) {
  const { canvas, ctx, size } = canvasTexture(768);
  drawBands(ctx, size, [style.bandB, style.light, style.bandA, '#ccb07b', '#efe1bb'], 12);
  drawNoiseOverlay(ctx, size, random, 800, [0.03, 0.08], () => 'rgba(255,255,255,0.7)');
  applySphereShading(ctx, size, 0.24);

  const texture = new THREE.CanvasTexture(canvas);
  texture.colorSpace = THREE.SRGBColorSpace;
  return texture;
}

function makeIceTexture(style, random, deep = false) {
  const { canvas, ctx, size } = canvasTexture();
  const gradient = ctx.createLinearGradient(0, 0, size, size);
  gradient.addColorStop(0, style.highlight || style.base);
  gradient.addColorStop(0.55, style.base);
  gradient.addColorStop(1, style.shade);
  ctx.fillStyle = gradient;
  ctx.fillRect(0, 0, size, size);

  for (let i = 0; i < 70; i += 1) {
    ctx.globalAlpha = deep ? 0.06 + random() * 0.08 : 0.03 + random() * 0.05;
    ctx.fillStyle = 'rgba(255,255,255,0.8)';
    ctx.fillRect(0, random() * size, size, 2 + random() * 5);
  }
  ctx.globalAlpha = 1;
  applySphereShading(ctx, size, deep ? 0.26 : 0.2);

  const texture = new THREE.CanvasTexture(canvas);
  texture.colorSpace = THREE.SRGBColorSpace;
  return texture;
}

function createBodyTexture(body) {
  const cacheKey = body.name;
  if (textureCache.has(cacheKey)) {
    return textureCache.get(cacheKey);
  }

  const random = createSeededRandom(hashSeed(body.name));
  let texture;

  switch (body.textureStyle.kind) {
    case 'sun':
      texture = makeSunTexture(body.textureStyle, random);
      break;
    case 'rocky':
      texture = makeRockyTexture(body.textureStyle, random);
      break;
    case 'cloudy':
      texture = makeCloudyTexture(body.textureStyle, random);
      break;
    case 'earth':
      texture = makeEarthTexture(body.textureStyle, random);
      break;
    case 'moon':
      texture = makeRockyTexture(body.textureStyle, random);
      break;
    case 'mars':
      texture = makeMarsTexture(body.textureStyle, random);
      break;
    case 'jupiter':
      texture = makeJupiterTexture(body.textureStyle, random);
      break;
    case 'saturn':
      texture = makeSaturnTexture(body.textureStyle, random);
      break;
    case 'uranus':
      texture = makeIceTexture(body.textureStyle, random, false);
      break;
    case 'neptune':
      texture = makeIceTexture(body.textureStyle, random, true);
      break;
    default:
      texture = makeRockyTexture(
        {
          base: '#999999',
          dark: '#666666',
          light: '#cccccc',
          crater: '#555555'
        },
        random
      );
      break;
  }

  texture.anisotropy = renderer.capabilities.getMaxAnisotropy();
  textureCache.set(cacheKey, texture);
  return texture;
}

function createRingTexture(key = 'saturn-ring') {
  if (ringTextureCache.has(key)) {
    return ringTextureCache.get(key);
  }

  const ringCanvas = document.createElement('canvas');
  ringCanvas.width = 1024;
  ringCanvas.height = 64;
  const ringCtx = ringCanvas.getContext('2d');
  const gradient = ringCtx.createLinearGradient(0, 0, ringCanvas.width, 0);
  gradient.addColorStop(0, 'rgba(170,150,110,0.02)');
  gradient.addColorStop(0.12, 'rgba(210,190,150,0.45)');
  gradient.addColorStop(0.24, 'rgba(235,220,190,0.92)');
  gradient.addColorStop(0.38, 'rgba(190,168,130,0.55)');
  gradient.addColorStop(0.5, 'rgba(245,235,210,0.72)');
  gradient.addColorStop(0.64, 'rgba(200,180,145,0.52)');
  gradient.addColorStop(0.8, 'rgba(225,210,176,0.86)');
  gradient.addColorStop(1, 'rgba(170,150,110,0.02)');
  ringCtx.fillStyle = gradient;
  ringCtx.fillRect(0, 0, ringCanvas.width, ringCanvas.height);

  const random = createSeededRandom(hashSeed(key));
  for (let x = 0; x < ringCanvas.width; x += 4) {
    ringCtx.globalAlpha = 0.16 + random() * 0.28;
    ringCtx.fillStyle = random() > 0.5 ? 'rgba(255,255,255,0.45)' : 'rgba(120,95,60,0.35)';
    ringCtx.fillRect(x, 0, 2 + random() * 3, ringCanvas.height);
  }
  ringCtx.globalAlpha = 1;

  const texture = new THREE.CanvasTexture(ringCanvas);
  texture.colorSpace = THREE.SRGBColorSpace;
  texture.anisotropy = renderer.capabilities.getMaxAnisotropy();
  ringTextureCache.set(key, texture);
  return texture;
}

function getSphereGeometry(radius) {
  const segments = radius >= 5 ? 40 : radius >= 3 ? 32 : 24;
  const key = `${radius}-${segments}`;
  if (!sphereGeometryCache.has(key)) {
    sphereGeometryCache.set(key, new THREE.SphereGeometry(radius, segments, segments));
  }
  return sphereGeometryCache.get(key);
}

function createStarField(count = 1800, spread = 1800) {
  const geometry = new THREE.BufferGeometry();
  const positions = new Float32Array(count * 3);
  const colors = new Float32Array(count * 3);
  const color = new THREE.Color();

  for (let i = 0; i < count; i += 1) {
    const i3 = i * 3;
    const radius = THREE.MathUtils.randFloat(spread * 0.35, spread);
    const theta = THREE.MathUtils.randFloat(0, Math.PI * 2);
    const phi = Math.acos(THREE.MathUtils.randFloatSpread(2));

    positions[i3] = radius * Math.sin(phi) * Math.cos(theta);
    positions[i3 + 1] = radius * Math.cos(phi);
    positions[i3 + 2] = radius * Math.sin(phi) * Math.sin(theta);

    color.setHSL(
      THREE.MathUtils.randFloat(0.52, 0.62),
      THREE.MathUtils.randFloat(0.2, 0.6),
      THREE.MathUtils.randFloat(0.7, 1.0)
    );
    colors[i3] = color.r;
    colors[i3 + 1] = color.g;
    colors[i3 + 2] = color.b;
  }

  geometry.setAttribute('position', new THREE.BufferAttribute(positions, 3));
  geometry.setAttribute('color', new THREE.BufferAttribute(colors, 3));

  const material = new THREE.PointsMaterial({
    size: 3,
    sizeAttenuation: true,
    vertexColors: true,
    transparent: true,
    opacity: 0.95,
    depthWrite: false
  });

  return new THREE.Points(geometry, material);
}

function createOrbitLine(radius, color = 0x3f5d8f, segments = 180) {
  const points = [];
  for (let i = 0; i <= segments; i += 1) {
    const angle = (i / segments) * Math.PI * 2;
    points.push(new THREE.Vector3(Math.cos(angle) * radius, 0, Math.sin(angle) * radius));
  }
  const geometry = new THREE.BufferGeometry().setFromPoints(points);
  const material = new THREE.LineBasicMaterial({
    color,
    transparent: true,
    opacity: 0.72
  });
  return new THREE.LineLoop(geometry, material);
}

const stars = createStarField();
scene.add(stars);

const accentStars = createStarField(220, 1200);
accentStars.material.size = 4.5;
accentStars.material.opacity = 0.5;
scene.add(accentStars);

const solarSystemGroup = new THREE.Group();
scene.add(solarSystemGroup);

const bodyObjects = new Map();
const bodyDataByName = new Map(solarSystemBodies.map((body) => [body.name, body]));

function buildSolarSystem() {
  const sunBody = bodyDataByName.get('Sun');

  const sun = new THREE.Mesh(
    getSphereGeometry(sunBody.visualRadius),
    new THREE.MeshBasicMaterial({ map: createBodyTexture(sunBody) })
  );
  sun.userData.bodyName = 'Sun';
  solarSystemGroup.add(sun);
  bodyObjects.set('Sun', { body: sunBody, mesh: sun, pivot: solarSystemGroup });

  const glow = new THREE.Mesh(
    new THREE.SphereGeometry(sunBody.visualRadius * 1.38, 32, 32),
    new THREE.MeshBasicMaterial({
      color: 0xffb347,
      transparent: true,
      opacity: 0.16
    })
  );
  solarSystemGroup.add(glow);

  solarSystemBodies
    .filter((body) => body.name !== 'Sun' && body.parent === 'Sun')
    .forEach((body) => {
      const orbitPivot = new THREE.Group();
      orbitPivot.rotation.y = body.initialAngle || 0;
      solarSystemGroup.add(orbitPivot);

      const orbitLine = createOrbitLine(body.orbitRadius, body.name === 'Earth' ? 0x6f8fd1 : 0x3f5d8f);
      solarSystemGroup.add(orbitLine);

      const mesh = new THREE.Mesh(
        getSphereGeometry(body.visualRadius),
        new THREE.MeshStandardMaterial({
          map: createBodyTexture(body),
          roughness: 1,
          metalness: 0
        })
      );
      mesh.position.set(body.orbitRadius, 0, 0);
      mesh.userData.bodyName = body.name;
      orbitPivot.add(mesh);

      bodyObjects.set(body.name, {
        body,
        mesh,
        pivot: orbitPivot,
        orbitLine
      });

      if (body.name === 'Saturn') {
        const ringGeometry = new THREE.RingGeometry(body.visualRadius * 1.45, body.visualRadius * 2.55, 128);
        const ringMaterial = new THREE.MeshBasicMaterial({
          map: createRingTexture(),
          transparent: true,
          side: THREE.DoubleSide,
          opacity: 0.9
        });
        const rings = new THREE.Mesh(ringGeometry, ringMaterial);
        rings.rotation.x = -Math.PI / 2.45;
        mesh.add(rings);
      }
    });

  const earthBody = bodyDataByName.get('Earth');
  const moonBody = bodyDataByName.get('Moon');
  const earthObject = bodyObjects.get('Earth');

  const moonPivot = new THREE.Group();
  moonPivot.rotation.y = moonBody.initialAngle || 0;
  earthObject.mesh.add(moonPivot);

  const moonOrbitLine = createOrbitLine(moonBody.orbitRadius, 0x8d96b7, 120);
  earthObject.mesh.add(moonOrbitLine);

  const moonMesh = new THREE.Mesh(
    getSphereGeometry(moonBody.visualRadius),
    new THREE.MeshStandardMaterial({
      map: createBodyTexture(moonBody),
      roughness: 1,
      metalness: 0
    })
  );
  moonMesh.position.set(moonBody.orbitRadius, 0, 0);
  moonMesh.userData.bodyName = 'Moon';
  moonPivot.add(moonMesh);

  bodyObjects.set('Moon', {
    body: moonBody,
    mesh: moonMesh,
    pivot: moonPivot,
    orbitLine: moonOrbitLine,
    parentMesh: earthObject.mesh
  });

  const earthTiltMarkerMaterial = new THREE.LineBasicMaterial({ color: 0x9ec7ff, transparent: true, opacity: 0.8 });
  const tiltPoints = [new THREE.Vector3(0, -4.5, 0), new THREE.Vector3(0, 4.5, 0)];
  const tiltGeometry = new THREE.BufferGeometry().setFromPoints(tiltPoints);
  const tiltLine = new THREE.Line(tiltGeometry, earthTiltMarkerMaterial);
  tiltLine.rotation.z = THREE.MathUtils.degToRad(23.5);
  earthObject.mesh.add(tiltLine);

  const sunAxis = new THREE.AxesHelper(0);
  sun.add(sunAxis);

  if (earthBody) {
    document.getElementById('selected-name').textContent = earthBody.name;
    document.getElementById('selected-type').textContent = earthBody.type;
    document.getElementById('selected-distance').textContent = earthBody.distanceText;
    document.getElementById('selected-orbit').textContent = earthBody.orbitalPeriodText;
    document.getElementById('selected-rotation').textContent = earthBody.rotationPeriodText;
    document.getElementById('selected-description').textContent = earthBody.description;
  }
}

function populateBodySummary() {
  bodySummary.innerHTML = '';
  solarSystemBodies.forEach((body) => {
    const card = document.createElement('div');
    card.className = 'body-chip';
    card.innerHTML = `
      <strong>${body.name}</strong>
      <span>${body.type}${body.parent ? ` · parent: ${body.parent}` : ''}</span>
      <span>${body.distanceText}</span>
      <span>Orbit radius (scene): ${body.orbitRadius}</span>
      <span>Texture style: ${body.textureStyle.kind}</span>
    `;
    bodySummary.appendChild(card);
  });
}

buildSolarSystem();
populateBodySummary();

const clock = new THREE.Clock();

function animate() {
  const elapsed = clock.getElapsedTime();
  const simDays = elapsed * 12;

  stars.rotation.y = elapsed * 0.01;
  accentStars.rotation.y = -elapsed * 0.015;

  bodyObjects.forEach((entry, name) => {
    if (entry.body.orbitDays && entry.body.orbitDays > 0) {
      entry.pivot.rotation.y = (entry.body.initialAngle || 0) + (simDays / entry.body.orbitDays) * Math.PI * 2;
    }

    if (entry.body.rotationHours && entry.body.rotationHours !== 0) {
      const rotationDirection = entry.body.rotationHours < 0 ? -1 : 1;
      const rotationMagnitude = Math.max(0.002, 24 / Math.abs(entry.body.rotationHours)) * 0.01;
      entry.mesh.rotation.y = elapsed * rotationMagnitude * rotationDirection * Math.PI * 2;
    }

    if (name === 'Sun') {
      entry.mesh.rotation.y = elapsed * 0.08;
    }
  });

  renderer.render(scene, camera);
  requestAnimationFrame(animate);
}

function handleResize() {
  const width = container.clientWidth;
  const height = container.clientHeight;
  camera.aspect = width / height;
  camera.updateProjectionMatrix();
  renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
  renderer.setSize(width, height, false);
}

window.__SOLAR_SYSTEM_DATA__ = solarSystemBodies;
window.__SOLAR_TEXTURE_CACHE__ = textureCache;
window.__SOLAR_BODY_OBJECTS__ = bodyObjects;

window.addEventListener('resize', handleResize);
handleResize();
animate();

```

### README.md

```text
# SolarSystem3D

SolarSystem3D is a static Three.js educational solar system simulator benchmark. This step implements the full educational-scale body layout with visible planetary orbits, Earth’s Moon orbit, and Saturn’s rings.

## Current task status

This is task 3 of the benchmark sequence.

Added in this step:
- The Sun, all eight planets, and Earth’s Moon rendered in one coherent 3D scene
- Educational scale mode as the default layout so all bodies remain inspectable
- Visible orbit paths for every planet
- A visible Moon orbit around Earth
- Saturn’s ring system
- Stable procedural textures reused from the previous task
- Simplified orbital motion so the orbit layout reads clearly in the scene

## Run instructions

Because `app.js` uses browser ES module imports for Three.js, direct `file://` loading may be unreliable or blocked in some browsers.

Recommended run method:

```bash
cd app
python3 -m http.server 8000
```

Then open:

```text
http://localhost:8000/
```

A direct double-click open of `index.html` may work in some environments, but the simple static server is the reliable fallback.

## Dependency note

This app uses pinned CDN imports:
- `three@0.160.0`
- URL: `https://cdn.jsdelivr.net/npm/three@0.160.0/build/three.module.js`

No package manager, bundler, or backend is required.

## Features present in this step

- Static browser app with a Three.js scene
- Procedural star background
- Procedural textures for all required bodies
- Sun at the center of the system
- Correct planet order from the Sun:
  - Mercury
  - Venus
  - Earth
  - Mars
  - Jupiter
  - Saturn
  - Uranus
  - Neptune
- Earth’s Moon positioned as a moon of Earth
- Visible orbit paths for planets and the Moon
- Saturn rings
- Sidebar body summary for review

## Procedural texture approach

All body textures are generated in-browser with Canvas and converted to `THREE.CanvasTexture` objects.

Implemented texture ideas:
- **Sun**: warm radial gradient, layered streaks, bright granular variation
- **Mercury / Moon**: gray rocky base with crater-like marks
- **Venus**: pale yellow cloudy haze with soft swirls
- **Earth**: blue oceans, green-brown land masses, white cloud layers
- **Mars**: red-orange rocky texture with dusty variation
- **Jupiter**: horizontal bands and a storm-like red spot
- **Saturn**: soft beige bands plus a separate procedural ring texture
- **Uranus**: smooth cyan-blue ice giant appearance
- **Neptune**: deeper blue ice giant appearance with stronger shading

The textures are intentionally educational and stylized rather than photorealistic.

## Educational simplifications

This benchmark is an educational approximation, not a precision ephemeris.

Current simplifications include:
- Educational orbit radii rather than real distances
- Educational visual radii so smaller planets remain visible
- Circular coplanar orbits for readability
- Simplified orbital motion speeds
- A visible Moon orbit that stays visually associated with Earth

Realistic scale mode, seasons, labels, click focus, camera presets, and full simulation controls are added in later tasks.

## Accessibility notes

- Controls use semantic HTML elements such as `button`, `input`, and labels.
- Focus-visible styling is included for keyboard users.
- The 3D canvas is the first-screen primary content.
- The current step keeps future controls visible but disabled until those features are implemented.
- Textual body information remains available in the sidebar for reviewability.

## Performance notes

- One main `requestAnimationFrame` loop is used.
- Procedural textures are generated once and cached.
- Orbit lines are created once and reused.
- Geometry segment counts are moderate.
- Window resize updates renderer size and camera projection.

## Manual verification

1. Start a static server from the `app/` directory.
2. Open the app in a browser.
3. Confirm the simulator is visible immediately on first load.
4. Confirm the Sun, all eight planets, and Earth’s Moon are present.
5. Confirm the planets appear in the correct order moving outward from the Sun.
6. Confirm every body has a visible texture-like appearance.
7. Confirm Saturn has a visible ring system.
8. Confirm orbit paths are visible for all planets.
9. Confirm a smaller Moon orbit is visible around Earth.
10. Confirm the selected-body panel still shows Earth information.
11. Confirm the scene remains usable on desktop and narrower tablet or phone widths.
12. Confirm no audio plays and no backend setup is required.

```
