import * as THREE from "https://cdn.jsdelivr.net/npm/three@0.160.0/build/three.module.js";
import { OrbitControls } from "https://cdn.jsdelivr.net/npm/three@0.160.0/examples/jsm/controls/OrbitControls.js";

const container = document.getElementById("sceneContainer");
const statusText = document.getElementById("statusText");

const bodyName = document.getElementById("bodyName");
const bodyType = document.getElementById("bodyType");
const bodyDistance = document.getElementById("bodyDistance");
const bodyOrbit = document.getElementById("bodyOrbit");
const bodyRotation = document.getElementById("bodyRotation");
const bodyDescription = document.getElementById("bodyDescription");

const playPauseButton = document.getElementById("playPauseButton");
const speedRange = document.getElementById("speedRange");
const labelsToggle = document.getElementById("labelsToggle");
const orbitsToggle = document.getElementById("orbitsToggle");
const scaleToggle = document.getElementById("scaleToggle");

const scene = new THREE.Scene();
scene.background = new THREE.Color(0x02040b);

const camera = new THREE.PerspectiveCamera(50, 1, 0.1, 4000);
camera.position.set(0, 24, 58);

const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
renderer.setSize(container.clientWidth, container.clientHeight, false);
container.appendChild(renderer.domElement);

const controls = new OrbitControls(camera, renderer.domElement);
controls.enableDamping = true;
controls.target.set(0, 0, 0);
controls.minDistance = 4;
controls.maxDistance = 1200;
controls.enablePan = true;
controls.enableZoom = true;
controls.screenSpacePanning = false;

scene.add(new THREE.AmbientLight(0xbfd5ff, 0.7));
const sunLight = new THREE.PointLight(0xffffff, 2.4, 0, 2);
sunLight.position.set(0, 0, 0);
scene.add(sunLight);
scene.add(new THREE.DirectionalLight(0xffffff, 0.4));

function createCanvasTexture(size, drawFn) {
  const canvas = document.createElement("canvas");
  canvas.width = size;
  canvas.height = size;
  const ctx = canvas.getContext("2d");
  drawFn(ctx, size);
  const texture = new THREE.CanvasTexture(canvas);
  texture.colorSpace = THREE.SRGBColorSpace;
  texture.anisotropy = 4;
  texture.needsUpdate = true;
  return texture;
}

function hashNoise(x, y, seed) {
  const value = Math.sin(x * 12.9898 + y * 78.233 + seed * 37.719) * 43758.5453;
  return value - Math.floor(value);
}

function paintCrateredSurface(ctx, size, palette, seed = 1) {
  ctx.fillStyle = palette.base;
  ctx.fillRect(0, 0, size, size);
  for (let i = 0; i < size * 28; i += 1) {
    const x = (hashNoise(i, seed, seed) * size) | 0;
    const y = (hashNoise(i + 2, seed + 1, seed) * size) | 0;
    const r = 1 + hashNoise(i + 3, seed + 2, seed) * 8;
    ctx.fillStyle = i % 4 === 0 ? palette.crater : palette.mottled;
    ctx.globalAlpha = 0.15 + hashNoise(i + 4, seed + 3, seed) * 0.5;
    ctx.beginPath();
    ctx.arc(x, y, r, 0, Math.PI * 2);
    ctx.fill();
  }
  ctx.globalAlpha = 1;
  for (let i = 0; i < size * 8; i += 1) {
    const x = hashNoise(i, seed + 7, seed) * size;
    const y = hashNoise(i + 1, seed + 11, seed) * size;
    const r = 1 + hashNoise(i + 2, seed + 13, seed) * 5;
    ctx.strokeStyle = palette.rim;
    ctx.globalAlpha = 0.18;
    ctx.beginPath();
    ctx.arc(x, y, r, 0, Math.PI * 2);
    ctx.stroke();
  }
  ctx.globalAlpha = 1;
}

function paintBands(ctx, size, colors, wobble = 0.08, seed = 1) {
  for (let y = 0; y < size; y += 1) {
    const band = Math.floor(((y / size) + Math.sin(y * wobble + seed) * 0.04) * colors.length * 1.8) % colors.length;
    ctx.fillStyle = colors[(band + colors.length) % colors.length];
    ctx.fillRect(0, y, size, 1);
  }
  for (let i = 0; i < size * 6; i += 1) {
    const x = hashNoise(i, seed + 5, seed) * size;
    const y = hashNoise(i + 8, seed + 6, seed) * size;
    const r = 1 + hashNoise(i + 9, seed + 7, seed) * 3;
    ctx.fillStyle = "rgba(255,255,255,0.08)";
    ctx.beginPath();
    ctx.arc(x, y, r, 0, Math.PI * 2);
    ctx.fill();
  }
}

