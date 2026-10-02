// 共用材質與幾何小工具。Node 驗證環境沒有 document，文字貼圖一律回傳 null。
import * as THREE from 'three';

export const D2R = Math.PI / 180;
export const HAS_DOM = typeof document !== 'undefined';

const std = (color, roughness = .6, metalness = .1, extra = {}) => new THREE.MeshStandardMaterial({ color, roughness, metalness, ...extra });
export const MAT = {
  floor: std(0x899696, .8, .04), floorOut: std(0x3a4148, .95),
  wall: std(0xdfe3e6, .9, 0, { transparent: true, opacity: .16, depthWrite: false, side: THREE.DoubleSide }),
  wallBase: std(0xc9ced2, .85), column: std(0xb7b2a8, .85),
  door: std(0x8e9aa6, .5, .3), window: std(0x9fc7e6, .1, 0, { transparent: true, opacity: .45 }),
  steelBlue: std(0x1f4e8c, .5, .4), steelOrange: std(0xe0781f, .5, .35), steel: std(0x9aa3ab, .4, .7),
  steelDark: std(0x3a4148, .5, .5), alu: std(0xc4ccd3, .35, .6), black: std(0x1d2126, .6, .2),
  yellow: std(0xf2c230, .45, .15), fanuc: std(0xf5c400, .4, .15), fanucDark: std(0x2d3136, .5, .4),
  pallet: std(0x4a5560, .8), palletEmpty: std(0x56626e, .8),
  drum: new THREE.MeshPhysicalMaterial({ color: 0x1250bc, roughness: .36, metalness: 0, clearcoat: .28, clearcoatRoughness: .4 }), drumLid: std(0x1b58c0, .5, 0), cap: std(0xf2f4f6, .5, 0), hole: std(0x0d1726, .9),
  roller: std(0xb5bec6, .3, .8), belt: std(0x2a2f35, .9), pu: std(0xd9a441, .9),
  pp: std(0xd8dfe3, .52, 0, { side: THREE.DoubleSide }),
  ppSolid: std(0xc9d3d8, .75), ppDark: std(0x7b8a94, .7),
  fence: std(0xf2c230, .5, .2), mesh: std(0x2b3036, .7, .2, { transparent: true, opacity: .22, depthWrite: false, side: THREE.DoubleSide }),
  glass: new THREE.MeshPhysicalMaterial({ color: 0x9cc8ff, roughness: .05, transmission: .5, transparent: true, opacity: .55 }),
  water: std(0x6fc4ff, .1, 0, { transparent: true, opacity: .6, depthWrite: false, emissive: 0x0a3a66, emissiveIntensity: .4 }),
  waste: std(0xd88a3c, .3, 0, { transparent: true, opacity: .75 }),
  tankW: std(0xe7e3d6, .45, 0),
  tankWaste: std(0xc77b34, .4, 0), tankAlkali: std(0x8c6bd6, .4, 0), tankClean: std(0x58b6f2, .4, 0), tankFresh: std(0x8fd3ff, .4, 0),
  agv: std(0xee8a26, .45, .2), agvDark: std(0x2b3036, .5, .4),
  cabinet: std(0xd9dde0, .5, .2), screen: std(0x10283a, .3, 0, { emissive: 0x1e6fa8, emissiveIntensity: .6 }),
  green: std(0x3dd68c, .4, 0, { emissive: 0x3dd68c, emissiveIntensity: .8 }),
  red: std(0xff4d4d, .4, 0, { emissive: 0xff4d4d, emissiveIntensity: .8 }),
  amber: std(0xffb020, .4, 0, { emissive: 0xffb020, emissiveIntensity: .8 }),
};

function shade(m) { m.castShadow = true; m.receiveShadow = true; return m; }
export function box(parent, w, h, d, mat, x = 0, y = 0, z = 0) {
  const m = shade(new THREE.Mesh(new THREE.BoxGeometry(w, h, d), mat)); m.position.set(x, y, z); parent?.add(m); return m;
}
// 以兩角點建立方塊
export function boxAt(parent, [x0, y0, z0], [x1, y1, z1], mat) {
  return box(parent, Math.abs(x1 - x0), Math.abs(y1 - y0), Math.abs(z1 - z0), mat, (x0 + x1) / 2, (y0 + y1) / 2, (z0 + z1) / 2);
}
export function cyl(parent, r, h, mat, x = 0, y = 0, z = 0, axis = 'y', seg = 28, r2 = r) {
  const m = shade(new THREE.Mesh(new THREE.CylinderGeometry(r2, r, h, seg), mat));
  if (axis === 'x') m.rotation.z = Math.PI / 2; else if (axis === 'z') m.rotation.x = Math.PI / 2;
  m.position.set(x, y, z); parent?.add(m); return m;
}
// 兩點之間的圓桿
export function rod(parent, a, b, r, mat, seg = 12) {
  const A = new THREE.Vector3(...a), B = new THREE.Vector3(...b), L = A.distanceTo(B);
  const m = shade(new THREE.Mesh(new THREE.CylinderGeometry(r, r, L, seg), mat));
  m.position.copy(A).add(B).multiplyScalar(.5);
  m.quaternion.setFromUnitVectors(new THREE.Vector3(0, 1, 0), B.clone().sub(A).normalize());
  parent?.add(m); return m;
}

