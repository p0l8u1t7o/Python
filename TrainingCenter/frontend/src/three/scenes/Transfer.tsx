import { useContext, useRef } from 'react';
import { useFrame } from '@react-three/fiber';
import * as THREE from 'three';
import { BeltConveyor, Blinker, Box, Cabinet, Cyl, Cylinder, Floor, RollerConveyor, SceneCtx, Static } from '../Parts';

export function TransferScene() {
  const { playing } = useContext(SceneCtx);
  const lift = useRef<THREE.Group>(null);
  const carrier = useRef<THREE.Group>(null);
  useFrame(({ clock }) => {
    if (!playing) return;
    const t = (clock.getElapsedTime() % 8) / 8; // 0..1
    // 載具：主線前進 → 擋停 → 頂升 → 橫向送出
    if (carrier.current) {
      if (t < 0.4) carrier.current.position.set(-2.2 + (t / 0.4) * 2.2, 0.82, 0);
      else if (t < 0.5) carrier.current.position.set(0, 0.82 + ((t - 0.4) / 0.1) * 0.06, 0);
      else if (t < 0.9) carrier.current.position.set(0, 0.88, -((t - 0.5) / 0.4) * 2.0);
      else carrier.current.position.set(-2.2, 0.82, 0);
    }
    if (lift.current) lift.current.position.y = t > 0.4 && t < 0.92 ? 0.06 : 0;
  });
  return (
    <group>
      <Floor size={10} />
      {/* 主線：滾筒段 + 皮帶段 */}
      <RollerConveyor position={[-1.5, 0.75, 0]} length={2.2} width={0.4} name="rollers" />
      <BeltConveyor position={[1.6, 0.75, 0]} length={1.4} width={0.4} names={{ belt: 'belt', motor: 'beltmotor' }} carrierColor="#8fd19e" />
      <Box name="guide" size={[2.2, 0.06, 0.02]} position={[-1.5, 0.85, 0.24]} color="#e8e8e8" metalness={0} roughness={0.8} />
      <Box name="guide" size={[2.2, 0.06, 0.02]} position={[-1.5, 0.85, -0.24]} color="#e8e8e8" metalness={0} roughness={0.8} />
      {/* 移載機 */}
      <Static position={[0, 0.35, 0]} size={[0.5, 0.7, 0.5]} color="#3d4650" />
      <Cylinder name="liftcyl" position={[0, 0.5, 0]} stroke={0.06} len={0.15} r={0.04} />
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
      <Cylinder name="stopper" position={[-0.55, 0.65, 0]} stroke={0.04} len={0.06} phase={2} />
      <Box name="cylsensor" size={[0.02, 0.03, 0.01]} position={[0, 0.6, 0.06]} color="#1b2430" />
      <Box name="speedctl" size={[0.02, 0.03, 0.02]} position={[0.1, 0.5, 0.2]} color="#1e5aa8" />
      {/* 支線與 AGV 對接 */}
      <RollerConveyor position={[0, 0.75, -1.4]} length={1.8} width={0.4} name="branch" rotationY={Math.PI / 2} />
      <Box name="agvdock" size={[0.1, 0.1, 0.05]} position={[0.25, 0.9, -2.1]} color="#1b2430" />
      <Blinker name="agvdock" position={[0.25, 0.9, -2.14]} color="#ff3030" r={0.015} />
      <Static position={[0, 0.2, -2.9]} size={[0.9, 0.4, 0.9]} color="#e07b00" />
      <Static position={[0, 0.45, -2.9]} size={[0.6, 0.1, 0.6]} color="#3d4650" />
      {/* 載具（動畫） */}
      <group ref={carrier}>
        <Box name="carrier" size={[0.3, 0.03, 0.3]} color="#d4a017" metalness={0.2} roughness={0.6} />
        <Static position={[0, 0.03, 0]} size={[0.2, 0.03, 0.2]} color="#8fd19e" />
      </group>
      {/* 感測 */}
      <Blinker name="rfid" position={[-0.8, 0.8, 0.3]} color="#4aa3ff" r={0.02} />
      <Box name="rfid" size={[0.05, 0.05, 0.02]} position={[-0.8, 0.8, 0.32]} color="#1b2430" />
      <Blinker name="psensor" position={[-0.4, 0.85, 0.3]} r={0.015} />
      <Blinker name="pswitch" position={[-2.4, 0.5, 0.4]} color="#33cc66" r={0.015} />
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
