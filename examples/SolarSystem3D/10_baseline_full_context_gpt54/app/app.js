import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';

const canvas = document.getElementById('scene-canvas');
const container = document.getElementById('scene-container');
const labelLayer = document.getElementById('label-layer');
const bodySummary = document.getElementById('body-summary');
const playButton = document.getElementById('playButton');
const pauseButton = document.getElementById('pauseButton');
const speedRange = document.getElementById('speedRange');
const speedValue = document.getElementById('speedValue');
const scaleModeSelect = document.getElementById('scaleModeSelect');
const scaleChip = document.getElementById('scale-chip');
const playbackChip = document.getElementById('playback-chip');
const seasonChip = document.getElementById('season-chip');
const selectionChip = document.getElementById('selection-chip');
const orbitChip = document.getElementById('orbit-chip');
const labelChip = document.getElementById('label-chip');
const dateInput = document.getElementById('dateInput');
const labelsToggle = document.getElementById('labelsToggle');
const orbitsToggle = document.getElementById('orbitsToggle');
const seasonButtons = Array.from(document.querySelectorAll('.season-button'));
const cameraPresetButtons = Array.from(document.querySelectorAll('.camera-preset-button'));

const selectedFields = {
  name: document.getElementById('selected-name'),
  type: document.getElementById('selected-type'),
  distance: document.getElementById('selected-distance'),
  orbit: document.getElementById('selected-orbit'),
  rotation: document.getElementById('selected-rotation'),
  description: document.getElementById('selected-description')
};

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
  5000
);
camera.position.set(0, 160, 235);
camera.lookAt(0, 0, 0);

const controls = new OrbitControls(camera, renderer.domElement);
controls.enableDamping = true;
controls.dampingFactor = 0.06;
controls.minDistance = 8;
controls.maxDistance = 1500;
controls.target.set(0, 0, 0);
controls.update();

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
const orbitGeometryCache = new Map();

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
    realisticVisualRadius: 10,
    orbitRadius: 0,
    realisticOrbitRadius: 0,
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
    realisticVisualRadius: 0.6,
    orbitRadius: 16,
    realisticOrbitRadius: 18,
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
    realisticVisualRadius: 1.2,
    orbitRadius: 23,
    realisticOrbitRadius: 26,
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
    realisticVisualRadius: 1.25,
    orbitRadius: 31,
    realisticOrbitRadius: 36,
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
    distanceText: '384,400 km from Earth (parent: Earth)',
    orbitalPeriodText: '27.3 days around Earth',
    rotationPeriodText: '27.3 days',
    description:
      "Earth's Moon is a rocky satellite with a gray cratered surface and a synchronous rotation in this simplified model.",
    visualRadius: 0.7,
    realisticVisualRadius: 0.4,
    orbitRadius: 4.2,
    realisticOrbitRadius: 3.2,
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
    realisticVisualRadius: 0.9,
    orbitRadius: 40,
    realisticOrbitRadius: 55,
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
    realisticVisualRadius: 4.2,
    orbitRadius: 56,
    realisticOrbitRadius: 120,
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
    realisticVisualRadius: 3.6,
    orbitRadius: 74,
    realisticOrbitRadius: 205,
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
    realisticVisualRadius: 2.2,
    orbitRadius: 92,
    realisticOrbitRadius: 295,
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
    realisticVisualRadius: 2.15,
    orbitRadius: 110,
    realisticOrbitRadius: 380,
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

const SEASON_PRESETS = {
  spring: {
    label: 'Spring equinox',
    angle: 0,
    date: '2024-03-20'
  },
  summer: {
    label: 'Summer solstice',
    angle: Math.PI / 2,
    date: '2024-06-20'
  },
  autumn: {
    label: 'Autumn equinox',
    angle: Math.PI,
    date: '2024-09-22'
  },
  winter: {
    label: 'Winter solstice',
    angle: (Math.PI * 3) / 2,
    date: '2024-12-21'
  }
};

