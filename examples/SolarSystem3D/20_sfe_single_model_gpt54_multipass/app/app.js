import * as THREE from "https://unpkg.com/three@0.165.0/build/three.module.js";

const canvas = document.querySelector("#scene-canvas");
const container = document.querySelector("#scene-container");

const BODY_VISUAL_CONFIG = {
  star: {
    educationalRadius: 3.4,
    realisticRadius: 3.4,
    orbitRadius: 0,
  },
  rockyPlanet: {
    realisticMultiplier: 0.9,
    minRadius: 0.35,
  },
  terrestrialPlanet: {
    realisticMultiplier: 1,
    minRadius: 0.4,
  },
  gasGiant: {
    realisticMultiplier: 1.15,
    minRadius: 0.95,
  },
  iceGiant: {
    realisticMultiplier: 1.05,
    minRadius: 0.75,
  },
  moon: {
    realisticMultiplier: 0.9,
    minRadius: 0.22,
  },
};

const SOLAR_SYSTEM_BODIES = [
  {
    id: "sun",
    name: "Sun",
    type: "star",
    parentId: null,
    order: 0,
    approximateDistanceAU: 0,
    approximateDistanceLabel: "Center of the solar system",
    orbitalPeriodDays: 0,
    orbitalPeriodLabel: "Not orbiting the Sun in this model",
    rotationPeriodDays: 25,
    rotationPeriodLabel: "~25 Earth days",
    description:
      "The Sun is the star at the center of the solar system and provides the light and energy that drive planetary climates and motion.",
    visualRadius: {
      educational: 3.4,
      realistic: 3.4,
    },
    orbitRadius: {
      educational: 0,
      realistic: 0,
    },
    textureStyle: {
      category: "sun",
      palette: ["#ffefb0", "#ffc857", "#ff8f3a", "#ff5e2b"],
      noiseScale: 0.012,
      flareIntensity: 0.28,
      streakCount: 24,
      glowColor: "#ffb347",
      plasmaRingAlpha: 0.22,
      granulationStrength: 0.38,
    },
  },
  {
    id: "mercury",
    name: "Mercury",
    type: "rocky planet",
    parentId: "sun",
    order: 1,
    approximateDistanceAU: 0.39,
    approximateDistanceLabel: "~0.39 AU from the Sun",
    orbitalPeriodDays: 88,
    orbitalPeriodLabel: "~88 Earth days",
    rotationPeriodDays: 58.6,
    rotationPeriodLabel: "~58.6 Earth days",
    description:
      "Mercury is the smallest planet and has a heavily cratered, rocky surface with extreme day-to-night temperature swings.",
    visualRadius: {
      educational: 0.55,
      realistic: 0.42,
    },
    orbitRadius: {
      educational: 6.5,
      realistic: 10,
    },
    textureStyle: {
      category: "rocky",
      baseColor: "#9f9b94",
      accentColor: "#c8c1b5",
      shadowColor: "#67635d",
      craterColor: "#7e776d",
      noiseScale: 0.03,
      craterDensity: 120,
      craterSize: 0.05,
      speckleColor: "#b8b1a7",
      ridgeColor: "#8f877a",
      mottling: 0.28,
      roughness: 0.95,
    },
  },
  {
    id: "venus",
    name: "Venus",
    type: "rocky planet",
    parentId: "sun",
    order: 2,
    approximateDistanceAU: 0.72,
    approximateDistanceLabel: "~0.72 AU from the Sun",
    orbitalPeriodDays: 225,
    orbitalPeriodLabel: "~225 Earth days",
    rotationPeriodDays: -243,
    rotationPeriodLabel: "~243 Earth days retrograde",
    description:
      "Venus is wrapped in thick reflective clouds, making it bright in the sky while hiding a hot, high-pressure world below.",
    visualRadius: {
      educational: 0.78,
      realistic: 0.62,
    },
    orbitRadius: {
      educational: 9.2,
      realistic: 14,
    },
    textureStyle: {
      category: "venus",
      baseColor: "#d8c08c",
      cloudColor: "#f1e1af",
      hazeColor: "#c59752",
      shadowColor: "#9c7743",
      bandCount: 8,
      swirlStrength: 0.22,
      noiseScale: 0.02,
      cloudContrast: 0.3,
      hazeAlpha: 0.18,
      roughness: 0.92,
    },
  },
  {
    id: "earth",
    name: "Earth",
    type: "rocky planet",
    parentId: "sun",
    order: 3,
    approximateDistanceAU: 1,
    approximateDistanceLabel: "~1 AU from the Sun",
    orbitalPeriodDays: 365,
    orbitalPeriodLabel: "~365 Earth days",
    rotationPeriodDays: 1,
    rotationPeriodLabel: "~24 hours",
    description:
      "Earth is a rocky world with liquid water oceans, varied continents, a dynamic atmosphere, and the only known life.",
    visualRadius: {
      educational: 0.82,
      realistic: 0.66,
    },
    orbitRadius: {
      educational: 12.4,
      realistic: 18,
    },
    textureStyle: {
      category: "earth",
      oceanColor: "#2d6cdf",
      shallowOceanColor: "#4ea4ff",
      landColor: "#4f8d45",
      desertColor: "#a78652",
      cloudColor: "#f3f7ff",
      iceColor: "#d7eefb",
      noiseScale: 0.018,
      cloudDensity: 0.18,
      landCoverage: 0.34,
      forestColor: "#356e34",
      mountainColor: "#7b715f",
      atmosphereColor: "#8ed2ff",
      roughness: 0.82,
    },
  },
  {
    id: "moon",
    name: "Moon",
    type: "moon",
    parentId: "earth",
    order: 4,
    approximateDistanceAU: 0,
    approximateDistanceLabel: "~384,400 km from Earth",
    orbitalPeriodDays: 27.3,
    orbitalPeriodLabel: "~27.3 Earth days",
    rotationPeriodDays: 27.3,
    rotationPeriodLabel: "~27.3 Earth days",
    description:
      "Earth's Moon is a rocky natural satellite with a gray, cratered surface and a synchronous rotation that keeps one face toward Earth.",
    visualRadius: {
      educational: 0.24,
      realistic: 0.22,
    },
    orbitRadius: {
      educational: 1.35,
      realistic: 1.1,
    },
    textureStyle: {
      category: "moon",
      baseColor: "#b8b8bc",
      accentColor: "#dddddf",
      shadowColor: "#7b7b82",
      craterColor: "#8e8e95",
      noiseScale: 0.028,
      craterDensity: 150,
      craterSize: 0.04,
      mariaColor: "#9d9da3",
      ridgeColor: "#d4d4d8",
      roughness: 0.96,
    },
  },
  {
    id: "mars",
    name: "Mars",
    type: "rocky planet",
    parentId: "sun",
    order: 5,
    approximateDistanceAU: 1.52,
    approximateDistanceLabel: "~1.52 AU from the Sun",
    orbitalPeriodDays: 687,
    orbitalPeriodLabel: "~687 Earth days",
    rotationPeriodDays: 1.03,
    rotationPeriodLabel: "~24.6 hours",
    description:
      "Mars is a cold desert world with iron-rich dust, polar caps, giant volcanoes, and evidence of ancient flowing water.",
    visualRadius: {
      educational: 0.68,
      realistic: 0.5,
    },
    orbitRadius: {
      educational: 16,
      realistic: 24,
    },
    textureStyle: {
      category: "mars",
      baseColor: "#b44d2d",
      accentColor: "#db7a43",
      shadowColor: "#7a2d18",
      polarColor: "#f3e4d4",
      darkRegionColor: "#6a3423",
      noiseScale: 0.022,
      dustColor: "#cf8b54",
      canyonColor: "#5b2418",
      roughness: 0.9,
    },
  },
  {
    id: "jupiter",
    name: "Jupiter",
    type: "gas giant",
    parentId: "sun",
    order: 6,
    approximateDistanceAU: 5.2,
    approximateDistanceLabel: "~5.2 AU from the Sun",
    orbitalPeriodDays: 4333,
    orbitalPeriodLabel: "~11.9 Earth years",
    rotationPeriodDays: 0.41,
    rotationPeriodLabel: "~9.9 hours",
    description:
      "Jupiter is the largest planet, a fast-spinning gas giant with layered cloud bands and powerful long-lived storms.",
    visualRadius: {
      educational: 1.95,
      realistic: 1.55,
    },
    orbitRadius: {
      educational: 22.5,
      realistic: 38,
    },
    textureStyle: {
      category: "jupiter",
      bandColors: ["#e9d2a5", "#cfa97d", "#f2e2bf", "#a96a48", "#d7b48c"],
      stormColor: "#b55a3d",
      bandCount: 12,
      noiseScale: 0.014,
      stormSize: 0.16,
      stormHighlightColor: "#e4a98b",
      turbulenceStrength: 0.28,
      roughness: 0.72,
    },
  },
  {
    id: "saturn",
    name: "Saturn",
    type: "gas giant",
    parentId: "sun",
    order: 7,
    approximateDistanceAU: 9.58,
    approximateDistanceLabel: "~9.58 AU from the Sun",
    orbitalPeriodDays: 10759,
    orbitalPeriodLabel: "~29.5 Earth years",
    rotationPeriodDays: 0.45,
    rotationPeriodLabel: "~10.7 hours",
    description:
      "Saturn is a gas giant known for its broad ring system, pale golden atmosphere, and visible banded cloud layers.",
    visualRadius: {
      educational: 1.72,
      realistic: 1.36,
    },
    orbitRadius: {
      educational: 29,
      realistic: 52,
    },
    textureStyle: {
      category: "saturn",
      bandColors: ["#ead8a2", "#d4b57b", "#f2e7c7", "#bc9661", "#e5c992"],
      ringColors: ["#f6edcf", "#c8b083", "#9f845e", "#e3d4b0"],
      bandCount: 11,
      noiseScale: 0.012,
      ringTiltDegrees: 26.7,
      ringContrast: 0.26,
      atmosphereHazeColor: "#f3e8c4",
      roughness: 0.76,
    },
  },
  {
    id: "uranus",
    name: "Uranus",
    type: "ice giant",
    parentId: "sun",
    order: 8,
    approximateDistanceAU: 19.2,
    approximateDistanceLabel: "~19.2 AU from the Sun",
    orbitalPeriodDays: 30687,
    orbitalPeriodLabel: "~84 Earth years",
    rotationPeriodDays: -0.72,
    rotationPeriodLabel: "~17.2 hours retrograde",
    description:
      "Uranus is an ice giant with a blue-green atmosphere and an extreme axial tilt that makes it rotate on its side.",
    visualRadius: {
      educational: 1.18,
      realistic: 0.96,
    },
    orbitRadius: {
      educational: 35.5,
      realistic: 68,
    },
    textureStyle: {
      category: "uranus",
      baseColor: "#93e0dc",
      accentColor: "#b8f1ee",
      shadowColor: "#5db6bb",
      bandCount: 6,
      noiseScale: 0.01,
      hazeColor: "#d7fbfa",
      softness: 0.42,
      roughness: 0.68,
    },
  },
  {
    id: "neptune",
    name: "Neptune",
    type: "ice giant",
    parentId: "sun",
    order: 9,
    approximateDistanceAU: 30.05,
    approximateDistanceLabel: "~30.05 AU from the Sun",
    orbitalPeriodDays: 60190,
    orbitalPeriodLabel: "~164.8 Earth years",
    rotationPeriodDays: 0.67,
    rotationPeriodLabel: "~16.1 hours",
    description:
      "Neptune is a deep blue ice giant with strong winds, dark storm systems, and a colder, more distant atmosphere than Uranus.",
    visualRadius: {
      educational: 1.14,
      realistic: 0.93,
    },
    orbitRadius: {
      educational: 42,
      realistic: 82,
    },
    textureStyle: {
      category: "neptune",
      baseColor: "#2c63d6",
      accentColor: "#5d93ff",
      shadowColor: "#1f3892",
      stormColor: "#86b8ff",
      bandCount: 7,
      noiseScale: 0.012,
      deepBandColor: "#18317a",
      turbulenceStrength: 0.24,
      roughness: 0.66,
    },
  },
];

