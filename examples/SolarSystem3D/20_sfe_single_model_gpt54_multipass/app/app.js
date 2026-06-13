import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";

const sceneContainer = document.getElementById("sceneContainer");
const labelsLayer = document.getElementById("labelsLayer");
const playPauseButton = document.getElementById("playPauseButton");
const timeSpeedInput = document.getElementById("timeSpeed");
const timeSpeedValue = document.getElementById("timeSpeedValue");
const datePreset = document.getElementById("datePreset");
const seasonButtons = document.querySelectorAll("[data-season]");
const cameraPresetButtons = document.querySelectorAll("[data-camera]");
const bodyName = document.getElementById("bodyName");
const bodyType = document.getElementById("bodyType");
const bodyDistance = document.getElementById("bodyDistance");
const bodyOrbitPeriod = document.getElementById("bodyOrbitPeriod");
const bodyRotationPeriod = document.getElementById("bodyRotationPeriod");
const bodyDescription = document.getElementById("bodyDescription");
const selectionStatus = document.getElementById("selectionStatus");
const selectionAnnouncement = document.getElementById("selectionAnnouncement");
const toggleOrbitsInput = document.getElementById("toggleOrbits");
const toggleLabelsInput = document.getElementById("toggleLabels");
const scaleModeInput = document.getElementById("scaleMode");
const refocusButton = document.getElementById("refocusButton");

const BODY_DEFINITIONS = [
  {
    name: "Sun",
    type: "Star",
    approximateDistance: {
      valueAu: 0,
      label: "0 AU",
    },
    orbitalPeriod: "Center of the solar system",
    rotationPeriod: "Approx. 27 Earth days",
    description:
      "The Sun is the star at the center of the solar system. Its light and gravity drive the motion and energy balance of the planets.",
    visualRadius: 5.8,
    realisticVisualRadius: 3.4,
    minimumRealisticRadius: 3.4,
    orbitRadius: 0,
    realisticOrbitRadius: 0,
    orbitPeriodDays: 0,
    rotationSpeed: 0.12,
    initialAngle: 0,
    parent: null,
    orbitColor: "#ffc46b",
    labelOffset: 8.2,
    focusDistanceMultiplier: 5.2,
    textureStyle: {
      preset: "sun",
      palette: ["#fff6ba", "#ffc44d", "#ff8b24", "#8d2d00"],
      glowColor: "#ffb347",
      flareColor: "#fff4b0",
      flareBias: 0.72,
      noiseIntensity: 0.2,
      cellularCount: 180,
      streakCount: 42,
    },
  },
  {
    name: "Mercury",
    type: "Rocky planet",
    approximateDistance: {
      valueAu: 0.39,
      label: "Approx. 0.39 AU from the Sun",
    },
    orbitalPeriod: "88 Earth days",
    rotationPeriod: "58.6 Earth days",
    description:
      "Mercury is the smallest planet and the closest to the Sun. Its airless surface is heavily cratered and experiences extreme temperature swings.",
    visualRadius: 0.72,
    realisticVisualRadius: 0.12,
    minimumRealisticRadius: 0.22,
    orbitRadius: 10,
    realisticOrbitRadius: 11.5,
    orbitPeriodDays: 88,
    rotationSpeed: 0.08,
    initialAngle: 0.5,
    parent: null,
    orbitColor: "#8f8a82",
    labelOffset: 1.65,
    focusDistanceMultiplier: 8.4,
    textureStyle: {
      preset: "rocky",
      base: "#8f8a82",
      accent: "#6d6963",
      crater: "#55514b",
      highlight: "#b6afa4",
      shadow: "#4c4944",
      craterDensity: 170,
      noiseScale: 0.62,
      mottlingCount: 360,
      ridgeCount: 18,
    },
  },
  {
    name: "Venus",
    type: "Rocky planet",
    approximateDistance: {
      valueAu: 0.72,
      label: "Approx. 0.72 AU from the Sun",
    },
    orbitalPeriod: "225 Earth days",
    rotationPeriod: "243 Earth days (retrograde)",
    description:
      "Venus is wrapped in dense clouds and is the hottest planet in the solar system. It rotates very slowly and in the opposite direction to most planets.",
    visualRadius: 1.1,
    realisticVisualRadius: 0.3,
    minimumRealisticRadius: 0.3,
    orbitRadius: 14,
    realisticOrbitRadius: 16.8,
    orbitPeriodDays: 225,
    rotationSpeed: -0.035,
    initialAngle: 1.15,
    parent: null,
    orbitColor: "#d8bf78",
    labelOffset: 2.05,
    focusDistanceMultiplier: 7,
    textureStyle: {
      preset: "rocky",
      base: "#d8bf78",
      accent: "#c7a55d",
      crater: "#b18e49",
      highlight: "#f1e1a5",
      shadow: "#a88545",
      craterDensity: 40,
      cloudBands: 38,
      noiseScale: 0.35,
      hazeOpacity: 0.24,
      mottlingCount: 280,
      ridgeCount: 8,
    },
  },
  {
    name: "Earth",
    type: "Rocky planet",
    approximateDistance: {
      valueAu: 1,
      label: "Approx. 1.00 AU from the Sun",
    },
    orbitalPeriod: "365 Earth days",
    rotationPeriod: "24 hours",
    description:
      "Earth is the only known world with surface oceans and life. Its seasons are caused by axial tilt relative to sunlight, not by changing distance from the Sun.",
    visualRadius: 1.18,
    realisticVisualRadius: 0.32,
    minimumRealisticRadius: 0.32,
    orbitRadius: 18,
    realisticOrbitRadius: 24.5,
    orbitPeriodDays: 365,
    rotationSpeed: 0.22,
    initialAngle: 1.9,
    parent: null,
    orbitColor: "#4f96e8",
    axialTiltDeg: 23.5,
    labelOffset: 2.1,
    focusDistanceMultiplier: 6.5,
    textureStyle: {
      preset: "earth",
      ocean: "#2566c7",
      shallowWater: "#4f96e8",
      deepWater: "#163f8f",
      landA: "#5e8e43",
      landB: "#9e7b4e",
      landHighlight: "#7daf57",
      cloud: "#ffffff",
      cloudShadow: "#dbe8ff",
      ice: "#dceeff",
      cloudAmount: 130,
      landMasses: 28,
      currentCount: 120,
    },
  },
  {
    name: "Moon",
    type: "Moon",
    approximateDistance: {
      valueKm: 384400,
      label: "Approx. 384,400 km from Earth",
    },
    orbitalPeriod: "27.3 Earth days",
    rotationPeriod: "27.3 Earth days",
    description:
      "Earth's Moon is tidally locked, so the same side generally faces Earth. It has a dusty gray surface marked by craters and darker maria.",
    visualRadius: 0.34,
    realisticVisualRadius: 0.08,
    minimumRealisticRadius: 0.12,
    orbitRadius: 2.4,
    realisticOrbitRadius: 1.1,
    orbitPeriodDays: 27.3,
    rotationSpeed: 0.06,
    initialAngle: 0.8,
    parent: "Earth",
    orbitColor: "#aeb4bd",
    labelOffset: 1.05,
    focusDistanceMultiplier: 10,
    textureStyle: {
      preset: "moon",
      base: "#a5a7ab",
      accent: "#8a8d91",
      crater: "#696d73",
      highlight: "#d7d9dc",
      maria: "#6e7278",
      craterDensity: 150,
      mariaCount: 9,
      brightRayCount: 18,
    },
  },
  {
    name: "Mars",
    type: "Rocky planet",
    approximateDistance: {
      valueAu: 1.52,
      label: "Approx. 1.52 AU from the Sun",
    },
    orbitalPeriod: "687 Earth days",
    rotationPeriod: "24.6 hours",
    description:
      "Mars is a cold desert world with iron-rich dust that gives it a reddish color. It shows darker surface regions and bright polar caps.",
    visualRadius: 0.92,
    realisticVisualRadius: 0.17,
    minimumRealisticRadius: 0.24,
    orbitRadius: 23,
    realisticOrbitRadius: 37,
    orbitPeriodDays: 687,
    rotationSpeed: 0.19,
    initialAngle: 2.6,
    parent: null,
    orbitColor: "#cf7b4a",
    labelOffset: 1.95,
    focusDistanceMultiplier: 7.6,
    textureStyle: {
      preset: "mars",
      base: "#b55a33",
      accent: "#8f3b24",
      crater: "#6c2818",
      highlight: "#e2a16f",
      polarCap: "#f5e6d8",
      dust: "#cf7b4a",
      craterDensity: 90,
      darkRegionCount: 22,
      dustBandCount: 12,
    },
  },
  {
    name: "Jupiter",
    type: "Gas giant",
    approximateDistance: {
      valueAu: 5.2,
      label: "Approx. 5.20 AU from the Sun",
    },
    orbitalPeriod: "11.9 Earth years",
    rotationPeriod: "9.9 hours",
    description:
      "Jupiter is the largest planet. Its atmosphere shows strong horizontal bands, giant storms, and the famous Great Red Spot.",
    visualRadius: 3.5,
    realisticVisualRadius: 1.55,
    minimumRealisticRadius: 1.55,
    orbitRadius: 33,
    realisticOrbitRadius: 60,
    orbitPeriodDays: 4333,
    rotationSpeed: 0.3,
    initialAngle: 3.45,
    parent: null,
    orbitColor: "#d8b08c",
    labelOffset: 5.1,
    focusDistanceMultiplier: 4.9,
    textureStyle: {
      preset: "jupiter",
      bandColors: ["#d8b08c", "#f0d1a3", "#b97d59", "#edd9bc", "#a86747"],
      stormColor: "#c96c50",
      stormHighlight: "#efb39d",
      bandCount: 14,
      turbulence: 0.4,
      waveStrength: 14,
      eddyCount: 70,
    },
  },
  {
    name: "Saturn",
    type: "Gas giant",
    approximateDistance: {
      valueAu: 9.58,
      label: "Approx. 9.58 AU from the Sun",
    },
    orbitalPeriod: "29.5 Earth years",
    rotationPeriod: "10.7 hours",
    description:
      "Saturn is a gas giant known for its extensive ring system. Its pale atmosphere also shows gentle banding.",
    visualRadius: 3,
    realisticVisualRadius: 1.28,
    minimumRealisticRadius: 1.28,
    orbitRadius: 43,
    realisticOrbitRadius: 82,
    orbitPeriodDays: 10759,
    rotationSpeed: 0.27,
    initialAngle: 4.15,
    parent: null,
    orbitColor: "#d8c49b",
    labelOffset: 5.15,
    focusDistanceMultiplier: 5.6,
    textureStyle: {
      preset: "saturn",
      bandColors: ["#d8c49b", "#c9ae7b", "#ebddb8", "#b99862"],
      stormColor: "#c6a273",
      ringInnerColor: "#b8a68a",
      ringOuterColor: "#d8cdb4",
      ringOpacity: 0.78,
      bandCount: 11,
      turbulence: 0.18,
      waveStrength: 7,
      eddyCount: 28,
    },
  },
  {
    name: "Uranus",
    type: "Ice giant",
    approximateDistance: {
      valueAu: 19.2,
      label: "Approx. 19.20 AU from the Sun",
    },
    orbitalPeriod: "84 Earth years",
    rotationPeriod: "17.2 hours (retrograde)",
    description:
      "Uranus is an ice giant with a blue-green atmosphere colored by methane. It rotates on an extreme tilt compared with the other planets.",
    visualRadius: 2.2,
    realisticVisualRadius: 0.64,
    minimumRealisticRadius: 0.64,
    orbitRadius: 54,
    realisticOrbitRadius: 108,
    orbitPeriodDays: 30687,
    rotationSpeed: -0.18,
    initialAngle: 4.95,
    parent: null,
    orbitColor: "#7dd3d9",
    labelOffset: 3.7,
    focusDistanceMultiplier: 6.1,
    textureStyle: {
      preset: "ice",
      base: "#7dd3d9",
      accent: "#9be7ea",
      bandColor: "#6bc4cc",
      hazeColor: "#c7fbff",
      bandCount: 6,
      softness: 0.72,
      streakCount: 18,
    },
  },
  {
    name: "Neptune",
    type: "Ice giant",
    approximateDistance: {
      valueAu: 30.05,
      label: "Approx. 30.05 AU from the Sun",
    },
    orbitalPeriod: "164.8 Earth years",
    rotationPeriod: "16.1 hours",
    description:
      "Neptune is a deep blue ice giant with fast winds and storm systems. It is the most distant major planet in this model.",
    visualRadius: 2.15,
    realisticVisualRadius: 0.62,
    minimumRealisticRadius: 0.62,
    orbitRadius: 66,
    realisticOrbitRadius: 132,
    orbitPeriodDays: 60190,
    rotationSpeed: 0.17,
    initialAngle: 5.55,
    parent: null,
    orbitColor: "#4f80eb",
    labelOffset: 3.7,
    focusDistanceMultiplier: 6.4,
    textureStyle: {
      preset: "neptune",
      base: "#2958d6",
      accent: "#4f80eb",
      bandColor: "#1d43a8",
      hazeColor: "#9cc3ff",
      stormColor: "#bfd7ff",
      bandCount: 8,
      softness: 0.45,
      streakCount: 26,
    },
  },
];

