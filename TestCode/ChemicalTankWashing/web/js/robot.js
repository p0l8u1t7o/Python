// FANUC R-2000iC/165F 六軸手臂（共用模型 core/models/robots/fanuc-r2000ic.js）＋夾桶夾爪。
// 本檔只放本專案的部分：手臂站位、夾桶夾爪與 TCP、夾桶位姿 poseDrum、碰撞連桿的工具段。
import * as THREE from 'three';
import { createArm, K, LIMITS, SPEED, JOINTS } from '@core/models/robots/fanuc-r2000ic.js';
import { createWashGripper } from './gripper.js';
import { ROBOT } from './layout.js';

export { K, LIMITS, SPEED, JOINTS };

export function createRobot() {
  const arm = createArm({ name: 'robot' });
  const { root, j, q, apply, setJoints } = arm;
  root.position.set(ROBOT.x, 0, ROBOT.z);

  // ---- 夾桶夾爪：工具 +Z 指向桶軸（＝法蘭軸），桶軸為工具 +Y，桶中心在工具 Z = ROBOT.grip ----
  const tool = new THREE.Group(); tool.rotation.y = Math.PI / 2; arm.flange.add(tool);
  const gripper = createWashGripper(tool);
  const tcp = new THREE.Object3D(); tcp.position.z = ROBOT.grip; tool.add(tcp);
  apply();

  // 工具 +Z 與法蘭軸同向；tool → flange 為繞 Y −90°（明確給定，與原本的幾何初始解逐位元相同）
  const solver = arm.createSolver({
    tool, tcp, approach: new THREE.Vector3(0, 0, 1),
    toFlange: new THREE.Quaternion().setFromAxisAngle(new THREE.Vector3(0, 1, 0), -Math.PI / 2),
  });

  // 夾桶位姿：center 為桶中心，up 為桶軸（桶頂方向），approach 為夾爪前進方向；roll 繞工具 Z 再轉
  const _m = new THREE.Matrix4();
  function poseDrum(center, up = new THREE.Vector3(0, 1, 0), approach = new THREE.Vector3(1, 0, 0), roll = 0, extra = null) {
    const Y = up.clone().normalize(), Z = approach.clone().addScaledVector(Y, -approach.dot(Y)).normalize(), X = new THREE.Vector3().crossVectors(Y, Z);
    const rot = new THREE.Quaternion().setFromRotationMatrix(_m.makeBasis(X, Y, Z));
    if (roll) rot.multiply(new THREE.Quaternion().setFromAxisAngle(new THREE.Vector3(0, 0, 1), roll));
    if (extra) rot.multiply(extra);
    return { target: center.clone(), rot };
  }
  // 碰撞連桿：手臂五段＋法蘭到夾爪前緣（工具 Z 230、半徑 300）
  const links = () => arm.links(tool.localToWorld(new THREE.Vector3(0, 0, 230)), 300);
  return { root, q, j, tool, tcp, apply, poseDrum, solve: solver.solve, track: solver.track, setJoints, gripper, setJaw: v => gripper.set(v), links, error: solver.error };
}
