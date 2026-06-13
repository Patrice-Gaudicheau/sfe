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

