import { useContext, useRef } from 'react';
import { useFrame } from '@react-three/fiber';
import * as THREE from 'three';
import {
  BeltConveyor, Blinker, Box, Cabinet, Cyl, Cylinder, Floor, RollerConveyor, SceneCtx, Static,
  cushion, ease, useCycle, type CycleStep,
} from '../Parts';

/**
 * 一個完整的移載循環，順序完全照教材 MEC-21 / CNV-10 / CNV-11：
 *   進料 → 擋停 → 頂升定位 → 作業 → 降下 → 放行 → 橫移送出
 * 感測器（到位、磁簧）依**實際**機構位置亮滅，不是照時間表亮，
 * 這樣才看得出「程式要等到位訊號才往下走」這件事。
 */
const STEPS: CycleStep[] = [
  { name: '進料：載具沿主線前進', dur: 3.0 },
  { name: '擋停：擋停氣缸伸出', dur: 1.2 },
  { name: '頂升定位：頂升氣缸伸出、定位銷插入', dur: 1.4 },
  { name: '作業中', dur: 2.0 },
  { name: '降下：頂升氣缸縮回', dur: 1.2 },
  { name: '放行：擋停氣缸縮回', dur: 1.0 },
  { name: '橫移：移載機送往支線', dur: 2.6 },
];

