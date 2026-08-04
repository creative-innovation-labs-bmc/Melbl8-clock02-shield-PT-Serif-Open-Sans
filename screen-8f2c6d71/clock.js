'use strict';

/*
  Particle Clock v5
  Efficient vanilla Canvas build for NVIDIA Shield signage.

  Restored from the original visual behaviour:
  - leaves occupy the filled digit area
  - thin architectural outlines move, fade and morph continuously
  - leaves jump and grow briefly on every second
  - digit transitions crossfade and become more unstable

  Main digits and leaf atlas are pre-rendered assets. The Shield does not need
  to rasterise the large font, recolour sprites, or build masks at startup.
*/

const PROFILE = 'shield';
const PROFILES = {
  shield: {
    particlesPerZone: 220,
    targetFps: 30,
    blueprintLayers: 15,
    maxSpeed: 4.1,
    steering: 0.14,
    damping: 0.84,
    driftAmount: 2.4
  },
  safe: {
    particlesPerZone: 180,
    targetFps: 24,
    blueprintLayers: 12,
    maxSpeed: 3.8,
    steering: 0.14,
    damping: 0.84,
    driftAmount: 2.0
  }
};

const CFG = PROFILES[PROFILE];
const BASE_W = 1920;
const BASE_H = 402;
const ZONE_W = BASE_W / 4;
// ============================================================
// NUMBER LAYOUT TUNING
// Internal canvas is 1920 x 402 and is doubled to 3840 x 804.
// y: 232 means the number centre sits at 464 px on the physical wall.
// ============================================================
const NUMBER_LAYOUT = {
  scale: 0.88, // 90% of the previous number size
  y: 242       // 10 internal px lower, equal to 20 px on the wall
};

window.NUMBER_LAYOUT_CONFIG = NUMBER_LAYOUT;
const FRAME_MS = 1000 / CFG.targetFps;
const PARTICLES_PER_ZONE = CFG.particlesPerZone;
const TOTAL_PARTICLES = PARTICLES_PER_ZONE * 4;
const BG = '#1C1B1C';

const OUTLINE_TILE_W = 360;
const OUTLINE_TILE_H = 480;
const OUTLINE_OFFSET = 15;
const OUTLINE_ROTATION = 0.16;
const OUTLINE_SCALE = 0.11;
const TRANSITION_MS = 1850;

const LEAF_TILE = 40;
const LEAF_ATLAS_COLS = 32;
const LEAF_ROTATIONS = 8;
const LEAF_COLOURS = 8;
const LEAF_SIZES = 4;
const LEAF_PULSE_LEVELS = 3;

// ============================================================
// HEARTBEAT TUNING
// Edit only these values to tune the once-per-second pulse.
// You can also change them live in the browser console through:
// window.HEARTBEAT_CONFIG
// ============================================================
const HEARTBEAT = {
  durationMs: 135,       // Beat length. Try 100 to 220.
  peak: 0.72,            // Master intensity. Try 0.50 to 0.85.
  curve: 3.0,            // Higher = sharper/faster falloff. Try 2.0 to 4.5.
  scaleBoost: 0.55,      // Leaf size growth. Effective visible growth is about 20% with peak 0.72.
  joltForce: 4.4,        // Leaf movement away from targets. Try 2.0 to 6.0.
  settleDamping: 0.84    // Lower settles faster. Try 0.78 to 0.90.
};

window.HEARTBEAT_CONFIG = HEARTBEAT;

const layoutCanvas = document.getElementById('layout-layer');
const blueprintCanvas = document.getElementById('blueprint-layer');
const leafCanvas = document.getElementById('leaf-layer');
const layoutCtx = layoutCanvas.getContext('2d', { alpha: false });
const blueprintCtx = blueprintCanvas.getContext('2d', { alpha: true, desynchronized: true });
const leafCtx = leafCanvas.getContext('2d', { alpha: true, desynchronized: true });
blueprintCtx.imageSmoothingEnabled = true;
leafCtx.imageSmoothingEnabled = true;

