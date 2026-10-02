import * as THREE from 'three';

export function block(parent, size, pos, material) {
  const m = new THREE.Mesh(new THREE.BoxGeometry(...size), material);
  m.position.set(...pos); m.castShadow = m.receiveShadow = true; parent.add(m); return m;
}
export function cylinder(parent, radius, length, pos, material, axis = 'y', segments = 20) {
  const m = new THREE.Mesh(new THREE.CylinderGeometry(radius, radius, length, segments), material);
  if (axis === 'x') m.rotation.z = Math.PI / 2;
  if (axis === 'z') m.rotation.x = Math.PI / 2;
  m.position.set(...pos); m.castShadow = m.receiveShadow = true; parent.add(m); return m;
}
export function bevelBox(w, h, d, material, radius = 2) {
  const r = Math.min(radius, w/5, h/5, d/5), s = new THREE.Shape();
  s.moveTo(-w/2+r,-h/2+r); s.lineTo(w/2-r,-h/2+r); s.lineTo(w/2-r,h/2-r); s.lineTo(-w/2+r,h/2-r); s.closePath();
  const geo = new THREE.ExtrudeGeometry(s,{depth:d-2*r,bevelEnabled:true,bevelSize:r,bevelThickness:r,bevelSegments:3,steps:1});
  geo.translate(0,0,-d/2+r);
  const m = new THREE.Mesh(geo,material); m.castShadow=m.receiveShadow=true; return m;
}
const screwMetal = new THREE.MeshStandardMaterial({color:0x687179,metalness:.8,roughness:.3});
const screwSlot = new THREE.MeshStandardMaterial({color:0x171c20,roughness:.8});
export function screw(parent, pos, radius = 2, axis = 'y') {
  const g = new THREE.Group(); g.position.set(...pos);
  if(axis==='z') g.rotation.x=Math.PI/2;
  if(axis==='x') g.rotation.z=-Math.PI/2;
  parent.add(g); cylinder(g,radius,.5,[0,0,0],screwMetal,'y',16);
  cylinder(g,radius*.45,.025,[0,.26,0],screwSlot,'y',6); return g;
}
const textureCache = new Map();
// Canvas lettering stays crisp in close-up; values marked DEMO are never product records.
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
export function tube(parent, points, radius, material, segments = 28) {
  const path = new THREE.CatmullRomCurve3(points.map(p => new THREE.Vector3(...p)));
  const m = new THREE.Mesh(new THREE.TubeGeometry(path, segments, radius, 7, false), material); m.castShadow=m.receiveShadow=true; parent.add(m); return m;
}
export function profile(parent, points, y, depth, material, bevel = .8) {
  const shape = new THREE.Shape(points.map(([x, z]) => new THREE.Vector2(x, -z)));
  const geo = new THREE.ExtrudeGeometry(shape, { depth, bevelEnabled: bevel > 0, bevelSize: bevel, bevelThickness: bevel, bevelSegments: 2, steps: 1 });
  geo.rotateX(-Math.PI / 2);
  const m = new THREE.Mesh(geo, material); m.position.y = y; m.castShadow = m.receiveShadow = true; parent.add(m); return m;
}
export function rounded(parent, w, d, height, r, pos, material) {
  r = Math.min(r, w / 2, d / 2);
  const s = new THREE.Shape(), x = -w / 2, z = -d / 2;
  s.moveTo(x+r,z); s.lineTo(x+w-r,z); s.quadraticCurveTo(x+w,z,x+w,z+r);
  s.lineTo(x+w,z+d-r); s.quadraticCurveTo(x+w,z+d,x+w-r,z+d);
  s.lineTo(x+r,z+d); s.quadraticCurveTo(x,z+d,x,z+d-r); s.lineTo(x,z+r); s.quadraticCurveTo(x,z,x+r,z);
  const geo = new THREE.ExtrudeGeometry(s, { depth: height, bevelEnabled: true, bevelSize: Math.min(.45,height/4), bevelThickness: Math.min(.45,height/4), bevelSegments: 2, curveSegments: 4 });
  geo.rotateX(-Math.PI/2);
  const m = new THREE.Mesh(geo,material); m.position.set(...pos); m.castShadow=m.receiveShadow=true; parent.add(m); return m;
}
