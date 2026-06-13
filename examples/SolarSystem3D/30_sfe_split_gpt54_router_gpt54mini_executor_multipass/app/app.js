import * as THREE from "https://cdn.jsdelivr.net/npm/three@0.160.0/build/three.module.js";
import { OrbitControls } from "https://cdn.jsdelivr.net/npm/three@0.160.0/examples/jsm/controls/OrbitControls.js";

const container = document.getElementById("scene-container");
const selectedBodyPanel = document.getElementById("selected-body-panel");
const speedRange = document.getElementById("speed-range");
const speedValue = document.getElementById("speed-value");
const playPauseButton = document.getElementById("play-pause-button");
const labelsToggle = document.getElementById("labels-toggle");
const orbitsToggle = document.getElementById("orbits-toggle");
const scaleToggle = document.getElementById("scale-toggle");

const scene = new THREE.Scene();
scene.background = new THREE.Color(0x050816);
scene.fog = new THREE.Fog(0x050816, 350, 1200);

const camera = new THREE.PerspectiveCamera(55, 1, 0.1, 5000);
camera.position.set(0, 120, 260);

const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: false });
renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
renderer.setSize(container.clientWidth || window.innerWidth, container.clientHeight || window.innerHeight);
container.appendChild(renderer.domElement);

const controls = new OrbitControls(camera, renderer.domElement);
controls.enableDamping = true;
controls.dampingFactor = 0.07;
controls.minDistance = 20;
controls.maxDistance = 1200;

const ambient = new THREE.AmbientLight(0x6f7da6, 0.55);
scene.add(ambient);

const sunLight = new THREE.PointLight(0xfff0cc, 3.2, 0, 2);
sunLight.position.set(0, 0, 0);
scene.add(sunLight);

const hemiLight = new THREE.HemisphereLight(0x8899ff, 0x090b14, 0.6);
scene.add(hemiLight);

const textureCanvas = document.createElement("canvas");
textureCanvas.width = 512;
textureCanvas.height = 256;
const textureContext = textureCanvas.getContext("2d");
const textureCache = new Map();
const bodiesByName = new Map();
const labels = [];
const orbitLines = [];
const selectableBodies = [];

function clamp(value, min, max) {
  return Math.min(max, Math.max(min, value));
}

function lerp(a, b, t) {
  return a + (b - a) * t;
}

function addNoise(imageData, strength, tint = [255, 255, 255]) {
  const { data } = imageData;
  for (let i = 0; i < data.length; i += 4) {
    const n = (Math.random() - 0.5) * strength;
    data[i] = clamp(data[i] + n * tint[0], 0, 255);
    data[i + 1] = clamp(data[i + 1] + n * tint[1], 0, 255);
    data[i + 2] = clamp(data[i + 2] + n * tint[2], 0, 255);
  }
}

function createCanvasTexture(key, drawFn) {
  if (textureCache.has(key)) {
    return textureCache.get(key);
  }
  textureContext.clearRect(0, 0, textureCanvas.width, textureCanvas.height);
  drawFn(textureContext, textureCanvas.width, textureCanvas.height);
  const texture = new THREE.CanvasTexture(textureCanvas.cloneNode(true));
  texture.colorSpace = THREE.SRGBColorSpace;
  texture.wrapS = THREE.RepeatWrapping;
  texture.wrapT = THREE.ClampToEdgeWrapping;
  texture.needsUpdate = true;
  textureCache.set(key, texture);
  return texture;
}

function drawBaseBands(ctx, width, height, colors, bandCount = 10, noiseStrength = 18) {
  const gradient = ctx.createLinearGradient(0, 0, 0, height);
  gradient.addColorStop(0, colors[0]);
  gradient.addColorStop(1, colors[colors.length - 1]);
  ctx.fillStyle = gradient;
  ctx.fillRect(0, 0, width, height);
  for (let i = 0; i < bandCount; i += 1) {
    const y = (i / bandCount) * height;
    ctx.fillStyle = colors[i % colors.length];
    ctx.globalAlpha = 0.2;
    ctx.fillRect(0, y, width, height / bandCount);
  }
  ctx.globalAlpha = 1;
  const imageData = ctx.getImageData(0, 0, width, height);
  addNoise(imageData, noiseStrength, [1, 1, 1]);
  ctx.putImageData(imageData, 0, 0);
}