const BODY_LOOKUP = new Map(BODY_DEFINITIONS.map((body) => [body.name, body]));
const tmpVector = new THREE.Vector3();
const tmpVectorB = new THREE.Vector3();
const tmpVectorC = new THREE.Vector3();
const tmpVectorD = new THREE.Vector3();
const tmpVectorE = new THREE.Vector3();
const raycaster = new THREE.Raycaster();
const pointer = new THREE.Vector2();

const SEASON_PRESET_ANGLES = {
  "spring-equinox": 0,
  "summer-solstice": Math.PI / 2,
  "autumn-equinox": Math.PI,
  "winter-solstice": (Math.PI * 3) / 2,
};

const SEASON_CONTEXT_COPY = {
  live: {
    title: "Live simulation position",
    detail:
      "Earth follows the normal animation-driven orbit based on the current simplified simulation time.",
  },
  "spring-equinox": {
    title: "Spring equinox",
    detail:
      "Earth is placed at a simplified equinox position where the axis is not leaning strongly toward or away from the Sun.",
  },
  "summer-solstice": {
    title: "Summer solstice",
    detail:
      "Earth is placed at a simplified solstice position where the Northern Hemisphere is tilted toward the Sun.",
  },
  "autumn-equinox": {
    title: "Autumn equinox",
    detail:
      "Earth is placed at the opposite simplified equinox position where the axis is again not leaning strongly toward or away from the Sun.",
  },
  "winter-solstice": {
    title: "Winter solstice",
    detail:
      "Earth is placed at the opposite simplified solstice position where the Northern Hemisphere is tilted away from the Sun.",
  },
};

const CAMERA_PRESETS = {
  overview: {
    label: "Overview",
    targetBodyName: "Sun",
    offset: new THREE.Vector3(0, 48, 130),
    minDistance: 68,
  },
  inner: {
    label: "Inner planets",
    targetBodyName: "Sun",
    offset: new THREE.Vector3(0, 22, 44),
    minDistance: 24,
  },
  earth: {
    label: "Earth and Moon",
    targetBodyName: "Earth",
    offset: new THREE.Vector3(8, 4.5, 9),
    minDistance: 5,
  },
  outer: {
    label: "Outer planets",
    targetBodyName: "Jupiter",
    offset: new THREE.Vector3(24, 18, 58),
    minDistance: 32,
  },
  sun: {
    label: "Sun view",
    targetBodyName: "Sun",
    offset: new THREE.Vector3(0, 11, 22),
    minDistance: 12,
  },
};

const state = {
  isPlaying: true,
  timeSpeed: Number(timeSpeedInput.value),
  selectedSeason: "live",
  selectedBodyName: "Sun",
  scaleMode: "educational",
  showOrbits: toggleOrbitsInput?.checked ?? true,
  showLabels: toggleLabelsInput?.checked ?? true,
  simulationDays: 0,
  activeCameraPreset: "overview",
};

const textureCache = new Map();
const bodyRecords = new Map();
const orbitLines = [];
const domLabels = [];
const selectableMeshes = [];

const cameraFocusState = {
  currentTarget: new THREE.Vector3(0, 0, 0),
  desiredTarget: new THREE.Vector3(0, 0, 0),
  desiredOffset: new THREE.Vector3(0, 34, 102),
  isAutoFraming: false,
  lerpStrength: 5.2,
};

const renderer = new THREE.WebGLRenderer({
  antialias: true,
  alpha: false,
  powerPreference: "high-performance",
});
renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
renderer.setSize(sceneContainer.clientWidth, sceneContainer.clientHeight);
renderer.outputColorSpace = THREE.SRGBColorSpace;
sceneContainer.appendChild(renderer.domElement);

const scene = new THREE.Scene();
scene.background = new THREE.Color(0x02050d);

const camera = new THREE.PerspectiveCamera(
  52,
  sceneContainer.clientWidth / sceneContainer.clientHeight,
  0.1,
  2400
);
camera.position.set(0, 34, 102);
camera.lookAt(0, 0, 0);

const controls = new OrbitControls(camera, renderer.domElement);
controls.enableDamping = true;
controls.dampingFactor = 0.07;
controls.enablePan = true;
controls.enableZoom = true;
controls.minDistance = 2;
controls.maxDistance = 900;
controls.target.set(0, 0, 0);
controls.update();

controls.addEventListener("start", () => {
  cameraFocusState.isAutoFraming = false;
});

cameraFocusState.currentTarget.copy(controls.target);
cameraFocusState.desiredTarget.copy(controls.target);
cameraFocusState.desiredOffset.copy(camera.position).sub(controls.target);

const ambientLight = new THREE.AmbientLight(0x8aa4ff, 0.7);
scene.add(ambientLight);

const sunLight = new THREE.PointLight(0xffe1a8, 3.1, 0, 2);
sunLight.position.set(0, 0, 0);
scene.add(sunLight);

const rimLight = new THREE.DirectionalLight(0x7aa2ff, 0.8);
rimLight.position.set(-40, 20, 25);
scene.add(rimLight);

const solarGroup = new THREE.Group();
scene.add(solarGroup);

const starfield = createStarfield(1800, 900);
scene.add(starfield);

buildSolarSystem();
setScaleMode("educational");
setOrbitVisibility(state.showOrbits);
setLabelVisibility(state.showLabels);
updateSelectedLabelState();
syncPlayPauseButton();
updateTimeSpeedLabel();
applyCameraPreset("overview", false);

const clock = new THREE.Clock();

