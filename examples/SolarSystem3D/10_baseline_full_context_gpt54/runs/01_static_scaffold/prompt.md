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

## 1. Static scaffold and Three.js scene shell

Create the initial static app files under the scenario's `app/` directory: `index.html`, `styles.css`, `app.js`, and `README.md`. Establish the SolarSystem3D app shell, full-screen 3D canvas, primary control areas, selected-body panel placeholder, responsive layout, and baseline Three.js scene with camera, renderer, lighting, resize handling, and a procedural star background.

Document whether the app opens directly from `index.html` or requires a simple static server because of browser module loading rules.

## Current generated app files

### index.html

File does not exist yet.

### styles.css

File does not exist yet.

### app.js

File does not exist yet.

### README.md

File does not exist yet.