const CAMERA_PRESETS = {
  overview: {
    label: 'Overview',
    position: new THREE.Vector3(0, 160, 235),
    target: new THREE.Vector3(0, 0, 0)
  },
  inner: {
    label: 'Inner planets',
    position: new THREE.Vector3(0, 65, 85),
    target: new THREE.Vector3(0, 0, 0)
  },
  earthmoon: {
    label: 'Earth and Moon',
    focusBody: 'Earth',
    offset: new THREE.Vector3(14, 7, 14)
  },
  outer: {
    label: 'Outer planets',
    position: new THREE.Vector3(60, 120, 300),
    target: new THREE.Vector3(0, 0, 120)
  },
  sun: {
    label: 'Sun view',
    focusBody: 'Sun',
    offset: new THREE.Vector3(28, 12, 28)
  }
};

const appState = {
  isPlaying: true,
  timeSpeed: Number(speedRange.value),
  scaleMode: 'educational',
  simDays: 0,
  selectedSeason: null,
  seasonLockEnabled: false,
  selectedBodyName: 'Earth',
  showLabels: true,
  showOrbits: true,
  activeCameraPreset: 'overview'
};

const labelObjects = new Map();
const bodyObjects = new Map();
const bodyDataByName = new Map(solarSystemBodies.map((body) => [body.name, body]));
const raycaster = new THREE.Raycaster();
const pointer = new THREE.Vector2();
const cameraFocus = {
  currentTarget: new THREE.Vector3(),
  desiredTarget: new THREE.Vector3(),
  currentOffset: new THREE.Vector3().copy(camera.position).sub(controls.target),
  desiredOffset: new THREE.Vector3().copy(camera.position).sub(controls.target),
  transitioning: false
};

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

function getOrbitGeometry(radius, segments = 180) {
  const key = `${radius}-${segments}`;
  if (!orbitGeometryCache.has(key)) {
    const points = [];
    for (let i = 0; i <= segments; i += 1) {
      const angle = (i / segments) * Math.PI * 2;
      points.push(new THREE.Vector3(Math.cos(angle) * radius, 0, Math.sin(angle) * radius));
    }
    orbitGeometryCache.set(key, new THREE.BufferGeometry().setFromPoints(points));
  }
  return orbitGeometryCache.get(key);
}

function createOrbitLine(radius, color = 0x3f5d8f, segments = 180) {
  const material = new THREE.LineBasicMaterial({
    color,
    transparent: true,
    opacity: 0.72
  });
  return new THREE.LineLoop(getOrbitGeometry(radius, segments), material);
}

const stars = createStarField();
scene.add(stars);

const accentStars = createStarField(220, 1200);
accentStars.material.size = 4.5;
accentStars.material.opacity = 0.5;
scene.add(accentStars);

const solarSystemGroup = new THREE.Group();
scene.add(solarSystemGroup);

function getOrbitRadiusForMode(body, mode) {
  return mode === 'realistic' ? body.realisticOrbitRadius ?? body.orbitRadius : body.orbitRadius;
}

function getVisualRadiusForMode(body, mode) {
  return mode === 'realistic' ? body.realisticVisualRadius ?? body.visualRadius : body.visualRadius;
}

function getBodyWorldPosition(name) {
  const entry = bodyObjects.get(name);
  if (!entry) {
    return new THREE.Vector3();
  }
  const position = new THREE.Vector3();
  entry.mesh.getWorldPosition(position);
  return position;
}

function createLabel(name) {
  const label = document.createElement('div');
  label.className = 'body-label';
  label.textContent = name;
  label.dataset.bodyName = name;
  labelLayer.appendChild(label);
  labelObjects.set(name, label);
  return label;
}

function updateSelectedBody(body) {
  appState.selectedBodyName = body.name;
  selectedFields.name.textContent = body.name;
  selectedFields.type.textContent = body.type;
  selectedFields.distance.textContent = body.distanceText;
  selectedFields.orbit.textContent = body.orbitalPeriodText;
  selectedFields.rotation.textContent = body.rotationPeriodText;
  selectedFields.description.textContent = body.description;
  selectionChip.textContent = `Selected: ${body.name}`;

  labelObjects.forEach((label, name) => {
    label.classList.toggle('selected', name === body.name);
  });
}