function animate() {
  requestAnimationFrame(animate);

  const delta = Math.min(clock.getDelta(), 0.05);

  if (state.isPlaying && state.timeSpeed > 0) {
    advanceSimulation(delta);
  }

  updateCameraFocus(delta);
  controls.update();
  updateDomLabels();
  renderer.render(scene, camera);
}

function advanceSimulation(deltaSeconds) {
  const simulatedDaysPerSecond = getSimulatedDaysPerSecond(state.timeSpeed);
  state.simulationDays += deltaSeconds * simulatedDaysPerSecond;
  updateBodyTransforms();
}

function getSimulatedDaysPerSecond(speedValue) {
  if (speedValue <= 0) {
    return 0;
  }

  const normalized = speedValue / 100;
  return 2 + normalized * normalized * 2200;
}

function buildSolarSystem() {
  BODY_DEFINITIONS.forEach((body) => {
    const record = createBodyRecord(body);
    bodyRecords.set(body.name, record);

    if (!body.parent) {
      solarGroup.add(record.orbitGroup);
    }

    if (record.orbitLine) {
      orbitLines.push(record.orbitLine);
    }

    if (record.domLabel) {
      domLabels.push(record.domLabel);
    }

    selectableMeshes.push(record.mesh);
  });

  updateBodyTransforms();
}

function createBodyRecord(body) {
  const orbitGroup = new THREE.Group();
  orbitGroup.name = `${body.name}-orbit-group`;

  if (body.parent) {
    const parentRecord = bodyRecords.get(body.parent);
    if (parentRecord) {
      parentRecord.mesh.add(orbitGroup);
    }
  }

  const geometryRadius = body.name === "Sun" ? body.visualRadius : 1;
  const sphereGeometry = new THREE.SphereGeometry(
    geometryRadius,
    body.name === "Sun" ? 48 : 28,
    body.name === "Sun" ? 48 : 28
  );

  const materialOptions = {
    map: getBodyTexture(body),
    roughness: body.name === "Sun" ? 0.84 : 1,
    metalness: 0,
  };

  if (body.name === "Sun") {
    materialOptions.emissive = new THREE.Color(0xffa83a);
    materialOptions.emissiveIntensity = 1.2;
  }

  const mesh = new THREE.Mesh(
    sphereGeometry,
    new THREE.MeshStandardMaterial(materialOptions)
  );
  mesh.userData.body = body;
  mesh.userData.isSelectableBody = true;
  orbitGroup.add(mesh);

  let ringMesh = null;
  if (body.name === "Saturn") {
    ringMesh = createSaturnRings(body);
    mesh.add(ringMesh);
  }

  let tiltMarker = null;
  if (body.name === "Earth") {
    tiltMarker = createAxialTiltMarker(body);
    mesh.add(tiltMarker);
  }

  const orbitLine = createOrbitPath(body);
  const domLabel = createBodyDomLabel(body);

  return {
    body,
    orbitGroup,
    mesh,
    ringMesh,
    tiltMarker,
    orbitLine,
    domLabel,
    currentOrbitRadius: 0,
    currentVisualRadius: body.name === "Sun" ? body.visualRadius : 1,
    currentRingScale: 1,
    currentTiltScale: 1,
    spinAngle: 0,
  };
}

function updateBodyTransforms() {
  BODY_DEFINITIONS.forEach((body) => {
    const record = bodyRecords.get(body.name);
    if (!record) {
      return;
    }

    const rotationSpeed = body.rotationSpeed || 0.1;
    record.spinAngle =
      state.simulationDays * rotationSpeed * 0.08 +
      (body.initialAngle || 0) * 0.25;
    record.mesh.rotation.y = record.spinAngle;

    if (body.name === "Sun") {
      record.orbitGroup.position.set(0, 0, 0);
      return;
    }

    const orbitalAngle = getOrbitalAngle(body);
    const orbitRadius = record.currentOrbitRadius;
    record.orbitGroup.position.set(
      Math.cos(orbitalAngle) * orbitRadius,
      0,
      Math.sin(orbitalAngle) * orbitRadius
    );
  });

  refreshCameraFocusTarget();
}

function getOrbitalAngle(body) {
  if (
    body.name === "Earth" &&
    state.selectedSeason !== "live" &&
    SEASON_PRESET_ANGLES[state.selectedSeason] !== undefined
  ) {
    return SEASON_PRESET_ANGLES[state.selectedSeason];
  }

  return (
    (body.initialAngle || 0) +
    (state.simulationDays / body.orbitPeriodDays) * Math.PI * 2
  );
}

function setScaleMode(mode) {
  state.scaleMode = mode;

  BODY_DEFINITIONS.forEach((body) => {
    const record = bodyRecords.get(body.name);
    if (!record) {
      return;
    }

    const orbitRadius =
      mode === "realistic"
        ? body.realisticOrbitRadius ?? body.orbitRadius
        : body.orbitRadius;

    const rawVisualRadius =
      mode === "realistic"
        ? body.realisticVisualRadius ?? body.visualRadius
        : body.visualRadius;

    const visualRadius =
      mode === "realistic"
        ? Math.max(
            body.minimumRealisticRadius ?? rawVisualRadius,
            rawVisualRadius
          )
        : body.visualRadius;

    record.currentOrbitRadius = orbitRadius;
    record.currentVisualRadius = visualRadius;

    if (body.name === "Sun") {
      record.mesh.scale.setScalar(visualRadius / body.visualRadius);
      record.orbitGroup.position.set(0, 0, 0);
    } else {
      record.mesh.scale.setScalar(visualRadius);
    }

    if (record.orbitLine) {
      updateOrbitPath(record.orbitLine, orbitRadius);
    }

    if (record.ringMesh) {
      const diameterRatio = visualRadius / body.visualRadius;
      const ringScaleBase =
        mode === "realistic"
          ? Math.max(0.75, diameterRatio)
          : Math.max(1, diameterRatio);
      record.currentRingScale = ringScaleBase;
      record.ringMesh.scale.set(ringScaleBase, ringScaleBase, ringScaleBase);
    }

    if (record.tiltMarker) {
      const tiltScale =
        mode === "realistic"
          ? Math.max(0.75, visualRadius / body.visualRadius)
          : Math.max(1, visualRadius / body.visualRadius);
      record.currentTiltScale = tiltScale;
      record.tiltMarker.scale.setScalar(tiltScale);
    }
  });

  if (scaleModeInput) {
    scaleModeInput.checked = mode === "realistic";
  }

  updateBodyTransforms();

  if (state.activeCameraPreset) {
    applyCameraPreset(state.activeCameraPreset, false);
  } else {
    frameBody(state.selectedBodyName, false);
  }
}

function formatTimeSpeedLabel(speedValue) {
  if (speedValue <= 0) {
    return "Paused";
  }

  const simulatedDaysPerSecond = getSimulatedDaysPerSecond(speedValue);

  if (simulatedDaysPerSecond < 10) {
    return `${simulatedDaysPerSecond.toFixed(1)} d/s`;
  }

  if (simulatedDaysPerSecond < 1000) {
    return `${Math.round(simulatedDaysPerSecond)} d/s`;
  }

  return `${(simulatedDaysPerSecond / 365).toFixed(1)} y/s`;
}

function updateTimeSpeedLabel() {
  state.timeSpeed = Number(timeSpeedInput.value);
  const label = formatTimeSpeedLabel(state.timeSpeed);
  timeSpeedValue.value = label;
  timeSpeedValue.textContent = label;
}

function syncPlayPauseButton() {
  playPauseButton.textContent = state.isPlaying ? "Pause" : "Play";
  playPauseButton.setAttribute("aria-pressed", String(state.isPlaying));
  playPauseButton.setAttribute(
    "aria-label",
    state.isPlaying ? "Pause simulation" : "Play simulation"
  );
}

function updatePlayPause() {
  state.isPlaying = !state.isPlaying;
  syncPlayPauseButton();
}

function applySeasonSelection(value) {
  state.selectedSeason = value;
  datePreset.value = value;
  updateBodyTransforms();

  const selectedBody =
    BODY_LOOKUP.get(state.selectedBodyName) || BODY_DEFINITIONS[0];
  updateSelectedBodyInfo(selectedBody, value);
  refreshCameraFocusTarget();
}

function getDistanceLabel(body) {
  if (body.parent === "Earth") {
    return `${body.approximateDistance.label} · Parent body: Earth`;
  }

  return body.approximateDistance.label;
}

function getSelectionStatusText(body, seasonValue = state.selectedSeason) {
  const context = getSeasonContextCopy(seasonValue);

  if (seasonValue === "live") {
    return `Focused: ${body.name}`;
  }

  if (body.name === "Earth") {
    return `Focused: Earth · ${context.title}`;
  }

  if (body.name === "Moon") {
    return `Focused: Moon · Earth in ${context.title}`;
  }

  return `Focused: ${body.name} · ${context.title}`;
}

function getSelectionAnnouncementText(body, seasonValue = state.selectedSeason) {
  const context = getSeasonContextCopy(seasonValue);

  if (seasonValue === "live") {
    return `Selected body is ${body.name}.`;
  }

  if (body.name === "Earth") {
    return `Selected body is Earth. Current season context is ${context.title}.`;
  }

  if (body.name === "Moon") {
    return `Selected body is Moon. Earth is shown in the ${context.title} teaching position.`;
  }

  return `Selected body is ${body.name}. Current season context is ${context.title}.`;
}

