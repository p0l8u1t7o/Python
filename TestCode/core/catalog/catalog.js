// 模型目錄：列出 core/models 登記的模型，可調參數、拖動狀態並看用法。
import * as THREE from 'three';
import { createStage, exposeSim } from '@core/ui/stage.js';
import { MODELS } from '@core/models/index.js';

const $ = id => document.getElementById(id);
const stage = createStage({ canvas: $('c'), camera: { near: 5, far: 40000 }, exposure: 1.05, sun: { position: [-2000, 4000, 2500], target: [0, 0, 0], shadow: { mapSize: 2048, camera: { left: -3000, right: 3000, top: 3000, bottom: -3000, near: 500, far: 12000 } } } });
const { scene, camera } = stage;
const floor = new THREE.Mesh(new THREE.CircleGeometry(6000, 64), new THREE.MeshStandardMaterial({ color: 0x5d6770, roughness: .9 }));
floor.rotation.x = -Math.PI / 2; floor.position.y = -1; floor.receiveShadow = true; scene.add(floor);
const grid = new THREE.GridHelper(12000, 60, 0x3a4652, 0x2a333c); grid.position.y = 0; scene.add(grid);

const defaults = spec => Object.fromEntries(Object.entries(spec || {}).map(([k, v]) => [k, v.value]));
let current = null, model = null, params = {}, state = {}, anim = false, phase = 0;

function slider(host, key, s, value, onInput) {
  const row = document.createElement('label'); row.className = 'row';
  const step = s.step ?? ((s.max - s.min) / 200);
  row.innerHTML = `<span>${s.label || key}${s.unit ? `（${s.unit}）` : ''}</span><output>${value}</output><input type="range" min="${s.min}" max="${s.max}" step="${step}" value="${value}">`;
  const input = row.querySelector('input'), out = row.querySelector('output');
  input.oninput = () => { out.textContent = (+input.value).toFixed(step < 1 ? 2 : 0); onInput(+input.value); };
  host.appendChild(row); return input;
}

function build(fit = false) {
  if (model) scene.remove(model.root);
  model = current.create({ ...params });
  model.root.traverse(o => { if (o.isMesh) { o.castShadow = o.receiveShadow = true; } });
  scene.add(model.root); model.set?.(state); stage.invalidate(true);
  if (fit) frame();
}
function frame() {
  const box = new THREE.Box3().setFromObject(model.root), size = box.getSize(new THREE.Vector3()), c = box.getCenter(new THREE.Vector3());
  const d = Math.max(size.x, size.y, size.z, 200) * 1.6;
  stage.goTo([c.x - d * .8, c.y + d * .6, c.z + d], [c.x, c.y, c.z], true);
}

function select(mod) {
  current = mod; params = defaults(mod.meta.params); state = defaults(mod.meta.states); anim = false; $('animate').textContent = '▶ 來回動作';
  document.querySelectorAll('#list button').forEach(b => b.classList.toggle('on', b.dataset.id === mod.meta.id));
  $('title').textContent = mod.meta.name;
  $('params').innerHTML = Object.keys(mod.meta.params || {}).length ? '' : '<p class="muted">固定尺寸</p>';
  for (const [k, s] of Object.entries(mod.meta.params || {})) slider($('params'), k, s, params[k], v => { params[k] = v; build(); });
  $('states').innerHTML = Object.keys(mod.meta.states || {}).length ? '' : '<p class="muted">靜態模型</p>';
  $('animate').hidden = !Object.keys(mod.meta.states || {}).length;
  for (const [k, s] of Object.entries(mod.meta.states || {})) slider($('states'), k, s, state[k], v => { state[k] = v; model.set?.(state); stage.invalidate(true); });
  $('usage').textContent = mod.meta.usage || '';
  $('source').textContent = mod.meta.source ? `原用於 ${mod.meta.source}` : 'core 內建';
  history.replaceState(null, '', '#' + mod.meta.id);
  build(true);
}

// 依分類列出
const cats = {};
for (const m of MODELS) (cats[m.meta.category] ||= []).push(m);
for (const [cat, list] of Object.entries(cats)) {
  const h = document.createElement('h2'); h.textContent = cat; $('list').appendChild(h);
  for (const m of list) { const b = document.createElement('button'); b.textContent = m.meta.name; b.dataset.id = m.meta.id; b.onclick = () => select(m); $('list').appendChild(b); }
}
$('animate').onclick = () => { anim = !anim; $('animate').textContent = anim ? '⏸ 停止' : '▶ 來回動作'; };
select(MODELS.find(m => m.meta.id === location.hash.slice(1)) || MODELS[0]);

stage.loop(dt => {
  if (!anim) return false;
  phase += dt * .4; const u = .5 - .5 * Math.cos(phase * Math.PI);
  for (const [k, s] of Object.entries(current.meta.states || {})) state[k] = s.min + (s.max - s.min) * u;
  model.set?.(state); return true;
});
exposeSim({ seekTo: () => { }, setView: id => { const m = MODELS.find(x => x.meta.id === id); if (m) select(m); }, views: MODELS.map(m => m.meta.id), total: 0, play: () => { anim = true; }, pause: () => { anim = false; } });