function buildSolarSystem() {
  const sunBody = bodyDataByName.get('Sun');

  const sun = new THREE.Mesh(
    getSphereGeometry(getVisualRadiusForMode(sunBody, appState.scaleMode)),
    new THREE.MeshBasicMaterial({ map: createBodyTexture(sunBody) })
  );
  sun.userData.bodyName = 'Sun';
  solarSystemGroup.add(sun);
  bodyObjects.set('Sun', { body: sunBody, mesh: sun, pivot: solarSystemGroup });
  createLabel('Sun');

  const glow = new THREE.Mesh(
    new THREE.SphereGeometry(getVisualRadiusForMode(sunBody, appState.scaleMode) * 1.38, 32, 32),
    new THREE.MeshBasicMaterial({
      color: 0xffb347,
      transparent: true,
      opacity: 0.16
    })
  );
  solarSystemGroup.add(glow);
  bodyObjects.get('Sun').glow = glow;

  solarSystemBodies
    .filter((body) => body.name !== 'Sun' && body.parent === 'Sun')
    .forEach((body) => {
      const orbitPivot = new THREE.Group();
      orbitPivot.rotation.y = body.initialAngle || 0;
      solarSystemGroup.add(orbitPivot);

      const orbitLine = createOrbitLine(getOrbitRadiusForMode(body, appState.scaleMode), body.name === 'Earth' ? 0x6f8fd1 : 0x3f5d8f);
      solarSystemGroup.add(orbitLine);

      const mesh = new THREE.Mesh(
        getSphereGeometry(getVisualRadiusForMode(body, appState.scaleMode)),
        new THREE.MeshStandardMaterial({
          map: createBodyTexture(body),
          roughness: 1,
          metalness: 0
        })
      );
      mesh.position.set(getOrbitRadiusForMode(body, appState.scaleMode), 0, 0);
      mesh.userData.bodyName = body.name;
      orbitPivot.add(mesh);

      bodyObjects.set(body.name, {
        body,
        mesh,
        pivot: orbitPivot,
        orbitLine
      });

      createLabel(body.name);

      if (body.name === 'Saturn') {
        const ringGeometry = new THREE.RingGeometry(4.9 * 1.45, 4.9 * 2.55, 128);
        const ringMaterial = new THREE.MeshBasicMaterial({
          map: createRingTexture(),
          transparent: true,
          side: THREE.DoubleSide,
          opacity: 0.9
        });
        const rings = new THREE.Mesh(ringGeometry, ringMaterial);
        rings.rotation.x = -Math.PI / 2.45;
        mesh.add(rings);
        bodyObjects.get('Saturn').rings = rings;
      }
    });

  const earthBody = bodyDataByName.get('Earth');
  const moonBody = bodyDataByName.get('Moon');
  const earthObject = bodyObjects.get('Earth');

  const moonPivot = new THREE.Group();
  moonPivot.rotation.y = moonBody.initialAngle || 0;
  earthObject.mesh.add(moonPivot);

  const moonOrbitLine = createOrbitLine(getOrbitRadiusForMode(moonBody, appState.scaleMode), 0x8d96b7, 120);
  earthObject.mesh.add(moonOrbitLine);

  const moonMesh = new THREE.Mesh(
    getSphereGeometry(getVisualRadiusForMode(moonBody, appState.scaleMode)),
    new THREE.MeshStandardMaterial({
      map: createBodyTexture(moonBody),
      roughness: 1,
      metalness: 0
    })
  );
  moonMesh.position.set(getOrbitRadiusForMode(moonBody, appState.scaleMode), 0, 0);
  moonMesh.userData.bodyName = 'Moon';
  moonPivot.add(moonMesh);

  bodyObjects.set('Moon', {
    body: moonBody,
    mesh: moonMesh,
    pivot: moonPivot,
    orbitLine: moonOrbitLine,
    parentMesh: earthObject.mesh
  });
  createLabel('Moon');

  const earthTiltMarkerMaterial = new THREE.LineBasicMaterial({ color: 0x9ec7ff, transparent: true, opacity: 0.92 });
  const tiltPoints = [new THREE.Vector3(0, -5.5, 0), new THREE.Vector3(0, 5.5, 0)];
  const tiltGeometry = new THREE.BufferGeometry().setFromPoints(tiltPoints);
  const tiltLine = new THREE.Line(tiltGeometry, earthTiltMarkerMaterial);
  earthObject.mesh.add(tiltLine);
  earthObject.tiltLine = tiltLine;

  const northPoleMarker = new THREE.Mesh(
    new THREE.SphereGeometry(0.22, 12, 12),
    new THREE.MeshBasicMaterial({ color: 0xe8f4ff })
  );
  northPoleMarker.position.set(0, 5.5, 0);
  tiltLine.add(northPoleMarker);
  earthObject.northPoleMarker = northPoleMarker;

  updateSelectedBody(earthBody);
}