function updateSelectedBodyInfo(body, seasonValue = "live") {
  state.selectedBodyName = body.name;
  bodyName.textContent = body.name;
  bodyType.textContent = body.type;
  bodyDistance.textContent = getDistanceLabel(body);
  bodyOrbitPeriod.textContent = body.orbitalPeriod;
  bodyRotationPeriod.textContent = body.rotationPeriod;

  if (selectionStatus) {
    selectionStatus.textContent = getSelectionStatusText(body, seasonValue);
  }

  if (selectionAnnouncement) {
    selectionAnnouncement.textContent = getSelectionAnnouncementText(
      body,
      seasonValue
    );
  }

  bodyDescription.textContent = buildSelectedBodyDescription(body, seasonValue);
  updateSelectedLabelState();
}

function buildSelectedBodyDescription(body, seasonValue) {
  const baseDescription = body.description;
  const context = getSeasonContextCopy(seasonValue);

  if (seasonValue === "live") {
    if (body.name === "Earth") {
      return `${baseDescription} Current context: ${context.title}. ${context.detail}`;
    }

    return baseDescription;
  }

  if (body.name === "Earth") {
    return `${baseDescription} Current context: ${context.title}. ${context.detail}`;
  }

  if (body.name === "Moon") {
    return `${baseDescription} Current context: ${context.title}. Earth is moved to a simplified teaching position, and the Moon remains visually associated with Earth because its orbit group is parented to Earth in the scene graph.`;
  }

  return `${baseDescription} Current context: ${context.title}. ${context.detail} Other bodies continue using the live simplified animation model while Earth is temporarily shown at the selected teaching position.`;
}

function getSeasonContextCopy(seasonValue) {
  return SEASON_CONTEXT_COPY[seasonValue] || SEASON_CONTEXT_COPY.live;
}

function updateSelectedLabelState() {
  domLabels.forEach((labelElement) => {
    labelElement.classList.toggle(
      "is-selected",
      labelElement.dataset.bodyName === state.selectedBodyName
    );
    if (labelElement.dataset.bodyName === state.selectedBodyName) {
      labelElement.setAttribute("aria-pressed", "true");
      labelElement.setAttribute("aria-current", "true");
    } else {
      labelElement.setAttribute("aria-pressed", "false");
      labelElement.removeAttribute("aria-current");
    }
  });
}

function getBodyWorldPosition(bodyName, target = new THREE.Vector3()) {
  const record = bodyRecords.get(bodyName);
  if (!record) {
    return target.set(0, 0, 0);
  }

  record.mesh.getWorldPosition(target);
  return target;
}

function getSelectedBodyRecord() {
  return bodyRecords.get(state.selectedBodyName) || bodyRecords.get("Sun");
}

function computeFocusOffsetForBody(bodyName) {
  const record = bodyRecords.get(bodyName);
  if (!record) {
    return new THREE.Vector3(0, 16, 32);
  }

  const body = record.body;
  const radius = Math.max(record.currentVisualRadius, 0.4);
  const distanceMultiplier = body.focusDistanceMultiplier || 6.5;
  const focusDistance = Math.max(radius * distanceMultiplier, 3.6);
  const verticalLift = Math.max(radius * 1.4, 1.8);

  if (bodyName === "Sun") {
    return new THREE.Vector3(0, focusDistance * 0.9, focusDistance);
  }

  if (bodyName === "Moon") {
    return new THREE.Vector3(
      focusDistance * 0.72,
      verticalLift * 0.8,
      focusDistance * 0.92
    );
  }

  return new THREE.Vector3(
    focusDistance * 0.82,
    verticalLift,
    focusDistance
  );
}

function frameBody(bodyName, shouldAnimate = true) {
  const target = getBodyWorldPosition(bodyName, new THREE.Vector3());
  const offset = computeFocusOffsetForBody(bodyName);
  moveCameraFocusTo(target, offset, shouldAnimate);
}

function moveCameraFocusTo(target, offset, shouldAnimate = true) {
  cameraFocusState.desiredTarget.copy(target);
  cameraFocusState.desiredOffset.copy(offset);

  if (!shouldAnimate) {
    cameraFocusState.currentTarget.copy(target);
    controls.target.copy(target);
    camera.position.copy(target).add(offset);
    cameraFocusState.isAutoFraming = false;
    controls.update();
    return;
  }

  cameraFocusState.isAutoFraming = true;
}

function refreshCameraFocusTarget() {
  const selectedRecord = getSelectedBodyRecord();
  if (!selectedRecord) {
    return;
  }

  const selectedTarget = getBodyWorldPosition(selectedRecord.body.name, tmpVector);
  const preset = CAMERA_PRESETS[state.activeCameraPreset];

  if (
    preset &&
    preset.targetBodyName === state.selectedBodyName &&
    !cameraFocusState.isAutoFraming
  ) {
    cameraFocusState.desiredTarget.copy(selectedTarget);
    return;
  }

  if (!preset) {
    cameraFocusState.desiredTarget.copy(selectedTarget);
    return;
  }

  if (preset.targetBodyName === selectedRecord.body.name) {
    cameraFocusState.desiredTarget.copy(selectedTarget);
    return;
  }

  getBodyWorldPosition(preset.targetBodyName, cameraFocusState.desiredTarget);
}

function updateCameraFocus(deltaSeconds) {
  const followSelectedBody =
    !state.activeCameraPreset ||
    CAMERA_PRESETS[state.activeCameraPreset]?.targetBodyName ===
      state.selectedBodyName;

  if (followSelectedBody) {
    const selectedRecord = getSelectedBodyRecord();
    if (selectedRecord) {
      getBodyWorldPosition(
        selectedRecord.body.name,
        cameraFocusState.desiredTarget
      );
    }
  } else {
    const preset = CAMERA_PRESETS[state.activeCameraPreset];
    if (preset) {
      getBodyWorldPosition(preset.targetBodyName, cameraFocusState.desiredTarget);
    }
  }

  const alpha = 1 - Math.exp(-cameraFocusState.lerpStrength * deltaSeconds);
  cameraFocusState.currentTarget.lerp(cameraFocusState.desiredTarget, alpha);

  const desiredCameraPosition = tmpVectorB
    .copy(cameraFocusState.currentTarget)
    .add(cameraFocusState.desiredOffset);

  if (cameraFocusState.isAutoFraming) {
    camera.position.lerp(desiredCameraPosition, alpha);

    if (camera.position.distanceTo(desiredCameraPosition) < 0.08) {
      camera.position.copy(desiredCameraPosition);
      cameraFocusState.isAutoFraming = false;
    }
  }

  controls.target.copy(cameraFocusState.currentTarget);
}

function applyCameraPreset(presetName, shouldAnimate = true) {
  const preset = CAMERA_PRESETS[presetName];
  if (!preset) {
    return;
  }

  state.activeCameraPreset = presetName;
  const target = getBodyWorldPosition(preset.targetBodyName, new THREE.Vector3());
  moveCameraFocusTo(target, preset.offset.clone(), shouldAnimate);
  controls.minDistance = preset.minDistance ?? 2;

  const focusedBody =
    BODY_LOOKUP.get(state.selectedBodyName) || BODY_DEFINITIONS[0];
  updateSelectedBodyInfo(focusedBody, state.selectedSeason);
}

function selectBody(body, options = {}) {
  if (!body) {
    return;
  }

  const { focusCamera = true, animateCamera = true } = options;

  updateSelectedBodyInfo(body, state.selectedSeason);
  state.activeCameraPreset = null;

  if (focusCamera) {
    frameBody(body.name, animateCamera);
    controls.minDistance = Math.max(
      2,
      computeFocusOffsetForBody(body.name).length() * 0.28
    );
  }
}

function adjustTimeSpeed(delta) {
  const currentValue = Number(timeSpeedInput.value);
  const nextValue = THREE.MathUtils.clamp(currentValue + delta, 0, 100);
  timeSpeedInput.value = String(nextValue);
  updateTimeSpeedLabel();
}

function refocusSelectedBody() {
  const selectedBody = BODY_LOOKUP.get(state.selectedBodyName);
  if (selectedBody) {
    selectBody(selectedBody, { focusCamera: true, animateCamera: true });
  }
}

function handleResize() {
  const width = Math.max(sceneContainer.clientWidth, 1);
  const height = Math.max(sceneContainer.clientHeight, 1);

  camera.aspect = width / height;
  camera.updateProjectionMatrix();

  renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
  renderer.setSize(width, height, false);
}

function createOrbitPath(body) {
  if (body.orbitRadius === 0) {
    return null;
  }

  const segments = body.parent ? 96 : 160;
  const points = [];

  for (let index = 0; index < segments; index += 1) {
    const angle = (index / segments) * Math.PI * 2;
    points.push(
      new THREE.Vector3(
        Math.cos(angle) * body.orbitRadius,
        0,
        Math.sin(angle) * body.orbitRadius
      )
    );
  }

  const geometry = new THREE.BufferGeometry().setFromPoints(points);
  const material = new THREE.LineBasicMaterial({
    color: body.orbitColor || "#7aa2ff",
    transparent: true,
    opacity: body.parent ? 0.58 : 0.35,
    depthWrite: false,
  });

  const line = new THREE.LineLoop(geometry, material);
  line.userData.bodyName = body.name;
  line.userData.baseRadius = body.orbitRadius;

  if (body.parent) {
    const parentRecord = bodyRecords.get(body.parent);
    if (parentRecord) {
      parentRecord.mesh.add(line);
      line.position.set(0, 0, 0);
      return line;
    }
  }

  solarGroup.add(line);
  return line;
}