function createNoiseValue(x, y, scale = 1) {
  const value =
    Math.sin(x * 12.9898 * scale + y * 78.233 * scale) * 43758.5453;
  return value - Math.floor(value);
}

function fractalNoise(x, y, scale = 0.02, octaves = 4, persistence = 0.5) {
  let total = 0;
  let amplitude = 1;
  let frequency = 1;
  let normalization = 0;

  for (let i = 0; i < octaves; i += 1) {
    total += createNoiseValue(x * frequency, y * frequency, scale) * amplitude;
    normalization += amplitude;
    amplitude *= persistence;
    frequency *= 2;
  }

  return normalization === 0 ? 0 : total / normalization;
}

function mixColor(colorA, colorB, amount) {
  const a = new THREE.Color(colorA);
  const b = new THREE.Color(colorB);
  return a.lerp(b, amount);
}

function colorToCss(color) {
  if (typeof color === "string") {
    return color;
  }

  if (color instanceof THREE.Color) {
    return `#${color.getHexString()}`;
  }

  return "#888888";
}

function clamp01(value) {
  return Math.min(1, Math.max(0, value));
}

function samplePalette(palette, t) {
  if (palette.length === 0) {
    return new THREE.Color("#888888");
  }

  if (palette.length === 1) {
    return new THREE.Color(palette[0]);
  }

  const normalized = clamp01(t);
  const scaled = normalized * (palette.length - 1);
  const index = Math.floor(scaled);
  const nextIndex = Math.min(index + 1, palette.length - 1);
  const amount = scaled - index;
  return mixColor(palette[index], palette[nextIndex], amount);
}

