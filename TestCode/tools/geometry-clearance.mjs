import * as THREE from 'three';

// Conservative oriented bounds of the rendered mesh (including rotation).
// A positive separating gap is a lower bound on physical separation. A
// negative value needs inspection for hollow/curved parts; it is not a
// measured penetration depth. Intended mount/slide contacts are excluded by
// explicit pair selection in the caller, never by a global collision bypass.
export function meshBounds(mesh) {
  if (!mesh.geometry.boundingBox) mesh.geometry.computeBoundingBox();
  const box = mesh.geometry.boundingBox;
  const center = box.getCenter(new THREE.Vector3()).applyMatrix4(mesh.matrixWorld);
  const half = box.getSize(new THREE.Vector3()).multiplyScalar(.5).toArray();
  const axes = [0, 1, 2].map(i => new THREE.Vector3().setFromMatrixColumn(mesh.matrixWorld, i));
  axes.forEach((axis, i) => { half[i] *= axis.length(); axis.normalize(); });
  return { mesh, center, half, axes };
}

export function separatingGap(a, b) {
  const delta = b.center.clone().sub(a.center);
  const axes = [...a.axes, ...b.axes, ...a.axes.flatMap(x => b.axes.map(y => new THREE.Vector3().crossVectors(x, y)))];
  let gap = -Infinity;
  for (const axis of axes) {
    if (axis.lengthSq() < 1e-12) continue;
    axis.normalize();
    const radius = o => o.axes.reduce((sum, v, i) => sum + o.half[i] * Math.abs(v.dot(axis)), 0);
    gap = Math.max(gap, Math.abs(delta.dot(axis)) - radius(a) - radius(b));
  }
  return gap;
}

export function minimumGap(first, second) {
  let result = { gap: Infinity };
  const a = first.map(meshBounds), b = second.map(meshBounds);
  for (const x of a) for (const y of b) {
    const gap = separatingGap(x, y);
    if (gap < result.gap) result = { gap, first: x.mesh.name || x.mesh.geometry.type, second: y.mesh.name || y.mesh.geometry.type };
  }
  return result;
}

// Includes exact endpoints even when duration is not a multiple of interval.
export function sampleTimes(start, duration, interval) {
  const count = Math.max(1, Math.ceil(duration / interval));
  return Array.from({ length: count + 1 }, (_, i) => start + duration * i / count);
}
