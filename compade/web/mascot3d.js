import * as THREE from './vendor/three.module.min.js';

const TAU = Math.PI * 2;
const BASE = new THREE.Color('#5f6f88');
const geometries = {};
const materialCache = new Map();
const instances = new Set();
let renderer = null;
let observer = null;
let raf = 0;
let reducedMotion = false;
let lastFrame = 0;
let fpsFrames = 0;
let fpsSince = 0;
const fpsListeners = new Set();

function geometry(key, make) {
  return geometries[key] || (geometries[key] = make());
}

function mat(key, make) {
  if (!materialCache.has(key)) materialCache.set(key, make());
  return materialCache.get(key);
}

function physical(color, roughness = 0.62) {
  const c = new THREE.Color(color);
  const key = `physical:${c.getHexString()}:${roughness}`;
  return mat(key, () => new THREE.MeshPhysicalMaterial({
    color: c, roughness, metalness: 0.02, clearcoat: 0.08, clearcoatRoughness: 0.7
  }));
}

function glowMaterial(opacity = 0.16) {
  return mat(`glow:${opacity}`, () => new THREE.MeshBasicMaterial({
    color: 0xffffff, transparent: true, opacity, blending: THREE.AdditiveBlending,
    depthWrite: false, side: THREE.DoubleSide
  }));
}

function basic(color, key = color) {
  return mat(`basic:${key}`, () => new THREE.MeshBasicMaterial({ color, toneMapped: false }));
}

function makeRenderer() {
  if (renderer) return renderer;
  try {
    const canvas = document.createElement('canvas');
    const gl = canvas.getContext('webgl2', { alpha: true, antialias: true }) || canvas.getContext('webgl', { alpha: true, antialias: true });
    if (!gl) return null;
    renderer = new THREE.WebGLRenderer({ canvas, context: gl, alpha: true, antialias: true, powerPreference: 'low-power' });
    renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 1.5));
    renderer.setSize(256, 256, false);
    renderer.outputColorSpace = THREE.SRGBColorSpace;
    renderer.toneMapping = THREE.ACESFilmicToneMapping;
    renderer.toneMappingExposure = 1.15;
    renderer.shadowMap.enabled = true;
    renderer.shadowMap.type = THREE.PCFSoftShadowMap;
    return renderer;
  } catch (_) { return null; }
}

function colorFor(roleColor) {
  return new THREE.Color('#5f6f88').lerp(new THREE.Color(roleColor || '#64748b'), 0.4);
}

function makeTextSprite(text, color = '#dbeafe') {
  const canvas = document.createElement('canvas');
  canvas.width = 256; canvas.height = 128;
  const ctx = canvas.getContext('2d');
  ctx.clearRect(0, 0, canvas.width, canvas.height);
  ctx.font = '700 76px ui-monospace, monospace';
  ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
  ctx.shadowColor = color; ctx.shadowBlur = 16; ctx.fillStyle = color;
  ctx.fillText(text, 128, 64);
  const texture = new THREE.CanvasTexture(canvas);
  texture.colorSpace = THREE.SRGBColorSpace;
  const sprite = new THREE.Sprite(new THREE.SpriteMaterial({ map: texture, transparent: true, depthWrite: false }));
  sprite.scale.set(0.75, 0.38, 1);
  sprite.userData.texture = texture;
  return sprite;
}