function drawNoiseLayer(
  context,
  width,
  height,
  palette,
  scale,
  alpha = 0.2,
  options = {},
) {
  const {
    octaves = 3,
    persistence = 0.55,
    compositeOperation = "source-over",
  } = options;

  context.globalCompositeOperation = compositeOperation;

  for (let y = 0; y < height; y += 1) {
    for (let x = 0; x < width; x += 1) {
      const noise = fractalNoise(x, y, scale, octaves, persistence);
      const color = samplePalette(palette, noise);
      context.fillStyle = colorToCss(color);
      context.globalAlpha = alpha * (0.55 + noise * 0.9);
      context.fillRect(x, y, 1, 1);
    }
  }

  context.globalAlpha = 1;
  context.globalCompositeOperation = "source-over";
}

function drawBands(
  context,
  width,
  height,
  colors,
  bandCount,
  noiseScale = 0.01,
  options = {},
) {
  const {
    wobbleStrength = 0.18,
    blendStrength = 0.55,
    turbulence = 0.12,
  } = options;

  for (let y = 0; y < height; y += 1) {
    const normalizedY = y / Math.max(height - 1, 1);
    const bandIndex = Math.floor(normalizedY * bandCount) % colors.length;
    const nextColor = colors[(bandIndex + 1) % colors.length];
    const t = (normalizedY * bandCount) % 1;
    const baseColor = mixColor(colors[bandIndex], nextColor, t * blendStrength);
    const wobble =
      (fractalNoise(y, bandIndex * 10, noiseScale, 4, 0.55) - 0.5) *
      wobbleStrength;
    const turbulenceNoise =
      (fractalNoise(y + 32, bandIndex * 17, noiseScale * 1.8, 3, 0.6) - 0.5) *
      turbulence;
    const shadedColor = baseColor.offsetHSL(
      0,
      wobble * 0.08,
      wobble * 0.12 + turbulenceNoise,
    );
    context.fillStyle = `#${shadedColor.getHexString()}`;
    context.fillRect(0, y, width, 1);
  }
}

function drawSpeckles(
  context,
  width,
  height,
  color,
  density,
  alphaRange = [0.08, 0.2],
) {
  const count = Math.floor(width * height * density);

  for (let i = 0; i < count; i += 1) {
    const px = createNoiseValue(i, 7.1, 0.71) * width;
    const py = createNoiseValue(i, 13.7, 0.59) * height;
    const radius = 0.5 + createNoiseValue(i, 23.9, 0.33) * 1.8;

    context.globalAlpha =
      alphaRange[0] +
      createNoiseValue(i, 41.2, 0.47) * (alphaRange[1] - alphaRange[0]);
    context.fillStyle = color;
    context.beginPath();
    context.arc(px, py, radius, 0, Math.PI * 2);
    context.fill();
  }

  context.globalAlpha = 1;
}

