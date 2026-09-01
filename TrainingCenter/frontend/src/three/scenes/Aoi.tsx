import { useContext, useRef } from 'react';
import { useFrame } from '@react-three/fiber';
import * as THREE from 'three';
import {
  BeltConveyor, Blinker, Box, Cabinet, Cyl, Cylinder, Floor, SceneCtx, Static,
  ease, useCycle, type CycleStep,
} from '../Parts';

/**
 * AOI 一個檢測循環：
 *   進料 → 擋停頂升 → XY 掃描取像（每個檢測點頻閃一次）→ 判定 → OK 放行 / NG 剔除
 * 相機在**停下來的瞬間**才頻閃，對應教材 AOI-06「高速下要用硬體觸發」。
 */
const STEPS: CycleStep[] = [
  { name: '進料：工件進入檢測區', dur: 2.4 },
  { name: '擋停 + 頂升定位', dur: 1.3 },
  { name: '掃描取像：XY 平台逐點定位、頻閃取像', dur: 5.0 },
  { name: '判定：影像處理與 OK / NG 判斷', dur: 1.0 },
  { name: 'NG 剔除：推料氣缸將不良品排出', dur: 1.6 },
  { name: '降下並放行', dur: 1.4 },
];

/** 掃描路徑：蛇行走 6 個檢測點（X、Z 為龍門座標）。 */
const POINTS: [number, number][] = [
  [-0.35, -0.25], [0, -0.25], [0.35, -0.25],
  [0.35, 0.25], [0, 0.25], [-0.35, 0.25],
];

