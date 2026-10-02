// Offline procedural surfaces. All markings are illustrative, not production records.
import * as THREE from 'three';

const cache = new Map();
export function microTexture(kind) {
  if (cache.has(kind)) return cache.get(kind);
  const n = 128, data = new Uint8Array(n * n * 4);
  for (let y = 0; y < n; y++) for (let x = 0; x < n; x++) {
    const hash = ((x * 1973 + y * 9277 + x * y * 26699) ^ (y << 7)) & 255;
    const warp = (Math.floor(x / 16) + Math.floor(y / 16)) % 2;
    const fiber = Math.sin((warp ? x : y) * Math.PI / 2);
    const arch = Math.sin(((warp ? y : x) % 16) / 16 * Math.PI);
    const v = kind === 'weave' ? 85 + arch * 65 + fiber * 15 + hash * .07
      : kind === 'brushed' ? 150 + Math.sin(y * 7.9) * 30 + hash * .13 : 145 + hash * .25;
    const i = (y * n + x) * 4;
    data[i] = data[i + 1] = data[i + 2] = v; data[i + 3] = 255;
  }
  const t = new THREE.DataTexture(data, n, n);
  t.wrapS = t.wrapT = THREE.RepeatWrapping; t.magFilter = THREE.LinearFilter;
  t.minFilter = THREE.LinearMipmapLinearFilter; t.generateMipmaps = true;
  t.anisotropy = 8; t.needsUpdate = true; cache.set(kind, t); return t;
}

export function pcbSurface(b) {
  const key = JSON.stringify([b.w, b.d, b.cx, b.cz, b.comps]);
  if (cache.has(key)) return cache.get(key);
  const c = document.createElement('canvas'); c.width = 512; c.height = 1024;
  const ctx = c.getContext('2d');
  // The headless kinematics verifier intentionally has no rasterizer.
  if (!ctx?.beginPath) return new THREE.MeshStandardMaterial({ color: 0x23694e, roughness: .48 });
  ctx.fillStyle = '#18573e'; ctx.fillRect(0, 0, 512, 1024);
  ctx.scale(512 / b.w, 1024 / b.d); ctx.translate(b.w / 2 - b.cx, b.d / 2 - b.cz);
  const stroke = (points, color, width) => {
    ctx.strokeStyle = color; ctx.lineWidth = width; ctx.beginPath();
    points.forEach(([x, z], i) => i ? ctx.lineTo(x, z) : ctx.moveTo(x, z)); ctx.stroke();
  };
  const xmin = b.cx - b.w / 2, zmin = b.cz - b.d / 2;
  for (let i = 0; i < 28; i++) {
    const x = xmin + 1.4 + (i % 14) * (b.w - 2.8) / 14;
    const z = zmin + 5 + Math.floor(i / 14) * b.d * .43;
    const end = Math.min(zmin + b.d - 2, z + b.d * .35 + i % 4);
    stroke([[x,z],[x,z+3],[x+1.1,z+4.1],[x+1.1,end-2],[x-.6,end-.3]], '#307559', .10);
    stroke([[x+.32,z],[x+.32,z+2.9],[x+1.42,z+4],[x+1.42,end-2]], '#164d3c', .09);
    ctx.fillStyle = '#b4ae75'; ctx.beginPath(); ctx.arc(x-.6,end-.3,.21,0,Math.PI*2); ctx.fill();
    ctx.fillStyle = '#153e32'; ctx.beginPath(); ctx.arc(x-.6,end-.3,.10,0,Math.PI*2); ctx.fill();
  }
  ctx.strokeStyle = '#b5d4ba'; ctx.fillStyle = '#d9e3cb'; ctx.lineWidth = .08;
  ctx.font = '.65px monospace';
  (b.comps || []).forEach((p, i) => {
    ctx.strokeRect(p.x-p.w/2-.35,p.z-p.d/2-.35,p.w+.7,p.d+.7);
    ctx.fillText((p.kind === 'chip' ? 'U' : 'C') + (i+1),p.x+p.w/2+.5,p.z+.2);
  });
  ctx.font = '1.05px monospace';
  ['SSD / USB', 'PCB  REV 1.0', 'DEMO  94V-0', 'CE'].forEach((s, i) => ctx.fillText(s,b.cx-b.w*.30,zmin+b.d*.60+i*1.65));
  const map = new THREE.CanvasTexture(c); map.colorSpace = THREE.SRGBColorSpace; map.anisotropy = 8;
  const mat = new THREE.MeshStandardMaterial({ map, roughness: .46, metalness: .12 });
  cache.set(key, mat); return mat;
}

// Merge only static geometry; connector pivots remain separate for physical motion.
export function batchStatic(group) {
  group.updateMatrixWorld(true);
  const inv = group.matrixWorld.clone().invert(), buckets = new Map(), meshes = [];
  group.traverse(o => {
    if (!o.isMesh || Array.isArray(o.material)) return;
    const geo = o.geometry.index ? o.geometry.toNonIndexed() : o.geometry.clone();
    geo.applyMatrix4(new THREE.Matrix4().multiplyMatrices(inv, o.matrixWorld));
    if (!buckets.has(o.material)) buckets.set(o.material, []);
    buckets.get(o.material).push(geo); meshes.push(o);
  });
  for (const m of meshes) { m.removeFromParent(); m.geometry.dispose(); }
  for (const [mat, geometries] of buckets) {
    const geo = new THREE.BufferGeometry();
    for (const name of ['position', 'normal', 'uv']) {
      const length = geometries.reduce((n,g) => n + g.getAttribute(name).array.length, 0);
      const data = new Float32Array(length); let offset = 0;
      for (const g of geometries) { const a = g.getAttribute(name).array; data.set(a, offset); offset += a.length; }
      geo.setAttribute(name, new THREE.BufferAttribute(data, name === 'uv' ? 2 : 3));
    }
    geometries.forEach(g => g.dispose());
    const m = new THREE.Mesh(geo, mat); m.castShadow = !mat.transparent; m.receiveShadow = true; group.add(m);
  }
}