export function TransferScene() {
  const { playing } = useContext(SceneCtx);
  const cycle = useCycle(STEPS);

  const lift = useRef<THREE.Group>(null);
  const carrier = useRef<THREE.Group>(null);

  // 氣缸的實際位置（0 縮回、1 伸出）—— 由 Cylinder 每幀回報，用來決定磁簧訊號
  const stopperPos = useRef(0);
  const liftPos = useRef(0);

  // 命令值：這一步該伸還是該縮
  const stopperCmd = () => (cycle.current.i >= 1 && cycle.current.i <= 4 ? 1 : 0);
  const liftCmd = () => (cycle.current.i >= 2 && cycle.current.i <= 3 ? 1 : 0);

  // 訊號：磁簧開關只有真的到位才 ON
  const stopperOn = () => stopperPos.current > 0.96;
  const liftOn = () => liftPos.current > 0.96;
  // 主線只有在進料那一步才跑；載具被擋停之後滾筒就停下來（累積式輸送）
  const lineRun = () => playing && cycle.current.i === 0;

  useFrame(() => {
    if (!playing) return;
    const { i, p } = cycle.current;
    const c = carrier.current;
    if (!c) return;

    // 位置：X 沿主線、Y 隨頂升、Z 橫移到支線
    let x = 0;
    let z = 0;
    if (i === 0) x = -2.2 + ease(p) * 2.2;      // 進料：S 形加減速
    else if (i === 6) z = -ease(p) * 2.0;        // 橫移送出
    // 載具跟著頂升平台走，所以 Y 用頂升氣缸的實際位置
    c.position.set(x, 0.82 + liftPos.current * 0.06, z);

    // 移載平台本身：由頂升氣缸的實際位置驅動，含末端緩衝
    if (lift.current) lift.current.position.y = cushion(liftPos.current) * 0.06;
  });

  return (
    <group>
      <Floor size={10} />
      {/* 主線：滾筒段 + 皮帶段。停線時滾筒與皮帶一起停 */}
      <RollerConveyor position={[-1.5, 0.75, 0]} length={2.2} width={0.4} name="rollers" run={lineRun} />
      <BeltConveyor
        position={[1.6, 0.75, 0]} length={1.4} width={0.4}
        names={{ belt: 'belt', motor: 'beltmotor' }} carrierColor="#8fd19e"
        run={lineRun} showCarrier={false}
      />
      <Box name="guide" size={[2.2, 0.06, 0.02]} position={[-1.5, 0.85, 0.24]} color="#e8e8e8" metalness={0} roughness={0.8} />
      <Box name="guide" size={[2.2, 0.06, 0.02]} position={[-1.5, 0.85, -0.24]} color="#e8e8e8" metalness={0} roughness={0.8} />

      {/* 移載機 */}
      <Static position={[0, 0.35, 0]} size={[0.5, 0.7, 0.5]} color="#3d4650" />
      <Cylinder
        name="liftcyl" position={[0, 0.5, 0]} stroke={0.06} len={0.15} r={0.04}
        drive={liftCmd} travel={0.5} onPos={(v) => (liftPos.current = v)}
      />
      {[[-0.2, 0.2], [0.2, 0.2], [-0.2, -0.2], [0.2, -0.2]].map(([x, z]) => (
        <Cyl key={`${x}${z}`} name="shaft" r={0.012} h={0.3} position={[x, 0.6, z]} color="#d0d4d8" metalness={0.9} roughness={0.2} />
      ))}
      <Cyl name="shock" r={0.015} h={0.08} position={[0.25, 0.55, -0.25]} color="#d4a017" />
      <group ref={lift}>
        {[-0.15, -0.05, 0.05, 0.15].map((x) => (
          <Box key={x} name="crossbelt" size={[0.02, 0.02, 0.5]} position={[x, 0.78, 0]} color="#2f6b3a" metalness={0.1} roughness={0.9} />
        ))}
        <Cyl name="crossmotor" r={0.035} h={0.1} position={[0.35, 0.6, 0]} rotation={[Math.PI / 2, 0, 0]} color="#3b4048" />
      </group>

      {/* 擋停氣缸：伸出時擋住載具 */}
      <Cylinder
        name="stopper" position={[-0.55, 0.65, 0]} stroke={0.04} len={0.06}
        drive={stopperCmd} travel={0.3} onPos={(v) => (stopperPos.current = v)}
      />
      {/* 磁簧開關：擋停到位才亮 */}
      <Blinker name="cylsensor" position={[-0.55, 0.72, 0.05]} color="#33cc66" r={0.014} on={stopperOn} />
      <Box name="cylsensor" size={[0.02, 0.03, 0.01]} position={[0, 0.6, 0.06]} color="#1b2430" />
      <Box name="speedctl" size={[0.02, 0.03, 0.02]} position={[0.1, 0.5, 0.2]} color="#1e5aa8" />

      {/* 支線與 AGV 對接 */}
      <RollerConveyor position={[0, 0.75, -1.4]} length={1.8} width={0.4} name="branch" rotationY={Math.PI / 2}
        run={() => playing && cycle.current.i === 6} />
      <Box name="agvdock" size={[0.1, 0.1, 0.05]} position={[0.25, 0.9, -2.1]} color="#1b2430" />
      <Blinker name="agvdock" position={[0.25, 0.9, -2.14]} color="#ff3030" r={0.015} on={() => cycle.current.i === 6} />
      <Static position={[0, 0.2, -2.9]} size={[0.9, 0.4, 0.9]} color="#e07b00" />
      <Static position={[0, 0.45, -2.9]} size={[0.6, 0.1, 0.6]} color="#3d4650" />

      {/* 載具 */}
      <group ref={carrier}>
        <Box name="carrier" size={[0.3, 0.03, 0.3]} color="#d4a017" metalness={0.2} roughness={0.6} />
        <Static position={[0, 0.03, 0]} size={[0.2, 0.03, 0.2]} color="#8fd19e" />
      </group>

      {/* 感測：RFID 在進料時讀取、到位光電在載具停妥時 ON、頂升到位訊號 */}
      <Blinker name="rfid" position={[-0.8, 0.8, 0.3]} color="#4aa3ff" r={0.02}
        on={() => cycle.current.i === 0 && cycle.current.p > 0.55} />
      <Box name="rfid" size={[0.05, 0.05, 0.02]} position={[-0.8, 0.8, 0.32]} color="#1b2430" />
      <Blinker name="psensor" position={[-0.4, 0.85, 0.3]} r={0.015}
        on={() => cycle.current.i >= 1 && cycle.current.i <= 5} />
      <Blinker name="liftcyl" position={[0.12, 0.62, 0.05]} color="#33cc66" r={0.014} on={liftOn} />
      <Blinker name="pswitch" position={[-2.4, 0.5, 0.4]} color="#33cc66" r={0.015} on={() => true} />

      {/* 氣路 */}
      <Box name="frl" size={[0.15, 0.2, 0.08]} position={[-2.6, 0.45, 0.4]} color="#d4a017" />
      <Box name="manifold" size={[0.3, 0.1, 0.1]} position={[0.7, 0.45, 0.45]} color="#1e5aa8" />
      <Box name="rio" size={[0.2, 0.08, 0.06]} position={[0.7, 0.6, 0.45]} color="#5a6470" />
      <Box name="rdctrl" size={[0.12, 0.05, 0.03]} position={[-1.5, 0.6, 0.35]} color="#2a7f8f" />
      <Cyl name="tube" r={0.005} h={0.6} position={[0.4, 0.5, 0.3]} rotation={[0, 0, Math.PI / 2]} color="#4aa3ff" />

      {/* 電控箱 */}
      <Cabinet position={[2.9, 0.0, -0.6]} size={[0.6, 1.5, 0.4]} names={{ body: 'ecab', hmi: 'hmi', estop: 'estop' }} />
      <Box name="plc" size={[0.2, 0.1, 0.1]} position={[2.9, 1.0, -0.35]} color="#5a6470" />
      <Box name="safety" size={[0.08, 0.1, 0.08]} position={[2.9, 0.8, -0.35]} color="#d4a017" />
      <Box name="vfd" size={[0.12, 0.15, 0.1]} position={[2.9, 0.6, -0.35]} color="#3b4048" />
    </group>
  );
}