const x = new Float32Array(TOTAL_PARTICLES);
const y = new Float32Array(TOTAL_PARTICLES);
const tx = new Float32Array(TOTAL_PARTICLES);
const ty = new Float32Array(TOTAL_PARTICLES);
const vx = new Float32Array(TOTAL_PARTICLES);
const vy = new Float32Array(TOTAL_PARTICLES);
const phase = new Float32Array(TOTAL_PARTICLES);
const spin = new Float32Array(TOTAL_PARTICLES);
const baseRotation = new Uint8Array(TOTAL_PARTICLES);
const colourIndex = new Uint8Array(TOTAL_PARTICLES);
const sizeIndex = new Uint8Array(TOTAL_PARTICLES);

const currentDigits = ['', '', '', ''];
const previousDigits = ['', '', '', ''];
const transitionStarted = new Float64Array(4);

let targetData = null;
let outlineGrey = null;
let outlineGreen = null;
let leafAtlas = null;
let footerFont = '700 20px Georgia, serif';
let sideFont = '600 8px Arial, sans-serif';
const FOOTER_X_SCALE = 1.0244;
const SIDE_X_SCALE = 0.9219;
let lastSecond = -1;
let heartbeatStarted = -10000;
let heartbeatSequence = 0;
let lastFrame = 0;

const DEBUG = new URLSearchParams(location.search).get('debug') === '1';
const debugElement = document.getElementById('debug');
let debugFrames = 0;
let debugStarted = performance.now();
let leafDrawAverage = 0;
let blueprintDrawAverage = 0;
window.clockStats = { fps: 0, leafMs: 0, blueprintMs: 0, leaves: TOTAL_PARTICLES };
window.forceHeartbeat = () => triggerHeartbeat(performance.now());
window.applyNumberLayout = () => {
  const nowMs = performance.now();
  for (let zone = 0; zone < 4; zone++) {
    if (currentDigits[zone]) assignDigit(zone, currentDigits[zone], true, nowMs);
  }
  drawBlueprints(nowMs);
  drawLeaves(nowMs);
};
if (DEBUG) debugElement.hidden = false;

function seededRandom(seed) {
  return function random() {
    let t = seed += 0x6D2B79F5;
    t = Math.imul(t ^ t >>> 15, t | 1);
    t ^= t + Math.imul(t ^ t >>> 7, t | 61);
    return ((t ^ t >>> 14) >>> 0) / 4294967296;
  };
}

function loadImage(url) {
  return new Promise((resolve, reject) => {
    const image = new Image();
    image.decoding = 'async';
    image.onload = () => resolve(image);
    image.onerror = reject;
    image.src = url;
  });
}

async function toBitmap(image) {
  if (!('createImageBitmap' in window)) return image;
  try {
    return await createImageBitmap(image);
  } catch {
    return image;
  }
}

async function loadOptionalFont(name, url, cssValue, weight) {
  if (!('FontFace' in window)) return false;
  try {
    const face = new FontFace(name, `url(${url})`, {
      style: 'normal',
      weight: String(weight)
    });
    await face.load();
    document.fonts.add(face);
    if (name === 'ClockFooter') footerFont = `${weight} ${cssValue}px "${name}"`;
    if (name === 'ClockSide') sideFont = `${weight} ${cssValue}px "${name}"`;
    return true;
  } catch {
    return false;
  }
}

function initialiseParticles() {
  const random = seededRandom(20260717);
  for (let zone = 0; zone < 4; zone++) {
    const centreX = zone * ZONE_W + ZONE_W / 2;
    for (let i = 0; i < PARTICLES_PER_ZONE; i++) {
      const index = zone * PARTICLES_PER_ZONE + i;
      x[index] = centreX + (random() - 0.5) * 180;
      y[index] = NUMBER_LAYOUT.y + (random() - 0.5) * 240 * NUMBER_LAYOUT.scale;
      tx[index] = x[index];
      ty[index] = y[index];
      phase[index] = random() * Math.PI * 2;
      spin[index] = 0.35 + random() * 0.8;
      baseRotation[index] = Math.floor(random() * LEAF_ROTATIONS);
      colourIndex[index] = Math.floor(random() * LEAF_COLOURS);
      const q = random();
      sizeIndex[index] = q < 0.16 ? 0 : q < 0.58 ? 1 : q < 0.9 ? 2 : 3;
    }
  }
}

