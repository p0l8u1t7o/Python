// 共用舞台：renderer、場景、相機、軌道控制、環境光與燈光、縮放、3D 標籤、視角轉場與畫面迴圈。
// 各專案只傳差異（曝光、背景、燈光位置、相機範圍），渲染的優化（對數深度、按需重繪、陰影更新）在這裡統一處理。
//
//   const stage = createStage({ canvas, exposure: .86, camera: { near: 100, far: 150000 }, sun: { position: [...], target: [...] } });
//   stage.loop(dt => { ...每格更新... });
//
// 網址參數（所有專案一致）：shadow=0 關陰影、aa=0 關反鋸齒、logdepth=0/1 覆寫對數深度、movie（不自動跑迴圈，交給錄影程式驅動）、
//   narrowfit=0 關閉窄畫面拉遠、declutter=0/1 關閉／強制標籤避讓
//
// 小螢幕（手機直向、窄視窗）：
//   narrowFit  畫布比 aspect 窄時，goTo 的相機距離乘上 (aspect / 畫布寬高比)^power（上限 max），保住水平方向的取景；
//              旋轉螢幕或改變視窗時依新比例調整目前距離（含使用者自己轉過的視角）與 maxDistance；
//              個別視角可用 goTo(…, { fit: false 或 (倍數, 偏移) => 新偏移 }) 自訂
//   declutter  'narrow'（預設：畫布寬度 < 1100 px 時，與精簡版面一致）、true（一律）或 false：標籤互相重疊時隱藏優先度低的
//              （addLabel 的 priority 大者優先，同優先度先加入者優先）
import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { RoomEnvironment } from 'three/addons/environments/RoomEnvironment.js';

// 外觀預設（look）：配色、曝光、環境光與燈光強度；專案明確給的選項優先（sun／hemi／fill 逐欄合併）
//   cell    深色工作站（多數單站／產線：手臂站、龍門機）
//   plant   廠房尺度（大範圍建築、按需重繪）
//   studio  較亮的灰藍背景＋輪廓光（單機台特寫展示）
export const LOOKS = {
  cell: { exposure: 1.05, background: 0x0d1117, envLight: 230, envBlur: .04, hemi: { sky: 0xbfd4ff, ground: 0x2a2f36, intensity: .6 }, sun: { color: 0xffffff, intensity: 1.5 }, fill: { color: 0x9fb8ff, intensity: .5 } },
  plant: { exposure: .86, background: 0x0d1117, hemi: { sky: 0xcfe0ff, ground: 0x30363d, intensity: .55 }, sun: { color: 0xffffff, intensity: 1.7 }, fill: { color: 0x9fb8ff, intensity: .45 } },
  studio: { exposure: .94, background: 0x202a34, sun: { color: 0xffffff, intensity: 1.4 }, fill: { color: 0x9fb8ff, intensity: .5 }, rim: { color: 0xffead2, intensity: .65 } },
};
// 場景範圍（extent = { center: [x,y,z], radius }，mm）推算的燈位、陰影範圍與霧：專案沒給的才用
function rigFor({ center: c = [0, 0, 0], radius: r }) {
  const at = k => [c[0] + k[0] * r, c[1] + k[1] * r, c[2] + k[2] * r];
  return {
    sun: { position: at([-.8, 1.8, 1]), target: c, shadow: { mapSize: 2048, camera: { left: -r, right: r, top: r, bottom: -r, near: .25 * r, far: 4.5 * r }, bias: -.0003, normalBias: .05 } },
    fill: { position: at([1, .85, -1]), target: c },
    rim: { position: at([.4, 1.2, -.3]), target: c },
    fog: [2.8 * r, 6.2 * r],
  };
}
export function createStage(options = {}) {
  const look = LOOKS[options.look] || {}, rig = options.extent ? rigFor(options.extent) : {};
  const part = (k, extra) => options[k] === null || options[k] === false ? null : (look[k] || rig[k] || options[k] || extra) ? { ...extra, ...rig[k], ...look[k], ...options[k] } : undefined;
  const merged = { ...look, ...(rig.fog && !('fog' in options) ? { fog: rig.fog } : {}), ...options };
  for (const k of ['hemi', 'sun', 'fill']) { const v = part(k); if (v !== undefined) merged[k] = v; }
  if (look.rim && options.rim !== false) merged.extraLights = [{ position: [700, 2100, -500], ...rig.rim, ...look.rim, ...options.rim }, ...(options.extraLights || [])];
  delete merged.look; delete merged.extent; delete merged.rim;
  return buildStage(merged);
}