// 流動條紋貼圖（DataTexture，Node 也能建立）；offset 由主程式推進
export function flowTexture(color) {
  const c = new THREE.Color(color), data = new Uint8Array(8 * 4);
  for (let i = 0; i < 8; i++) {
    const k = i < 3 ? 1 : .35;
    data.set([c.r * 255 * k, c.g * 255 * k, c.b * 255 * k, 255], i * 4);
  }
  const t = new THREE.DataTexture(data, 8, 1); t.wrapS = t.wrapT = THREE.RepeatWrapping; t.magFilter = THREE.LinearFilter; t.needsUpdate = true;
  return t;
}
// 直角配管：points 為轉折點，回傳 { mesh, setFlow(on), length }
export function pipe(parent, points, r, color, idle = 0x6b7680) {
  const path = new THREE.CurvePath();
  for (let i = 1; i < points.length; i++) path.add(new THREE.LineCurve3(new THREE.Vector3(...points[i - 1]), new THREE.Vector3(...points[i])));
  const length = path.getLength(), tex = flowTexture(color); tex.repeat.set(length / 160, 1);
  const mat = new THREE.MeshStandardMaterial({ color: idle, roughness: .45, metalness: .3 });
  const mesh = shade(new THREE.Mesh(new THREE.TubeGeometry(path, Math.max(8, (points.length - 1) * 12), r, 10, false), mat));
  parent?.add(mesh);
  for (const p of points.slice(1, -1)) { const s = shade(new THREE.Mesh(new THREE.SphereGeometry(r * 1.15, 12, 8), mat)); s.position.set(...p); parent?.add(s); }
  let on = false;
  return {
    mesh, length, points, radius: r,
    setFlow(v) {
      if (v === on) return; on = v;
      mat.map = v ? tex : null; mat.color.setHex(v ? 0xffffff : idle); mat.emissive.setHex(v ? color : 0); mat.emissiveIntensity = v ? .35 : 0; mat.needsUpdate = true;
    },
    tick(time) { tex.offset.x = on ? -time * 2.2 : 0; },
  };
}

// 文字貼圖（瀏覽器才有）
export function textTexture(lines, { w = 512, h = 128, bg = null, fg = '#e8eef3', font = 'bold 54px "Noto Sans TC","Microsoft JhengHei",sans-serif', align = 'center' } = {}) {
  if (!HAS_DOM) return null;
  const c = document.createElement('canvas'); c.width = w; c.height = h; const g = c.getContext('2d');
  if (bg) { g.fillStyle = bg; g.fillRect(0, 0, w, h); }
  g.fillStyle = fg; g.font = font; g.textAlign = align; g.textBaseline = 'middle';
  const list = Array.isArray(lines) ? lines : [lines];
  list.forEach((s, i) => g.fillText(s, align === 'center' ? w / 2 : 16, h * (i + .5) / list.length));
  const t = new THREE.CanvasTexture(c); t.colorSpace = THREE.SRGBColorSpace; t.anisotropy = 4; return t;
}
// 地面文字（平放）
export function floorText(parent, lines, x, z, w, h, opts = {}) {
  // 畫布比例跟著平面尺寸，字級依行數自動縮放
  const n = Array.isArray(lines) ? lines.length : 1, cw = 1024, ch = Math.round(cw * h / w);
  const px = Math.floor(Math.min(ch / n * .62, 120));
  const tex = textTexture(lines, { w: cw, h: ch, font: `bold ${px}px "Noto Sans TC","Microsoft JhengHei",sans-serif`, ...opts }); if (!tex) return null;
  const m = new THREE.Mesh(new THREE.PlaneGeometry(w, h), new THREE.MeshBasicMaterial({ map: tex, transparent: true, depthWrite: false }));
  m.rotation.x = -Math.PI / 2; if (opts.rot) m.rotation.z = opts.rot; m.position.set(x, opts.y ?? 6, z); m.renderOrder = 2; parent.add(m); return m;
}
// 面板文字（直立）
export function plate(parent, lines, w, h, pos, rotY = 0, opts = {}) {
  const tex = textTexture(lines, { bg: '#e9edf0', fg: '#1d2833', font: 'bold 44px "Noto Sans TC","Microsoft JhengHei",sans-serif', ...opts });
  if (!tex) return null;
  const m = new THREE.Mesh(new THREE.PlaneGeometry(w, h), new THREE.MeshStandardMaterial({ map: tex, roughness: .6 }));
  m.position.set(...pos); m.rotation.y = rotY; parent.add(m); return m;
}

// 平滑曲線：五次 S 曲線，端點速度與加速度為 0
export const smooth = t => t * t * t * (10 + t * (-15 + 6 * t));
export const lerp = (a, b, t) => a + (b - a) * t;
export const clamp01 = t => Math.max(0, Math.min(1, t));