function updateOrbitPath(line, radius) {
  const positionAttribute = line.geometry.getAttribute("position");
  const count = positionAttribute.count;

  for (let index = 0; index < count; index += 1) {
    const angle = (index / count) * Math.PI * 2;
    positionAttribute.setXYZ(
      index,
      Math.cos(angle) * radius,
      0,
      Math.sin(angle) * radius
    );
  }

  positionAttribute.needsUpdate = true;
  line.geometry.computeBoundingSphere();
}

function createSaturnRings(body) {
  const style = body.textureStyle;
  const geometry = new THREE.RingGeometry(1.45, 2.55, 96);
  const position = geometry.attributes.position;
  const colors = [];
  const innerColor = new THREE.Color(style.ringInnerColor);
  const outerColor = new THREE.Color(style.ringOuterColor);

  for (let index = 0; index < position.count; index += 1) {
    const x = position.getX(index);
    const y = position.getY(index);
    const radius = Math.sqrt(x * x + y * y);
    const mix = THREE.MathUtils.clamp((radius - 1.45) / (2.55 - 1.45), 0, 1);
    const color = innerColor.clone().lerp(outerColor, mix);
    colors.push(color.r, color.g, color.b);
  }

  geometry.setAttribute("color", new THREE.Float32BufferAttribute(colors, 3));

  const material = new THREE.MeshBasicMaterial({
    vertexColors: true,
    side: THREE.DoubleSide,
    transparent: true,
    opacity: style.ringOpacity || 0.78,
    depthWrite: false,
  });

  const rings = new THREE.Mesh(geometry, material);
  rings.rotation.x = Math.PI / 2.65;
  rings.rotation.z = 0.18;
  rings.renderOrder = 2;
  return rings;
}

function createAxialTiltMarker(body) {
  const tiltGroup = new THREE.Group();
  const tiltAngle = THREE.MathUtils.degToRad(body.axialTiltDeg || 23.5);
  tiltGroup.rotation.z = tiltAngle;

  const markerMaterial = new THREE.MeshBasicMaterial({ color: 0xaed8ff });
  const lineGeometry = new THREE.CylinderGeometry(0.028, 0.028, 4.8, 8);
  const line = new THREE.Mesh(lineGeometry, markerMaterial);
  tiltGroup.add(line);

  const capGeometry = new THREE.SphereGeometry(0.11, 12, 12);
  const topCap = new THREE.Mesh(capGeometry, markerMaterial);
  const bottomCap = new THREE.Mesh(capGeometry, markerMaterial);
  topCap.position.y = 2.4;
  bottomCap.position.y = -2.4;
  tiltGroup.add(topCap, bottomCap);

  const northIndicatorGeometry = new THREE.ConeGeometry(0.12, 0.34, 12);
  const northIndicator = new THREE.Mesh(northIndicatorGeometry, markerMaterial);
  northIndicator.position.y = 2.75;
  northIndicator.rotation.z = Math.PI;
  tiltGroup.add(northIndicator);

  return tiltGroup;
}

function createBodyDomLabel(body) {
  const element = document.createElement("button");
  element.type = "button";
  element.className = "body-label";
  element.dataset.bodyName = body.name;
  element.textContent = body.name;
  element.tabIndex = state.showLabels ? 0 : -1;
  element.setAttribute("aria-label", `Focus ${body.name}`);
  element.setAttribute(
    "aria-pressed",
    body.name === state.selectedBodyName ? "true" : "false"
  );
  if (body.name === state.selectedBodyName) {
    element.setAttribute("aria-current", "true");
  }
  element.addEventListener("click", () => {
    selectBody(body, { focusCamera: true, animateCamera: true });
  });
  labelsLayer.appendChild(element);
  return element;
}

function syncToggleInputs() {
  if (toggleLabelsInput) {
    toggleLabelsInput.checked = state.showLabels;
    toggleLabelsInput.setAttribute("aria-checked", String(state.showLabels));
  }

  if (toggleOrbitsInput) {
    toggleOrbitsInput.checked = state.showOrbits;
    toggleOrbitsInput.setAttribute("aria-checked", String(state.showOrbits));
  }
}

function setOrbitVisibility(visible) {
  state.showOrbits = visible;

  orbitLines.forEach((line) => {
    line.visible = visible;
  });

  syncToggleInputs();
}

function setLabelVisibility(visible) {
  state.showLabels = visible;

  domLabels.forEach((labelElement) => {
    labelElement.style.display = visible ? "block" : "none";
    labelElement.tabIndex = visible ? 0 : -1;

    if (!visible) {
      labelElement.classList.add("is-hidden");
      labelElement.setAttribute("aria-hidden", "true");
    } else {
      labelElement.classList.remove("is-hidden");
      labelElement.removeAttribute("aria-hidden");
    }
  });

  if (labelsLayer) {
    labelsLayer.setAttribute("aria-hidden", visible ? "false" : "true");
  }

  syncToggleInputs();
}

function updateDomLabels() {
  if (!state.showLabels) {
    return;
  }

  const width = sceneContainer.clientWidth;
  const height = sceneContainer.clientHeight;
  const smallViewport = width <= 520;
  const compactViewport = width <= 760;

  BODY_DEFINITIONS.forEach((body) => {
    const record = bodyRecords.get(body.name);
    if (!record?.domLabel) {
      return;
    }

    record.mesh.getWorldPosition(tmpVector);
    tmpVectorE.copy(tmpVector);
    tmpVector.y += (body.labelOffset || 1.8) + record.currentVisualRadius * 0.25;

    const projected = tmpVector.project(camera);
    const isOutsideDepthRange = projected.z < -1 || projected.z > 1;

    if (isOutsideDepthRange) {
      hideDomLabel(record.domLabel);
      record.domLabel.classList.remove("is-occluded");
      return;
    }

    const x = (projected.x * 0.5 + 0.5) * width;
    const y = (-projected.y * 0.5 + 0.5) * height;
    const edgeMarginX = smallViewport ? 54 : 80;
    const edgeMarginY = smallViewport ? 28 : 40;
    const isOffscreen =
      x < -edgeMarginX ||
      x > width + edgeMarginX ||
      y < -edgeMarginY ||
      y > height + edgeMarginY;

    if (isOffscreen) {
      hideDomLabel(record.domLabel);
      record.domLabel.classList.remove("is-occluded");
      return;
    }

    const bodyCameraDistance = camera.position.distanceTo(tmpVectorE);
    const shouldHideForDensity =
      (smallViewport && bodyCameraDistance > 120) ||
      (compactViewport &&
        body.name !== state.selectedBodyName &&
        bodyCameraDistance > 210 &&
        body.approximateDistance.valueAu >= 19);

    if (shouldHideForDensity) {
      hideDomLabel(record.domLabel);
      record.domLabel.classList.remove("is-occluded");
      return;
    }

    showDomLabel(record.domLabel);

    const clampedX = THREE.MathUtils.clamp(x, 20, width - 20);
    const clampedY = THREE.MathUtils.clamp(y, 16, height - 16);
    record.domLabel.style.transform = `translate(-50%, -50%) translate(${clampedX}px, ${clampedY}px)`;

    const distance = camera.position.distanceTo(tmpVector);
    const scale = THREE.MathUtils.clamp(1.1 - distance / 280, 0.72, 1.1);
    const opacity = THREE.MathUtils.clamp(1.2 - distance / 340, 0.65, 1);
    record.domLabel.style.opacity = `${opacity}`;
    record.domLabel.style.scale = `${scale}`;

    const cameraToBodyDirection = tmpVectorD
      .copy(tmpVectorE)
      .sub(camera.position)
      .normalize();
    raycaster.set(camera.position, cameraToBodyDirection);
    const intersections = raycaster.intersectObjects(selectableMeshes, false);
    const firstBodyHit = intersections.find(
      (entry) => entry.object?.userData?.isSelectableBody
    );
    const isOccluded =
      firstBodyHit &&
      firstBodyHit.object !== record.mesh &&
      firstBodyHit.distance < bodyCameraDistance - record.currentVisualRadius * 0.4;

    record.domLabel.classList.toggle("is-occluded", Boolean(isOccluded));
  });
}

function hideDomLabel(labelElement) {
  labelElement.classList.add("is-hidden");
  labelElement.setAttribute("aria-hidden", "true");
  labelElement.tabIndex = -1;
}

function showDomLabel(labelElement) {
  labelElement.classList.remove("is-hidden");
  labelElement.removeAttribute("aria-hidden");
  labelElement.tabIndex = 0;
}

function getBodyTexture(body) {
  const cacheKey = `${body.name}-${JSON.stringify(body.textureStyle)}`;

  if (textureCache.has(cacheKey)) {
    return textureCache.get(cacheKey);
  }

  let texture;

  switch (body.textureStyle.preset) {
    case "sun":
      texture = createSunTexture(body.textureStyle);
      break;
    case "earth":
      texture = createEarthTexture(body.textureStyle);
      break;
    case "moon":
      texture = createMoonTexture(body.textureStyle);
      break;
    case "mars":
      texture = createMarsTexture(body.textureStyle);
      break;
    case "jupiter":
      texture = createGasGiantTexture(body.textureStyle, {
        addStorm: true,
      });
      break;
    case "saturn":
      texture = createGasGiantTexture(body.textureStyle, {
        addStorm: false,
      });
      break;
    case "ice":
    case "neptune":
      texture = createIceGiantTexture(body.textureStyle);
      break;
    case "rocky":
    default:
      texture = createRockyPlanetTexture(body.textureStyle);
      break;
  }

  textureCache.set(cacheKey, texture);
  return texture;
}