function drawCraterField(
  context,
  width,
  height,
  craterDensity,
  craterSize,
  craterColor,
  options = {},
) {
  const {
    highlightColor = "#ffffff",
    floorColor = null,
    alpha = 0.22,
  } = options;
  const count = craterDensity;

  for (let i = 0; i < count; i += 1) {
    const px = createNoiseValue(i, 17.2, 0.37) * width;
    const py = createNoiseValue(i, 48.3, 0.29) * height;
    const radius = Math.max(
      1.5,
      (createNoiseValue(i, 92.7, 0.41) * craterSize + craterSize * 0.35) * width,
    );

    context.globalAlpha = alpha;
    context.fillStyle = craterColor;
    context.beginPath();
    context.arc(px, py, radius, 0, Math.PI * 2);
    context.fill();

    if (floorColor) {
      context.globalAlpha = alpha * 0.6;
      context.fillStyle = floorColor;
      context.beginPath();
      context.arc(
        px + radius * 0.06,
        py + radius * 0.05,
        radius * 0.56,
        0,
        Math.PI * 2,
      );
      context.fill();
    }

    context.globalAlpha = 0.12;
    context.strokeStyle = highlightColor;
    context.lineWidth = Math.max(0.8, radius * 0.08);
    context.beginPath();
    context.arc(
      px - radius * 0.12,
      py - radius * 0.12,
      radius * 0.78,
      0,
      Math.PI * 2,
    );
    context.stroke();
  }

  context.globalAlpha = 1;
}

function drawSwirlBands(
  context,
  width,
  height,
  colors,
  bandCount,
  noiseScale,
  swirlStrength,
) {
  for (let y = 0; y < height; y += 1) {
    for (let x = 0; x < width; x += 1) {
      const twist =
        (fractalNoise(x + 50, y + 10, noiseScale * 1.2, 4, 0.55) - 0.5) *
        swirlStrength;
      const normalizedY = clamp01(y / Math.max(height - 1, 1) + twist);
      const bandPosition = (normalizedY * bandCount) % 1;
      const bandIndex = Math.floor(normalizedY * bandCount) % colors.length;
      const nextColor = colors[(bandIndex + 1) % colors.length];
      const color = mixColor(colors[bandIndex], nextColor, bandPosition);
      context.fillStyle = colorToCss(color);
      context.fillRect(x, y, 1, 1);
    }
  }
}

function drawPolarCaps(context, width, height, color, capHeightRatio, alpha = 0.7) {
  const capHeight = height * capHeightRatio;
  context.fillStyle = color;
  context.globalAlpha = alpha;

  context.beginPath();
  context.moveTo(0, 0);
  for (let x = 0; x <= width; x += 1) {
    const wave = Math.sin((x / width) * Math.PI * 4) * capHeight * 0.12;
    context.lineTo(x, capHeight + wave);
  }
  context.lineTo(width, 0);
  context.closePath();
  context.fill();

  context.beginPath();
  context.moveTo(0, height);
  for (let x = 0; x <= width; x += 1) {
    const wave = Math.sin((x / width) * Math.PI * 5 + 1.2) * capHeight * 0.12;
    context.lineTo(x, height - capHeight + wave);
  }
  context.lineTo(width, height);
  context.closePath();
  context.fill();

  context.globalAlpha = 1;
}

function drawEllipticalStorm(
  context,
  centerX,
  centerY,
  radiusX,
  radiusY,
  fillColor,
  highlightColor,
  rotation = 0,
) {
  context.globalAlpha = 0.78;
  context.fillStyle = fillColor;
  context.beginPath();
  context.ellipse(centerX, centerY, radiusX, radiusY, rotation, 0, Math.PI * 2);
  context.fill();

  context.globalAlpha = 0.28;
  context.fillStyle = highlightColor;
  context.beginPath();
  context.ellipse(
    centerX - radiusX * 0.14,
    centerY - radiusY * 0.1,
    radiusX * 0.65,
    radiusY * 0.48,
    rotation,
    0,
    Math.PI * 2,
  );
  context.fill();

  context.globalAlpha = 1;
}

function drawSoftHaze(context, width, height, color, alpha = 0.12) {
  const gradient = context.createRadialGradient(
    width * 0.5,
    height * 0.5,
    width * 0.12,
    width * 0.5,
    height * 0.5,
    width * 0.65,
  );
  gradient.addColorStop(0, "rgba(255,255,255,0)");
  gradient.addColorStop(0.7, `${color}00`);
  gradient.addColorStop(1, `${color}55`);
  context.globalAlpha = alpha;
  context.fillStyle = gradient;
  context.fillRect(0, 0, width, height);
  context.globalAlpha = 1;
}

