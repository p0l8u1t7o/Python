import { useContext, useRef } from 'react';
import { useFrame } from '@react-three/fiber';
import * as THREE from 'three';
import { BeltConveyor, Blinker, Box, Cabinet, Cyl, Cylinder, Floor, SceneCtx, Static } from '../Parts';

export function AoiScene() {
  const { playing } = useContext(SceneCtx);
  const xCarriage = useRef<THREE.Group>(null);
  const yBeam = useRef<THREE.Group>(null);
  const flash = useRef<THREE.MeshStandardMaterial>(null);
  useFrame(({ clock }) => {
    if (!playing) return;
    const t = clock.getElapsedTime();
    if (xCarriage.current) xCarriage.current.position.x = Math.sin(t * 0.7) * 0.35;
    if (yBeam.current) yBeam.current.position.z = Math.cos(t * 0.35) * 0.25;
    if (flash.current) flash.current.emissiveIntensity = Math.pow(Math.max(0, Math.sin(t * 3)), 12) * 3;
  });
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
      <BeltConveyor position={[0, 0.75, 0]} length={3} width={0.3} names={{ belt: 'belt', motor: 'beltmotor' }} />
      <Cyl name="encoder" r={0.03} h={0.05} position={[-1.2, 0.6, 0.3]} rotation={[0, 0, Math.PI / 2]} color="#1b2430" />
      <Cylinder name="stopper" position={[0.2, 0.62, 0]} stroke={0.05} len={0.08} />
      <Cylinder name="lift" position={[-0.2, 0.6, 0.1]} stroke={0.04} len={0.08} r={0.03} phase={1} />
      <Cylinder name="lift" position={[-0.2, 0.6, -0.1]} stroke={0.04} len={0.08} r={0.03} phase={1} />
      <Cylinder name="reject" position={[1.0, 0.85, -0.35]} rotation={[-Math.PI / 2, 0, 0]} stroke={0.1} len={0.14} r={0.025} phase={2} />
      <Blinker name="psensor" position={[0.35, 0.8, 0.2]} r={0.02} />
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
      <Blinker name="curtain" position={[0, 1.0, 0.75]} color="#ff3030" r={0.015} />
      <Cyl name="tower" r={0.03} h={0.25} position={[1.3, 1.9, -0.5]} color="#33cc66" />
      <Blinker name="tower" position={[1.3, 2.05, -0.5]} color="#33cc66" r={0.035} />
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