function createCanvas(size = 512) {
  const canvas = document.createElement("canvas");
  canvas.width = size;
  canvas.height = size;
  return {
    canvas,
    ctx: canvas.getContext("2d"),
    size,
  };
}

function finalizeTexture(canvas) {
  const texture = new THREE.CanvasTexture(canvas);
  texture.colorSpace = THREE.SRGBColorSpace;
  texture.wrapS = THREE.RepeatWrapping;
  texture.wrapT = THREE.ClampToEdgeWrapping;
  texture.needsUpdate = true;
  return texture;
}

function randomBetween(min, max) {
  return min + Math.random() * (max - min);
}

function drawNoiseSpeckles(
  ctx,
  size,
  colors,
  count,
  minRadius,
  maxRadius,
  opacity
) {
  for (let i = 0; i < count; i += 1) {
    ctx.fillStyle = hexToRgba(
      colors[Math.floor(Math.random() * colors.length)],
      randomBetween(opacity * 0.55, opacity)
    );
    ctx.beginPath();
    ctx.arc(
      Math.random() * size,
      Math.random() * size,
      randomBetween(minRadius, maxRadius),
      0,
      Math.PI * 2
    );
    ctx.fill();
  }
}

function drawBandLayer(
  ctx,
  size,
  colors,
  bandCount,
  opacity,
  blur = 0,
  waveStrength = 0
) {
  const bandHeight = size / bandCount;

  ctx.save();
  ctx.globalAlpha = opacity;
  ctx.filter = blur > 0 ? `blur(${blur}px)` : "none";

  for (let i = 0; i < bandCount; i += 1) {
    const y = i * bandHeight;
    const height = bandHeight * randomBetween(0.8, 1.35);
    const gradient = ctx.createLinearGradient(0, y, 0, y + height);
    const colorA = colors[i % colors.length];
    const colorB = colors[(i + 1) % colors.length];
    gradient.addColorStop(0, colorA);
    gradient.addColorStop(1, colorB);
    ctx.fillStyle = gradient;
    ctx.fillRect(0, y, size, height);

    if (waveStrength > 0) {
      ctx.strokeStyle = hexToRgba(colors[i % colors.length], 0.3);
      ctx.lineWidth = randomBetween(3, 8);
      ctx.beginPath();
      for (let x = 0; x <= size; x += 12) {
        const waveY =
          y +
          height * 0.5 +
          Math.sin((x / size) * Math.PI * 2 + i * 0.7) *
            randomBetween(2, waveStrength);
        if (x === 0) {
          ctx.moveTo(x, waveY);
        } else {
          ctx.lineTo(x, waveY);
        }
      }
      ctx.stroke();
    }
  }

  ctx.restore();
}

function drawCraterField(ctx, size, options) {
  const {
    craterColor,
    highlightColor,
    craterDensity = 120,
    minRadius = 3,
    maxRadius = 18,
  } = options;

  for (let i = 0; i < craterDensity; i += 1) {
    const x = Math.random() * size;
    const y = Math.random() * size;
    const radius = randomBetween(minRadius, maxRadius);

    ctx.fillStyle = hexToRgba(craterColor, randomBetween(0.2, 0.45));
    ctx.beginPath();
    ctx.arc(x, y, radius, 0, Math.PI * 2);
    ctx.fill();

    ctx.strokeStyle = hexToRgba(highlightColor, randomBetween(0.15, 0.32));
    ctx.lineWidth = randomBetween(1, 2.5);
    ctx.beginPath();
    ctx.arc(
      x - radius * 0.12,
      y - radius * 0.12,
      radius * 0.72,
      0,
      Math.PI * 2
    );
    ctx.stroke();
  }
}

function drawSoftMottling(
  ctx,
  size,
  palette,
  count,
  minRadius,
  maxRadius,
  alphaRange
) {
  ctx.save();
  ctx.globalCompositeOperation = "multiply";
  for (let i = 0; i < count; i += 1) {
    const x = Math.random() * size;
    const y = Math.random() * size;
    const radius = randomBetween(minRadius, maxRadius);
    const color = palette[Math.floor(Math.random() * palette.length)];
    const glow = ctx.createRadialGradient(x, y, 0, x, y, radius);
    glow.addColorStop(
      0,
      hexToRgba(color, randomBetween(alphaRange[0], alphaRange[1]))
    );
    glow.addColorStop(1, hexToRgba(color, 0));
    ctx.fillStyle = glow;
    ctx.beginPath();
    ctx.arc(x, y, radius, 0, Math.PI * 2);
    ctx.fill();
  }
  ctx.restore();
}

function drawContourStreaks(ctx, size, color, count, opacity, widthRange) {
  ctx.save();
  ctx.strokeStyle = hexToRgba(color, opacity);
  ctx.lineCap = "round";
  for (let i = 0; i < count; i += 1) {
    const startY = Math.random() * size;
    ctx.lineWidth = randomBetween(widthRange[0], widthRange[1]);
    ctx.beginPath();
    for (let x = 0; x <= size; x += 18) {
      const y =
        startY +
        Math.sin((x / size) * Math.PI * randomBetween(2.5, 6.5) + i * 0.6) *
          randomBetween(3, 11);
      if (x === 0) {
        ctx.moveTo(x, y);
      } else {
        ctx.lineTo(x, y);
      }
    }
    ctx.stroke();
  }
  ctx.restore();
}

function drawCloudVeils(ctx, size, color, count) {
  ctx.save();
  ctx.globalCompositeOperation = "screen";
  for (let i = 0; i < count; i += 1) {
    const x = Math.random() * size;
    const y = Math.random() * size;
    const width = randomBetween(20, 68);
    const height = randomBetween(8, 22);
    ctx.fillStyle = hexToRgba(color, randomBetween(0.12, 0.28));
    ctx.beginPath();
    ctx.ellipse(
      x,
      y,
      width,
      height,
      Math.random() * Math.PI,
      0,
      Math.PI * 2
    );
    ctx.fill();
  }
  ctx.restore();
}

function drawPlanetShading(ctx, size, alpha = 0.16) {
  const vignette = ctx.createRadialGradient(
    size * 0.38,
    size * 0.34,
    size * 0.08,
    size * 0.5,
    size * 0.5,
    size * 0.72
  );
  vignette.addColorStop(0, "rgba(255,255,255,0)");
  vignette.addColorStop(0.7, "rgba(0,0,0,0)");
  vignette.addColorStop(1, `rgba(0,0,0,${alpha})`);
  ctx.fillStyle = vignette;
  ctx.fillRect(0, 0, size, size);
}

function createSunTexture(style) {
  const { canvas, ctx, size } = createCanvas(512);

  const gradient = ctx.createRadialGradient(
    size * 0.5,
    size * 0.5,
    size * 0.05,
    size * 0.5,
    size * 0.5,
    size * 0.52
  );
  gradient.addColorStop(0, style.palette[0]);
  gradient.addColorStop(0.28, style.palette[1]);
  gradient.addColorStop(0.72, style.palette[2]);
  gradient.addColorStop(1, style.palette[3]);
  ctx.fillStyle = gradient;
  ctx.fillRect(0, 0, size, size);

  drawNoiseSpeckles(ctx, size, style.palette.slice(1), 900, 3, 24, 0.16);

  ctx.save();
  ctx.globalCompositeOperation = "screen";
  for (let i = 0; i < (style.cellularCount || 180); i += 1) {
    const x = Math.random() * size;
    const y = Math.random() * size;
    const radius = randomBetween(10, 44);
    const glow = ctx.createRadialGradient(x, y, 0, x, y, radius);
    glow.addColorStop(0, hexToRgba(style.flareColor || "#fff2ad", 0.35));
    glow.addColorStop(0.6, hexToRgba(style.glowColor || "#ff9f2b", 0.12));
    glow.addColorStop(1, hexToRgba("#ff5d00", 0));
    ctx.fillStyle = glow;
    ctx.beginPath();
    ctx.arc(x, y, radius, 0, Math.PI * 2);
    ctx.fill();
  }
  ctx.restore();

  drawContourStreaks(
    ctx,
    size,
    style.palette[1],
    style.streakCount || 42,
    0.08,
    [2, 5]
  );
  drawSoftMottling(
    ctx,
    size,
    [style.palette[2], style.palette[3]],
    140,
    18,
    80,
    [0.08, 0.18]
  );
  drawPlanetShading(ctx, size, 0.08);

  return finalizeTexture(canvas);
}