function drawCraters(ctx, width, height, count = 38, tint = "rgba(255,255,255,0.15)") {
  for (let i = 0; i < count; i += 1) {
    const x = Math.random() * width;
    const y = Math.random() * height;
    const r = 4 + Math.random() * 26;
    ctx.beginPath();
    ctx.fillStyle = tint;
    ctx.arc(x, y, r, 0, Math.PI * 2);
    ctx.fill();
    ctx.beginPath();
    ctx.strokeStyle = "rgba(0,0,0,0.22)";
    ctx.lineWidth = 1;
    ctx.arc(x + 2, y + 2, r * 0.82, 0, Math.PI * 2);
    ctx.stroke();
  }
}

function drawPlanetTexture(style) {
  const key = JSON.stringify(style);
  return createCanvasTexture(key, (ctx, width, height) => {
    if (style.type === "sun") {
      const gradient = ctx.createRadialGradient(width * 0.45, height * 0.42, 10, width * 0.5, height * 0.5, width * 0.52);
      gradient.addColorStop(0, "#fff9cf");
      gradient.addColorStop(0.32, "#ffd36b");
      gradient.addColorStop(0.68, "#ff9f2e");
      gradient.addColorStop(1, "#a93f08");
      ctx.fillStyle = gradient;
      ctx.fillRect(0, 0, width, height);
      for (let i = 0; i < 120; i += 1) {
        ctx.beginPath();
        ctx.fillStyle = `rgba(255, ${160 + Math.random() * 80}, ${40 + Math.random() * 80}, ${0.08 + Math.random() * 0.16})`;
        ctx.arc(Math.random() * width, Math.random() * height, 8 + Math.random() * 36, 0, Math.PI * 2);
        ctx.fill();
      }
      return;
    }
    if (style.type === "earth") {
      ctx.fillStyle = "#123c8f";
      ctx.fillRect(0, 0, width, height);
      for (let i = 0; i < 20; i += 1) {
        ctx.beginPath();
        ctx.fillStyle = `rgba(40, 180, 90, ${0.25 + Math.random() * 0.25})`;
        ctx.ellipse(Math.random() * width, Math.random() * height, 18 + Math.random() * 40, 8 + Math.random() * 20, Math.random() * Math.PI, 0, Math.PI * 2);
        ctx.fill();
      }
      for (let i = 0; i < 16; i += 1) {
        ctx.beginPath();
        ctx.fillStyle = `rgba(255,255,255,${0.12 + Math.random() * 0.18})`;
        ctx.ellipse(Math.random() * width, Math.random() * height, 20 + Math.random() * 48, 4 + Math.random() * 16, Math.random() * Math.PI, 0, Math.PI * 2);
        ctx.fill();
      }
      drawCraters(ctx, width, height, 10, "rgba(255,255,255,0.04)");
      return;
    }
    if (style.type === "jupiter") {
      drawBaseBands(ctx, width, height, ["#e7c79a", "#c58d54", "#9e6231", "#e0b17f"], 16, 12);
      ctx.beginPath();
      ctx.fillStyle = "rgba(176, 96, 55, 0.95)";
      ctx.ellipse(width * 0.7, height * 0.6, 30, 18, -0.28, 0, Math.PI * 2);
      ctx.fill();
      return;
    }
    if (style.type === "saturn") {
      drawBaseBands(ctx, width, height, ["#e9d7a6", "#d0b57e", "#aa8a56", "#e3cc9f"], 12, 10);
      return;
    }
    if (style.type === "uranus") {
      drawBaseBands(ctx, width, height, ["#9be6ea", "#76cdd7", "#a7f0ef"], 8, 8);
      return;
    }
    if (style.type === "neptune") {
      drawBaseBands(ctx, width, height, ["#5b7fff", "#2551c8", "#2c3ea2"], 9, 9);
      return;
    }
    if (style.type === "mars") {
      drawBaseBands(ctx, width, height, ["#c55a2d", "#8f341c", "#d77b4a"], 8, 11);
      drawCraters(ctx, width, height, 24, "rgba(0,0,0,0.10)");
      return;
    }
    if (style.type === "venus") {
      drawBaseBands(ctx, width, height, ["#e9d59b", "#c9b06e", "#f3e3b8"], 7, 8);
      ctx.globalAlpha = 0.25;
      drawCraters(ctx, width, height, 14, "rgba(255,255,255,0.12)");
      ctx.globalAlpha = 1;
      return;
    }
    if (style.type === "moon" || style.type === "mercury") {
      drawBaseBands(ctx, width, height, ["#b5b2ad", "#8f8c87", "#d4d0cb"], 6, 8);
      drawCraters(ctx, width, height, style.type === "moon" ? 40 : 30, "rgba(255,255,255,0.10)");
      return;
    }
    drawBaseBands(ctx, width, height, ["#a6a09a", "#7a756d", "#bcb8b1"], 6, 8);
  });
}