function createModel(options) {
  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(32, 1, 0.1, 40);
  camera.position.set(0, 0.35, 6.6);
  camera.lookAt(0, 0.08, 0);

  scene.add(new THREE.HemisphereLight(0xe9f2ff, 0x465166, 2.05));
  const keyLight = new THREE.DirectionalLight(0xfff8ed, 2.7);
  keyLight.position.set(-3.5, 5, 5); keyLight.castShadow = true;
  keyLight.shadow.mapSize.set(512, 512);
  keyLight.shadow.camera.left = -3; keyLight.shadow.camera.right = 3;
  keyLight.shadow.camera.top = 3; keyLight.shadow.camera.bottom = -3;
  keyLight.shadow.bias = -0.0005;
  scene.add(keyLight);
  const fill = new THREE.DirectionalLight(0xc7ddff, 0.9);
  fill.position.set(4, 1, 3); scene.add(fill);

  const root = new THREE.Group(); scene.add(root);
  const bodyColor = colorFor(options.color);
  const body = new THREE.Mesh(geometry('body', () => new THREE.SphereGeometry(1, 48, 36)), physical(bodyColor));
  body.scale.set(1, 1, 0.91); body.position.y = 0.06; body.castShadow = true; body.receiveShadow = true;
  root.add(body);

  const darkColor = bodyColor.clone().multiplyScalar(0.78);
  const limbMat = physical(darkColor, 0.68);
  const armGeo = geometry('arm', () => new THREE.CapsuleGeometry(0.16, 0.48, 8, 16));
  const arms = [];
  for (const side of [-1, 1]) {
    const arm = new THREE.Mesh(armGeo, limbMat);
    arm.position.set(side * 0.96, -0.19, 0.01); arm.rotation.z = side * -0.12;
    arm.castShadow = true; root.add(arm); arms.push(arm);
  }
  const footGeo = geometry('foot', () => new THREE.SphereGeometry(0.23, 24, 18));
  const feet = [];
  for (const side of [-1, 1]) {
    const foot = new THREE.Mesh(footGeo, limbMat);
    foot.scale.set(0.9, 1.05, 0.95); foot.position.set(side * 0.38, -0.91, 0.04);
    foot.castShadow = true; root.add(foot); feet.push(foot);
  }

  const eyeGeo = geometry('eye', () => new THREE.SphereGeometry(0.18, 32, 24));
  const eyeGlowGeo = geometry('eyeGlow', () => new THREE.CircleGeometry(0.235, 32));
  const eyes = [], eyeGlows = [];
  for (const side of [-1, 1]) {
    const eye = new THREE.Mesh(eyeGeo, basic(0xffffff, 'white-eye'));
    eye.position.set(side * 0.31, 0.22, 0.865); eye.scale.set(1, 1, 0.38); root.add(eye); eyes.push(eye);
    const halo = new THREE.Mesh(eyeGlowGeo, glowMaterial(0.12));
    halo.position.set(side * 0.31, 0.22, 0.873); root.add(halo); eyeGlows.push(halo);
  }

  // The open end faces right, matching the thin illuminated C on the reference.
  const cCurve = new THREE.TorusGeometry(0.105, 0.013, 8, 48, Math.PI * 1.62);
  const cMark = new THREE.Mesh(cCurve, basic(0xffffff, 'white-c'));
  cMark.position.set(-0.02, -0.34, 0.895); cMark.rotation.z = 0.81; root.add(cMark);
  const cHalo = new THREE.Mesh(new THREE.TorusGeometry(0.105, 0.03, 8, 48, Math.PI * 1.62), glowMaterial(0.08));
  cHalo.position.copy(cMark.position); cHalo.rotation.z = cMark.rotation.z; root.add(cHalo);

  const antenna = new THREE.Group(); antenna.position.set(0, 1.02, 0.02); root.add(antenna);
  const rod = new THREE.Mesh(geometry('antennaRod', () => new THREE.CylinderGeometry(0.025, 0.025, 0.31, 12)), limbMat);
  rod.position.y = 0.14; antenna.add(rod);
  const tip = new THREE.Mesh(geometry('antennaTip', () => new THREE.SphereGeometry(0.065, 20, 16)), physical('#78869a', 0.48));
  tip.position.y = 0.32; antenna.add(tip);

  const crown = new THREE.Group(); crown.position.set(0, 1.02, 0.08); root.add(crown);
  const gold = physical('#fbbf24', 0.42);
  const crownBase = new THREE.Mesh(new THREE.CylinderGeometry(0.16, 0.18, 0.075, 5), gold); crown.add(crownBase);
  for (let i = 0; i < 3; i++) {
    const point = new THREE.Mesh(new THREE.ConeGeometry(0.045, 0.13, 5), gold);
    point.position.set((i - 1) * 0.1, 0.095, 0); crown.add(point);
  }
  crown.visible = !!options.chief;

  const keyboard = new THREE.Group(); keyboard.position.set(0, -0.76, 1.02); root.add(keyboard);
  const keyBase = new THREE.Mesh(geometry('keyboardBase', () => new THREE.BoxGeometry(0.7, 0.075, 0.28)), physical('#2d384b', 0.72));
  keyBase.castShadow = true; keyboard.add(keyBase);
  const keysGeo = geometry('key', () => new THREE.BoxGeometry(0.075, 0.025, 0.065));
  for (let row = 0; row < 2; row++) for (let col = 0; col < 6; col++) {
    const key = new THREE.Mesh(keysGeo, physical('#9aa9bc', 0.55));
    key.position.set((col - 2.5) * 0.095, 0.05, (row - 0.5) * 0.09); keyboard.add(key);
  }
  keyboard.visible = false;

  const codeSprite = makeTextSprite('</>');
  codeSprite.position.set(1.05, 0.58, 0.2); root.add(codeSprite); codeSprite.visible = false;
  const zSprite = makeTextSprite('z', '#94a3b8');
  zSprite.scale.set(0.24, 0.3, 1); zSprite.position.set(0.62, 0.83, 0.25); root.add(zSprite); zSprite.visible = false;

  const floor = new THREE.Mesh(geometry('floor', () => new THREE.PlaneGeometry(200, 200)), mat('floor', () => new THREE.ShadowMaterial({ opacity: 0.18 })));
  floor.rotation.x = -Math.PI / 2; floor.position.y = -1.12; floor.receiveShadow = true; scene.add(floor);

  const shadowCanvas = document.createElement('canvas'); shadowCanvas.width = shadowCanvas.height = 128;
  const ctx = shadowCanvas.getContext('2d');
  const gradient = ctx.createRadialGradient(64, 64, 4, 64, 64, 62);
  gradient.addColorStop(0, 'rgba(18,25,38,.30)'); gradient.addColorStop(1, 'rgba(18,25,38,0)');
  ctx.fillStyle = gradient; ctx.fillRect(0, 0, 128, 128);
  const shadowTex = new THREE.CanvasTexture(shadowCanvas);
  const contact = new THREE.Mesh(new THREE.PlaneGeometry(2.8, 1.05), new THREE.MeshBasicMaterial({ map: shadowTex, transparent: true, depthWrite: false }));
  contact.rotation.x = -Math.PI / 2; contact.position.set(0, -1.105, 0); scene.add(contact);

  return { scene, camera, root, body, arms, feet, eyes, eyeGlows, antenna, tip, crown, keyboard, codeSprite, zSprite, cMark, contact, shadowTex };
}

