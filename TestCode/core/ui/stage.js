// 共用舞台：renderer、場景、相機、軌道控制、環境光與燈光、縮放、3D 標籤、視角轉場與畫面迴圈。
// 各專案只傳差異（曝光、背景、燈光位置、相機範圍），渲染的優化（對數深度、按需重繪、陰影更新）在這裡統一處理。
//
//   const stage = createStage({ canvas, exposure: .86, camera: { near: 100, far: 150000 }, sun: { position: [...], target: [...] } });
//   stage.loop(dt => { ...每格更新... });
//
// 網址參數（所有專案一致）：shadow=0 關陰影、aa=0 關反鋸齒、logdepth=0/1 覆寫對數深度、movie（不自動跑迴圈，交給錄影程式驅動）
import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { RoomEnvironment } from 'three/addons/environments/RoomEnvironment.js';

export function createStage({
  canvas, qp = new URLSearchParams(location.search),
  exposure = 1.05, background = 0x0d1117, fog = null,          // fog：[near, far]
  logDepth = true,                                              // 大場景（m 級）建議開；近裁切面很小時可關
  camera: cam = {}, controls: ctl = {},
  envLight = null, envBlur = .04,                              // envLight：RoomEnvironment 點光強度（SSD／快門站用 220）
  hemi = { sky: 0xbfd4ff, ground: 0x2a2f36, intensity: .6 },
  sun = { color: 0xffffff, intensity: 1.5, position: [-1500, 3200, 1800], target: [0, 0, 0], shadow: { mapSize: 2048 } },
  fill = { color: 0x9fb8ff, intensity: .5, position: [1800, 1500, -1800] },
  extraLights = [],                                             // [{ color, intensity, position, target?, shadow? }]（shadow 同 sun.shadow）
  onDemand = false,                                             // true：靜止時不重繪（需在狀態改變時呼叫 invalidate）
  preserveDrawingBuffer = qp.has('shot'),
} = {}) {
  // 錄影（?movie）一律用對數深度：4K 取樣的細線與遠景不閃
  const useLog = qp.has('logdepth') ? qp.get('logdepth') !== '0' : qp.has('movie') || logDepth;
  const renderer = new THREE.WebGLRenderer({ canvas, antialias: qp.get('aa') !== '0', powerPreference: 'high-performance', logarithmicDepthBuffer: useLog, preserveDrawingBuffer });
  renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
  renderer.shadowMap.enabled = qp.get('shadow') !== '0'; renderer.shadowMap.type = THREE.PCFSoftShadowMap;
  renderer.toneMapping = THREE.ACESFilmicToneMapping; renderer.toneMappingExposure = exposure;
  renderer.outputColorSpace = THREE.SRGBColorSpace;

  const scene = new THREE.Scene(); scene.background = new THREE.Color(background);
  if (fog) scene.fog = new THREE.Fog(background, fog[0], fog[1]);
  const pmrem = new THREE.PMREMGenerator(renderer), room = new RoomEnvironment(renderer);
  if (envLight != null) room.traverse(o => { if (o.isPointLight) o.intensity = envLight; });
  scene.environment = pmrem.fromScene(room, envBlur).texture; room.dispose(); pmrem.dispose();

  const camera = new THREE.PerspectiveCamera(cam.fov ?? 40, 1, cam.near ?? 2, cam.far ?? 20000);
  const controls = new OrbitControls(camera, canvas);
  Object.assign(controls, { enableDamping: true, dampingFactor: .08, maxPolarAngle: Math.PI * .49 }, ctl);

  const lights = {};
  if (hemi) scene.add(lights.hemi = new THREE.HemisphereLight(hemi.sky, hemi.ground, hemi.intensity));
  // 平行光：shadow 給定時投陰影（mapSize、camera 範圍、bias、normalBias），target 為照射點
  const directional = (l, defaults, castShadow) => {
    const d = new THREE.DirectionalLight(l.color ?? defaults.color, l.intensity ?? defaults.intensity);
    d.position.set(...l.position); d.target.position.set(...(l.target || [0, 0, 0]));
    if (castShadow) {
      d.castShadow = renderer.shadowMap.enabled;
      const sh = l.shadow || {};
      d.shadow.mapSize.set(sh.mapSize ?? 2048, sh.mapSize ?? 2048);
      if (sh.camera) Object.assign(d.shadow.camera, sh.camera);
      if (sh.bias != null) d.shadow.bias = sh.bias;
      if (sh.normalBias != null) d.shadow.normalBias = sh.normalBias;
    }
    scene.add(d, d.target); return d;
  };
  if (sun) lights.sun = directional(sun, { color: 0xffffff, intensity: 1.5 }, true);
  if (fill) lights.fill = directional(fill, { color: 0x9fb8ff, intensity: .5 }, false);
  lights.extra = extraLights.map(l => directional(l, { color: 0xffffff, intensity: .5 }, !!l.shadow));

  // ---------------------------------------------------------------- 3D 標籤（HTML 疊在畫布上）
  const host = canvas.parentElement, labels = [], _v = new THREE.Vector3();
  // anchor：'center'（標籤中心在點上）或 'above'（標籤底邊在點上方 6 px）；位置已含畫布在頁面中的偏移，專案不必自行補正
  function addLabel(html, getPos, cls = '', { anchor = 'center' } = {}) {
    const el = document.createElement('div'); el.className = 'label3d' + (cls ? ' ' + cls : ''); el.innerHTML = html;
    el.style.left = '0px'; el.style.top = '0px'; host.appendChild(el);
    const pos = typeof getPos === 'function' ? getPos : () => getPos;
    const item = { el, pos, anchor }; labels.push(item); return item;
  }
  function updateLabels(show = true) {
    const w = canvas.clientWidth, h = canvas.clientHeight, cr = canvas.getBoundingClientRect(), hr = host.getBoundingClientRect();
    const ox = cr.left - hr.left + host.scrollLeft - host.clientLeft, oy = cr.top - hr.top + host.scrollTop - host.clientTop;
    for (const l of labels) {
      const p = l.pos(); if (!show || !p) { l.el.style.display = 'none'; continue; }
      _v.copy(p).project(camera);
      const on = _v.z < 1 && Math.abs(_v.x) < 1.1 && Math.abs(_v.y) < 1.1;
      l.el.style.display = on ? '' : 'none';
      if (on) l.el.style.transform = `${l.anchor === 'above' ? 'translate(-50%,calc(-100% - 6px))' : 'translate(-50%,-50%)'} translate(${ox + (_v.x * .5 + .5) * w}px,${oy + (-_v.y * .5 + .5) * h}px)`;
    }
  }

  // ---------------------------------------------------------------- 視角轉場
  let tween = null;
  function goTo(position, target, instant = false, duration = .9) {
    const P = new THREE.Vector3(...position), Tg = new THREE.Vector3(...target);
    if (instant) { camera.position.copy(P); controls.target.copy(Tg); controls.update(); tween = null; invalidate(); return; }
    tween = { p0: camera.position.clone(), t0: controls.target.clone(), P, Tg, u: 0, duration }; invalidate();
  }
  // 取消進行中的轉場（相機停在目前位置）
  function cancelTween() { tween = null; }
  // 整體平移視角：相機、注視點與進行中轉場的起訖點一起移動（跟著輸送中的工件看）
  function shiftView(delta) {
    camera.position.add(delta); controls.target.add(delta);
    if (tween) { tween.p0.add(delta); tween.t0.add(delta); tween.P.add(delta); tween.Tg.add(delta); }
    invalidate();
  }
  const tweening = () => !!tween;
  function stepTween(dt) {
    if (!tween) return false;
    tween.u = Math.min(1, tween.u + dt / tween.duration);
    const e = tween.u * tween.u * (3 - 2 * tween.u);
    camera.position.lerpVectors(tween.p0, tween.P, e); controls.target.lerpVectors(tween.t0, tween.Tg, e);
    if (tween.u >= 1) tween = null; return true;
  }

  // ---------------------------------------------------------------- 縮放與迴圈
  let dirty = true;
  function invalidate(shadows = false) { dirty = true; if (shadows) renderer.shadowMap.needsUpdate = true; }
  function resize() {
    const w = canvas.clientWidth, h = canvas.clientHeight; if (!w || !h) return;
    renderer.setSize(w, h, false); camera.aspect = w / h; camera.updateProjectionMatrix(); invalidate();
  }
  if (!qp.has('movie')) addEventListener('resize', resize);   // 錄影時畫布尺寸由錄影程式固定
  if (onDemand) { renderer.shadowMap.autoUpdate = false; controls.addEventListener('change', () => invalidate()); }
  const render = (cam2 = camera) => renderer.render(scene, cam2);
  const clock = new THREE.Clock();
  let tick = null, running = false, draw = () => render();
  function frame() {
    if (!running) return;
    requestAnimationFrame(frame);
    const dt = Math.min(clock.getDelta(), .05);
    const moved = stepTween(dt);
    const keep = tick?.(dt);
    controls.update();
    if (!onDemand || dirty || moved || keep) { if (onDemand) renderer.shadowMap.needsUpdate = true; draw(); dirty = false; }
  }
  // tick(dt) 回傳 true 代表這格有變化（onDemand 模式下需要重繪）。
  // opts.render：自訂整格繪製（例如主畫面＋相機子畫面＋疊圖），預設只畫主畫面
  function loop(fn, opts = {}) { tick = fn; if (opts.render) draw = opts.render; resize(); if (qp.has('movie') || running) return; running = true; clock.getDelta(); frame(); }
  function stop() { running = false; }

  return { renderer, scene, camera, controls, lights, qp, addLabel, updateLabels, labels, goTo, cancelTween, shiftView, get tweening() { return tweening(); }, resize, render, invalidate, loop, stop, clock, useLog };
}

// 標準 window.sim：統一檢查與截圖工具依賴 seekTo、setView、views、total、play、pause；
// 專案可再附加自己的成員（getter 會保留，例如 get T()）
export function exposeSim(members) {
  const sim = Object.defineProperties({}, Object.getOwnPropertyDescriptors(members));
  if (!Array.isArray(sim.views)) Object.defineProperty(sim, 'views', { value: Object.keys(members.views || {}), enumerable: true });
  for (const k of ['seekTo', 'setView', 'total', 'play', 'pause']) if (!(k in sim)) console.warn(`window.sim 缺少 ${k}`);
  window.sim = sim; return sim;
}
