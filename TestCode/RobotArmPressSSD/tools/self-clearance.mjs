import * as THREE from 'three';

// Oriented mesh bounds, rather than world AABBs, avoid false overlap when the
// camera is tilted. Cylinders and bevels remain conservatively enclosed.
function bounds(mesh) {
  if (!mesh.geometry.boundingBox) mesh.geometry.computeBoundingBox();
  const box = mesh.geometry.boundingBox;
  const center = box.getCenter(new THREE.Vector3()).applyMatrix4(mesh.matrixWorld);
  const half = box.getSize(new THREE.Vector3()).multiplyScalar(.5).toArray();
  const axes = [0, 1, 2].map(i => new THREE.Vector3().setFromMatrixColumn(mesh.matrixWorld, i));
  axes.forEach((axis, i) => { half[i] *= axis.length(); axis.normalize(); });
  return { mesh, center, half, axes };
}

function separatingGap(a, b) {
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

export function cameraArmClearance(robot) {
  const arm = robot.clearanceParts.arm.map(bounds), camera = robot.clearanceParts.camera.map(bounds);
  let closest = { gap: Infinity };
  for (const a of arm) for (const c of camera) {
    const gap = separatingGap(a, c);
    if (gap < closest.gap) closest = { gap, arm: a.mesh.name, camera: c.mesh.name || c.mesh.geometry.type };
  }
  return closest;
}