function createTextureForStyle(style) {
  const size = 512;
  switch (style) {
    case "sun":
      return createCanvasTexture(size, (ctx) => {
        const grad = ctx.createRadialGradient(220, 200, 30, 256, 256, 260);
        grad.addColorStop(0, "#fff8ba");
        grad.addColorStop(0.45, "#ffcc54");
        grad.addColorStop(0.75, "#ff8c1a");
        grad.addColorStop(1, "#6f1800");
        ctx.fillStyle = grad;
        ctx.fillRect(0, 0, size, size);
        for (let i = 0; i < 1200; i += 1) {
          const x = hashNoise(i, 1, 1) * size;
          const y = hashNoise(i + 2, 2, 2) * size;
          const r = hashNoise(i + 3, 3, 3) * 7 + 1;
          const g = 160 + hashNoise(i + 4, 4, 4) * 80;
          const b = 40 + hashNoise(i + 5, 5, 5) * 40;
          const a = 0.06 + hashNoise(i + 6, 6, 6) * 0.18;
          ctx.fillStyle = `rgba(255, ${g}, ${b}, ${a})`;
          ctx.beginPath();
          ctx.arc(x, y, r, 0, Math.PI * 2);
          ctx.fill();
        }
      });
    case "earth":
      return createCanvasTexture(size, (ctx) => {
        ctx.fillStyle = "#1a4fd1";
        ctx.fillRect(0, 0, size, size);
        for (let i = 0; i < 360; i += 1) {
          ctx.fillStyle = i % 3 === 0 ? "#2f7a34" : "#8a6a40";
          ctx.globalAlpha = 0.18;
          ctx.beginPath();
          ctx.ellipse(
            hashNoise(i, 1, 3) * size,
            hashNoise(i + 1, 2, 4) * size,
            20 + hashNoise(i + 2, 3, 5) * 45,
            12 + hashNoise(i + 3, 4, 6) * 24,
            hashNoise(i + 4, 5, 7) * Math.PI,
            0,
            Math.PI * 2
          );
          ctx.fill();
        }
        ctx.globalAlpha = 1;
        for (let i = 0; i < 520; i += 1) {
          ctx.fillStyle = "rgba(255,255,255,0.11)";
          ctx.beginPath();
          ctx.arc(
            hashNoise(i, 9, 9) * size,
            hashNoise(i + 1, 10, 10) * size,
            2 + hashNoise(i + 2, 11, 11) * 6,
            0,
            Math.PI * 2
          );
          ctx.fill();
        }
      });
    case "venus":
      return createCanvasTexture(size, (ctx) => {
        ctx.fillStyle = "#d7c57e";
        ctx.fillRect(0, 0, size, size);
        paintBands(ctx, size, ["#e2d595", "#c8b56c", "#f0e3b3", "#b59f5a"], 0.05, 3);
      });
    case "mars":
      return createCanvasTexture(size, (ctx) => {
        ctx.fillStyle = "#a44520";
        ctx.fillRect(0, 0, size, size);
        paintCrateredSurface(ctx, size, { base: "#b34a23", crater: "#7c2f16", mottled: "#d17a45", rim: "#4c1d0c" }, 5);
      });
    case "mercury":
    case "moon":
      return createCanvasTexture(size, (ctx) => {
        paintCrateredSurface(ctx, size, {
          base: "#8e8a86",
          crater: "#5f5b58",
          mottled: "#b3ada7",
          rim: "#2f2d2b",
        }, style === "moon" ? 7 : 2);
      });
    case "jupiter":
      return createCanvasTexture(size, (ctx) => {
        paintBands(ctx, size, ["#d1b08b", "#b97f52", "#f0dfc5", "#a9643f", "#d6c19c"], 0.02, 11);
        ctx.fillStyle = "rgba(134, 84, 51, 0.85)";
        ctx.beginPath();
        ctx.ellipse(size * 0.66, size * 0.58, 52, 28, -0.2, 0, Math.PI * 2);
        ctx.fill();
      });
    case "saturn":
      return createCanvasTexture(size, (ctx) => {
        paintBands(ctx, size, ["#d7c29d", "#bfa474", "#efe1c4", "#ab8e5c"], 0.02, 13);
      });
    case "uranus":
      return createCanvasTexture(size, (ctx) => {
        ctx.fillStyle = "#8ed7d6";
        ctx.fillRect(0, 0, size, size);
        paintBands(ctx, size, ["#9de2e1", "#7bcac9", "#b7efef"], 0.03, 17);
      });
    case "neptune":
      return createCanvasTexture(size, (ctx) => {
        ctx.fillStyle = "#2358d6";
        ctx.fillRect(0, 0, size, size);
        paintBands(ctx, size, ["#2d61e8", "#1e46ba", "#4f79f3"], 0.03, 23);
      });
    default:
      return createCanvasTexture(size, (ctx) => {
        ctx.fillStyle = "#999";
        ctx.fillRect(0, 0, size, size);
      });
  }
}