function createRingTexture(ringColors, size = 1024) {
  const textureCanvas = document.createElement("canvas");
  textureCanvas.width = size;
  textureCanvas.height = size;
  const context = textureCanvas.getContext("2d");

  if (!context) {
    return null;
  }

  for (let x = 0; x < size; x += 1) {
    const normalized = x / Math.max(size - 1, 1);
    const bandNoise = fractalNoise(x, 4, 0.02, 4, 0.55);
    const streakNoise = fractalNoise(x + 200, 30, 0.06, 3, 0.48);
    const color = samplePalette(
      ringColors,
      clamp01(normalized * 0.9 + bandNoise * 0.15),
    );
    const alpha = clamp01(0.22 + bandNoise * 0.45 + streakNoise * 0.18);

    context.fillStyle = colorToCss(color);
    context.globalAlpha = alpha;
    context.fillRect(x, 0, 1, size);
  }

  context.globalAlpha = 1;

  const texture = new THREE.CanvasTexture(textureCanvas);
  texture.colorSpace = THREE.SRGBColorSpace;
  texture.wrapS = THREE.ClampToEdgeWrapping;
  texture.wrapT = THREE.ClampToEdgeWrapping;
  texture.anisotropy = 4;
  texture.needsUpdate = true;
  return texture;
}

