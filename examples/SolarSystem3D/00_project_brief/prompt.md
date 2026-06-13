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