function getDigitTargets(digit) {
  const all = targetData.targets[Number(digit)];
  if (PARTICLES_PER_ZONE === all.length) return all;
  const chosen = new Array(PARTICLES_PER_ZONE);
  const step = all.length / PARTICLES_PER_ZONE;
  for (let i = 0; i < PARTICLES_PER_ZONE; i++) {
    chosen[i] = all[Math.floor(i * step) % all.length];
  }
  return chosen;
}

function assignDigit(zone, digit, snap, nowMs) {
  const points = getDigitTargets(digit);
  const random = seededRandom(411 + zone * 1009 + Number(digit) * 97);
  const centreX = zone * ZONE_W + ZONE_W / 2;
  const start = zone * PARTICLES_PER_ZONE;

  previousDigits[zone] = currentDigits[zone] || String(digit);
  currentDigits[zone] = String(digit);
  transitionStarted[zone] = snap ? nowMs - TRANSITION_MS : nowMs;

  for (let i = 0; i < PARTICLES_PER_ZONE; i++) {
    const index = start + i;
    const point = points[i];
    tx[index] = centreX + point[0] * NUMBER_LAYOUT.scale + (random() - 0.5) * 5;
    ty[index] = NUMBER_LAYOUT.y + point[1] * NUMBER_LAYOUT.scale + (random() - 0.5) * 5;
    if (snap) {
      x[index] = tx[index];
      y[index] = ty[index];
      vx[index] = 0;
      vy[index] = 0;
    }
  }
}

function triggerHeartbeat(nowMs) {
  heartbeatStarted = nowMs;
  heartbeatSequence++;
}

function heartbeatValue(nowMs) {
  const elapsed = nowMs - heartbeatStarted;
  if (elapsed < 0 || elapsed >= HEARTBEAT.durationMs) return 0;
  const linear = 1 - elapsed / HEARTBEAT.durationMs;
  const reducedPeak = linear * HEARTBEAT.peak;
  return Math.pow(reducedPeak, HEARTBEAT.curve);
}

function updateClock(force, nowMs) {
  const now = new Date();
  const hours = String(now.getHours()).padStart(2, '0');
  const minutes = String(now.getMinutes()).padStart(2, '0');
  const digits = [hours[0], hours[1], minutes[0], minutes[1]];
  const second = now.getSeconds();
  let redrawLayout = force;

  if (force || second !== lastSecond) {
    lastSecond = second;
    triggerHeartbeat(nowMs);
    redrawLayout = true;
  }

  for (let zone = 0; zone < 4; zone++) {
    if (force || digits[zone] !== currentDigits[zone]) {
      assignDigit(zone, digits[zone], force, nowMs);
    }
  }

  if (redrawLayout) drawLayout(now);
}