function createBodyTexture(style, size = 512) {
  const textureCanvas = document.createElement("canvas");
  textureCanvas.width = size;
  textureCanvas.height = size;
  const context = textureCanvas.getContext("2d");

  if (!context) {
    return null;
  }

  switch (style.category) {
    case "sun": {
      const gradient = context.createRadialGradient(
        size * 0.5,
        size * 0.5,
        size * 0.08,
        size * 0.5,
        size * 0.5,
        size * 0.5,
      );
      gradient.addColorStop(0, style.palette[0]);
      gradient.addColorStop(0.4, style.palette[1]);
      gradient.addColorStop(0.75, style.palette[2]);
      gradient.addColorStop(1, style.palette[3]);
      context.fillStyle = gradient;
      context.fillRect(0, 0, size, size);

      drawNoiseLayer(context, size, size, style.palette, style.noiseScale, 0.16, {
        octaves: 5,
        persistence: 0.58,
        compositeOperation: "screen",
      });

      drawNoiseLayer(
        context,
        size,
        size,
        [style.palette[3], style.palette[2], style.palette[1]],
        style.noiseScale * 2.1,
        style.granulationStrength,
        {
          octaves: 4,
          persistence: 0.52,
          compositeOperation: "overlay",
        },
      );

      context.globalAlpha = style.plasmaRingAlpha;
      context.strokeStyle = style.glowColor;
      context.lineWidth = size * 0.055;
      context.beginPath();
      context.arc(size * 0.5, size * 0.5, size * 0.39, 0, Math.PI * 2);
      context.stroke();
      context.globalAlpha = 1;

      context.globalCompositeOperation = "screen";
      for (let i = 0; i < style.streakCount; i += 1) {
        const angle = (i / style.streakCount) * Math.PI * 2;
        const x = size * 0.5 + Math.cos(angle) * size * 0.34;
        const y = size * 0.5 + Math.sin(angle) * size * 0.34;
        const flare = context.createRadialGradient(x, y, 0, x, y, size * 0.16);
        flare.addColorStop(0, "rgba(255,255,255,0.2)");
        flare.addColorStop(1, "rgba(255,179,71,0)");
        context.fillStyle = flare;
        context.beginPath();
        context.arc(x, y, size * 0.16, 0, Math.PI * 2);
        context.fill();
      }
      context.globalCompositeOperation = "source-over";
      break;
    }
    case "rocky":
    case "moon": {
      context.fillStyle = style.baseColor;
      context.fillRect(0, 0, size, size);

      drawNoiseLayer(
        context,
        size,
        size,
        [style.baseColor, style.accentColor, style.shadowColor],
        style.noiseScale,
        0.28,
        {
          octaves: 4,
          persistence: 0.56,
        },
      );

      if (style.speckleColor) {
        drawSpeckles(context, size, size, style.speckleColor, 0.0022);
      }

      if (style.mariaColor) {
        drawNoiseLayer(
          context,
          size,
          size,
          [style.baseColor, style.mariaColor, style.shadowColor],
          style.noiseScale * 0.8,
          0.12,
          {
            octaves: 3,
            persistence: 0.62,
            compositeOperation: "multiply",
          },
        );
      }

      if (style.mottling) {
        drawNoiseLayer(
          context,
          size,
          size,
          [style.baseColor, style.ridgeColor || style.accentColor, style.shadowColor],
          style.noiseScale * 1.7,
          style.mottling,
          {
            octaves: 4,
            persistence: 0.48,
            compositeOperation: "soft-light",
          },
        );
      }

      drawCraterField(
        context,
        size,
        size,
        style.craterDensity,
        style.craterSize,
        style.craterColor,
        {
          highlightColor: style.ridgeColor || "#ffffff",
          floorColor: style.shadowColor,
          alpha: 0.2,
        },
      );
      break;
    }
    case "venus": {
      context.fillStyle = style.baseColor;
      context.fillRect(0, 0, size, size);

      drawSwirlBands(
        context,
        size,
        size,
        [style.baseColor, style.cloudColor, style.hazeColor, style.shadowColor],
        style.bandCount,
        style.noiseScale * 1.2,
        style.swirlStrength,
      );

      drawNoiseLayer(
        context,
        size,
        size,
        [style.cloudColor, style.hazeColor, style.baseColor],
        style.noiseScale,
        style.cloudContrast,
        {
          octaves: 4,
          persistence: 0.56,
          compositeOperation: "screen",
        },
      );

      drawSoftHaze(context, size, size, style.hazeColor, style.hazeAlpha);
      break;
    }
    case "earth": {
      context.fillStyle = style.oceanColor;
      context.fillRect(0, 0, size, size);

      for (let y = 0; y < size; y += 1) {
        for (let x = 0; x < size; x += 1) {
          const landNoise = fractalNoise(x, y, style.noiseScale, 5, 0.55);
          const climateNoise = fractalNoise(
            x + 100,
            y + 100,
            style.noiseScale * 1.4,
            4,
            0.58,
          );
          const terrainNoise = fractalNoise(
            x + 220,
            y + 24,
            style.noiseScale * 2,
            3,
            0.52,
          );

          if (landNoise > 1 - style.landCoverage) {
            if (terrainNoise > 0.78) {
              context.fillStyle = style.mountainColor;
            } else if (climateNoise > 0.68) {
              context.fillStyle = style.forestColor;
            } else if (climateNoise > 0.52) {
              context.fillStyle = style.landColor;
            } else {
              context.fillStyle = style.desertColor;
            }
            context.fillRect(x, y, 1, 1);
          } else if (climateNoise > 0.82) {
            context.fillStyle = style.shallowOceanColor;
            context.fillRect(x, y, 1, 1);
          }

          if (Math.abs(y / size - 0.5) > 0.38 && climateNoise > 0.66) {
            context.fillStyle = style.iceColor;
            context.fillRect(x, y, 1, 1);
          }

          if (
            fractalNoise(x + 200, y + 50, style.noiseScale * 2.2, 4, 0.56) >
            1 - style.cloudDensity
          ) {
            context.globalAlpha = 0.65;
            context.fillStyle = style.cloudColor;
            context.fillRect(x, y, 1, 1);
          }
        }
      }

      drawSoftHaze(context, size, size, style.atmosphereColor, 0.08);
      context.globalAlpha = 1;
      break;
    }
    case "mars": {
      context.fillStyle = style.baseColor;
      context.fillRect(0, 0, size, size);

      drawNoiseLayer(
        context,
        size,
        size,
        [
          style.baseColor,
          style.accentColor,
          style.darkRegionColor,
          style.shadowColor,
        ],
        style.noiseScale,
        0.26,
        {
          octaves: 4,
          persistence: 0.54,
        },
      );

      drawNoiseLayer(
        context,
        size,
        size,
        [style.baseColor, style.dustColor, style.accentColor],
        style.noiseScale * 1.8,
        0.14,
        {
          octaves: 3,
          persistence: 0.48,
          compositeOperation: "screen",
        },
      );

      drawNoiseLayer(
        context,
        size,
        size,
        [style.canyonColor, style.darkRegionColor, style.shadowColor],
        style.noiseScale * 1.35,
        0.1,
        {
          octaves: 4,
          persistence: 0.58,
          compositeOperation: "multiply",
        },
      );

      drawPolarCaps(context, size, size, style.polarColor, 0.08, 0.72);
      break;
    }
    case "jupiter":
    case "saturn": {
      drawBands(context, size, size, style.bandColors, style.bandCount, style.noiseScale, {
        wobbleStrength: 0.24,
        blendStrength: 0.62,
        turbulence: style.turbulenceStrength || 0.12,
      });

      drawNoiseLayer(
        context,
        size,
        size,
        style.bandColors,
        style.noiseScale * 2.4,
        0.08,
        {
          octaves: 3,
          persistence: 0.55,
          compositeOperation: "soft-light",
        },
      );

      if (style.category === "jupiter") {
        drawEllipticalStorm(
          context,
          size * 0.72,
          size * 0.58,
          size * style.stormSize,
          size * style.stormSize * 0.62,
          style.stormColor,
          style.stormHighlightColor,
          -0.2,
        );
      } else if (style.atmosphereHazeColor) {
        drawSoftHaze(context, size, size, style.atmosphereHazeColor, 0.06);
      }
      break;
    }
    case "uranus":
    case "neptune": {
      drawBands(
        context,
        size,
        size,
        style.deepBandColor
          ? [style.shadowColor, style.baseColor, style.accentColor, style.deepBandColor]
          : [style.baseColor, style.accentColor, style.shadowColor],
        style.bandCount,
        style.noiseScale,
        {
          wobbleStrength: 0.09,
          blendStrength: 0.48,
          turbulence: style.turbulenceStrength || 0.08,
        },
      );

      drawNoiseLayer(
        context,
        size,
        size,
        [style.baseColor, style.accentColor, style.shadowColor],
        style.noiseScale * 2.2,
        0.08,
        {
          octaves: 3,
          persistence: 0.5,
          compositeOperation: "soft-light",
        },
      );

      if (style.stormColor) {
        drawEllipticalStorm(
          context,
          size * 0.68,
          size * 0.44,
          size * 0.09,
          size * 0.05,
          style.stormColor,
          style.accentColor,
          -0.18,
        );
      } else if (style.hazeColor) {
        drawSoftHaze(context, size, size, style.hazeColor, style.softness * 0.18);
      }

      break;
    }
    default:
      context.fillStyle = "#888888";
      context.fillRect(0, 0, size, size);
  }

  const texture = new THREE.CanvasTexture(textureCanvas);
  texture.colorSpace = THREE.SRGBColorSpace;
  texture.wrapS = THREE.RepeatWrapping;
  texture.wrapT = THREE.ClampToEdgeWrapping;
  texture.anisotropy = 4;
  texture.needsUpdate = true;
  return texture;
}

const bodyTextureCache = new Map();
const ringTextureCache = new Map();

function getTextureCacheKey(body, size = 512) {
  return `${body.id}:${size}`;
}

function getRingTextureCacheKey(body, size = 1024) {
  return `${body.id}:ring:${size}`;
}

