import * as THREE from "three";
import type { Timeline } from "./types";

type RestTransform = {
  position: THREE.Vector3;
  quaternion: THREE.Quaternion;
  scale: THREE.Vector3;
  axis: THREE.Vector3;
  type: string;
};

export type RestTransforms = Map<string, RestTransform>;

export function captureRestTransforms(root: THREE.Object3D): RestTransforms {
  const rest: RestTransforms = new Map();
  root.traverse((object) => {
    const joint = object.userData.joint as
      { type?: string; axis?: [number, number, number] } | undefined;
    if (!joint) return;
    rest.set(object.name, {
      position: object.position.clone(),
      quaternion: object.quaternion.clone(),
      scale: object.scale.clone(),
      axis: new THREE.Vector3(...(joint.axis ?? [0, 0, 1])).normalize(),
      type: joint.type ?? "fixed",
    });
  });
  const workpiece = root.getObjectByName("workpiece");
  if (workpiece && !rest.has("workpiece")) {
    rest.set("workpiece", {
      position: workpiece.position.clone(),
      quaternion: workpiece.quaternion.clone(),
      scale: workpiece.scale.clone(),
      axis: new THREE.Vector3(0, 0, 1),
      type: "pose",
    });
  }
  return rest;
}

export function applyTimeline(
  root: THREE.Object3D,
  timeline: Timeline,
  time: number,
  rest: RestTransforms,
) {
  for (const [name, transform] of rest) {
    const object = root.getObjectByName(name);
    if (!object) continue;
    object.position.copy(transform.position);
    object.quaternion.copy(transform.quaternion);
    object.scale.copy(transform.scale);
  }

  for (const [name, track] of Object.entries(timeline.nodes)) {
    if (track.joints_deg?.length && track.joint_names?.length) {
      const values = interpolateLinear(track.joints_deg, time);
      track.joint_names.forEach((jointName, index) => {
        applyJoint(root.getObjectByName(`${name}.${jointName}`), values[index], rest);
      });
    }
    const scalarTrack = track.value_mm ?? track.value_deg ?? track.value;
    if (scalarTrack?.length) {
      applyJoint(root.getObjectByName(name), interpolateLinear(scalarTrack, time)[0], rest);
    }
  }

  const poseTrack = timeline.nodes.workpiece?.pose_quat;
  const workpiece = root.getObjectByName("workpiece");
  if (workpiece && poseTrack?.length) {
    const pose = interpolatePose(poseTrack, time);
    workpiece.position.fromArray(pose.position);
    workpiece.quaternion.copy(pose.quaternion);
  }
  root.updateMatrixWorld(true);
}

function applyJoint(
  object: THREE.Object3D | undefined,
  value: number | undefined,
  rest: RestTransforms,
) {
  if (!object || value === undefined) return;
  const transform = rest.get(object.name);
  if (!transform) return;
  if (transform.type === "revolute") {
    object.quaternion
      .copy(transform.quaternion)
      .multiply(
        new THREE.Quaternion().setFromAxisAngle(transform.axis, THREE.MathUtils.degToRad(value)),
      );
  } else if (transform.type === "prismatic") {
    const parentDirection = transform.axis.clone().applyQuaternion(transform.quaternion);
    object.position.copy(transform.position).addScaledVector(parentDirection, value);
  }
}

export function interpolateLinear(keys: number[][], time: number): number[] {
  const { first, second, ratio } = bracket(keys, time);
  return first
    .slice(1)
    .map((value, index) => THREE.MathUtils.lerp(value, second[index + 1], ratio));
}

function interpolatePose(keys: number[][], time: number) {
  const { first, second, ratio } = bracket(keys, time);
  const position = first
    .slice(1, 4)
    .map((value, index) => THREE.MathUtils.lerp(value, second[index + 1], ratio)) as [
    number,
    number,
    number,
  ];
  const firstQuaternion = new THREE.Quaternion().fromArray(first.slice(4, 8));
  const secondQuaternion = new THREE.Quaternion().fromArray(second.slice(4, 8));
  return { position, quaternion: firstQuaternion.slerp(secondQuaternion, ratio) };
}

function bracket(keys: number[][], time: number) {
  if (time <= keys[0][0]) return { first: keys[0], second: keys[0], ratio: 0 };
  for (let index = 1; index < keys.length; index += 1) {
    if (time <= keys[index][0]) {
      const first = keys[index - 1];
      const second = keys[index];
      return {
        first,
        second,
        ratio: (time - first[0]) / Math.max(second[0] - first[0], Number.EPSILON),
      };
    }
  }
  const last = keys.at(-1)!;
  return { first: last, second: last, ratio: 0 };
}