function createLabelSprite(text) {
  const canvas = document.createElement("canvas");
  canvas.width = 256;
  canvas.height = 64;
  const ctx = canvas.getContext("2d");
  ctx.clearRect(0, 0, canvas.width, canvas.height);
  ctx.font = "bold 28px Inter, system-ui, sans-serif";
  ctx.textAlign = "center";
  ctx.textBaseline = "middle";
  ctx.fillStyle = "rgba(7, 12, 22, 0.72)";
  ctx.fillRect(16, 10, 224, 44);
  ctx.strokeStyle = "rgba(160, 194, 255, 0.45)";
  ctx.strokeRect(16, 10, 224, 44);
  ctx.fillStyle = "#ffffff";
  ctx.fillText(text, 128, 32);
  const texture = new THREE.CanvasTexture(canvas);
  texture.colorSpace = THREE.SRGBColorSpace;
  const material = new THREE.SpriteMaterial({ map: texture, transparent: true, depthTest: false });
  const sprite = new THREE.Sprite(material);
  sprite.scale.set(36, 9, 1);
  return sprite;
}

const bodyData = [
  {
    name: "Sun",
    type: "star",
    distanceFromSun: "0 AU",
    orbitalPeriod: "—",
    rotationPeriod: "Approx. 25 days at equator",
    description: "The central star of the system. Its bright surface is generated with warm layered canvas texture and animated glow.",
    visualRadius: 18,
    orbitRadius: 0,
    parent: null,
    textureStyle: { type: "sun" },
    color: 0xffc45e,
  },
  {
    name: "Mercury",
    type: "rocky planet",
    distanceFromSun: "Approx. 0.39 AU",
    orbitalPeriod: "Approx. 88 days",
    rotationPeriod: "Approx. 59 days",
    description: "Small, airless, cratered world with a gray mottled surface.",
    visualRadius: 2.6,
    orbitRadius: 32,
    parent: "Sun",
    textureStyle: { type: "mercury" },
    color: 0xb8b1a8,
  },
  {
    name: "Venus",
    type: "rocky planet",
    distanceFromSun: "Approx. 0.72 AU",
    orbitalPeriod: "Approx. 225 days",
    rotationPeriod: "Approx. 243 days, retrograde",
    description: "Hot cloud-covered planet with a pale yellow, hazy appearance.",
    visualRadius: 4.5,
    orbitRadius: 44,
    parent: "Sun",
    textureStyle: { type: "venus" },
    color: 0xe3c77f,
  },
  {
    name: "Earth",
    type: "rocky planet",
    distanceFromSun: "Approx. 1 AU",
    orbitalPeriod: "Approx. 365 days",
    rotationPeriod: "Approx. 24 hours",
    description: "Blue world with land, oceans, and clouds. Earth's axial tilt is shown with a marker for season explanations.",
    visualRadius: 4.8,
    orbitRadius: 60,
    parent: "Sun",
    textureStyle: { type: "earth" },
    color: 0x4a7bff,
  },
  {
    name: "Moon",
    type: "moon",
    distanceFromSun: "Approx. 1 AU",
    orbitalPeriod: "Approx. 27.3 days around Earth",
    rotationPeriod: "Approx. 27.3 days",
    description: "Earth's natural satellite. It stays visually associated with Earth and shows a cratered gray surface.",
    visualRadius: 1.6,
    orbitRadius: 10,
    parent: "Earth",
    textureStyle: { type: "moon" },
    color: 0xb4b4b4,
  },
  {
    name: "Mars",
    type: "rocky planet",
    distanceFromSun: "Approx. 1.52 AU",
    orbitalPeriod: "Approx. 687 days",
    rotationPeriod: "Approx. 24.6 hours",
    description: "Dusty red planet with darker surface variation and cratered texture.",
    visualRadius: 3.4,
    orbitRadius: 78,
    parent: "Sun",
    textureStyle: { type: "mars" },
    color: 0xd2683b,
  },
  {
    name: "Jupiter",
    type: "gas giant",
    distanceFromSun: "Approx. 5.2 AU",
    orbitalPeriod: "Approx. 11.9 years",
    rotationPeriod: "Approx. 9.9 hours",
    description: "Largest planet, shown with broad bands and a storm-like feature.",
    visualRadius: 11,
    orbitRadius: 108,
    parent: "Sun",
    textureStyle: { type: "jupiter" },
    color: 0xd8b38c,
  },
  {
    name: "Saturn",
    type: "gas giant",
    distanceFromSun: "Approx. 9.5 AU",
    orbitalPeriod: "Approx. 29.5 years",
    rotationPeriod: "Approx. 10.7 hours",
    description: "Banding is paired with a visible ring system made from a thin mesh.",
    visualRadius: 9.4,
    orbitRadius: 142,
    parent: "Sun",
    textureStyle: { type: "saturn" },
    color: 0xd9c28c,
  },
  {
    name: "Uranus",
    type: "ice giant",
    distanceFromSun: "Approx. 19.2 AU",
    orbitalPeriod: "Approx. 84 years",
    rotationPeriod: "Approx. 17.2 hours, retrograde",
    description: "Ice giant with a cyan-blue green tint and gentle banding.",
    visualRadius: 7.2,
    orbitRadius: 182,
    parent: "Sun",
    textureStyle: { type: "uranus" },
    color: 0x9be6ea,
  },
  {
    name: "Neptune",
    type: "ice giant",
    distanceFromSun: "Approx. 30 AU",
    orbitalPeriod: "Approx. 165 years",
    rotationPeriod: "Approx. 16.1 hours",
    description: "Deep blue ice giant with slightly stronger contrast than Uranus.",
    visualRadius: 7,
    orbitRadius: 216,
    parent: "Sun",
    textureStyle: { type: "neptune" },
    color: 0x4e6fff,
  },
];