function applyState(instance, patch = {}) {
  const options = instance.options;
  if ('color' in patch && patch.color) {
    options.color = patch.color;
    const color = colorFor(patch.color);
    instance.model.body.material = physical(color);
    const limbs = color.clone().multiplyScalar(0.78);
    instance.model.arms.forEach(m => m.material = physical(limbs, 0.68));
    instance.model.feet.forEach(m => m.material = physical(limbs, 0.68));
  }
  if ('chief' in patch) { options.chief = !!patch.chief; instance.model.crown.visible = options.chief; }
  if ('state' in patch && patch.state) options.state = patch.state;
  instance.model.keyboard.visible = options.state === 'working';
  instance.model.codeSprite.visible = options.state === 'working';
  instance.model.zSprite.visible = options.state === 'sleeping';
  instance.dirty = true;
}

function animate(instance, time) {
  const m = instance.model, state = instance.options.state;
  const t = time / 1000;
  m.root.position.y = 0;
  m.root.rotation.set(0, 0, 0);
  m.eyes.forEach(e => { e.scale.y = 1; e.position.y = 0.22; });
  m.arms.forEach((a, i) => { a.rotation.z = (i === 0 ? 1 : -1) * 0.12; });
  m.tip.material = physical('#78869a', 0.48);
  m.codeSprite.position.y = 0.58 + (t % 1.8) * 0.2;
  m.codeSprite.material.opacity = 0.55 + Math.sin(t * 4) * 0.35;
  if (state === 'idle' || state === 'sleeping') m.root.scale.y = 1 + Math.sin(t * 1.45) * 0.012;
  else m.root.scale.y = 1;
  if (state === 'idle' && Math.sin(t * 0.75 + instance.seed) > 0.993) m.eyes.forEach(e => e.scale.y = 0.12);
  if (state === 'working') {
    m.arms.forEach((a, i) => { a.rotation.z += Math.sin(t * 12 + i * Math.PI) * 0.28; });
    m.eyes.forEach((e, i) => { e.position.y = 0.1 + Math.sin(t * 2.1 + i * 1.7) * 0.035; });
    m.tip.material = physical(Math.sin(t * 7) > 0 ? '#22c55e' : '#116b40', 0.38);
  } else if (state === 'waiting') {
    m.root.rotation.z = Math.sin(t * 1.3) * 0.045;
    m.eyes.forEach(e => e.scale.y = 0.58);
  } else if (state === 'success') {
    m.root.position.y = Math.max(0, Math.sin(t * 7)) * 0.22;
    m.eyes.forEach(e => e.scale.y = 1.18);
  } else if (state === 'error') {
    m.root.position.x = Math.sin(t * 45) * 0.045 * Math.max(0, 1 - (t % 1.4));
    m.tip.material = physical('#ef4444', 0.38);
  } else if (state === 'sleeping') {
    m.eyes.forEach(e => { e.scale.y = 0.07; e.position.y = 0.18; });
    m.root.rotation.z = Math.sin(t * 0.65) * 0.018;
    m.zSprite.position.y = 0.83 + (t % 2.5) * 0.16;
    m.zSprite.material.opacity = 1 - (t % 2.5) / 2.5;
  }
}

