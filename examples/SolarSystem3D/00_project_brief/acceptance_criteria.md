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

