// 共用建模形狀（所有專案與共用模型只用這一套）。單位 mm；位置、尺寸一律用陣列 [x, y, z]。
//   block(parent, [w, h, d], [x, y, z], mat)            方塊
//   blockBetween(parent, [x0,y0,z0], [x1,y1,z1], mat)   以兩角點建立方塊
//   cylinder(parent, r, length, [x,y,z], mat, axis, segments, radiusTop)   圓柱（axis 'x'／'y'／'z'；radiusTop 做錐度）
//   rod(parent, a, b, r, mat)                           兩點之間的圓桿
//   tube／pipe／profile／rounded／bevelBox／screw       曲線管、直角配管（含流動貼圖）、擠出輪廓、圓角板、倒角方塊、螺絲
//   decal／plate／floorText／textTexture                文字貼紙、直立面板文字、地面文字、文字貼圖
// 材質用 core/geom/materials.js 的 MAT；parent 可為 null（只建網格不加入場景）。
import * as THREE from 'three';

export const D2R = Math.PI / 180;
export const HAS_DOM = typeof document !== 'undefined';

const shade = m => { m.castShadow = m.receiveShadow = true; return m; };

export function block(parent, size, pos, material) {
  const m = shade(new THREE.Mesh(new THREE.BoxGeometry(...size), material));
  m.position.set(...pos); parent?.add(m); return m;
}
export function blockBetween(parent, [x0, y0, z0], [x1, y1, z1], material) {
  return block(parent, [Math.abs(x1 - x0), Math.abs(y1 - y0), Math.abs(z1 - z0)], [(x0 + x1) / 2, (y0 + y1) / 2, (z0 + z1) / 2], material);
}
export function cylinder(parent, radius, length, pos, material, axis = 'y', segments = 20, radiusTop = radius) {
  const m = shade(new THREE.Mesh(new THREE.CylinderGeometry(radiusTop, radius, length, segments), material));
  if (axis === 'x') m.rotation.z = Math.PI / 2; else if (axis === 'z') m.rotation.x = Math.PI / 2;
  m.position.set(...pos); parent?.add(m); return m;
}
export function rod(parent, a, b, r, material, segments = 12) {
  const A = new THREE.Vector3(...a), B = new THREE.Vector3(...b), L = A.distanceTo(B);
  const m = shade(new THREE.Mesh(new THREE.CylinderGeometry(r, r, L, segments), material));
  m.position.copy(A).add(B).multiplyScalar(.5);
  m.quaternion.setFromUnitVectors(new THREE.Vector3(0, 1, 0), B.clone().sub(A).normalize());
  parent?.add(m); return m;
}
export function tube(parent, points, radius, material, segments = 28) {
  const path = new THREE.CatmullRomCurve3(points.map(p => new THREE.Vector3(...p)));
  const m = shade(new THREE.Mesh(new THREE.TubeGeometry(path, segments, radius, 7, false), material)); parent?.add(m); return m;
}
export function bevelBox(w, h, d, material, radius = 2) {
  const r = Math.min(radius, w / 5, h / 5, d / 5), s = new THREE.Shape();
  s.moveTo(-w / 2 + r, -h / 2 + r); s.lineTo(w / 2 - r, -h / 2 + r); s.lineTo(w / 2 - r, h / 2 - r); s.lineTo(-w / 2 + r, h / 2 - r); s.closePath();
  const geo = new THREE.ExtrudeGeometry(s, { depth: d - 2 * r, bevelEnabled: true, bevelSize: r, bevelThickness: r, bevelSegments: 3, steps: 1 });
  geo.translate(0, 0, -d / 2 + r);
  return shade(new THREE.Mesh(geo, material));
}
const screwMetal = new THREE.MeshStandardMaterial({ color: 0x687179, metalness: .8, roughness: .3 });
const screwSlot = new THREE.MeshStandardMaterial({ color: 0x171c20, roughness: .8 });
export function screw(parent, pos, radius = 2, axis = 'y') {
  const g = new THREE.Group(); g.position.set(...pos);
  if (axis === 'z') g.rotation.x = Math.PI / 2;
  if (axis === 'x') g.rotation.z = -Math.PI / 2;
  parent.add(g); cylinder(g, radius, .5, [0, 0, 0], screwMetal, 'y', 16);
  cylinder(g, radius * .45, .025, [0, .26, 0], screwSlot, 'y', 6); return g;
}
export function profile(parent, points, y, depth, material, bevel = .8) {
  const shape = new THREE.Shape(points.map(([x, z]) => new THREE.Vector2(x, -z)));
  const geo = new THREE.ExtrudeGeometry(shape, { depth, bevelEnabled: bevel > 0, bevelSize: bevel, bevelThickness: bevel, bevelSegments: 2, steps: 1 });
  geo.rotateX(-Math.PI / 2);
  const m = shade(new THREE.Mesh(geo, material)); m.position.y = y; parent.add(m); return m;
}
export function rounded(parent, w, d, height, r, pos, material) {
  r = Math.min(r, w / 2, d / 2);
  const s = new THREE.Shape(), x = -w / 2, z = -d / 2;
  s.moveTo(x + r, z); s.lineTo(x + w - r, z); s.quadraticCurveTo(x + w, z, x + w, z + r);
  s.lineTo(x + w, z + d - r); s.quadraticCurveTo(x + w, z + d, x + w - r, z + d);
  s.lineTo(x + r, z + d); s.quadraticCurveTo(x, z + d, x, z + d - r); s.lineTo(x, z + r); s.quadraticCurveTo(x, z, x + r, z);
  const geo = new THREE.ExtrudeGeometry(s, { depth: height, bevelEnabled: true, bevelSize: Math.min(.45, height / 4), bevelThickness: Math.min(.45, height / 4), bevelSegments: 2, curveSegments: 4 });
  geo.rotateX(-Math.PI / 2);
  const m = shade(new THREE.Mesh(geo, material)); m.position.set(...pos); parent.add(m); return m;
}