const bodyData = [
  {
    name: "Sun",
    type: "star",
    distanceFromSun: 0,
    orbitalPeriod: 0,
    rotationPeriod: 25,
    description: "The Sun is the central star of the solar system and the source of almost all visible light and heat.",
    visualRadius: 4,
    orbitRadius: 0,
    textureStyle: "sun",
  },
  {
    name: "Mercury",
    type: "rocky planet",
    distanceFromSun: 57.9,
    orbitalPeriod: 88,
    rotationPeriod: 58.6,
    description: "Mercury is a small, heavily cratered rocky planet close to the Sun.",
    visualRadius: 0.6,
    orbitRadius: 8,
    textureStyle: "mercury",
  },
  {
    name: "Venus",
    type: "rocky planet",
    distanceFromSun: 108.2,
    orbitalPeriod: 224.7,
    rotationPeriod: 243,
    description: "Venus is a hot rocky planet with a thick, bright cloud layer.",
    visualRadius: 0.95,
    orbitRadius: 11,
    textureStyle: "venus",
  },
  {
    name: "Earth",
    type: "rocky planet",
    distanceFromSun: 149.6,
    orbitalPeriod: 365.25,
    rotationPeriod: 1,
    description: "Earth has blue oceans, land, clouds, and a 23.5° axial tilt that drives seasonal sunlight differences.",
    visualRadius: 1,
    orbitRadius: 14,
    textureStyle: "earth",
  },
  {
    name: "Moon",
    type: "moon",
    distanceFromSun: 149.6,
    orbitalPeriod: 27.3,
    rotationPeriod: 27.3,
    description: "Earth's Moon is a cratered natural satellite that stays visually associated with Earth.",
    visualRadius: 0.27,
    orbitRadius: 2.2,
    parent: "Earth",
    textureStyle: "moon",
  },
  {
    name: "Mars",
    type: "rocky planet",
    distanceFromSun: 227.9,
    orbitalPeriod: 687,
    rotationPeriod: 1.03,
    description: "Mars is a red, dusty rocky planet with visible dark surface variation.",
    visualRadius: 0.75,
    orbitRadius: 17,
    textureStyle: "mars",
  },
  {
    name: "Jupiter",
    type: "gas giant",
    distanceFromSun: 778.5,
    orbitalPeriod: 4331,
    rotationPeriod: 0.41,
    description: "Jupiter is the largest planet, with strong horizontal cloud bands and a long-lived storm.",
    visualRadius: 2.6,
    orbitRadius: 24,
    textureStyle: "jupiter",
  },
  {
    name: "Saturn",
    type: "gas giant",
    distanceFromSun: 1433.5,
    orbitalPeriod: 10747,
    rotationPeriod: 0.44,
    description: "Saturn is a gas giant with pale bands and a prominent ring system.",
    visualRadius: 2.2,
    orbitRadius: 31,
    textureStyle: "saturn",
  },
  {
    name: "Uranus",
    type: "ice giant",
    distanceFromSun: 2872.5,
    orbitalPeriod: 30589,
    rotationPeriod: 0.72,
    description: "Uranus is an ice giant with a cyan color and subtle banding.",
    visualRadius: 1.6,
    orbitRadius: 38,
    textureStyle: "uranus",
  },
  {
    name: "Neptune",
    type: "ice giant",
    distanceFromSun: 4495.1,
    orbitalPeriod: 59800,
    rotationPeriod: 0.67,
    description: "Neptune is a deep blue ice giant with faint texture variation.",
    visualRadius: 1.55,
    orbitRadius: 45,
    textureStyle: "neptune",
  },
];

