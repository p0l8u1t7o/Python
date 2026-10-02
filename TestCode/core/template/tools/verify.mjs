// 本專案自有檢查（範例）：製程上的規則寫在這裡；通用的干涉、閃爍、倒序一致由 core 統一檢查負責。
//   node --import ../core/tools/register.mjs tools/verify.mjs
import '@core/verify/dom-stub.mjs';
import * as THREE from 'three';
import { writeFileSync, mkdirSync } from 'node:fs';
import { createProject, LAYOUT } from '../web/js/project.js';

const scene = new THREE.Scene(), project = createProject({ scene });
const failures = [];
// 例：放料時工件中心必須在出料台上方 ±5 mm
const placeStep = project.timeline.tracks.part.steps.find(s => s.end.mode === 'placed');
const st = project.apply(placeStep.start + .01);
if (Math.abs(st.gantry.x - LAYOUT.place.x) > 5) failures.push(`放料位置偏差 ${(st.gantry.x - LAYOUT.place.x).toFixed(1)} mm`);
// 例：節拍上限
if (project.total > 20) failures.push(`節拍 ${project.total.toFixed(1)} s 超過 20 s`);

const result = { ok: !failures.length, total: +project.total.toFixed(2), failures };
mkdirSync(new URL('../review/', import.meta.url), { recursive: true });
writeFileSync(new URL('../review/verification.json', import.meta.url), JSON.stringify(result, null, 2));
console.log(JSON.stringify(result));
process.exit(result.ok ? 0 : 1);