// ---------------------------------------------------------------- 配管與流動貼圖
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
// 直角配管：points 為轉折點，回傳 { mesh, setFlow(on), tick(time), length }
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

// ---------------------------------------------------------------- 文字
// 文字貼圖（瀏覽器才有；Node 端的 dom-stub 也能建立空白貼圖）
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
// 貼紙（產品標示、設備銘牌）：canvas 文字，近看清晰；同內容共用貼圖
const textureCache = new Map();
export function decal(parent, w, h, pos, rotation, lines, options = {}) {
  const key = JSON.stringify([lines, options]);
  let map = textureCache.get(key);
  if (!map) {
    const c = document.createElement('canvas'); c.width = 1024; c.height = 512;
    const ctx = c.getContext('2d');
    if (options.bg) { ctx.fillStyle = options.bg; ctx.fillRect(0, 0, c.width, c.height); }
    ctx.fillStyle = options.color || '#d9ddda';
    const rows = typeof lines === 'string' ? [lines] : lines;
    const font = Math.min(320, 390 / rows.length);
    ctx.font = `${options.bold ? 'bold ' : ''}${font}px Arial, sans-serif`;
    ctx.textAlign = options.center ? 'center' : 'left'; ctx.textBaseline = 'middle';
    rows.forEach((line, i) => ctx.fillText(line, options.center ? 512 : 26, 54 + (i + .5) * 390 / rows.length, 970));
    if (options.barcode) {
      for (let i = 0, x = 26; i < 86; i++) {
        const b = 2 + ((i * 13 + 7) % 5); if (i % 2 === 0) ctx.fillRect(x, 15, b, 110); x += b * 2;
      }
    }
    map = new THREE.CanvasTexture(c); map.colorSpace = THREE.SRGBColorSpace; map.anisotropy = 4;
    textureCache.set(key, map);
  }
  const m = new THREE.Mesh(new THREE.PlaneGeometry(w, h), new THREE.MeshStandardMaterial({ map, transparent: true, roughness: .85, polygonOffset: true, polygonOffsetFactor: -2 }));
  m.position.set(...pos); m.rotation.set(...rotation); parent.add(m); return m;
}