function applyScaleMode(mode) {
  appState.scaleMode = mode;

  bodyObjects.forEach((entry, name) => {
    const radius = getVisualRadiusForMode(entry.body, mode);
    entry.mesh.geometry = getSphereGeometry(radius);

    if (name === 'Sun' && entry.glow) {
      entry.glow.scale.setScalar(radius / 10);
    }

    if (entry.body.parent === 'Sun') {
      const orbitRadius = getOrbitRadiusForMode(entry.body, mode);
      entry.mesh.position.set(orbitRadius, 0, 0);
      if (entry.orbitLine) {
        entry.orbitLine.geometry = getOrbitGeometry(orbitRadius, 180);
      }
    }

    if (name === 'Moon') {
      const moonOrbitRadius = getOrbitRadiusForMode(entry.body, mode);
      entry.mesh.position.set(moonOrbitRadius, 0, 0);
      if (entry.orbitLine) {
        entry.orbitLine.geometry = getOrbitGeometry(moonOrbitRadius, 120);
      }
    }

    if (name === 'Saturn' && entry.rings) {
      const baseScale = radius / 4.9;
      entry.rings.scale.set(baseScale, baseScale, baseScale);
    }
  });

  scaleChip.textContent = mode === 'realistic' ? 'Realistic scale mode' : 'Educational scale mode';
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
      <span>Educational orbit: ${body.orbitRadius} · realistic orbit: ${body.realisticOrbitRadius ?? body.orbitRadius}</span>
      <span>Educational radius: ${body.visualRadius} · realistic radius: ${body.realisticVisualRadius ?? body.visualRadius}</span>
    `;
    bodySummary.appendChild(card);
  });
}

function updatePlaybackChip() {
  if (!appState.isPlaying || appState.timeSpeed === 0) {
    playbackChip.textContent = 'Simulation paused';
  } else {
    playbackChip.textContent = `Simulation running at ${appState.timeSpeed} days / second`;
  }
}

function updateSeasonButtons() {
  seasonButtons.forEach((button) => {
    const isActive = appState.selectedSeason === button.dataset.season && appState.seasonLockEnabled;
    button.classList.toggle('active', isActive);
    button.setAttribute('aria-pressed', isActive ? 'true' : 'false');
  });
}

function updateCameraPresetButtons() {
  cameraPresetButtons.forEach((button) => {
    const isActive = appState.activeCameraPreset === button.dataset.preset;
    button.classList.toggle('active', isActive);
    button.setAttribute('aria-pressed', isActive ? 'true' : 'false');
  });
}

function updateSeasonChip() {
  if (appState.seasonLockEnabled && appState.selectedSeason && SEASON_PRESETS[appState.selectedSeason]) {
    seasonChip.textContent = `Season view: ${SEASON_PRESETS[appState.selectedSeason].label}`;
  } else {
    seasonChip.textContent = 'Season view: live orbit motion';
  }
}

function updateOrbitVisibility() {
  bodyObjects.forEach((entry) => {
    if (entry.orbitLine) {
      entry.orbitLine.visible = appState.showOrbits;
    }
  });
  orbitChip.textContent = appState.showOrbits ? 'Visible orbit paths' : 'Orbit paths hidden';
}

function updateLabelVisibility() {
  labelChip.textContent = appState.showLabels ? 'Visible labels' : 'Labels hidden';
  labelObjects.forEach((label) => {
    label.style.display = appState.showLabels ? 'block' : 'none';
  });
}

function setPlaying(nextPlaying) {
  appState.isPlaying = nextPlaying;
  updatePlaybackChip();
}

function stepSimulationDays(days) {
  appState.simDays += days;
  if (appState.seasonLockEnabled) {
    appState.seasonLockEnabled = false;
    updateSeasonButtons();
    updateSeasonChip();
  }
}

function adjustSpeed(delta) {
  const nextSpeed = THREE.MathUtils.clamp(appState.timeSpeed + delta, Number(speedRange.min), Number(speedRange.max));
  appState.timeSpeed = nextSpeed;
  speedRange.value = String(nextSpeed);
  speedValue.textContent = String(nextSpeed);
  updatePlaybackChip();
}

function getEarthSpinAngle() {
  const days = appState.simDays;
  return (days * Math.PI * 2) % (Math.PI * 2);
}

function getSeasonKeyFromMonthDay(month, day) {
  const numeric = month * 100 + day;
  if (numeric >= 1221 || numeric < 320) {
    return 'winter';
  }
  if (numeric >= 320 && numeric < 620) {
    return 'spring';
  }
  if (numeric >= 620 && numeric < 922) {
    return 'summer';
  }
  return 'autumn';
}

function applyEarthSeasonOrientation(earthObject, orbitalAngle) {
  const tiltDegrees = 23.5;
  const sunDirection = new THREE.Vector3(-Math.cos(orbitalAngle), 0, -Math.sin(orbitalAngle)).normalize();
  const tiltAxis = new THREE.Vector3(0, 1, 0).applyAxisAngle(new THREE.Vector3(0, 0, 1), THREE.MathUtils.degToRad(tiltDegrees));
  const seasonalNorth = tiltAxis.clone();
  const zAxis = new THREE.Vector3(0, 0, 1);
  const projected = seasonalNorth.clone().projectOnPlane(zAxis).normalize();
  const projectedSun = sunDirection.clone().projectOnPlane(zAxis).normalize();
  let heading = 0;
  if (projected.lengthSq() > 0 && projectedSun.lengthSq() > 0) {
    heading = Math.atan2(projectedSun.x, projectedSun.y);
  }

  earthObject.mesh.rotation.set(0, 0, 0);
  earthObject.mesh.rotateZ(THREE.MathUtils.degToRad(tiltDegrees));
  earthObject.mesh.rotateY(-heading);
  earthObject.mesh.rotateY(getEarthSpinAngle());

  if (earthObject.tiltLine) {
    earthObject.tiltLine.visible = true;
  }
}

function applySeasonPreset(seasonKey) {
  const preset = SEASON_PRESETS[seasonKey];
  const earthObject = bodyObjects.get('Earth');
  if (!preset || !earthObject) {
    return;
  }

  appState.selectedSeason = seasonKey;
  appState.seasonLockEnabled = true;
  appState.simDays = (preset.angle / (Math.PI * 2)) * earthObject.body.orbitDays;
  earthObject.pivot.rotation.y = preset.angle;
  applyEarthSeasonOrientation(earthObject, preset.angle);
  dateInput.value = preset.date;
  updateSeasonButtons();
  updateSeasonChip();
}

function applyDatePreset(dateString) {
  const date = new Date(`${dateString}T12:00:00`);
  if (Number.isNaN(date.getTime())) {
    return;
  }

  const month = date.getUTCMonth() + 1;
  const day = date.getUTCDate();
  const seasonKey = getSeasonKeyFromMonthDay(month, day);
  applySeasonPreset(seasonKey);
}

function focusCameraOn(targetPosition, distance = 28, verticalOffset = 8, preserveDirection = true) {
  const nextTarget = targetPosition.clone();
  let offset;

  if (preserveDirection) {
    offset = camera.position.clone().sub(controls.target);
    if (offset.length() < 0.001) {
      offset.set(distance, verticalOffset, distance);
    }
    offset.setLength(Math.max(distance, offset.length()));
    if (Math.abs(offset.y) < verticalOffset * 0.35) {
      offset.y = verticalOffset;
    }
  } else {
    offset = new THREE.Vector3(distance, verticalOffset, distance);
  }

  cameraFocus.desiredTarget.copy(nextTarget);
  cameraFocus.desiredOffset.copy(offset);
  cameraFocus.transitioning = true;
}

function selectBodyByName(name, focus = true, presetKey = null) {
  const body = bodyDataByName.get(name);
  if (!body) {
    return;
  }
  updateSelectedBody(body);

  if (presetKey) {
    appState.activeCameraPreset = presetKey;
  } else {
    appState.activeCameraPreset = null;
  }
  updateCameraPresetButtons();

  if (focus) {
    const position = getBodyWorldPosition(name);
    const radius = getVisualRadiusForMode(body, appState.scaleMode);
    const focusDistance = Math.max(radius * 8, name === 'Sun' ? 32 : 12);
    const verticalOffset = Math.max(radius * 2.4, name === 'Sun' ? 10 : 4);
    focusCameraOn(position, focusDistance, verticalOffset, true);
  }
}

function applyCameraPreset(presetKey) {
  const preset = CAMERA_PRESETS[presetKey];
  if (!preset) {
    return;
  }

  appState.activeCameraPreset = presetKey;
  updateCameraPresetButtons();

  if (preset.focusBody) {
    const position = getBodyWorldPosition(preset.focusBody);
    cameraFocus.desiredTarget.copy(position);
    cameraFocus.desiredOffset.copy(preset.offset.clone());
    cameraFocus.transitioning = true;
    selectBodyByName(preset.focusBody, false, presetKey);
  } else {
    cameraFocus.desiredTarget.copy(preset.target.clone());
    cameraFocus.desiredOffset.copy(preset.position.clone().sub(preset.target));
    cameraFocus.transitioning = true;
  }
}

function updateCameraTransition(delta) {
  if (!cameraFocus.transitioning) {
    return;
  }

  const lerpAlpha = 1 - Math.pow(0.001, delta * 2.2);
  cameraFocus.currentTarget.lerp(cameraFocus.desiredTarget, lerpAlpha);
  cameraFocus.currentOffset.lerp(cameraFocus.desiredOffset, lerpAlpha);

  controls.target.copy(cameraFocus.currentTarget);
  camera.position.copy(cameraFocus.currentTarget).add(cameraFocus.currentOffset);
  controls.update();

  if (
    cameraFocus.currentTarget.distanceTo(cameraFocus.desiredTarget) < 0.03 &&
    cameraFocus.currentOffset.distanceTo(cameraFocus.desiredOffset) < 0.03
  ) {
    cameraFocus.currentTarget.copy(cameraFocus.desiredTarget);
    cameraFocus.currentOffset.copy(cameraFocus.desiredOffset);
    controls.target.copy(cameraFocus.currentTarget);
    camera.position.copy(cameraFocus.currentTarget).add(cameraFocus.currentOffset);
    controls.update();
    cameraFocus.transitioning = false;
  }
}

function updateLabels() {
  if (!appState.showLabels) {
    return;
  }

  const width = container.clientWidth;
  const height = container.clientHeight;
  const cameraDirection = new THREE.Vector3();
  camera.getWorldDirection(cameraDirection);

  labelObjects.forEach((label, name) => {
    const position = getBodyWorldPosition(name);
    const screenPosition = position.clone().project(camera);
    const toBody = position.clone().sub(camera.position);
    const inFront = toBody.dot(cameraDirection) > 0;
    const withinView = screenPosition.z > -1 && screenPosition.z < 1;

    if (!inFront || !withinView) {
      label.classList.add('hidden');
      return;
    }

    const x = (screenPosition.x * 0.5 + 0.5) * width;
    const y = (-screenPosition.y * 0.5 + 0.5) * height;
    const body = bodyDataByName.get(name);
    const radius = getVisualRadiusForMode(body, appState.scaleMode);
    const yOffset = Math.max(12, radius * 3.5);

    if (x < -40 || x > width + 40 || y < -40 || y > height + 40) {
      label.classList.add('hidden');
      return;
    }

    label.classList.remove('hidden');
    label.style.transform = `translate(-50%, -50%) translate(${x}px, ${y - yOffset}px)`;
  });
}

function handlePointerSelect(event) {
  const rect = renderer.domElement.getBoundingClientRect();
  pointer.x = ((event.clientX - rect.left) / rect.width) * 2 - 1;
  pointer.y = -((event.clientY - rect.top) / rect.height) * 2 + 1;

  raycaster.setFromCamera(pointer, camera);
  const meshes = Array.from(bodyObjects.values()).map((entry) => entry.mesh);
  const intersections = raycaster.intersectObjects(meshes, false);

  if (intersections.length > 0) {
    const bodyName = intersections[0].object.userData.bodyName;
    if (bodyName) {
      selectBodyByName(bodyName, true, null);
    }
  }
}

buildSolarSystem();
populateBodySummary();
applyScaleMode(appState.scaleMode);
speedValue.textContent = String(appState.timeSpeed);
updatePlaybackChip();
updateOrbitVisibility();
updateLabelVisibility();
applySeasonPreset('spring');
applyCameraPreset('overview');

const clock = new THREE.Clock();

function animate() {
  const delta = clock.getDelta();
  const elapsed = clock.elapsedTime;

  if (appState.isPlaying && appState.timeSpeed > 0) {
    appState.simDays += delta * appState.timeSpeed;
    if (appState.seasonLockEnabled) {
      appState.seasonLockEnabled = false;
      updateSeasonButtons();
      updateSeasonChip();
    }
  }

  stars.rotation.y = elapsed * 0.01;
  accentStars.rotation.y = -elapsed * 0.015;

  bodyObjects.forEach((entry, name) => {
    if (name === 'Earth') {
      return;
    }

    if (entry.body.orbitDays && entry.body.orbitDays > 0) {
      entry.pivot.rotation.y = (entry.body.initialAngle || 0) + (appState.simDays / entry.body.orbitDays) * Math.PI * 2;
    }

    if (entry.body.rotationHours && entry.body.rotationHours !== 0) {
      const rotationDirection = entry.body.rotationHours < 0 ? -1 : 1;
      const spinCyclesPerDay = 24 / Math.abs(entry.body.rotationHours);
      entry.mesh.rotation.y += delta * spinCyclesPerDay * 0.8 * rotationDirection;
    }

    if (name === 'Sun') {
      entry.mesh.rotation.y += delta * 0.22;
    }
  });

  const earthObject = bodyObjects.get('Earth');
  if (earthObject) {
    const earthAngle = appState.seasonLockEnabled && appState.selectedSeason
      ? SEASON_PRESETS[appState.selectedSeason].angle
      : (earthObject.body.initialAngle || 0) + (appState.simDays / earthObject.body.orbitDays) * Math.PI * 2;

    earthObject.pivot.rotation.y = earthAngle;
    applyEarthSeasonOrientation(earthObject, earthAngle);
  }

  const moonObject = bodyObjects.get('Moon');
  if (moonObject && moonObject.body.orbitDays > 0) {
    moonObject.pivot.rotation.y = (moonObject.body.initialAngle || 0) + (appState.simDays / moonObject.body.orbitDays) * Math.PI * 2;
    const moonSpinCyclesPerDay = 24 / Math.abs(moonObject.body.rotationHours);
    moonObject.mesh.rotation.y += delta * moonSpinCyclesPerDay * 0.8;
  }

  updateCameraTransition(delta);
  controls.update();
  updateLabels();
  renderer.render(scene, camera);
  requestAnimationFrame(animate);
}

function handleResize() {
  const width = container.clientWidth;
  const height = Math.max(container.clientHeight, 240);
  camera.aspect = width / height;
  camera.updateProjectionMatrix();
  renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
  renderer.setSize(width, height, false);
}

playButton.addEventListener('click', () => {
  setPlaying(true);
});

pauseButton.addEventListener('click', () => {
  setPlaying(false);
});

speedRange.addEventListener('input', (event) => {
  appState.timeSpeed = Number(event.target.value);
  speedValue.textContent = String(appState.timeSpeed);
  updatePlaybackChip();
});

scaleModeSelect.addEventListener('change', (event) => {
  applyScaleMode(event.target.value);
});

dateInput.addEventListener('change', (event) => {
  applyDatePreset(event.target.value);
});

labelsToggle.addEventListener('change', (event) => {
  appState.showLabels = event.target.checked;
  updateLabelVisibility();
});

orbitsToggle.addEventListener('change', (event) => {
  appState.showOrbits = event.target.checked;
  updateOrbitVisibility();
});

seasonButtons.forEach((button) => {
  button.addEventListener('click', () => {
    applySeasonPreset(button.dataset.season);
    setPlaying(false);
  });
});

cameraPresetButtons.forEach((button) => {
  button.addEventListener('click', () => {
    applyCameraPreset(button.dataset.preset);
  });
});

renderer.domElement.addEventListener('pointerdown', handlePointerSelect);

window.addEventListener('keydown', (event) => {
  if (event.target && ['INPUT', 'SELECT', 'TEXTAREA'].includes(event.target.tagName)) {
    return;
  }

  if (event.code === 'Space') {
    event.preventDefault();
    setPlaying(!appState.isPlaying);
  }

  if (event.key === 'l' || event.key === 'L') {
    appState.showLabels = !appState.showLabels;
    labelsToggle.checked = appState.showLabels;
    updateLabelVisibility();
  }

  if (event.key === 'o' || event.key === 'O') {
    appState.showOrbits = !appState.showOrbits;
    orbitsToggle.checked = appState.showOrbits;
    updateOrbitVisibility();
  }

  if (event.key === '[') {
    adjustSpeed(-5);
  }

  if (event.key === ']') {
    adjustSpeed(5);
  }

  if (event.key === 'ArrowLeft' && !appState.isPlaying) {
    event.preventDefault();
    stepSimulationDays(-1);
  }

  if (event.key === 'ArrowRight' && !appState.isPlaying) {
    event.preventDefault();
    stepSimulationDays(1);
  }

  if (event.key === '1') {
    applyCameraPreset('overview');
  }
  if (event.key === '2') {
    applyCameraPreset('inner');
  }
  if (event.key === '3') {
    applyCameraPreset('earthmoon');
  }
  if (event.key === '4') {
    applyCameraPreset('outer');
  }
  if (event.key === '5') {
    applyCameraPreset('sun');
  }
});

window.__SOLAR_SYSTEM_DATA__ = solarSystemBodies;
window.__SOLAR_TEXTURE_CACHE__ = textureCache;
window.__SOLAR_BODY_OBJECTS__ = bodyObjects;
window.__SOLAR_APP_STATE__ = appState;
window.__SOLAR_SEASON_PRESETS__ = SEASON_PRESETS;
window.__SOLAR_CAMERA_PRESETS__ = CAMERA_PRESETS;

window.addEventListener('resize', handleResize);
handleResize();
animate();
