import * as THREE from 'three';

/** Rotate around a parent-space pivot while retaining the authored transform. */
export function rotateAroundPivot(node: THREE.Object3D, restPosition: THREE.Vector3, restRotation: THREE.Quaternion, pivot: THREE.Vector3, rotation: THREE.Quaternion) {
  node.quaternion.copy(rotation).multiply(restRotation);
  node.position.copy(restPosition).sub(pivot).applyQuaternion(rotation).add(pivot);
}

export function translateAlongAxis(node: THREE.Object3D, restPosition: THREE.Vector3, axis: THREE.Vector3, distance: number) {
  node.position.copy(restPosition).addScaledVector(axis, distance);
}
