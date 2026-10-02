// 主程式：舞台（core/ui/stage.js）＋播放控制（core/ui/player.js）＋本專案的視角與面板。
// 場景與每個時間點的狀態全部來自 project.js，與 core 統一檢查用的是同一份。
import * as THREE from 'three';
import { createStage, exposeSim } from '@core/ui/stage.js';
import { createPlayer } from '@core/ui/player.js';
import { createProject, LAYOUT } from './project.js';

const qp = new URLSearchParams(location.search);
const stage = createStage({
  canvas: document.getElementById('c'),
  camera: { near: 5, far: 30000 },
  controls: { minDistance: 200, maxDistance: 12000 },
  sun: { intensity: 1.5, position: [-1500, 3200, 1800], target: [0, 600, 0], shadow: { mapSize: 2048, camera: { left: -2000, right: 2000, top: 2000, bottom: -2000, near: 500, far: 8000 } } },
});
const { scene, camera, controls } = stage;
const project = createProject({ scene });

// ---------------------------------------------------------------- 視角：[相機位置, 注視點]
const VIEWS = {
  iso: [[-2200, 2200, 2600], [0, 800, 0]],
  top: [[0, 4200, 10], [0, 0, 0]],
  pick: [[-1100, 1700, 1700], [LAYOUT.pick.x, 1000, 0]],
  place: [[1700, 1700, 1700], [LAYOUT.place.x, 1000, 0]],
};
function setView(name, instant = false) {
  const v = VIEWS[name]; if (!v) return;
  stage.goTo(v[0], v[1], instant);
  document.querySelectorAll('#views button').forEach(b => b.classList.toggle('on', b.dataset.view === name));
}
const viewBar = document.getElementById('views');
for (const name of Object.keys(VIEWS)) { const b = document.createElement('button'); b.textContent = name; b.dataset.view = name; b.onclick = () => setView(name); viewBar.appendChild(b); }

stage.addLabel('取料位', () => new THREE.Vector3(LAYOUT.pick.x, 1100, 0));

// ---------------------------------------------------------------- 播放與面板
const phase = document.getElementById('phase');
const player = createPlayer({
  total: project.total,
  apply: T => project.apply(T),
  events: project.timeline.events.map(e => ({ time: e.start, label: e.action })),
  onChange: (T) => {
    const act = project.timeline.activity(T);
    phase.textContent = act.length ? act.map(s => s.action).join('、') : '待命';
    stage.invalidate(true);
  },
});
document.getElementById('cycleTime').textContent = `節拍 ${project.total.toFixed(1)} s`;
document.getElementById('checks').innerHTML = (project.layoutChecks?.() || []).map(r => `<li class="${r.ok ? 'ok' : 'ng'}">${r.ok ? '✓' : '✗'} ${r.name}<span>${r.value ?? ''}</span></li>`).join('');

setView(qp.get('view') || 'iso', true);
if (qp.has('cam')) { const a = qp.get('cam').split(',').map(Number); if (a.length === 6) stage.goTo(a.slice(0, 3), a.slice(3), true); }
document.getElementById('loading')?.classList.add('hide');
stage.loop(dt => { const changed = player.update(dt); stage.updateLabels(); return changed; });

exposeSim({ seekTo: player.seekTo, setView, views: VIEWS, total: project.total, play: player.play, pause: player.pause, get T() { return player.T; }, project });