function drawLayout(now) {
  layoutCtx.fillStyle = BG;
  layoutCtx.fillRect(0, 0, BASE_W, BASE_H);

  layoutCtx.strokeStyle = 'rgba(255,255,255,0.07)';
  layoutCtx.lineWidth = 1;
  for (let i = 1; i < 4; i++) {
    const dividerX = Math.round(i * ZONE_W) + 0.5;
    layoutCtx.beginPath();
    layoutCtx.moveTo(dividerX, 0);
    layoutCtx.lineTo(dividerX, BASE_H);
    layoutCtx.stroke();
  }

  const hours = String(now.getHours()).padStart(2, '0');
  const minutes = String(now.getMinutes()).padStart(2, '0');
  const seconds = String(now.getSeconds()).padStart(2, '0');
  const time = `${hours}:${minutes}:${seconds}`;
  const months = ['JANUARY','FEBRUARY','MARCH','APRIL','MAY','JUNE','JULY','AUGUST','SEPTEMBER','OCTOBER','NOVEMBER','DECEMBER'];
  const days = ['SUNDAY','MONDAY','TUESDAY','WEDNESDAY','THURSDAY','FRIDAY','SATURDAY'];
  const date = `${now.getDate()} ${months[now.getMonth()]} ${now.getFullYear()} ${days[now.getDay()]}`;

  layoutCtx.fillStyle = '#fff';
  layoutCtx.font = footerFont;
  layoutCtx.textAlign = 'left';
  layoutCtx.textBaseline = 'alphabetic';
  for (let zone = 0; zone < 4; zone++) {
    layoutCtx.save();
    layoutCtx.translate(zone * ZONE_W + 20, BASE_H - 15);
    layoutCtx.scale(FOOTER_X_SCALE, 1);
    layoutCtx.fillText(time, 0, 0);
    layoutCtx.restore();
  }

  layoutCtx.fillStyle = '#BBC6C3';
  layoutCtx.font = sideFont;
  for (let zone = 0; zone < 4; zone++) {
    const sideX = zone * ZONE_W + ZONE_W - 18;
    layoutCtx.save();
    layoutCtx.translate(sideX, 20);
    layoutCtx.rotate(-Math.PI / 2);
    layoutCtx.scale(SIDE_X_SCALE, 1);
    layoutCtx.textAlign = 'right';
    layoutCtx.textBaseline = 'middle';
    layoutCtx.fillText('MELBOURNE, AUSTRALIA', 0, 0);
    layoutCtx.restore();

    layoutCtx.save();
    layoutCtx.translate(sideX, BASE_H - 20);
    layoutCtx.rotate(-Math.PI / 2);
    layoutCtx.scale(SIDE_X_SCALE, 1);
    layoutCtx.textAlign = 'left';
    layoutCtx.textBaseline = 'middle';
    layoutCtx.fillText(date, 0, 0);
    layoutCtx.restore();
  }
}

function drawOutlineSprite(source, digit, centreX, centreY, offsetX, offsetY, rotation, scale, alpha) {
  if (alpha <= 0.001) return;
  const cos = Math.cos(rotation) * scale;
  const sin = Math.sin(rotation) * scale;
  blueprintCtx.setTransform(cos, sin, -sin, cos, centreX + offsetX, centreY + offsetY);
  blueprintCtx.globalAlpha = alpha;
  blueprintCtx.drawImage(
    source,
    Number(digit) * OUTLINE_TILE_W, 0, OUTLINE_TILE_W, OUTLINE_TILE_H,
    -OUTLINE_TILE_W / 2, -OUTLINE_TILE_H / 2, OUTLINE_TILE_W, OUTLINE_TILE_H
  );
}