function getBodyTexture(body) {
  const size = body.textureStyle.category === "sun" ? 1024 : 512;
  const cacheKey = getTextureCacheKey(body, size);

  if (!bodyTextureCache.has(cacheKey)) {
    bodyTextureCache.set(cacheKey, createBodyTexture(body.textureStyle, size));
  }

  return bodyTextureCache.get(cacheKey);
}

function getRingTexture(body) {
  if (!body.textureStyle.ringColors) {
    return null;
  }

  const size = 1024;
  const cacheKey = getRingTextureCacheKey(body, size);

  if (!ringTextureCache.has(cacheKey)) {
    ringTextureCache.set(
      cacheKey,
      createRingTexture(body.textureStyle.ringColors, size),
    );
  }

  return ringTextureCache.get(cacheKey);
}

function prewarmBodyTextures() {
  SOLAR_SYSTEM_BODIES.forEach((body) => {
    getBodyTexture(body);
    getRingTexture(body);
  });
}

prewarmBodyTextures();

const renderer = new THREE.WebGLRenderer({
  canvas,
  antialias: true,
  alpha: false,
});
renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
renderer.setSize(container.clientWidth, container.clientHeight, false);
renderer.outputColorSpace = THREE.SRGBColorSpace;

const scene = new THREE.Scene();
scene.background = new THREE.Color(0x03050c);

const camera = new THREE.PerspectiveCamera(
  50,
  container.clientWidth / Math.max(container.clientHeight, 1),
  0.1,
  2000,
);
camera.position.set(0, 18, 42);

const ambientLight = new THREE.AmbientLight(0x8ea6ff, 0.65);
scene.add(ambientLight);

const sunLight = new THREE.PointLight(0xffffff, 2.8, 0, 2);
sunLight.position.set(0, 0, 0);
scene.add(sunLight);

function getMaterialForBody(body) {
  const baseConfig = {
    map: getBodyTexture(body),
    color: 0xffffff,
    metalness: 0,
    roughness: body.textureStyle.roughness ?? 0.9,
  };

  if (body.textureStyle.category === "sun") {
    return new THREE.MeshStandardMaterial({
      ...baseConfig,
      emissive: 0xffa726,
      emissiveIntensity: 1.15,
    });
  }

  return new THREE.MeshStandardMaterial(baseConfig);
}

function getSegmentsForBody(body) {
  switch (body.textureStyle.category) {
    case "sun":
      return 48;
    case "jupiter":
    case "saturn":
      return 42;
    default:
      return 32;
  }
}

function createOrbitLine(radius, color = 0x5f7399, opacity = 0.45) {
  const curve = new THREE.EllipseCurve(
    0,
    0,
    radius,
    radius,
    0,
    Math.PI * 2,
    false,
    0,
  );
  const points = curve.getPoints(180);
  const positions = [];

  points.forEach((point) => {
    positions.push(point.x, 0, point.y);
  });

  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute(
    "position",
    new THREE.Float32BufferAttribute(positions, 3),
  );

  return new THREE.LineLoop(
    geometry,
    new THREE.LineBasicMaterial({
      color,
      transparent: true,
      opacity,
    }),
  );
}

function createPreviewSystem() {
  const bodyMeshes = new Map();
  const bodyGroups = new Map();
  const bodyObjects = [];
  const previewGroup = new THREE.Group();
  scene.add(previewGroup);

  const sunData = SOLAR_SYSTEM_BODIES.find((body) => body.id === "sun");
  const earthData = SOLAR_SYSTEM_BODIES.find((body) => body.id === "earth");
  const moonData = SOLAR_SYSTEM_BODIES.find((body) => body.id === "moon");
  const saturnData = SOLAR_SYSTEM_BODIES.find((body) => body.id === "saturn");

  const sunMesh = new THREE.Mesh(
    new THREE.SphereGeometry(
      sunData.visualRadius.educational,
      getSegmentsForBody(sunData),
      getSegmentsForBody(sunData),
    ),
    getMaterialForBody(sunData),
  );
  sunMesh.userData.bodyId = sunData.id;
  previewGroup.add(sunMesh);
  bodyMeshes.set(sunData.id, sunMesh);
  bodyObjects.push(sunMesh);

  const sampledPlanetIds = ["mercury", "venus", "earth", "mars", "jupiter", "saturn", "uranus", "neptune"];

  sampledPlanetIds.forEach((bodyId) => {
    const body = SOLAR_SYSTEM_BODIES.find((item) => item.id === bodyId);
    if (!body) {
      return;
    }

    const planetGroup = new THREE.Group();
    planetGroup.userData.bodyId = body.id;
    previewGroup.add(planetGroup);
    bodyGroups.set(body.id, planetGroup);

    const orbitLine = createOrbitLine(body.orbitRadius.educational);
    previewGroup.add(orbitLine);

    const mesh = new THREE.Mesh(
      new THREE.SphereGeometry(
        body.visualRadius.educational,
        getSegmentsForBody(body),
        getSegmentsForBody(body),
      ),
      getMaterialForBody(body),
    );
    mesh.userData.bodyId = body.id;
    mesh.position.set(body.orbitRadius.educational, 0, 0);
    planetGroup.add(mesh);
    bodyMeshes.set(body.id, mesh);
    bodyObjects.push(mesh);

    if (body.id === saturnData?.id) {
      const ringTexture = getRingTexture(body);
      const ring = new THREE.Mesh(
        new THREE.RingGeometry(
          body.visualRadius.educational * 1.35,
          body.visualRadius.educational * 2.35,
          96,
        ),
        new THREE.MeshStandardMaterial({
          map: ringTexture,
          color: 0xffffff,
          side: THREE.DoubleSide,
          transparent: true,
          opacity: 0.9,
          roughness: 0.9,
          metalness: 0,
          alphaTest: 0.08,
        }),
      );
      ring.rotation.x = Math.PI / 2;
      ring.rotation.z = THREE.MathUtils.degToRad(
        body.textureStyle.ringTiltDegrees || 26.7,
      );
      mesh.add(ring);
    }

    if (body.id === earthData?.id && moonData) {
      const moonOrbitLine = createOrbitLine(
        moonData.orbitRadius.educational,
        0x7f8baa,
        0.38,
      );
      moonOrbitLine.rotation.x = Math.PI / 2;
      mesh.add(moonOrbitLine);

      const moonPivot = new THREE.Group();
      moonPivot.userData.bodyId = moonData.id;
      mesh.add(moonPivot);
      bodyGroups.set(moonData.id, moonPivot);

      const moonMesh = new THREE.Mesh(
        new THREE.SphereGeometry(
          moonData.visualRadius.educational,
          28,
          28,
        ),
        getMaterialForBody(moonData),
      );
      moonMesh.userData.bodyId = moonData.id;
      moonMesh.position.set(moonData.orbitRadius.educational, 0, 0);
      moonPivot.add(moonMesh);
      bodyMeshes.set(moonData.id, moonMesh);
      bodyObjects.push(moonMesh);
    }
  });

  return {
    root: previewGroup,
    bodyMeshes,
    bodyGroups,
    bodyObjects,
  };
}

