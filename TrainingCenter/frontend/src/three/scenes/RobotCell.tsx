import { BeltConveyor, Blinker, Box, Cabinet, Cyl, Cylinder, Floor, RobotArm, Static } from '../Parts';

export function RobotCellScene() {
  return (
    <group>
      <Floor size={10} />
      {/* 手臂安裝台座 */}
      {[[-1.6, 0], [0, -1.5], [1.0, 0]].map(([x, z]) => (
        <Static key={`${x}${z}`} position={[x, 0.4, z]} size={[0.5, 0.8, 0.5]} color="#3d4650" />
      ))}
      <RobotArm prefix="r1-" position={[-1.6, 0.8, 0]} rotation={[0, Math.PI / 4, 0]} phase={0} tool="gripper" />
      <RobotArm prefix="r2-" position={[0, 0.8, -1.5]} rotation={[0, Math.PI / 2, 0]} phase={2} tool="screwdriver" color="#f2c744" />
      <RobotArm prefix="r3-" position={[1.0, 0.8, 0]} rotation={[0, Math.PI, 0]} phase={4} tool="vacuum" color="#dfe3e6" />
      {/* 站間輸送帶與治具 */}
      <BeltConveyor position={[0, 0.75, -0.6]} length={2.4} width={0.25} names={{ belt: 'belt' }} />
      <Cylinder name="fixture" position={[0, 0.62, -0.6]} stroke={0.03} len={0.06} />
      {/* 料盤供料機 */}
      <Static position={[-2.4, 0.4, 0.8]} size={[0.5, 0.8, 0.5]} color="#4a525c" />
      <Box name="tray" size={[0.45, 0.04, 0.45]} position={[-2.4, 0.82, 0.8]} color="#1e5aa8" />
      {/* 固定相機龍門 */}
      {[-2.65, -2.15].map((x) => (
        <Static key={x} position={[x, 1.5, 0.8]} size={[0.05, 1.6, 0.05]} color="#7a828c" />
      ))}
      <Static position={[-2.4, 2.32, 0.8]} size={[0.6, 0.05, 0.05]} color="#7a828c" />
      <Box name="cam-fixed" size={[0.08, 0.1, 0.08]} position={[-2.4, 2.25, 0.8]} color="#1b2430" />
      <Cyl name="cam-fixed" r={0.1} h={0.02} position={[-2.4, 2.15, 0.8]} color="#eee" metalness={0} roughness={0.5} />
      <Blinker name="cam-fixed" position={[-2.4, 2.13, 0.8]} color="#ffffff" r={0.03} />
      {/* 3D 相機與料箱 */}
      <Static position={[-2.4, 0.3, -0.3]} size={[0.5, 0.6, 0.5]} color="#6b6b6b" />
      <Static position={[-2.4, 1.5, -0.3]} size={[0.05, 1.6, 0.05]} color="#7a828c" />
      <Box name="cam-3d" size={[0.25, 0.08, 0.08]} position={[-2.4, 2.3, -0.3]} color="#1b2430" />
      <Blinker name="cam-3d" position={[-2.3, 2.25, -0.3]} color="#4aa3ff" r={0.02} />
      <Box name="calib" size={[0.2, 0.01, 0.15]} position={[-2.6, 0.9, -0.6]} color="#fafafa" metalness={0} roughness={0.9} />
      {/* 氣路 */}
      <Box name="manifold" size={[0.2, 0.08, 0.08]} position={[-1.9, 0.75, -0.4]} color="#1e5aa8" />
      <Box name="frl" size={[0.15, 0.2, 0.08]} position={[2.6, 0.5, 0.9]} color="#d4a017" />
      {/* 安全 */}
      <Blinker name="scanner" position={[1.5, 0.3, 1.3]} color="#ff3030" r={0.03} />
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