function drawBlueprints(nowMs) {
  const start = DEBUG ? performance.now() : 0;
  blueprintCtx.setTransform(1, 0, 0, 1, 0, 0);
  blueprintCtx.globalAlpha = 1;
  blueprintCtx.clearRect(0, 0, BASE_W, BASE_H);

  for (let zone = 0; zone < 4; zone++) {
    const centreX = zone * ZONE_W + ZONE_W / 2;
    const progress = Math.min(1, Math.max(0, (nowMs - transitionStarted[zone]) / TRANSITION_MS));
    const incoming = 1 - Math.pow(1 - progress, 2);
    const outgoing = Math.pow(1 - progress, 2);
    const transitionWave = Math.sin(Math.PI * progress);
    const shake = 1 + transitionWave * 1.2;

    for (let layer = 0; layer < CFG.blueprintLayers; layer++) {
      const layerRatio = layer / Math.max(1, CFG.blueprintLayers - 1);
      const layerPhase = layer * 1.73 + zone * 0.91;
      const motionTime = nowMs * 0.00082;
      const fadeWave = 0.5 + 0.5 * Math.sin(nowMs * 0.00105 + layerPhase * 1.91);
      const fade = 0.75 + 0.25 * fadeWave;
      const amplitude = (2.0 + layerRatio * OUTLINE_OFFSET) * shake;
      const offsetX = (
        Math.sin(motionTime * (1 + layer * 0.012) + layerPhase) +
        Math.sin(motionTime * 0.43 + layerPhase * 2.1) * 0.35
      ) * amplitude;
      const offsetY = (
        Math.cos(motionTime * 0.87 + layerPhase * 1.27) +
        Math.sin(motionTime * 0.34 + layerPhase) * 0.30
      ) * amplitude * 0.72;
      const rotation = Math.sin(motionTime * 0.73 + layerPhase * 0.77) * OUTLINE_ROTATION * (0.45 + layerRatio * 0.55) * shake;
      const scale = NUMBER_LAYOUT.scale * (1 + Math.sin(motionTime * 0.62 + layerPhase * 1.13) * OUTLINE_SCALE * (0.45 + layerRatio * 0.55));
      // Original p5 version used alpha 20..50 out of 255 across 15 layers.
      const baseAlpha = (0.200 + layerRatio * 0.200) * fade;

      if (outgoing > 0.002 && previousDigits[zone]) {
        drawOutlineSprite(outlineGrey, previousDigits[zone], centreX, NUMBER_LAYOUT.y, offsetX, offsetY, rotation, scale, baseAlpha * outgoing);
      }
      drawOutlineSprite(outlineGrey, currentDigits[zone], centreX, NUMBER_LAYOUT.y, offsetX, offsetY, rotation, scale, baseAlpha * incoming);

      if (transitionWave > 0.01) {
        drawOutlineSprite(
          outlineGreen,
          currentDigits[zone],
          centreX,
          NUMBER_LAYOUT.y,
          -offsetX * 0.75,
          offsetY * 0.65,
          -rotation * 0.85,
          scale,
          baseAlpha * transitionWave * 0.75
        );
      }
    }
  }

  blueprintCtx.setTransform(1, 0, 0, 1, 0, 0);
  blueprintCtx.globalAlpha = 1;
  if (DEBUG) blueprintDrawAverage = blueprintDrawAverage * 0.94 + (performance.now() - start) * 0.06;
}

function updateParticles(deltaFrames, nowMs) {
  const slowRadius = 58;
  const maxSpeed = CFG.maxSpeed;
  const steering = CFG.steering;
  const damping = HEARTBEAT.settleDamping;
  const drift = CFG.driftAmount;
  const heartbeat = heartbeatValue(nowMs);
  const heartbeatForce = heartbeat * HEARTBEAT.joltForce;
  const heartbeatPhase = heartbeatSequence * 1.61803398875;

  for (let i = 0; i < TOTAL_PARTICLES; i++) {
    const driftX = Math.sin(nowMs * 0.00052 + phase[i]) * drift;
    const driftY = Math.cos(nowMs * 0.00043 + phase[i] * 1.31) * drift * 0.85;
    const deltaX = tx[i] + driftX - x[i];
    const deltaY = ty[i] + driftY - y[i];
    const distanceSquared = deltaX * deltaX + deltaY * deltaY;

    if (distanceSquared > 0.04) {
      const distance = Math.sqrt(distanceSquared);
      const speed = distance < slowRadius ? maxSpeed * distance / slowRadius : maxSpeed;
      const desiredX = deltaX / distance * speed;
      const desiredY = deltaY / distance * speed;
      vx[i] += (desiredX - vx[i]) * steering;
      vy[i] += (desiredY - vy[i]) * steering;
    }

    if (heartbeatForce > 0.001) {
      const angle = phase[i] + heartbeatPhase;
      vx[i] += Math.cos(angle) * heartbeatForce * deltaFrames;
      vy[i] += Math.sin(angle * 1.17) * heartbeatForce * deltaFrames;
    }

    x[i] += vx[i] * deltaFrames;
    y[i] += vy[i] * deltaFrames;
    vx[i] *= damping;
    vy[i] *= damping;
  }
}

function leafAtlasIndex(colour, size, pulseLevel, rotation) {
  return (((colour * LEAF_SIZES + size) * LEAF_PULSE_LEVELS + pulseLevel) * LEAF_ROTATIONS + rotation);
}