function visible(instance) {
  if (!instance.el.isConnected || instance.width <= 0 || instance.height <= 0) return false;
  const rect = instance.el.getBoundingClientRect();
  return rect.bottom > 0 && rect.right > 0 && rect.top < innerHeight && rect.left < innerWidth;
}

function shouldAnimate(state) { return ['working', 'success', 'error'].includes(state); }

function frame(time) {
  raf = 0;
  if (!renderer) return;
  fpsFrames++;
  if (!fpsSince) fpsSince = time;
  if (time - fpsSince >= 500) {
    const fps = Math.round(fpsFrames * 1000 / (time - fpsSince));
    fpsListeners.forEach(fn => fn(fps)); fpsFrames = 0; fpsSince = time;
  }
  for (const instance of instances) {
    if (!instance.visible || !visible(instance)) continue;
    const busy = shouldAnimate(instance.options.state);
    const interval = reducedMotion ? Infinity : busy ? 0 : 100;
    if (!instance.dirty && time - instance.lastDraw < interval) continue;
    instance.lastDraw = time; instance.dirty = false;
    if (!reducedMotion) animate(instance, time);
    renderer.setSize(instance.width, instance.height, false);
    renderer.setViewport(0, 0, instance.width, instance.height);
    renderer.setScissor(0, 0, instance.width, instance.height);
    renderer.setScissorTest(false);
    renderer.render(instance.model.scene, instance.model.camera);
    const ctx = instance.ctx;
    ctx.clearRect(0, 0, instance.width, instance.height);
    ctx.drawImage(renderer.domElement, 0, 0, instance.width, instance.height);
  }
  if (!reducedMotion && instances.size) raf = requestAnimationFrame(frame);
}

function schedule() { if (!raf && !reducedMotion && instances.size) raf = requestAnimationFrame(frame); }

function mount(el, options = {}) {
  const webgl = makeRenderer();
  if (!webgl || !el) return null;
  const canvas = document.createElement('canvas');
  canvas.setAttribute('aria-hidden', 'true');
  canvas.style.display = 'block'; canvas.style.width = '100%'; canvas.style.height = '100%';
  const ctx = canvas.getContext('2d');
  if (!ctx) return null;
  el.replaceChildren(canvas);
  const width = Math.max(1, Math.round(el.clientWidth || options.size || 180));
  const height = Math.max(1, Math.round(el.clientHeight || options.size || width));
  canvas.width = width; canvas.height = height;
  const instance = {
    el, canvas, ctx, width, height, options: { color: options.color || '#64748b', state: options.state || 'idle', chief: !!options.chief },
    seed: Math.random() * TAU, lastDraw: -Infinity, dirty: true, visible: true,
    model: createModel(options)
  };
  instances.add(instance);
  if ('IntersectionObserver' in window) {
    if (!observer) observer = new IntersectionObserver(entries => {
      for (const entry of entries) {
        const found = [...instances].find(item => item.el === entry.target);
        if (found) { found.visible = entry.isIntersecting; found.dirty = true; }
      }
      schedule();
    });
    observer.observe(el);
  }
  instance.resize = new ResizeObserver(() => {
    instance.width = Math.max(1, Math.round(el.clientWidth || options.size || 180));
    instance.height = Math.max(1, Math.round(el.clientHeight || options.size || instance.width));
    canvas.width = instance.width; canvas.height = instance.height; instance.dirty = true; schedule();
  });
  instance.resize.observe(el);
  if (!reducedMotion) schedule(); else { instance.dirty = true; frame(performance.now()); }
  return {
    update(patch) { applyState(instance, patch || {}); schedule(); if (reducedMotion) frame(performance.now()); },
    destroy() {
      instances.delete(instance); observer?.unobserve(el); instance.resize.disconnect();
      instance.model.shadowTex.dispose();
      for (const sprite of [instance.model.codeSprite, instance.model.zSprite]) sprite.material.map?.dispose();
      canvas.remove();
      if (!instances.size && raf) { cancelAnimationFrame(raf); raf = 0; }
    }
  };
}

if (typeof window !== 'undefined') {
  reducedMotion = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches || false;
  window.matchMedia?.('(prefers-reduced-motion: reduce)').addEventListener?.('change', event => {
    reducedMotion = event.matches;
    instances.forEach(instance => { instance.dirty = true; });
    if (reducedMotion) { if (raf) cancelAnimationFrame(raf); raf = 0; instances.forEach(() => frame(performance.now())); }
    else schedule();
  });
  window.Mascot3D = { mount, onFps(callback) { fpsListeners.add(callback); return () => fpsListeners.delete(callback); } };
}

export const Mascot3D = { mount, onFps(callback) { fpsListeners.add(callback); return () => fpsListeners.delete(callback); } };
export { mount };
