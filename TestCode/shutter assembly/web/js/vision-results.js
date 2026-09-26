// 相機畫面上的模擬檢測標記（投影 3D 位置；數值為示意，非影像辨識結果）
import * as THREE from 'three';
import { planeRegion } from './vision-overlay.js';
import { PART, BLADES, bladeHoles, bladeOutline, drivePin } from './product.js';
import { OFFSETS } from './sequence.js';

const fmt = n => (n >= 0 ? '+' : '') + n.toFixed(2);
const holeBox = (obj, x, z, y = 0, r = 0.75) => planeRegion(obj, x, y, z, r * 2, r * 2);

export function shutterMarks(st, s, { cam, exposure }) {
  const P = st.parts, marks = [];
  const shot = s.shot || '', [kind, id] = shot.split(':');
  if (cam === 'up') {
    const held = id || Object.keys(P).find(k => ['T1', 'T2'].includes(s.loc[k]));
    if (!held || !['T1', 'T2'].includes(s.loc[held])) return marks;
    const obj = P[held], off = OFFSETS[held], status = !exposure ? 'pending' : held === 'L2x' ? 'ng' : 'ok';
    if (held === 'cover') {
      const [aw, ad] = PART.base.aperture;
      marks.push({ points: planeRegion(obj, 0, -PART.cover.t, 0, aw, ad), status, label: exposure ? `光圈中心 Δx ${fmt(off.x)} Δz ${fmt(off.z)}` : '上蓋 待取像' });
      marks.push({ points: planeRegion(obj, 0, -PART.cover.t, 0, PART.cover.w, PART.cover.d), status, label: exposure ? `外形 θ ${fmt(off.a)}°` : '' });
      return marks;
    }
    const h = bladeHoles(), y = -PART.blade.t * (held === 'L2x' ? 2 : 1);
    const bladeKind = held === 'L2x' ? 'large' : BLADES.find(b => b.id === held).kind;
    const contour = bladeOutline(bladeKind).map(p => obj.localToWorld(new THREE.Vector3(p.x, y, p.z)));
    contour.push(contour[0]);
    marks.push({ points: holeBox(obj, h.pivot.x, h.pivot.z, y), status, label: !exposure ? '樞軸孔 待取像' : held === 'L2x' ? '疊片：厚度／輪廓異常 NG' : `樞軸孔 Δx ${fmt(off.x)} Δz ${fmt(off.z)}` });
    marks.push({ points: holeBox(obj, h.slot.x, h.slot.z, y, 0.9), status, label: exposure && held !== 'L2x' ? `長孔 θ ${fmt(off.a)}°` : '', contour });
    return marks;
  }
  // 下視相機
  const base = P.base;
  if (kind === 'down' && id === 'pins') {
    for (const key of ['P1', 'P2']) {
      const pv = PART.pivots[key], d = drivePin(key);
      marks.push({ points: holeBox(base, pv.x, pv.z, PART.pin.pivotTop, 0.8), status: exposure ? 'ok' : 'pending', label: `${key} 樞軸銷 φ0.80` });
      marks.push({ points: holeBox(base, d.x, d.z, PART.pin.driveTop, 0.7), status: exposure ? 'ok' : 'pending', label: `撥桿銷 ${key}` });
    }
  } else if (kind === 'down' && (id === 'checkS' || id === 'checkL')) {
    const list = BLADES.filter(b => id === 'checkL' || b.kind === 'small');
    for (const b of list) { const h = bladeHoles(); marks.push({ points: holeBox(P[b.id], h.pivot.x, h.pivot.z, 0, 0.9), status: exposure ? 'ok' : 'pending', label: `${b.name} 套銷 OK` }); }
  } else if (kind === 'down' && id === 'final') {
    const [aw, ad] = PART.base.aperture;
    marks.push({ points: planeRegion(P.cover, 0, 0, 0, PART.cover.w, PART.cover.d), status: exposure ? 'ok' : 'pending', label: '上蓋平貼、4 卡勾 OK' });
    marks.push({ points: planeRegion(P.cover, 0, 0, 0, aw, ad), status: exposure ? 'ok' : 'pending', label: '光圈淨空 OK' });
  }
  return marks;
}