export function AoiScene() {
  const { playing } = useContext(SceneCtx);
  const cycle = useCycle(STEPS);
  const xCarriage = useRef<THREE.Group>(null);
  const yBeam = useRef<THREE.Group>(null);
  const flash = useRef<THREE.MeshStandardMaterial>(null);
  const workpiece = useRef<THREE.Group>(null);
  const liftPos = useRef(0);
  const stopperPos = useRef(0);

  const stopperCmd = () => (cycle.current.i >= 1 && cycle.current.i <= 4 ? 1 : 0);
  const liftCmd = () => (cycle.current.i >= 1 && cycle.current.i <= 4 ? 1 : 0);
  // 這一輪是不是 NG？用循環次數做出「大部分 OK、偶爾 NG」的節奏
  const rejectCmd = () => (cycle.current.i === 4 ? 1 : 0);

  useFrame(() => {
    if (!playing) return;
    const { i, p } = cycle.current;

    // --- 龍門：掃描階段逐點定位，其餘時間回到待命點
    let gx = 0;
    let gz = 0;
    let strobe = 0;
    if (i === 2) {
      // 每個點：前 60% 移動（S 形加減速）、後 40% 靜止取像
      const per = 1 / POINTS.length;
      const idx = Math.min(POINTS.length - 1, Math.floor(p / per));
      const local = (p - idx * per) / per;
      const from = idx === 0 ? [0, 0] : POINTS[idx - 1];
      const to = POINTS[idx];
      const k = ease(Math.min(1, local / 0.6));
      gx = from[0] + (to[0] - from[0]) * k;
      gz = from[1] + (to[1] - from[1]) * k;
      // 停穩之後才頻閃：閃一下就過
      if (local > 0.62 && local < 0.78) strobe = 1 - Math.abs(local - 0.7) / 0.08;
    } else {
      gx = 0;
      gz = 0;
    }
    if (xCarriage.current) xCarriage.current.position.x = gx;
    if (yBeam.current) yBeam.current.position.z = gz;
    if (flash.current) flash.current.emissiveIntensity = 0.25 + strobe * 4;

    // --- 工件：進料 → 停在檢測位 → 放行（NG 時往後方排出）
    const w = workpiece.current;
    if (w) {
      if (i === 0) w.position.set(-1.4 + ease(p) * 1.4, 0.79 + liftPos.current * 0.04, 0);
      else if (i === 4) w.position.set(1.0 * ease(p), 0.79 + liftPos.current * 0.04, -ease(p) * 0.5);
      else if (i === 5) w.position.set(ease(p) * 1.5, 0.79 + liftPos.current * 0.04, 0);
      else w.position.set(0, 0.79 + liftPos.current * 0.04, 0);
    }
  });

  const lineRun = () => playing && (cycle.current.i === 0 || cycle.current.i === 5);

  return (
    <group>
      <Floor />
      {/* 機台底座與立柱 */}
      <Static position={[0, 0.25, 0]} size={[3.2, 0.5, 1.6]} color="#3d4650" />
      {[[-1.4, -0.6], [1.4, -0.6], [-1.4, 0.6], [1.4, 0.6]].map(([x, z]) => (
        <Static key={`${x}${z}`} position={[x, 1.1, z]} size={[0.08, 1.2, 0.08]} color="#7a828c" />
      ))}
      <Static position={[0, 1.72, 0]} size={[3.0, 0.05, 1.4]} color="#4a525c" />

      {/* 輸送與定位 */}
      <BeltConveyor position={[0, 0.75, 0]} length={3} width={0.3}
        names={{ belt: 'belt', motor: 'beltmotor' }} run={lineRun} showCarrier={false} />
      <Cyl name="encoder" r={0.03} h={0.05} position={[-1.2, 0.6, 0.3]} rotation={[0, 0, Math.PI / 2]} color="#1b2430" />
      <Cylinder name="stopper" position={[0.2, 0.62, 0]} stroke={0.05} len={0.08}
        drive={stopperCmd} travel={0.3} onPos={(v) => (stopperPos.current = v)} />
      <Cylinder name="lift" position={[-0.2, 0.6, 0.1]} stroke={0.04} len={0.08} r={0.03}
        drive={liftCmd} travel={0.45} onPos={(v) => (liftPos.current = v)} />
      <Cylinder name="lift" position={[-0.2, 0.6, -0.1]} stroke={0.04} len={0.08} r={0.03}
        drive={liftCmd} travel={0.45} />
      <Cylinder name="reject" position={[1.0, 0.85, -0.35]} rotation={[-Math.PI / 2, 0, 0]}
        stroke={0.1} len={0.14} r={0.025} drive={rejectCmd} travel={0.25} />
      <Blinker name="psensor" position={[0.35, 0.8, 0.2]} r={0.02}
        on={() => cycle.current.i >= 1 && cycle.current.i <= 4} />
      <Blinker name="stopper" position={[0.2, 0.72, 0.07]} color="#33cc66" r={0.013}
        on={() => stopperPos.current > 0.96} />

      {/* 工件 */}
      <group ref={workpiece}>
        <Box name="belt" size={[0.22, 0.02, 0.22]} color="#8fd19e" metalness={0.2} roughness={0.6} />
      </group>

      {/* 龍門 */}
      {[-0.45, 0.45].map((z) => (
        <Box key={z} name="yaxis" size={[1.6, 0.08, 0.08]} position={[0, 1.3, z]} color="#5a6470" />
      ))}
      <group ref={yBeam}>
        <Box name="xaxis" size={[1.4, 0.1, 0.1]} position={[0, 1.35, 0]} color="#8f97a0" />
        <Cyl name="servo" r={0.04} h={0.12} position={[0.76, 1.35, 0]} rotation={[0, 0, Math.PI / 2]} color="#3b4048" />
        <Box name="chain" size={[1.2, 0.03, 0.05]} position={[0, 1.42, 0.12]} color="#222" />
        <group ref={xCarriage}>
          <Box name="zaxis" size={[0.12, 0.3, 0.1]} position={[0, 1.2, 0]} color="#5a6470" />
          <Box name="camera" size={[0.06, 0.08, 0.06]} position={[0, 1.1, 0]} color="#1b2430" />
          <Cyl name="lens" r={0.02} h={0.06} position={[0, 1.02, 0]} color="#111" />
          <mesh position={[0, 0.97, 0]} name="ring">
            <torusGeometry args={[0.07, 0.015, 12, 32]} />
            <meshStandardMaterial ref={flash} color="#fff" emissive="#ffffff" emissiveIntensity={0.3} />
          </mesh>
          <Cyl name="ring" r={0.09} h={0.01} position={[0, 0.975, 0]} color="#444" />
        </group>
      </group>

      {/* 光柵、警示燈、螢幕 */}
      {[-1.3, 1.3].map((x) => (
        <Box key={x} name="curtain" size={[0.03, 0.6, 0.03]} position={[x, 1.0, 0.75]} color="#d4a017" />
      ))}
      <Blinker name="curtain" position={[0, 1.0, 0.75]} color="#33cc66" r={0.015} on={() => true} />
      {/* 三色燈：NG 剔除時轉紅，其餘時間綠燈運轉 */}
      <Cyl name="tower" r={0.03} h={0.25} position={[1.3, 1.9, -0.5]} color="#33cc66" />
      <Blinker name="tower" position={[1.3, 2.05, -0.5]} color="#33cc66" r={0.035}
        on={() => cycle.current.i !== 4} />
      <Blinker name="tower" position={[1.3, 2.12, -0.5]} color="#ff3030" r={0.035}
        on={() => cycle.current.i === 4} />
      <Box name="screen" size={[0.35, 0.25, 0.03]} position={[1.5, 1.3, 0.6]} color="#1b2430" />

      {/* 電控箱 / IPC / 氣路 */}
      <Cabinet position={[-1.2, 0.0, -0.9]} size={[0.6, 1.2, 0.35]} names={{ body: 'ecab', estop: 'estop' }} />
      <Box name="plc" size={[0.2, 0.1, 0.1]} position={[-1.2, 0.8, -0.65]} color="#5a6470" />
      <Box name="drive" size={[0.1, 0.15, 0.1]} position={[-1.2, 0.65, -0.65]} color="#3b4048" />
      <Box name="lightctrl" size={[0.12, 0.06, 0.1]} position={[-1.2, 0.5, -0.65]} color="#2a7f8f" />
      <Box name="psu" size={[0.15, 0.08, 0.1]} position={[-1.2, 0.35, -0.65]} color="#8f97a0" />
      <Box name="ipc" size={[0.35, 0.15, 0.3]} position={[-1.6, 0.9, -0.6]} color="#2b3038" />
      <Box name="manifold" size={[0.25, 0.08, 0.1]} position={[1.0, 0.4, 0.5]} color="#1e5aa8" />
      <Box name="frl" size={[0.15, 0.2, 0.08]} position={[-1.4, 0.4, 0.5]} color="#d4a017" />
    </group>
  );
}