function createOrbit(radius, color = 0x506080) {
  const points = Array.from({ length: 160 }, (_, index) => {
    const angle = (index / 160) * Math.PI * 2;
    return new THREE.Vector3(Math.cos(angle) * radius, 0, Math.sin(angle) * radius);
  });
  const line = new THREE.LineLoop(
    new THREE.BufferGeometry().setFromPoints(points),
    new THREE.LineBasicMaterial({ color, transparent: true, opacity: 0.55 })
  );
  scene.add(line);
  orbitLines.push(line);
  return line;
}

function createBody(body) {
  const geometry = new THREE.SphereGeometry(body.visualRadius, 32, 24);
  const material = new THREE.MeshStandardMaterial({
    map: drawPlanetTexture(body.textureStyle),
    color: body.color,
    roughness: 1,
    metalness: 0,
  });
  const mesh = new THREE.Mesh(geometry, material);
  mesh.name = body.name;
  mesh.userData.body = body;
  scene.add(mesh);
  bodiesByName.set(body.name, mesh);
  selectableBodies.push(mesh);
  const label = createLabelSprite(body.name);
  label.visible = true;
  label.position.set(0, body.visualRadius + 5, 0);
  mesh.add(label);
  labels.push(label);
  return mesh;
}

function createSaturnRings(saturn) {
  const ringGeometry = new THREE.RingGeometry(11, 18, 64);
  const ringMaterial = new THREE.MeshBasicMaterial({
    color: 0xdccca0,
    side: THREE.DoubleSide,
    transparent: true,
    opacity: 0.65,
  });
  const rings = new THREE.Mesh(ringGeometry, ringMaterial);
  rings.rotation.x = Math.PI / 2.15;
  saturn.add(rings);
}

function updateSelectedBodyPanel(body) {
  selectedBodyPanel.innerHTML = `
    <dl>
      <div><dt>Name</dt><dd>${body.name}</dd></div>
      <div><dt>Type</dt><dd>${body.type}</dd></div>
      <div><dt>Distance from Sun</dt><dd>${body.parent === "Earth" ? "Distance from Earth's surface: Approx. 384,400 km" : body.distanceFromSun}</dd></div>
      <div><dt>Orbital period</dt><dd>${body.orbitalPeriod}</dd></div>
      <div><dt>Rotation period</dt><dd>${body.rotationPeriod}</dd></div>
      <div><dt>Description</dt><dd>${body.description}</dd></div>
    </dl>
  `;
}

const bodies = bodyData.map(createBody);
const sun = bodiesByName.get("Sun");
const mercury = bodiesByName.get("Mercury");
const venus = bodiesByName.get("Venus");
const earth = bodiesByName.get("Earth");
const moon = bodiesByName.get("Moon");
const mars = bodiesByName.get("Mars");
const jupiter = bodiesByName.get("Jupiter");
const saturn = bodiesByName.get("Saturn");
const uranus = bodiesByName.get("Uranus");
const neptune = bodiesByName.get("Neptune");
createSaturnRings(saturn);

