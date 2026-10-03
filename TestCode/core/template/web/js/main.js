// 主程式：舞台（core/ui/stage.js）＋播放列（core/ui/player.js）＋共用版面與相機視窗（core/ui/viewer-workspace.js）＋本專案的視角、站別與面板。
// 場景與每個時間點的狀態全部來自 project.js，與 core 統一檢查用的是同一份。
// 版面骨架在 index.html（#topbar／#side／#bottombar）；手機、平板的精簡版面由 createViewerWorkspace 自動切換，這裡不必處理。
import * as THREE from 'three';
import { createStage, exposeSim } from '@core/ui/stage.js';
import { createPlayer } from '@core/ui/player.js';
import { createViewerWorkspace } from '@core/ui/viewer-workspace.js';
import { createProject, LAYOUT, STATIONS } from './project.js';

const qp = new URLSearchParams(location.search);
const $ = id => document.getElementById(id);

// ---------------------------------------------------------------- 舞台
// look：配色、曝光與燈光強度；extent：場景中心與半徑（mm），推算太陽／補光位置、陰影範圍與霧
const canvas = $('c');
const stage = createStage({
  canvas, look: 'cell', extent: { center: [0, 700, 0], radius: 2200 },
  camera: { near: 5, far: 30000 },
  controls: { minDistance: 200, maxDistance: 12000 },
});
const { renderer, scene, camera, controls } = stage;
const project = createProject({ scene });
const { timeline, part, stationStart } = project;

// ---------------------------------------------------------------- 相機視窗（範例：取料位上方的虛擬相機；不需要時連同 render() 裡的 renderCamera 一起刪掉）
const pickCam = new THREE.PerspectiveCamera(32, 1.5, 50, 8000);
pickCam.position.set(LAYOUT.pick.x, 1900, 700); pickCam.lookAt(LAYOUT.pick.x, LAYOUT.conveyor.top, LAYOUT.pick.z);

// ---------------------------------------------------------------- 共用版面：精簡版面（☰ 製程與視角、⚙ 播放設定、工具列開側欄）、相機視窗、焦點追隨（◎）
const workspace = createViewerWorkspace({
  camera, controls, canvas, resize: stage.resize,
  getFocus: () => part.getWorldPosition(new THREE.Vector3()).add(new THREE.Vector3(0, LAYOUT.part[1] / 2, 0)),
  focusOffset: [-600, 550, 800],
  onFocus: () => { stage.cancelTween(); document.querySelectorAll('.views [data-view]').forEach(b => b.classList.remove('on')); },
});

// ---------------------------------------------------------------- 視角：[相機位置, 注視點]（照桌面寫；手機直向等窄畫布由 stage 自動拉遠）
const VIEWS = {
  iso: [[-2200, 2200, 2600], [0, 800, 0]],
  pick: [[-1100, 1700, 1700], [LAYOUT.pick.x, 1000, 0]],
  place: [[1700, 1700, 1700], [LAYOUT.place.x, 1000, 0]],
  top: [[0, 4200, 10], [0, 0, 0]],
};
function setView(name, instant = false) {
  const v = typeof VIEWS[name] === 'function' ? VIEWS[name]() : VIEWS[name]; if (!v) return;
  workspace.stopFollowing();
  stage.goTo(v[0], v[1], instant);
  document.querySelectorAll('.views [data-view]').forEach(b => b.classList.toggle('on', b.dataset.view === name));
}
document.querySelectorAll('.views [data-view]').forEach(b => b.onclick = () => setView(b.dataset.view));

// ---------------------------------------------------------------- 3D 標籤：標籤底邊在點上方；priority 大者在窄畫布避讓時優先顯示
const label = (html, getPos, priority = 0) => stage.addLabel(html, getPos, '', { anchor: 'above', priority });
label('取料位', new THREE.Vector3(LAYOUT.pick.x, LAYOUT.conveyor.top + 40, LAYOUT.conveyor.width / 2 + 120), 2);
label('出料台', new THREE.Vector3(LAYOUT.place.x, LAYOUT.place.top, LAYOUT.place.z + 200), 1);
label('龍門', new THREE.Vector3(LAYOUT.gantry.cx, LAYOUT.gantry.height + 150, LAYOUT.conveyor.z - LAYOUT.gantry.offset));

// ---------------------------------------------------------------- 站別按鈕（跳到該站第一個步驟）
const stationBar = $('stations');
STATIONS.forEach((name, i) => {
  const b = document.createElement('button'); b.className = 'st'; b.dataset.st = i;
  b.innerHTML = `<span class="idx">S${i + 1}</span>${name}`; b.onclick = () => player.seekTo(stationStart[i]);
  stationBar.appendChild(b);
});

// ---------------------------------------------------------------- 面板
const events = timeline.events;
const ui = { action: $('action'), substep: $('substep'), stationName: $('stationName'), stations: [...stationBar.children] };
$('cycleTime').textContent = `節拍 ${project.total.toFixed(1)} s`;
const checks = project.layoutChecks?.() || [];
$('checks').innerHTML = checks.map(r => `<li class="${r.ok ? 'ok' : 'ng'}">${r.ok ? '✓' : '✗'} ${r.name}<span>${r.value ?? ''}</span></li>`).join('');
$('checkCount').textContent = `${checks.filter(r => r.ok).length} / ${checks.length}`;
let shown = '';
function updatePanels(T) {
  const act = timeline.activity(T), last = events.filter(e => e.start <= T + 1e-6).at(-1), station = last?.station ?? 0;
  const key = act.map(s => s.action).join('、') + '|' + station + '|' + (T >= project.total - 1e-6);
  if (key === shown) return; shown = key;
  ui.action.textContent = act.length ? act.map(s => s.action).join('、') : T >= project.total - 1e-6 ? '完成' : '待命';
  ui.substep.textContent = act.map(s => s.sub).filter(Boolean).join('、');
  ui.stationName.textContent = `S${station + 1} ${STATIONS[station]}`;
  ui.stations.forEach((b, i) => { b.classList.toggle('active', i === station); b.classList.toggle('done', i < station || T >= project.total - 1e-6); });
}

// ---------------------------------------------------------------- 播放列（標準元素 playBtn／restartBtn／speed／timeline／clock／stepSelect／previous／next／loop）
const player = createPlayer({
  total: project.total,
  apply: T => project.apply(T),
  events: events.map(e => ({ time: e.start, label: `S${e.station + 1} · ${e.action}` })),
  onChange: T => { updatePanels(T); stage.invalidate(true); },
});

// 每格繪製：相機視窗（畫進離屏目標，不動主畫布）→ 主畫面
function render() {
  workspace.renderCamera({ renderer, scene, camera: pickCam, title: '取料位相機（虛擬）', result: ui.action.textContent, marks: { time: player.T } });
  workspace.renderOverview(renderer, scene);
}

setView(qp.get('view') in VIEWS ? qp.get('view') : 'iso', true);
if (qp.has('cam')) { const a = qp.get('cam').split(',').map(Number); if (a.length === 6 && a.every(Number.isFinite)) stage.goTo(a.slice(0, 3), a.slice(3), true); }
$('loading').classList.add('hide');
// ?movie 時 stage 不啟動迴圈（交給錄影程式）
stage.loop(dt => { const changed = player.update(dt); workspace.follow(); stage.updateLabels(); return changed; }, { render });

exposeSim({ seekTo: player.seekTo, setView, views: VIEWS, total: project.total, play: player.play, pause: player.pause, get T() { return player.T; }, stationStart, project });