const bodies = new Map();
const orbitGroup = new THREE.Group();
scene.add(orbitGroup);
const bodyGroup = new THREE.Group();
scene.add(bodyGroup);
const seasonGroup = new THREE.Group();
scene.add(seasonGroup);

function makeOrbit(radius, color = 0x4d6387) {
  const pts = [];
  for (let i = 0; i <= 180; i += 1) {
    const a = (i / 180) * Math.PI * 2;
    pts.push(new THREE.Vector3(Math.cos(a) * radius, 0, Math.sin(a) * radius));
  }
  return new THREE.Line(
    new THREE.BufferGeometry().setFromPoints(pts),
    new THREE.LineBasicMaterial({ color, transparent: true, opacity: 0.55 })
  );
}

function makeRing(inner, outer, color = 0xd9c89a) {
  const geometry = new THREE.RingGeometry(inner, outer, 96);
  const material = new THREE.MeshBasicMaterial({
    color,
    side: THREE.DoubleSide,
    transparent: true,
    opacity: 0.55,
  });
  const mesh = new THREE.Mesh(geometry, material);
  mesh.rotation.x = Math.PI / 2.2;
  return mesh;
}

function makeLabelSprite(text) {
  const canvas = document.createElement("canvas");
  canvas.width = 256;
  canvas.height = 64;
  const ctx = canvas.getContext("2d");
  ctx.fillStyle = "rgba(0,0,0,0.55)";
  ctx.fillRect(0, 0, 256, 64);
  ctx.fillStyle = "#eef4ff";
  ctx.font = "24px sans-serif";
  ctx.textAlign = "center";
  ctx.textBaseline = "middle";
  ctx.fillText(text, 128, 32);
  const texture = new THREE.CanvasTexture(canvas);
  texture.colorSpace = THREE.SRGBColorSpace;
  const material = new THREE.SpriteMaterial({ map: texture, transparent: true });
  const sprite = new THREE.Sprite(material);
  sprite.scale.set(5, 1.25, 1);
  sprite.renderOrder = 10;
  return sprite;
}

for (const data of bodyData) {
  const geometry = new THREE.SphereGeometry(data.visualRadius, 28, 20);
  const material = data.name === "Sun"
    ? new THREE.MeshBasicMaterial({ map: createTextureForStyle(data.textureStyle) })
    : new THREE.MeshStandardMaterial({ map: createTextureForStyle(data.textureStyle), roughness: 1, metalness: 0 });
  const mesh = new THREE.Mesh(geometry, material);
  mesh.userData.bodyName = data.name;
  bodyGroup.add(mesh);

  const label = makeLabelSprite(data.name);
  label.visible = true;
  mesh.add(label);

  bodies.set(data.name, { data, mesh, label });

  if (data.orbitRadius > 0) {
    const orbit = makeOrbit(data.orbitRadius);
    orbitGroup.add(orbit);
    data.orbitLine = orbit;
  }
}

const saturnRings = makeRing(3.0, 4.4);
bodies.get("Saturn").mesh.add(saturnRings);

const earth = bodies.get("Earth").mesh;
const moon = bodies.get("Moon").mesh;
const earthAxis = new THREE.Group();
const axisLine = new THREE.Line(
  new THREE.BufferGeometry().setFromPoints([
    new THREE.Vector3(0, -1.8, 0),
    new THREE.Vector3(0, 1.8, 0),
  ]),
  new THREE.LineBasicMaterial({ color: 0x9bd8ff })
);
earthAxis.add(axisLine);
earth.add(earthAxis);
earthAxis.rotation.z = THREE.MathUtils.degToRad(23.5);
const earthAxisNorth = new THREE.Mesh(
  new THREE.ConeGeometry(0.11, 0.45, 10),
  new THREE.MeshBasicMaterial({ color: 0xd7f0ff })
);
earthAxisNorth.position.y = 1.98;
earthAxis.add(earthAxisNorth);
const earthAxisSouth = new THREE.Mesh(
  new THREE.ConeGeometry(0.11, 0.45, 10),
  new THREE.MeshBasicMaterial({ color: 0xd7f0ff })
);
earthAxisSouth.rotation.x = Math.PI;
earthAxisSouth.position.y = -1.98;
earthAxis.add(earthAxisSouth);