bodyData.forEach((body) => {
  if (body.orbitRadius > 0) {
    createOrbit(body.orbitRadius, body.name === "Moon" ? 0x74829b : 0x506080);
  }
});

const moonPivot = new THREE.Group();
earth.add(moonPivot);
moonPivot.add(moon);
moon.position.set(moon.userData?.body?.orbitRadius || 10, 0, 0);
moonPivot.rotation.x = THREE.MathUtils.degToRad(5);

const earthAxis = new THREE.Group();
earth.add(earthAxis);
const axisLine = new THREE.Line(
  new THREE.BufferGeometry().setFromPoints([new THREE.Vector3(0, -7, 0), new THREE.Vector3(0, 7, 0)]),
  new THREE.LineBasicMaterial({ color: 0xf7d77e })
);
axisLine.rotation.z = THREE.MathUtils.degToRad(23.5);
earthAxis.add(axisLine);

let isPlaying = true;
let timeScale = 1;
let labelsVisible = true;
let scaleMode = "educational";
let selectedBody = earth;
let targetFocus = earth.position.clone();
const earthOrbitAngle = { spring: 0, summer: Math.PI / 2, autumn: Math.PI, winter: (Math.PI * 3) / 2 };

function setSelectedBody(body) {
  selectedBody = body;
  updateSelectedBodyPanel(body.userData.body);
  targetFocus.copy(body.getWorldPosition(new THREE.Vector3()));
}

setSelectedBody(earth);

function makeStarfield(count = 2200) {
  const geometry = new THREE.BufferGeometry();
  const positions = new Float32Array(count * 3);
  for (let i = 0; i < count; i += 1) {
    const radius = 1800 + Math.random() * 1700;
    const theta = Math.random() * Math.PI * 2;
    const phi = Math.acos(THREE.MathUtils.randFloatSpread(2));
    const x = radius * Math.sin(phi) * Math.cos(theta);
    const y = radius * Math.sin(phi) * Math.sin(theta);
    const z = radius * Math.cos(phi);
    positions[i * 3] = x;
    positions[i * 3 + 1] = y;
    positions[i * 3 + 2] = z;
  }
  geometry.setAttribute("position", new THREE.BufferAttribute(positions, 3));
  const material = new THREE.PointsMaterial({ color: 0xdde7ff, size: 1.25, sizeAttenuation: true });
  const stars = new THREE.Points(geometry, material);
  scene.add(stars);
}

makeStarfield();

function applyScaleMode(mode) {
  scaleMode = mode;
  const distanceScale = mode === "educational" ? 1 : 0.72;
  const minRadius = mode === "educational" ? 1.6 : 1.0;
  bodyData.forEach((body) => {
    const mesh = bodiesByName.get(body.name);
    if (mesh) {
      mesh.scale.setScalar(Math.max(minRadius, body.visualRadius / 4));
      if (body.name !== "Sun") {
        mesh.position.x = body.orbitRadius * distanceScale;
      }
    }
  });
  updateOrbitGeometry(distanceScale);
}

function updateOrbitGeometry(distanceScale) {
  orbitLines.forEach((line, index) => {
    const body = bodyData.find((item) => item.orbitRadius > 0)[index];
    if (!body) return;
    const radius = body.orbitRadius * distanceScale;
    const points = Array.from({ length: 160 }, (_, pointIndex) => {
      const angle = (pointIndex / 160) * Math.PI * 2;
      return new THREE.Vector3(Math.cos(angle) * radius, 0, Math.sin(angle) * radius);
    });
    line.geometry.dispose();
    line.geometry = new THREE.BufferGeometry().setFromPoints(points);
  });
}

applyScaleMode("educational");

function resize() {
  const width = container.clientWidth;
  const height = container.clientHeight;
  camera.aspect = width / height;
  camera.updateProjectionMatrix();
  renderer.setSize(width, height);
}

window.addEventListener("resize", resize);

playPauseButton.addEventListener("click", () => {
  isPlaying = !isPlaying;
  playPauseButton.textContent = isPlaying ? "Pause" : "Play";
});

speedRange.addEventListener("input", () => {
  timeScale = Number(speedRange.value);
  speedValue.textContent = `${timeScale.toFixed(1)}×`;
});