function drawLeaves(nowMs) {
  const start = DEBUG ? performance.now() : 0;
  leafCtx.clearRect(0, 0, BASE_W, BASE_H);
  const pulse = heartbeatValue(nowMs);
  const pulseScale = 1 + pulse * HEARTBEAT.scaleBoost;
  const rotationTick = Math.floor(nowMs / 170);
  const drawSize = LEAF_TILE * pulseScale;
  const halfDrawSize = drawSize / 2;

  for (let i = 0; i < TOTAL_PARTICLES; i++) {
    const rotation = (baseRotation[i] + Math.floor(rotationTick * spin[i])) % LEAF_ROTATIONS;
    // Always use the normal atlas frame. Heartbeat scaling is continuous at draw time.
    const sprite = leafAtlasIndex(colourIndex[i], sizeIndex[i], 0, rotation);
    const sourceX = (sprite % LEAF_ATLAS_COLS) * LEAF_TILE;
    const sourceY = Math.floor(sprite / LEAF_ATLAS_COLS) * LEAF_TILE;
    leafCtx.drawImage(
      leafAtlas,
      sourceX, sourceY, LEAF_TILE, LEAF_TILE,
      Math.round(x[i] - halfDrawSize), Math.round(y[i] - halfDrawSize), drawSize, drawSize
    );
  }

  if (DEBUG) leafDrawAverage = leafDrawAverage * 0.94 + (performance.now() - start) * 0.06;
}

function updateDebug(nowMs) {
  if (!DEBUG) return;
  debugFrames++;
  if (nowMs - debugStarted >= 1000) {
    const fps = debugFrames * 1000 / (nowMs - debugStarted);
    window.clockStats = {
      fps: Number(fps.toFixed(1)),
      leafMs: Number(leafDrawAverage.toFixed(2)),
      blueprintMs: Number(blueprintDrawAverage.toFixed(2)),
      leaves: TOTAL_PARTICLES
    };
    debugElement.textContent = `${fps.toFixed(0)} fps · leaves ${leafDrawAverage.toFixed(1)} ms · lines ${blueprintDrawAverage.toFixed(1)} ms · ${TOTAL_PARTICLES} leaves`;
    debugFrames = 0;
    debugStarted = nowMs;
  }
}

function animationLoop(nowMs) {
  requestAnimationFrame(animationLoop);
  if (document.hidden || nowMs - lastFrame < FRAME_MS) return;

  const deltaFrames = Math.min(2, (nowMs - lastFrame) / FRAME_MS || 1);
  lastFrame = nowMs - (nowMs - lastFrame) % FRAME_MS;

  updateClock(false, nowMs);
  updateParticles(deltaFrames, nowMs);
  drawBlueprints(nowMs);
  drawLeaves(nowMs);
  updateDebug(nowMs);
}

async function start() {
  targetData = window.DIGIT_ASSETS;
  if (!targetData || !targetData.targets) throw new Error('Digit target data is missing');

  const [greyImage, greenImage, leafImage] = await Promise.all([
    loadImage('digit_outlines_grey.png'),
    loadImage('digit_outlines_green.png'),
    loadImage('leaf_atlas.png')
  ]);

  [outlineGrey, outlineGreen, leafAtlas] = await Promise.all([
    toBitmap(greyImage),
    toBitmap(greenImage),
    toBitmap(leafImage)
  ]);

  await Promise.all([
    loadOptionalFont('ClockFooter', 'fonts/PTSerif-Bold.ttf', 20, 700),
    loadOptionalFont('ClockSide', 'fonts/OpenSans-SemiBold.ttf', 8, 600)
  ]);

  initialiseParticles();
  const nowMs = performance.now();
  updateClock(true, nowMs);
  drawBlueprints(nowMs);
  drawLeaves(nowMs);
  requestAnimationFrame(animationLoop);
}

start().catch(error => {
  layoutCtx.fillStyle = BG;
  layoutCtx.fillRect(0, 0, BASE_W, BASE_H);
  if (DEBUG) {
    debugElement.hidden = false;
    debugElement.textContent = `Clock failed to start: ${error.message}`;
  }
});