function createRockyPlanetTexture(style) {
  const { canvas, ctx, size } = createCanvas(512);

  const gradient = ctx.createLinearGradient(0, 0, size, size);
  gradient.addColorStop(0, style.highlight || style.base);
  gradient.addColorStop(0.45, style.base);
  gradient.addColorStop(1, style.accent);
  ctx.fillStyle = gradient;
  ctx.fillRect(0, 0, size, size);

  drawSoftMottling(
    ctx,
    size,
    [
      style.base,
      style.accent,
      style.shadow || style.crater,
      style.highlight || style.base,
    ],
    style.mottlingCount || 320,
    10,
    52,
    [0.06, 0.18]
  );

  drawNoiseSpeckles(
    ctx,
    size,
    [style.base, style.accent, style.highlight || style.base],
    320,
    4,
    30,
    0.24
  );

  if ((style.ridgeCount || 0) > 0) {
    drawContourStreaks(
      ctx,
      size,
      style.shadow || style.crater,
      style.ridgeCount,
      0.08,
      [1, 3]
    );
  }

  drawCraterField(ctx, size, {
    craterColor: style.crater,
    highlightColor: style.highlight || "#d9d4cc",
    craterDensity: style.craterDensity,
    minRadius: 3,
    maxRadius: 16,
  });

  if (style.cloudBands) {
    drawBandLayer(
      ctx,
      size,
      [
        hexToRgba("#fff0c9", 0.16),
        hexToRgba("#d8c182", 0.2),
        hexToRgba("#ffffff", 0.08),
      ],
      style.cloudBands,
      0.26,
      1.5,
      2
    );
    drawCloudVeils(ctx, size, "#fff5d1", 90);
  }

  if (style.hazeOpacity) {
    ctx.fillStyle = hexToRgba("#fff5cf", style.hazeOpacity);
    ctx.fillRect(0, 0, size, size);
  }

  drawPlanetShading(ctx, size, 0.15);
  return finalizeTexture(canvas);
}

function createEarthTexture(style) {
  const { canvas, ctx, size } = createCanvas(512);

  const oceanGradient = ctx.createLinearGradient(0, 0, size, size);
  oceanGradient.addColorStop(0, style.shallowWater);
  oceanGradient.addColorStop(0.45, style.ocean);
  oceanGradient.addColorStop(1, style.deepWater || "#163f8f");
  ctx.fillStyle = oceanGradient;
  ctx.fillRect(0, 0, size, size);

  drawSoftMottling(
    ctx,
    size,
    [style.shallowWater, style.ocean, style.deepWater || "#163f8f"],
    style.currentCount || 120,
    16,
    60,
    [0.05, 0.12]
  );

  for (let i = 0; i < style.landMasses; i += 1) {
    const x = Math.random() * size;
    const y = Math.random() * size;
    const radiusX = randomBetween(24, 70);
    const radiusY = randomBetween(12, 40);
    const rotation = Math.random() * Math.PI;

    ctx.fillStyle = Math.random() > 0.5 ? style.landA : style.landB;
    ctx.beginPath();
    ctx.ellipse(x, y, radiusX, radiusY, rotation, 0, Math.PI * 2);
    ctx.fill();

    ctx.fillStyle = hexToRgba(style.landHighlight || "#8cb65d", 0.3);
    ctx.beginPath();
    ctx.ellipse(
      x + randomBetween(-8, 8),
      y + randomBetween(-8, 8),
      radiusX * 0.58,
      radiusY * 0.52,
      rotation,
      0,
      Math.PI * 2
    );
    ctx.fill();
  }

  drawNoiseSpeckles(
    ctx,
    size,
    [style.landA, style.landB, "#6da8ef"],
    260,
    3,
    18,
    0.14
  );
  drawSoftMottling(ctx, size, [style.landA, style.landB], 90, 12, 36, [
    0.08,
    0.18,
  ]);

  for (let i = 0; i < style.cloudAmount; i += 1) {
    ctx.fillStyle = hexToRgba(style.cloud, randomBetween(0.16, 0.38));
    ctx.beginPath();
    ctx.ellipse(
      Math.random() * size,
      Math.random() * size,
      randomBetween(12, 40),
      randomBetween(5, 16),
      Math.random() * Math.PI,
      0,
      Math.PI * 2
    );
    ctx.fill();
  }

  drawCloudVeils(ctx, size, style.cloudShadow || style.cloud, 72);

  ctx.fillStyle = hexToRgba(style.ice, 0.52);
  ctx.fillRect(0, 0, size, 34);
  ctx.fillRect(0, size - 34, size, 34);

  drawPlanetShading(ctx, size, 0.12);
  return finalizeTexture(canvas);
}

function createMoonTexture(style) {
  const { canvas, ctx, size } = createCanvas(512);

  const gradient = ctx.createLinearGradient(0, 0, size, size);
  gradient.addColorStop(0, style.highlight);
  gradient.addColorStop(0.35, style.base);
  gradient.addColorStop(1, style.accent);
  ctx.fillStyle = gradient;
  ctx.fillRect(0, 0, size, size);

  drawSoftMottling(
    ctx,
    size,
    [style.base, style.accent, style.maria],
    180,
    12,
    42,
    [0.08, 0.18]
  );

  for (let i = 0; i < style.mariaCount; i += 1) {
    ctx.fillStyle = hexToRgba(
      style.maria || "#6e7278",
      randomBetween(0.2, 0.34)
    );
    ctx.beginPath();
    ctx.ellipse(
      Math.random() * size,
      Math.random() * size,
      randomBetween(24, 65),
      randomBetween(16, 40),
      Math.random() * Math.PI,
      0,
      Math.PI * 2
    );
    ctx.fill();
  }

  drawCraterField(ctx, size, {
    craterColor: style.crater,
    highlightColor: style.highlight,
    craterDensity: style.craterDensity,
    minRadius: 2,
    maxRadius: 14,
  });

  if ((style.brightRayCount || 0) > 0) {
    ctx.save();
    ctx.globalCompositeOperation = "screen";
    for (let i = 0; i < style.brightRayCount; i += 1) {
      const centerX = Math.random() * size;
      const centerY = Math.random() * size;
      ctx.strokeStyle = hexToRgba(style.highlight, 0.08);
      ctx.lineWidth = randomBetween(1, 2.5);
      for (let ray = 0; ray < 8; ray += 1) {
        const angle = (Math.PI * 2 * ray) / 8 + Math.random() * 0.2;
        const length = randomBetween(20, 70);
        ctx.beginPath();
        ctx.moveTo(centerX, centerY);
        ctx.lineTo(
          centerX + Math.cos(angle) * length,
          centerY + Math.sin(angle) * length
        );
        ctx.stroke();
      }
    }
    ctx.restore();
  }

  drawPlanetShading(ctx, size, 0.16);
  return finalizeTexture(canvas);
}

function createMarsTexture(style) {
  const { canvas, ctx, size } = createCanvas(512);

  const gradient = ctx.createLinearGradient(0, 0, size, size);
  gradient.addColorStop(0, style.highlight);
  gradient.addColorStop(0.45, style.base);
  gradient.addColorStop(1, style.accent);
  ctx.fillStyle = gradient;
  ctx.fillRect(0, 0, size, size);

  drawSoftMottling(
    ctx,
    size,
    [style.base, style.accent, style.dust || style.highlight],
    220,
    14,
    52,
    [0.08, 0.18]
  );

  for (let i = 0; i < style.darkRegionCount; i += 1) {
    ctx.fillStyle = hexToRgba(style.crater, randomBetween(0.22, 0.4));
    ctx.beginPath();
    ctx.ellipse(
      Math.random() * size,
      Math.random() * size,
      randomBetween(20, 64),
      randomBetween(8, 24),
      Math.random() * Math.PI,
      0,
      Math.PI * 2
    );
    ctx.fill();
  }

  if ((style.dustBandCount || 0) > 0) {
    drawBandLayer(
      ctx,
      size,
      [
        hexToRgba(style.dust || style.highlight, 0.08),
        hexToRgba(style.base, 0.05),
      ],
      style.dustBandCount,
      0.35,
      1.2,
      4
    );
  }

  drawCraterField(ctx, size, {
    craterColor: style.crater,
    highlightColor: style.highlight,
    craterDensity: style.craterDensity,
    minRadius: 2,
    maxRadius: 12,
  });

  ctx.fillStyle = hexToRgba(style.polarCap, 0.72);
  ctx.fillRect(0, 0, size, 24);
  ctx.fillRect(0, size - 24, size, 24);

  drawPlanetShading(ctx, size, 0.15);
  return finalizeTexture(canvas);
}

function createGasGiantTexture(style, options = {}) {
  const { canvas, ctx, size } = createCanvas(512);

  drawBandLayer(
    ctx,
    size,
    style.bandColors,
    style.bandCount,
    1,
    0,
    style.waveStrength || 0
  );

  drawNoiseSpeckles(ctx, size, style.bandColors, 220, 12, 54, 0.12);
  drawSoftMottling(
    ctx,
    size,
    style.bandColors,
    style.eddyCount || 40,
    20,
    80,
    [0.05, 0.13]
  );

  ctx.save();
  ctx.globalAlpha = 0.18;
  ctx.filter = "blur(3px)";
  for (let i = 0; i < 36; i += 1) {
    ctx.fillStyle = style.bandColors[i % style.bandColors.length];
    ctx.fillRect(0, randomBetween(0, size), size, randomBetween(8, 24));
  }
  ctx.restore();

  drawContourStreaks(
    ctx,
    size,
    style.bandColors[Math.floor(style.bandColors.length / 2)],
    Math.max(10, Math.floor((style.eddyCount || 40) / 4)),
    0.06,
    [2, 4]
  );

  if (options.addStorm && style.stormColor) {
    ctx.fillStyle = hexToRgba(style.stormColor, 0.85);
    ctx.beginPath();
    ctx.ellipse(size * 0.72, size * 0.62, 46, 24, -0.18, 0, Math.PI * 2);
    ctx.fill();

    ctx.strokeStyle = hexToRgba(style.stormHighlight || "#f2c1a5", 0.5);
    ctx.lineWidth = 6;
    ctx.beginPath();
    ctx.ellipse(size * 0.72, size * 0.62, 54, 29, -0.18, 0, Math.PI * 2);
    ctx.stroke();

    drawContourStreaks(ctx, size, style.stormColor, 8, 0.08, [1, 2.5]);
  }

  drawPlanetShading(ctx, size, 0.1);
  return finalizeTexture(canvas);
}

