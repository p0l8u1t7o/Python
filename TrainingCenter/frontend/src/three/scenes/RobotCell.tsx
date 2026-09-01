import { useContext, useRef } from 'react';
import { useFrame } from '@react-three/fiber';
import * as THREE from 'three';
import {
  BeltConveyor, Blinker, Box, Cabinet, Cyl, Cylinder, Floor, RobotArm, SceneCtx, Static,
  ease, useCycle, type CycleStep,
} from '../Parts';

/**
 * 三站接力的組裝循環。三支手臂**互相等待**而不是各動各的，
 * 對應教材 ARM-20「兩台手臂共用區域一定要有互鎖旗標，一次只能一台進入」。
 *
 *   R1 從料盤取件放上輸送帶 → 輸送到 R2 → R2 鎖螺絲 → 輸送到 R3 → R3 真空吸取下料
 */
const STEPS: CycleStep[] = [
  { name: 'R1 視覺定位：固定相機拍照算出工件座標', dur: 1.6 },
  { name: 'R1 取件：下降、夾爪夾持、上升', dur: 2.4 },
  { name: 'R1 放件：移到輸送帶並放開', dur: 2.2 },
  { name: '輸送：載具送往 R2 鎖付站', dur: 2.0 },
  { name: '治具夾緊 + R2 鎖螺絲', dur: 2.6 },
  { name: '輸送：載具送往 R3 下料站', dur: 2.0 },
  { name: 'R3 真空吸取下料', dur: 2.4 },
];

type Pose = [number, number, number, number, number, number];

/** 在兩組關節角之間內插，夾爪值直接取目標值。 */
const lerpPose = (a: Pose, b: Pose, k: number): Pose =>
  a.map((v, i) => v + (b[i] - v) * k) as Pose;

// 待命 / 取料 / 放料 三個姿態（J1,J2,J3,J4,J5,夾爪開度）
const R1_HOME: Pose = [0.0, -0.35, 0.9, 0, -0.5, 1];
const R1_PICK: Pose = [-0.95, 0.25, 1.25, 0, -0.6, 1];
const R1_PICK_CLOSED: Pose = [-0.95, 0.25, 1.25, 0, -0.6, 0];
const R1_PLACE: Pose = [0.55, 0.05, 1.05, 0, -0.5, 0];
const R1_PLACE_OPEN: Pose = [0.55, 0.05, 1.05, 0, -0.5, 1];

const R2_HOME: Pose = [0, -0.5, 1.0, 0, -0.4, 0];
const R2_WORK: Pose = [0, 0.15, 1.2, 0, -0.35, 0];

const R3_HOME: Pose = [0, -0.45, 0.95, 0, -0.5, 0];
const R3_PICK: Pose = [0.5, 0.2, 1.2, 0, -0.5, 0];