const stars = new THREE.BufferGeometry();
const starCount = 1200;
const starPositions = new Float32Array(starCount * 3);
for (let i = 0; i < starCount; i += 1) {
  const radius = 450 + Math.random() * 500;
  const theta = Math.random() * Math.PI * 2;
  const phi = Math.acos(THREE.MathUtils.randFloatSpread(2));
  const x = radius * Math.sin(phi) * Math.cos(theta);
  const y = radius * Math.cos(phi);
  const z = radius * Math.sin(phi) * Math.sin(theta);
  starPositions.set([x, y, z], i * 3);
}
stars.setAttribute("position", new THREE.BufferAttribute(starPositions, 3));
const starField = new THREE.Points(
  stars,
  new THREE.PointsMaterial({ color: 0xffffff, size: 1.4, sizeAttenuation: true })
);
scene.add(starField);

let simulationRunning = true;
let timeSpeed = Number(speedRange.value);
let showLabels = labelsToggle.checked;
let showOrbits = orbitsToggle.checked;
let realisticScale = scaleToggle.checked;
let simTime = 0;
let seasonPreset = "spring";
let focusedBodyName = "Sun";
let focusTarget = new THREE.Vector3(0, 0, 0);
const scaleModes = {
  educational: {
    orbit: 1,
    planetMin: 0.65,
    moonMin: 0.22,
    sun: 4,
  },
  realistic: {
    orbit: 0.05,
    planetMin: 0.16,
    moonMin: 0.08,
    sun: 2.1,
  },
};

const seasonOffsets = { spring: 0, summer: Math.PI / 2, autumn: Math.PI, winter: Math.PI * 1.5 };

function updateInfoPanel(name) {
  const entry = bodies.get(name);
  if (!entry) return;
  const { data } = entry;
  bodyName.textContent = data.name;
  bodyType.textContent = data.type;
  bodyDistance.textContent = data.parent
    ? `${data.distanceFromSun} million km from Sun; orbiting ${data.parent}`
    : `${data.distanceFromSun} million km from Sun`;
  bodyOrbit.textContent = data.orbitalPeriod
    ? `${data.orbitalPeriod} days`
    : "—";
  bodyRotation.textContent = data.rotationPeriod
    ? `${data.rotationPeriod} days`
    : "—";
  bodyDescription.textContent = data.description;
}

function setBodyFocus(name) {
  const entry = bodies.get(name);
  if (!entry) return;
  focusedBodyName = name;
  updateInfoPanel(name);
  const pos = new THREE.Vector3();
  entry.mesh.getWorldPosition(pos);
  focusTarget.copy(pos);
  statusText.textContent = `Focused ${name}`;
}

function setSeasonPreset(name) {
  const earthBody = bodies.get("Earth");
  const moonBody = bodies.get("Moon");
  if (!earthBody || !moonBody) return;
  seasonPreset = name in seasonOffsets ? name : "spring";
  setBodyFocus("Earth");
  statusText.textContent = {
    spring: "Spring equinox preset selected",
    summer: "Summer solstice preset selected",
    autumn: "Autumn equinox preset selected",
    winter: "Winter solstice preset selected",
  }[seasonPreset];
}

const seasonOrder = ["spring", "summer", "autumn", "winter"];

function applyScaleMode() {
  const scale = realisticScale ? scaleModes.realistic : scaleModes.educational;
  const planetScale = realisticScale ? 0.45 : 1;
  const moonScale = realisticScale ? 0.35 : 1;
  bodies.forEach(({ data, mesh, label }) => {
    let targetRadius = data.visualRadius;
    if (data.name === "Sun") {
      targetRadius = scale.sun;
    } else if (data.name === "Moon") {
      targetRadius = Math.max(data.visualRadius * moonScale, scale.moonMin);
    } else {
      targetRadius = Math.max(data.visualRadius * planetScale, scale.planetMin);
    }
    mesh.scale.setScalar(targetRadius / data.visualRadius);
    if (data.orbitLine) {
      data.orbitLine.scale.setScalar(scale.orbit);
    }
    label.position.set(0, targetRadius + 0.35, 0);
  });
  earthAxis.scale.setScalar(realisticScale ? 0.8 : 1);
  saturnRings.scale.setScalar(realisticScale ? 0.7 : 1);
}