const previewSystem = createPreviewSystem();

function createStarField(count = 1800) {
  const positions = new Float32Array(count * 3);
  for (let i = 0; i < count; i += 1) {
    const radius = 350 + Math.random() * 800;
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
    size: 2.2,
    sizeAttenuation: true,
    transparent: true,
    opacity: 0.9,
  });

  return new THREE.Points(geometry, material);
}

scene.add(createStarField());

function onResize() {
  const width = container.clientWidth;
  const height = Math.max(container.clientHeight, 1);
  camera.aspect = width / height;
  camera.updateProjectionMatrix();
  renderer.setSize(width, height, false);
}

window.addEventListener("resize", onResize);

const BODY_DATA_BY_ID = new Map(
  SOLAR_SYSTEM_BODIES.map((body) => [body.id, body]),
);

const appState = {
  bodies: SOLAR_SYSTEM_BODIES,
  bodiesById: BODY_DATA_BY_ID,
  previewSystem,
  bodyVisualConfig: BODY_VISUAL_CONFIG,
  textureCache: bodyTextureCache,
  textureFactory: {
    createNoiseValue,
    fractalNoise,
    drawNoiseLayer,
    drawBands,
    drawCraterField,
    drawSwirlBands,
    drawSpeckles,
    drawPolarCaps,
    drawSoftHaze,
    createRingTexture,
    createBodyTexture,
    getBodyTexture,
  },
};

window.SOLAR_SYSTEM_DATA = appState;

const statusNote = document.querySelector(".status-note");
const selectedPanel = document.querySelector(".selected-panel");

if (statusNote) {
  statusNote.textContent =
    "Preview scene now uses the shared solar-system dataset and procedural body textures";
}

if (selectedPanel) {
  const saturnData = BODY_DATA_BY_ID.get("saturn");

  selectedPanel.innerHTML = `
    <h2 id="selected-body-title">Selected body</h2>
    <p>
      Dataset ready: ${SOLAR_SYSTEM_BODIES.length} bodies with orbital facts,
      parent metadata, cached procedural textures, and reusable Canvas texture
      helpers for stars, rocky worlds, gas giants, ice giants, and the Moon.
    </p>
    <p class="selected-panel-note">
      Current preview: Sun plus representative planet meshes for all eight planets, Earth's Moon, visible orbit guides, and Saturn ring texture scaffolding using the ${saturnData?.name || "Saturn"} style data.
    </p>
  `;
}

const clock = new THREE.Clock();
const bodyAnimationData = SOLAR_SYSTEM_BODIES.filter((body) => body.id !== "sun");

function animate() {
  requestAnimationFrame(animate);

  const elapsed = clock.getElapsedTime();

  const sunMesh = previewSystem.bodyMeshes.get("sun");
  if (sunMesh) {
    sunMesh.rotation.y = elapsed * 0.18;
  }

  bodyAnimationData.forEach((body) => {
    const mesh = previewSystem.bodyMeshes.get(body.id);
    const group = previewSystem.bodyGroups.get(body.id);

    if (mesh) {
      const rotationDirection = body.rotationPeriodDays < 0 ? -1 : 1;
      const rotationMagnitude = 0.08 + 1 / Math.max(Math.abs(body.rotationPeriodDays), 0.5);
      mesh.rotation.y = elapsed * rotationMagnitude * 0.16 * rotationDirection;
    }

    if (!group) {
      return;
    }

    if (body.parentId === "sun") {
      const orbitalSpeed = 10 / Math.max(body.orbitalPeriodDays, 40);
      group.rotation.y = elapsed * orbitalSpeed;
    }

    if (body.parentId === "earth") {
      const orbitalSpeed = 12 / Math.max(body.orbitalPeriodDays, 8);
      group.rotation.y = elapsed * orbitalSpeed;
    }
  });

  renderer.render(scene, camera);
}

onResize();
animate();