export function RobotCellScene() {
  const { playing } = useContext(SceneCtx);
  const cycle = useCycle(STEPS);
  const part = useRef<THREE.Group>(null);
  const fixturePos = useRef(0);

  // 三支手臂各自的姿態：只有輪到自己時才動，其餘時間停在待命點
  const r1Pose = (): Pose => {
    const { i, p } = cycle.current;
    if (i === 0) return lerpPose(R1_HOME, R1_PICK, ease(p));
    if (i === 1) return p < 0.55 ? R1_PICK : lerpPose(R1_PICK, R1_PICK_CLOSED, ease((p - 0.55) / 0.45));
    if (i === 2) return p < 0.75 ? lerpPose(R1_PICK_CLOSED, R1_PLACE, ease(p / 0.75))
      : lerpPose(R1_PLACE, R1_PLACE_OPEN, ease((p - 0.75) / 0.25));
    return lerpPose(R1_PLACE_OPEN, R1_HOME, ease(Math.min(1, cycle.current.p * 2)));
  };

  const r2Pose = (): Pose => {
    const { i, p } = cycle.current;
    if (i !== 4) return R2_HOME;
    // 下壓 → 鎖付（末端軸持續旋轉）→ 退回
    const k = p < 0.3 ? ease(p / 0.3) : p < 0.75 ? 1 : 1 - ease((p - 0.75) / 0.25);
    const pose = lerpPose(R2_HOME, R2_WORK, k);
    if (p >= 0.3 && p < 0.75) pose[3] = (p - 0.3) * 40;    // J4 轉動＝起子在鎖
    return pose;
  };

  const r3Pose = (): Pose => {
    const { i, p } = cycle.current;
    if (i !== 6) return R3_HOME;
    const k = p < 0.45 ? ease(p / 0.45) : p < 0.7 ? 1 : 1 - ease((p - 0.7) / 0.3);
    return lerpPose(R3_HOME, R3_PICK, k);
  };

  // 治具氣缸：只有在 R2 作業時夾緊
  const fixtureCmd = () => (cycle.current.i === 4 ? 1 : 0);
  // 輸送帶只有在輸送步驟才跑
  const beltRun = () => playing && (cycle.current.i === 3 || cycle.current.i === 5);

  useFrame(() => {
    if (!playing || !part.current) return;
    const { i, p } = cycle.current;
    // 工件：料盤 → R1 手上 → 輸送帶 → R2 站 → R3 站 → 消失（下料）
    if (i <= 1) part.current.position.set(-2.4, 0.86, 0.8);
    else if (i === 2) {
      const k = ease(p);
      part.current.position.set(-2.4 + k * 3.0, 0.86 + Math.sin(k * Math.PI) * 0.35, 0.8 - k * 1.4);
    } else if (i === 3) part.current.position.set(0.6 - ease(p) * 0.6, 0.8, -0.6);
    else if (i === 4) part.current.position.set(0, 0.8, -0.6);
    else if (i === 5) part.current.position.set(ease(p) * 0.9, 0.8, -0.6);
    else part.current.position.set(0.9, 0.8 + ease(p) * 0.4, -0.6);
  });

  return (
    <group>
      <Floor size={10} />
      {/* 手臂安裝台座 */}
      {[[-1.6, 0], [0, -1.5], [1.0, 0]].map(([x, z]) => (
        <Static key={`${x}${z}`} position={[x, 0.4, z]} size={[0.5, 0.8, 0.5]} color="#3d4650" />
      ))}
      <RobotArm prefix="r1-" position={[-1.6, 0.8, 0]} rotation={[0, Math.PI / 4, 0]} tool="gripper" pose={r1Pose} />
      <RobotArm prefix="r2-" position={[0, 0.8, -1.5]} rotation={[0, Math.PI / 2, 0]} tool="screwdriver" color="#f2c744" pose={r2Pose} />
      <RobotArm prefix="r3-" position={[1.0, 0.8, 0]} rotation={[0, Math.PI, 0]} tool="vacuum" color="#dfe3e6" pose={r3Pose} />

      {/* 站間輸送帶與治具 */}
      <BeltConveyor position={[0, 0.75, -0.6]} length={2.4} width={0.25}
        names={{ belt: 'belt' }} run={beltRun} showCarrier={false} />
      <Cylinder name="fixture" position={[0, 0.62, -0.6]} stroke={0.03} len={0.06}
        drive={fixtureCmd} travel={0.25} onPos={(v) => (fixturePos.current = v)} />
      <Blinker name="fixture" position={[0.1, 0.68, -0.5]} color="#33cc66" r={0.013}
        on={() => fixturePos.current > 0.96} />

      {/* 工件 */}
      <group ref={part}>
        <Box name="tray" size={[0.12, 0.04, 0.12]} color="#8fd19e" metalness={0.2} roughness={0.6} />
      </group>

      {/* 料盤供料機 */}
      <Static position={[-2.4, 0.4, 0.8]} size={[0.5, 0.8, 0.5]} color="#4a525c" />
      <Box name="tray" size={[0.45, 0.04, 0.45]} position={[-2.4, 0.82, 0.8]} color="#1e5aa8" />

      {/* 固定相機龍門：只有視覺定位那一步會打光 */}
      {[-2.65, -2.15].map((x) => (
        <Static key={x} position={[x, 1.5, 0.8]} size={[0.05, 1.6, 0.05]} color="#7a828c" />
      ))}
      <Static position={[-2.4, 2.32, 0.8]} size={[0.6, 0.05, 0.05]} color="#7a828c" />
      <Box name="cam-fixed" size={[0.08, 0.1, 0.08]} position={[-2.4, 2.25, 0.8]} color="#1b2430" />
      <Cyl name="cam-fixed" r={0.1} h={0.02} position={[-2.4, 2.15, 0.8]} color="#eee" metalness={0} roughness={0.5} />
      <Blinker name="cam-fixed" position={[-2.4, 2.13, 0.8]} color="#ffffff" r={0.03}
        on={() => cycle.current.i === 0} />

      {/* 3D 相機與料箱 */}
      <Static position={[-2.4, 0.3, -0.3]} size={[0.5, 0.6, 0.5]} color="#6b6b6b" />
      <Static position={[-2.4, 1.5, -0.3]} size={[0.05, 1.6, 0.05]} color="#7a828c" />
      <Box name="cam-3d" size={[0.25, 0.08, 0.08]} position={[-2.4, 2.3, -0.3]} color="#1b2430" />
      <Blinker name="cam-3d" position={[-2.3, 2.25, -0.3]} color="#4aa3ff" r={0.02}
        on={() => cycle.current.i === 0} />
      <Box name="calib" size={[0.2, 0.01, 0.15]} position={[-2.6, 0.9, -0.6]} color="#fafafa" metalness={0} roughness={0.9} />

      {/* 氣路 */}
      <Box name="manifold" size={[0.2, 0.08, 0.08]} position={[-1.9, 0.75, -0.4]} color="#1e5aa8" />
      <Box name="frl" size={[0.15, 0.2, 0.08]} position={[2.6, 0.5, 0.9]} color="#d4a017" />

      {/* 安全：圍籬內有手臂在動時掃描器亮綠（區域已清空、允許運轉） */}
      <Blinker name="scanner" position={[1.5, 0.3, 1.3]} color="#33cc66" r={0.03} on={() => true} />
      <Box name="scanner" size={[0.1, 0.1, 0.1]} position={[1.5, 0.25, 1.3]} color="#d4a017" />
      {[-3, -1.5, 0, 1.5, 3].map((x) => (
        <Static key={x} position={[x, 1.0, 1.8]} size={[0.04, 2.0, 0.04]} color="#d4a017" />
      ))}
      <mesh position={[0, 1.0, 1.8]} name="fence">
        <boxGeometry args={[6, 2.0, 0.01]} />
        <meshStandardMaterial color="#ffb100" transparent opacity={0.12} />
      </mesh>
      <Box name="fence" size={[6, 0.04, 0.04]} position={[0, 2.0, 1.8]} color="#d4a017" />

      {/* 電控櫃 */}
      <Cabinet position={[2.8, 0.0, -1.2]} size={[1.2, 1.8, 0.5]} names={{ body: 'ecab', hmi: 'hmi', estop: 'estop' }} />
      <Box name="rc" size={[1.0, 0.3, 0.3]} position={[2.8, 0.4, -0.9]} color="#3b4048" />
      <Box name="ipc" size={[0.4, 0.15, 0.3]} position={[2.8, 1.0, -0.9]} color="#2b3038" />
      <Box name="switch" size={[0.3, 0.06, 0.1]} position={[2.8, 0.85, -0.9]} color="#2a7f8f" />
      <Box name="plc" size={[0.25, 0.1, 0.1]} position={[2.8, 1.3, -0.9]} color="#5a6470" />
      <Box name="safety" size={[0.15, 0.1, 0.1]} position={[2.8, 1.15, -0.9]} color="#d4a017" />
      <Box name="pendant" size={[0.15, 0.22, 0.04]} position={[3.1, 1.2, -0.6]} color="#e8e8e8" metalness={0} roughness={0.6} />
    </group>
  );
}