document.querySelectorAll("[data-camera]").forEach((button) => {
  button.addEventListener("click", () => {
    const cameraMode = button.dataset.camera;
    if (cameraMode === "overview") {
      camera.position.set(0, 28, 76);
      controls.target.set(0, 0, 0);
      focusTarget.set(0, 0, 0);
    } else if (cameraMode === "inner") {
      camera.position.set(0, 16, 28);
      controls.target.set(0, 0, 0);
      focusTarget.set(0, 0, 0);
    } else if (cameraMode === "earth-moon") {
      setBodyFocus("Earth");
      camera.position.set(18, 8, 18);
      const earthPos = new THREE.Vector3();
      bodies.get("Earth").mesh.getWorldPosition(earthPos);
      focusTarget.copy(earthPos);
    } else if (cameraMode === "outer") {
      camera.position.set(0, 34, 110);
      controls.target.set(0, 0, 0);
      focusTarget.set(0, 0, 0);
    } else if (cameraMode === "sun") {
      setBodyFocus("Sun");
      camera.position.set(0, 8, 12);
      focusTarget.set(0, 0, 0);
    }
    statusText.textContent = `Camera preset: ${button.textContent}`;
  });
});

document.querySelectorAll("[data-season]").forEach((button) => {
  button.addEventListener("click", () => setSeasonPreset(button.dataset.season));
});

playPauseButton.addEventListener("click", () => {
  simulationRunning = !simulationRunning;
  playPauseButton.textContent = simulationRunning ? "Pause" : "Play";
  playPauseButton.setAttribute("aria-pressed", String(simulationRunning));
  statusText.textContent = simulationRunning ? "Simulation resumed" : "Simulation paused";
});

speedRange.addEventListener("input", () => {
  timeSpeed = Number(speedRange.value);
  statusText.textContent = `Time speed set to ${timeSpeed.toFixed(1)}`;
});

labelsToggle.addEventListener("change", () => {
  showLabels = labelsToggle.checked;
  bodies.forEach(({ label }) => {
    label.visible = showLabels;
  });
  statusText.textContent = showLabels ? "Labels shown" : "Labels hidden";
});

orbitsToggle.addEventListener("change", () => {
  showOrbits = orbitsToggle.checked;
  orbitGroup.visible = showOrbits;
  statusText.textContent = showOrbits ? "Orbits shown" : "Orbits hidden";
});

scaleToggle.addEventListener("change", () => {
  realisticScale = scaleToggle.checked;
  applyScaleMode();
  statusText.textContent = realisticScale
    ? "Realistic scale mode enabled"
    : "Educational scale mode enabled";
});

renderer.domElement.addEventListener("pointerdown", (event) => {
  const rect = renderer.domElement.getBoundingClientRect();
  const pointer = new THREE.Vector2(
    ((event.clientX - rect.left) / rect.width) * 2 - 1,
    -(((event.clientY - rect.top) / rect.height) * 2 - 1)
  );
  const raycaster = new THREE.Raycaster();
  raycaster.setFromCamera(pointer, camera);
  const targets = [...bodies.values()].map((entry) => entry.mesh);
  const hits = raycaster.intersectObjects(targets, true);
  if (hits.length > 0) {
    const hitName = hits[0].object.userData.bodyName || hits[0].object.parent?.userData.bodyName;
    if (hitName) {
      setBodyFocus(hitName);
      const pos = new THREE.Vector3();
      bodies.get(hitName).mesh.getWorldPosition(pos);
      camera.position.lerpVectors(camera.position, pos.clone().add(new THREE.Vector3(6, 4, 6)), 0.25);
    }
  }
});

window.addEventListener("keydown", (event) => {
  const key = event.key.toLowerCase();
  if (event.key === " ") {
    event.preventDefault();
    playPauseButton.click();
  } else if (key === "l") {
    labelsToggle.click();
  } else if (key === "o") {
    orbitsToggle.click();
  } else if (key === "r") {
    scaleToggle.click();
  } else if (key === "s") {
    const currentIndex = seasonOrder.indexOf(seasonPreset);
    const nextSeason = seasonOrder[(currentIndex + 1) % seasonOrder.length];
    setSeasonPreset(nextSeason);
  } else if (key === "1") {
    document.querySelector('[data-camera="overview"]')?.click();
  } else if (key === "2") {
    document.querySelector('[data-camera="inner"]')?.click();
  } else if (key === "3") {
    document.querySelector('[data-camera="earth-moon"]')?.click();
  } else if (key === "4") {
    document.querySelector('[data-camera="outer"]')?.click();
  } else if (key === "5") {
    document.querySelector('[data-camera="sun"]')?.click();
  }
});