function buildStage({
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
  narrowFit = { aspect: 1.25, power: .85, max: 2.4 },
  declutter = 'narrow',
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
  function addLabel(html, getPos, cls = '', { anchor = 'center', priority = 0 } = {}) {
    const el = document.createElement('div'); el.className = 'label3d' + (cls ? ' ' + cls : ''); el.innerHTML = html;
    el.style.left = '0px'; el.style.top = '0px'; host.appendChild(el);
    const pos = typeof getPos === 'function' ? getPos : () => getPos;
    const item = { el, pos, anchor, priority, order: labels.length }; labels.push(item); return item;
  }
  const declutterOn = () => qp.has('declutter') ? qp.get('declutter') !== '0' : declutter === 'narrow' ? canvas.clientWidth < 1100 : !!declutter;
  function updateLabels(show = true) {
    const w = canvas.clientWidth, h = canvas.clientHeight, cr = canvas.getBoundingClientRect(), hr = host.getBoundingClientRect();
    const ox = cr.left - hr.left + host.scrollLeft - host.clientLeft, oy = cr.top - hr.top + host.scrollTop - host.clientTop;
    const avoid = declutterOn(), placed = [];
    // 避讓時先讀尺寸（被避讓的標籤用 visibility 隱藏，尺寸仍讀得到），再依優先度逐一放置
    const items = labels.map(l => {
      const p = show && l.pos(); if (!p) return { l, on: false };
      _v.copy(p).project(camera);
      const on = _v.z < 1 && Math.abs(_v.x) < 1.1 && Math.abs(_v.y) < 1.1;
      return { l, on, x: (_v.x * .5 + .5) * w, y: (-_v.y * .5 + .5) * h, bw: 0, bh: 0 };
    });
    // 先讓要顯示的標籤都進版面再一次讀尺寸（上一格隱藏的標籤尺寸才不會是 0；按需重繪時沒有下一格可以補正）
    if (avoid) { for (const it of items) if (it.on) it.l.el.style.display = ''; for (const it of items) if (it.on) { it.bw = it.l.el.offsetWidth; it.bh = it.l.el.offsetHeight; } }
    if (avoid) items.sort((a, b) => b.l.priority - a.l.priority || a.l.order - b.l.order);
    for (const it of items) {
      const { l, on } = it;
      l.el.style.display = on ? '' : 'none'; if (!on) continue;
      l.el.style.transform = `${l.anchor === 'above' ? 'translate(-50%,calc(-100% - 6px))' : 'translate(-50%,-50%)'} translate(${ox + it.x}px,${oy + it.y}px)`;
      if (!avoid) { l.el.style.visibility = ''; continue; }
      const r = { x0: it.x - it.bw / 2 - 2, x1: it.x + it.bw / 2 + 2, y1: l.anchor === 'above' ? it.y - 4 : it.y + it.bh / 2 + 2 };
      r.y0 = r.y1 - it.bh - 4;
      // 避讓時標籤框須完整落在畫布內（小螢幕上畫布外是工具列與選單，不要蓋上去）
      const clash = r.x0 < -2 || r.x1 > w + 2 || r.y0 < -2 || r.y1 > h + 2 || placed.some(q => r.x0 < q.x1 && q.x0 < r.x1 && r.y0 < q.y1 && q.y0 < r.y1);
      l.el.style.visibility = clash ? 'hidden' : ''; if (!clash) placed.push(r);
    }
  }

  // ---------------------------------------------------------------- 視角轉場
  let tween = null;
  // 窄畫面拉遠：fitScale 為目前相機距離已乘上的倍數（resize 時依新倍數調整）
  const fitOff = qp.get('narrowfit') === '0' || !narrowFit || qp.has('movie');
  const fitFor = () => {
    const w = canvas.clientWidth, h = canvas.clientHeight; if (fitOff || !w || !h || w / h >= narrowFit.aspect) return 1;
    return Math.min(narrowFit.max ?? 2.4, (narrowFit.aspect / (w / h)) ** (narrowFit.power ?? .85));
  };
  let fitScale = 1, baseMaxDistance = null;
  // 最近一次 goTo 的視角：注視點、桌面偏移（相機－注視點）、fit 方式與目前套用的偏移；
  // 相機仍停在該視角（或正轉場過去）時，旋轉螢幕依該視角的 fit 重算，使用者自己轉過則整體距離依比例調整
  let view = null;
  const fitOffset = (v, f) => v.fit === false ? v.base.clone() : typeof v.fit === 'function' ? v.fit(f, v.base.clone()) : v.base.clone().multiplyScalar(f);
  function refit() {
    const f = fitFor(); if (Math.abs(f - fitScale) < 1e-6) return;
    baseMaxDistance ??= controls.maxDistance; controls.maxDistance = baseMaxDistance * f;
    const onView = view && controls.target.distanceTo(view.Tg) < 1e-3 && camera.position.clone().sub(view.Tg).distanceTo(view.applied) < 1e-3;
    if (view && (onView || (tween && tween.Tg.distanceTo(view.Tg) < 1e-3))) {
      view.applied = fitOffset(view, f);
      (tween ? tween.P : camera.position).copy(view.Tg).add(view.applied);
    } else {
      const k = f / fitScale; camera.position.sub(controls.target).multiplyScalar(k).add(controls.target);
      if (tween) tween.P.sub(tween.Tg).multiplyScalar(k).add(tween.Tg);
    }
    fitScale = f; controls.update(); invalidate();
  }
  // fit：true（預設）整體距離乘倍數；false 不拉遠（視角已自己依畫面比例取景）；
  //      (倍數, 桌面偏移 Vector3) => 新偏移（例如只拉遠水平方向、高度不變，避免相機穿過上方的樑）
  function goTo(position, target, instant = false, duration = .9, { fit = true } = {}) {
    refit();
    const Tg = new THREE.Vector3(...target);
    view = { Tg: Tg.clone(), base: new THREE.Vector3(...position).sub(Tg), fit };
    view.applied = fitOffset(view, fitScale);
    const P = Tg.clone().add(view.applied);
    if (instant) { camera.position.copy(P); controls.target.copy(Tg); controls.update(); tween = null; invalidate(); return; }
    tween = { p0: camera.position.clone(), t0: controls.target.clone(), P, Tg, u: 0, duration }; invalidate();
  }
  // 取消進行中的轉場（相機停在目前位置）
  function cancelTween() { tween = null; }
  // 整體平移視角：相機、注視點與進行中轉場的起訖點一起移動（跟著輸送中的工件看）
  function shiftView(delta) {
    camera.position.add(delta); controls.target.add(delta); view?.Tg.add(delta);
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
    renderer.setSize(w, h, false); camera.aspect = w / h; camera.updateProjectionMatrix(); refit(); invalidate();
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

  return { renderer, scene, camera, controls, lights, qp, addLabel, updateLabels, labels, goTo, cancelTween, shiftView, get tweening() { return tweening(); }, get fitScale() { return fitScale; }, resize, render, invalidate, loop, stop, clock, useLog };
}

// 標準 window.sim：統一檢查與截圖工具依賴 seekTo、setView、views、total、play、pause；
// 專案可再附加自己的成員（getter 會保留，例如 get T()）
export function exposeSim(members) {
  const sim = Object.defineProperties({}, Object.getOwnPropertyDescriptors(members));
  if (!Array.isArray(sim.views)) Object.defineProperty(sim, 'views', { value: Object.keys(members.views || {}), enumerable: true });
  for (const k of ['seekTo', 'setView', 'total', 'play', 'pause']) if (!(k in sim)) console.warn(`window.sim 缺少 ${k}`);
  window.sim = sim; return sim;
}