labelsToggle.addEventListener("click", () => {
  labelsVisible = !labelsVisible;
  labels.forEach((label) => {
    label.visible = labelsVisible;
  });
  labelsToggle.textContent = labelsVisible ? "Hide labels" : "Show labels";
});

orbitsToggle.addEventListener("click", () => {
  const hidden = orbitLines[0]?.visible;
  orbitLines.forEach((line) => {
    line.visible = !hidden;
  });
  orbitsToggle.textContent = hidden ? "Show orbits" : "Hide orbits";
});

scaleToggle.addEventListener("click", () => {
  const nextMode = scaleMode === "educational" ? "realistic" : "educational";
  applyScaleMode(nextMode);
  scaleToggle.textContent = nextMode === "educational" ? "Realistic scale" : "Educational scale";
});

const presetButtons = [
  ["spring-equinox-button", "spring"],
  ["summer-solstice-button", "summer"],
  ["autumn-equinox-button", "autumn"],
  ["winter-solstice-button", "winter"],
];

presetButtons.forEach(([id, preset]) => {
  const button = document.getElementById(id);
  if (!button) return;
  button.addEventListener("click", () => {
    const angle = earthOrbitAngle[preset];
    const distanceScale = scaleMode === "educational" ? 1 : 0.72;
    earth.position.set(Math.cos(angle) * earth.userData.body.orbitRadius * distanceScale, 0, Math.sin(angle) * earth.userData.body.orbitRadius * distanceScale);
    moonPivot.rotation.y = angle;
    moonPivot.rotation.x = THREE.MathUtils.degToRad(5);
    targetFocus.copy(earth.position);
    setSelectedBody(earth);
  });
});

const cameraPreset = document.getElementById("camera-preset");
if (cameraPreset) {
  cameraPreset.addEventListener("change", () => {
    const presets = {
      overview: [0, 120, 260],
      inner: [0, 70, 150],
      "earth-moon": [28, 18, 46],
      outer: [0, 160, 360],
      sun: [0, 32, 70],
    };
    const [x, y, z] = presets[cameraPreset.value] || presets.overview;
    camera.position.set(x, y, z);
    controls.target.copy(selectedBody.getWorldPosition(new THREE.Vector3()));
  });
}

const raycaster = new THREE.Raycaster();
const pointer = new THREE.Vector2();
renderer.domElement.addEventListener("pointerdown", (event) => {
  const rect = renderer.domElement.getBoundingClientRect();
  pointer.x = ((event.clientX - rect.left) / rect.width) * 2 - 1;
  pointer.y = -(((event.clientY - rect.top) / rect.height) * 2 - 1);
  raycaster.setFromCamera(pointer, camera);
  const intersects = raycaster.intersectObjects(selectableBodies, false);
  if (intersects.length > 0) {
    const picked = intersects[0].object;
    setSelectedBody(picked);
    controls.target.copy(picked.getWorldPosition(new THREE.Vector3()));
  }
});

const clock = new THREE.Clock();
let simulationTime = 0;

function animate() {
  requestAnimationFrame(animate);
  const delta = clock.getDelta();
  if (isPlaying) {
    simulationTime += delta * timeScale;
    const distanceScale = scaleMode === "educational" ? 1 : 0.72;
    const bodiesWithOrbits = [mercury, venus, earth, mars, jupiter, saturn, uranus, neptune];
    bodiesWithOrbits.forEach((body, index) => {
      const period = body.userData.body.orbitalPeriod.includes("days") ? (index + 1) * 0.9 : (index + 1) * 2.4;
      const angle = simulationTime / period;
      body.position.x = Math.cos(angle) * body.userData.body.orbitRadius * distanceScale;
      body.position.z = Math.sin(angle) * body.userData.body.orbitRadius * distanceScale;
      body.rotation.y += delta * timeScale * 0.2;
    });
    moonPivot.rotation.y = simulationTime * 0.9;
    moon.rotation.y += delta * timeScale * 0.3;
    sun.rotation.y += delta * timeScale * 0.08;
    sunLight.intensity = 3.1 + Math.sin(performance.now() * 0.001) * 0.15;
    targetFocus.lerp(selectedBody.getWorldPosition(new THREE.Vector3()), 0.08);
    controls.target.lerp(targetFocus, 0.1);
  }
  labels.forEach((label) => {
    label.visible = labelsVisible;
  });
  if (selectedBody) {
    controls.target.lerp(selectedBody.getWorldPosition(new THREE.Vector3()), 0.08);
  }
  controls.update();
  renderer.render(scene, camera);
}

animate();