function onResize() {
  const { clientWidth, clientHeight } = container;
  camera.aspect = clientWidth / clientHeight;
  camera.updateProjectionMatrix();
  renderer.setSize(clientWidth, clientHeight, false);
}

window.addEventListener("resize", onResize);
onResize();

statusText.textContent = "Solar system data model and procedural textures loaded";
updateInfoPanel("Sun");
setSeasonPreset("spring");
applyScaleMode();

function updateEarthSeasonPlacement() {
  const earthEntry = bodies.get("Earth");
  const moonEntry = bodies.get("Moon");
  if (!earthEntry || !moonEntry) return;
  const orbitScale = realisticScale ? scaleModes.realistic.orbit : scaleModes.educational.orbit;
  const r = earthEntry.data.orbitRadius * orbitScale;
  const angle = seasonOffsets[seasonPreset] ?? 0;
  earthEntry.mesh.position.set(Math.cos(angle) * r, 0, Math.sin(angle) * r);
  moonEntry.mesh.position.set(
    earthEntry.mesh.position.x + Math.cos(simTime * 0.5 + 0.8) * moonEntry.data.orbitRadius,
    0,
    earthEntry.mesh.position.z + Math.sin(simTime * 0.5 + 0.8) * moonEntry.data.orbitRadius
  );
  const sunDirection = earthEntry.mesh.position.clone().multiplyScalar(-1).normalize();
  const axisDirection = new THREE.Vector3(0, 1, 0)
    .applyAxisAngle(new THREE.Vector3(0, 0, 1), THREE.MathUtils.degToRad(23.5));
  if (seasonPreset === "summer") {
    axisDirection.y = 0.92;
  } else if (seasonPreset === "winter") {
    axisDirection.y = 0.78;
  } else if (seasonPreset === "spring" || seasonPreset === "autumn") {
    axisDirection.y = 0.88;
  }
  earthAxis.quaternion.setFromUnitVectors(new THREE.Vector3(0, 1, 0), axisDirection.normalize());
  earthAxisNorth.position.set(0, 1.98, 0);
  earthAxisSouth.position.set(0, -1.98, 0);
  const sunAligned = sunDirection.dot(new THREE.Vector3(0, 0, 1));
  if (Math.abs(sunAligned) < 0.15) {
    earthAxisNorth.material.color.set(0xd7f0ff);
    earthAxisSouth.material.color.set(0xd7f0ff);
  }
}

function animate() {
  requestAnimationFrame(animate);

  if (simulationRunning) {
    simTime += timeSpeed * 0.01;
  }

  bodies.forEach(({ data, mesh }) => {
    if (data.name === "Sun") {
      mesh.rotation.y += 0.002;
      return;
    }
    if (data.name === "Moon") return;
    const angle = simTime / Math.max(data.orbitalPeriod, 1) * Math.PI * 2 + data.orbitRadius * 0.03;
    const orbitScale = realisticScale ? scaleModes.realistic.orbit : scaleModes.educational.orbit;
    mesh.position.set(Math.cos(angle) * data.orbitRadius * orbitScale, 0, Math.sin(angle) * data.orbitRadius * orbitScale);
    mesh.rotation.y += 0.002 / Math.max(data.rotationPeriod, 0.25);
  });

  updateEarthSeasonPlacement();
  const moonEntry = bodies.get("Moon");
  if (moonEntry) moonEntry.mesh.rotation.y += 0.01;

  bodies.forEach(({ label, mesh, data }) => {
    const distance = camera.position.distanceTo(mesh.getWorldPosition(new THREE.Vector3()));
    label.scale.setScalar(THREE.MathUtils.clamp(distance / 40, 0.9, 3));
    if (data.name === focusedBodyName) {
      label.material.opacity = 1;
    }
  });

  const target = focusTarget.clone();
  controls.target.lerp(target, 0.18);
  controls.update();
  renderer.render(scene, camera);
}

animate();