function createIceGiantTexture(style) {
  const { canvas, ctx, size } = createCanvas(512);

  const gradient = ctx.createLinearGradient(0, 0, 0, size);
  gradient.addColorStop(0, lightenColor(style.accent, 0.18));
  gradient.addColorStop(0.5, style.base);
  gradient.addColorStop(1, darkenColor(style.base, 0.18));
  ctx.fillStyle = gradient;
  ctx.fillRect(0, 0, size, size);

  drawBandLayer(
    ctx,
    size,
    [hexToRgba(style.bandColor, 0.3), hexToRgba(style.accent, 0.22)],
    style.bandCount,
    0.45,
    2,
    3
  );

  drawNoiseSpeckles(
    ctx,
    size,
    [style.base, style.accent, style.bandColor],
    120,
    10,
    38,
    0.08
  );
  drawSoftMottling(
    ctx,
    size,
    [style.base, style.accent, style.bandColor],
    90,
    18,
    70,
    [0.04, 0.1]
  );

  if ((style.streakCount || 0) > 0) {
    drawContourStreaks(
      ctx,
      size,
      style.hazeColor || style.accent,
      style.streakCount,
      0.06,
      [2, 4]
    );
  }

  if (style.stormColor) {
    ctx.fillStyle = hexToRgba(style.stormColor, 0.16);
    ctx.beginPath();
    ctx.ellipse(size * 0.66, size * 0.46, 28, 16, -0.25, 0, Math.PI * 2);
    ctx.fill();
  }

  ctx.fillStyle = hexToRgba(style.hazeColor || style.accent, 0.08);
  ctx.fillRect(0, 0, size, size);

  drawPlanetShading(ctx, size, 0.1);
  return finalizeTexture(canvas);
}

function hexToRgba(hex, alpha) {
  const normalized = hex.replace("#", "");
  const value =
    normalized.length === 3
      ? normalized
          .split("")
          .map((character) => character + character)
          .join("")
      : normalized;

  const r = Number.parseInt(value.slice(0, 2), 16);
  const g = Number.parseInt(value.slice(2, 4), 16);
  const b = Number.parseInt(value.slice(4, 6), 16);

  return `rgba(${r}, ${g}, ${b}, ${alpha})`;
}

function lightenColor(hex, amount) {
  return adjustColor(hex, amount);
}

function darkenColor(hex, amount) {
  return adjustColor(hex, -amount);
}

function adjustColor(hex, amount) {
  const normalized = hex.replace("#", "");
  const parts =
    normalized.length === 3
      ? normalized.split("").map((character) => character + character)
      : [
          normalized.slice(0, 2),
          normalized.slice(2, 4),
          normalized.slice(4, 6),
        ];

  const adjusted = parts.map((part) => {
    const base = Number.parseInt(part, 16);
    const next = Math.max(0, Math.min(255, Math.round(base + 255 * amount)));
    return next.toString(16).padStart(2, "0");
  });

  return `#${adjusted.join("")}`;
}

function createStarfield(count, spread) {
  const positions = new Float32Array(count * 3);

  for (let i = 0; i < count; i += 1) {
    const radius = spread * (0.55 + Math.random() * 0.45);
    const theta = Math.random() * Math.PI * 2;
    const phi = Math.acos(2 * Math.random() - 1);
    const index = i * 3;

    positions[index] = radius * Math.sin(phi) * Math.cos(theta);
    positions[index + 1] = radius * Math.cos(phi);
    positions[index + 2] = radius * Math.sin(phi) * Math.sin(theta);
  }

  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute("position", new THREE.BufferAttribute(positions, 3));

  const material = new THREE.PointsMaterial({
    color: 0xffffff,
    size: 1.6,
    sizeAttenuation: true,
    transparent: true,
    opacity: 0.88,
  });

  return new THREE.Points(geometry, material);
}

function isPrimaryPointer(event) {
  const isMouseLikePointer =
    event.pointerType === "mouse" || event.pointerType === "";
  if (isMouseLikePointer) {
    return event.button === 0;
  }

  return event.isPrimary !== false;
}

function intersectsLabelButton(event) {
  const element = document.elementFromPoint(event.clientX, event.clientY);
  return Boolean(element?.closest?.(".body-label"));
}

function handlePointerSelection(event) {
  if (!isPrimaryPointer(event) || intersectsLabelButton(event)) {
    return;
  }

  const rect = renderer.domElement.getBoundingClientRect();
  pointer.x = ((event.clientX - rect.left) / rect.width) * 2 - 1;
  pointer.y = -((event.clientY - rect.top) / rect.height) * 2 + 1;

  raycaster.setFromCamera(pointer, camera);

  const intersections = raycaster.intersectObjects(selectableMeshes, false);
  const hit = intersections.find(
    (entry) => entry.object?.userData?.isSelectableBody
  );

  if (!hit) {
    let nearestBody = null;
    let nearestDistanceSq = Number.POSITIVE_INFINITY;

    BODY_DEFINITIONS.forEach((body) => {
      const record = bodyRecords.get(body.name);
      if (!record) {
        return;
      }

      const center = getBodyWorldPosition(body.name, tmpVectorC);
      const radius =
        body.name === "Sun"
          ? body.visualRadius * record.mesh.scale.x
          : record.currentVisualRadius;
      const threshold = Math.max(radius * 0.65, 0.38);
      const distanceSq = raycaster.ray.distanceSqToPoint(center);

      if (distanceSq <= threshold * threshold && distanceSq < nearestDistanceSq) {
        nearestDistanceSq = distanceSq;
        nearestBody = body;
      }
    });

    if (nearestBody) {
      selectBody(nearestBody, { focusCamera: true, animateCamera: true });
    }

    return;
  }

  const body = hit.object.userData.body;
  selectBody(body, { focusCamera: true, animateCamera: true });
}

function isShortcutSuppressedByFocusedControl() {
  const activeElement = document.activeElement;
  if (!activeElement) {
    return false;
  }

  const tagName = activeElement.tagName;
  const isFormControl =
    tagName === "INPUT" ||
    tagName === "SELECT" ||
    tagName === "TEXTAREA" ||
    activeElement.isContentEditable;

  if (!isFormControl) {
    return false;
  }

  return activeElement !== timeSpeedInput;
}

function handleKeyShortcuts(event) {
  if (event.defaultPrevented || event.altKey || event.ctrlKey || event.metaKey) {
    return;
  }

  const shortcutSuppressed = isShortcutSuppressedByFocusedControl();
  const lowerKey = event.key?.toLowerCase();

  if (event.code === "Space") {
    const isButtonFocused = document.activeElement === playPauseButton;
    if (!shortcutSuppressed || isButtonFocused) {
      event.preventDefault();
      updatePlayPause();
    }
    return;
  }

  if (shortcutSuppressed) {
    return;
  }

  if (lowerKey === "l") {
    event.preventDefault();
    setLabelVisibility(!state.showLabels);
    return;
  }

  if (lowerKey === "o") {
    event.preventDefault();
    setOrbitVisibility(!state.showOrbits);
    return;
  }

  if (lowerKey === "f") {
    event.preventDefault();
    refocusSelectedBody();
    return;
  }

  if (event.key >= "1" && event.key <= "5") {
    const presetNames = ["overview", "inner", "earth", "outer", "sun"];
    const presetName = presetNames[Number(event.key) - 1];
    if (presetName) {
      event.preventDefault();
      applyCameraPreset(presetName, true);
    }
    return;
  }

  if (
    event.key === "ArrowUp" ||
    event.key === "ArrowRight" ||
    event.key === "ArrowDown" ||
    event.key === "ArrowLeft"
  ) {
    const delta =
      event.key === "ArrowUp" || event.key === "ArrowRight" ? 5 : -5;
    event.preventDefault();
    adjustTimeSpeed(delta);
  }
}

playPauseButton.addEventListener("click", updatePlayPause);
timeSpeedInput.addEventListener("input", updateTimeSpeedLabel);
datePreset.addEventListener("change", (event) => {
  applySeasonSelection(event.target.value);
});

seasonButtons.forEach((button) => {
  button.addEventListener("click", () => {
    applySeasonSelection(button.dataset.season);
  });
});

cameraPresetButtons.forEach((button) => {
  button.addEventListener("click", () => {
    applyCameraPreset(button.dataset.camera, true);
  });
});

toggleOrbitsInput?.addEventListener("change", (event) => {
  setOrbitVisibility(event.target.checked);
});

toggleLabelsInput?.addEventListener("change", (event) => {
  setLabelVisibility(event.target.checked);
});

scaleModeInput?.addEventListener("change", (event) => {
  setScaleMode(event.target.checked ? "realistic" : "educational");
});

refocusButton?.addEventListener("click", () => {
  refocusSelectedBody();
});

renderer.domElement.addEventListener("pointerdown", handlePointerSelection);
window.addEventListener("keydown", handleKeyShortcuts);
window.addEventListener("resize", handleResize);

updateSelectedBodyInfo(BODY_DEFINITIONS[0], state.selectedSeason);
handleResize();
animate();
