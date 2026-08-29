import { Blinker, Box, Cabinet, Cyl, Fan, Floor, Pipe, Static } from '../Parts';

export function FuelCellScene() {
  return (
    <group>
      <Floor />
      {/* 平台底座 */}
      <Static position={[0, 0.05, -0.3]} size={[6, 0.1, 3]} color="#3d4650" />
      {/* 氫氣儲槽 */}
      <Cyl name="h2tank" r={0.25} h={1.1} position={[-1.6, 0.55, 0]} rotation={[0, 0, Math.PI / 2]} color="#c8102e" metalness={0.5} roughness={0.3} />
      <Static position={[-1.6, 0.2, 0]} size={[0.8, 0.2, 0.3]} />
      {/* 氫氣管路與閥件 */}
      <Pipe from={[-1.05, 0.55, 0]} to={[-1.05, 0.7, 0]} />
      <Pipe from={[-1.4, 0.7, 0]} to={[-0.4, 0.7, 0]} />
      <Box name="h2filter" size={[0.08, 0.14, 0.08]} position={[-1.3, 0.7, 0]} color="#8f97a0" />
      <Box name="h2reg" size={[0.1, 0.12, 0.1]} position={[-1.05, 0.7, 0]} color="#d4a017" />
      <Box name="ptx" size={[0.04, 0.1, 0.04]} position={[-0.85, 0.85, 0]} color="#1b2430" />
      <Box name="h2sol" size={[0.08, 0.1, 0.06]} position={[-0.7, 0.7, 0]} color="#1e5aa8" />
      {/* 電堆 */}
      <Box name="stack" size={[0.8, 0.6, 0.5]} position={[0, 0.6, 0]} color="#b9c0c7" metalness={0.7} roughness={0.25} />
      {Array.from({ length: 9 }).map((_, i) => (
        <Static key={i} position={[-0.36 + i * 0.09, 0.6, 0.255]} size={[0.02, 0.56, 0.01]} color="#3b4048" />
      ))}
      <Box name="cvm" size={[0.05, 0.3, 0.2]} position={[0.45, 0.6, 0.1]} color="#2a7f8f" />
      <Box name="purge" size={[0.06, 0.08, 0.06]} position={[0.5, 0.35, 0.3]} color="#1e5aa8" />
      <Box name="rtd" size={[0.03, 0.08, 0.03]} position={[0.3, 0.55, -0.5]} color="#1b2430" />
      {/* 空氣供應 */}
      <Fan name="blower" position={[1.1, 0.35, 0.45]} r={0.15} />
      <Box name="airfilter" size={[0.12, 0.3, 0.3]} position={[1.45, 0.35, 0.45]} color="#e0e4e8" roughness={0.9} metalness={0} />
      <Cyl name="humidifier" r={0.08} h={0.35} position={[0.7, 0.5, 0.45]} rotation={[0, 0, Math.PI / 2]} color="#d8dce0" />
      <Pipe from={[0.95, 0.35, 0.45]} to={[0.88, 0.5, 0.45]} r={0.03} />
      <Pipe from={[0.52, 0.5, 0.45]} to={[0.4, 0.5, 0.25]} r={0.03} />
      {/* 水熱管理 */}
      <Cyl name="pump" r={0.08} h={0.15} position={[-0.5, 0.2, -0.7]} color="#3b4048" />
      <Cyl name="difilter" r={0.06} h={0.25} position={[-0.9, 0.3, -0.7]} color="#1e5aa8" />
      <Box name="radiator" size={[1.2, 0.8, 0.08]} position={[0, 0.7, -1.3]} color="#1b1f24" roughness={0.8} metalness={0.4} />
      <Fan name="radiator" position={[-0.28, 0.7, -1.2]} r={0.22} />
      <Fan name="radiator" position={[0.28, 0.7, -1.2]} r={0.22} />
      <Pipe from={[-0.3, 0.4, -0.25]} to={[-0.5, 0.3, -0.7]} r={0.025} color="#4aa3ff" />
      <Pipe from={[-0.5, 0.28, -0.7]} to={[-0.4, 0.5, -1.25]} r={0.025} color="#4aa3ff" />
      <Pipe from={[0.4, 0.5, -1.25]} to={[0.3, 0.55, -0.5]} r={0.025} color="#ff6b6b" />
      {/* 電力櫃 */}
      <Cabinet position={[1.9, 0.1, -0.8]} size={[0.7, 1.4, 0.5]} names={{ body: 'powercab' }} />
      <Box name="dcdc" size={[0.5, 0.35, 0.3]} position={[1.9, 1.0, -0.45]} color="#3b4048" />
      <Box name="inverter" size={[0.5, 0.35, 0.3]} position={[1.9, 0.45, -0.45]} color="#2a4a6a" />
      <Box name="contactor" size={[0.1, 0.12, 0.1]} position={[1.5, 0.9, -0.5]} color="#1b2430" />
      <Box name="battery" size={[0.5, 0.3, 0.4]} position={[2.5, 0.3, -0.8]} color="#2d5f2d" />
      {/* 控制櫃 */}
      <Cabinet position={[-2.2, 0.1, -0.8]} names={{ body: 'cabinet', hmi: 'hmi', estop: 'estop' }} />
      <Box name="plc" size={[0.25, 0.12, 0.1]} position={[-2.2, 1.1, -0.5]} color="#5a6470" />
      <Box name="safetyplc" size={[0.12, 0.12, 0.1]} position={[-1.95, 1.1, -0.5]} color="#d4a017" />
      <Box name="gateway" size={[0.1, 0.1, 0.1]} position={[-2.5, 0.9, -0.5]} color="#2a7f8f" />
      {/* 頂棚與氫氣偵測器 */}
      <Static position={[-0.5, 2.2, -0.3]} size={[4, 0.05, 2.5]} color="#4a525c" />
      {[-2.3, 1.3].map((x) => (
        <Static key={x} position={[x, 1.1, -1.5]} size={[0.06, 2.2, 0.06]} color="#7a828c" />
      ))}
      <Blinker name="h2det" position={[-0.5, 2.05, 0]} color="#ff3030" r={0.05} />
      <Box name="h2det" size={[0.15, 0.1, 0.1]} position={[-0.5, 2.1, 0]} color="#d0d4d8" />
    </group>
  );
}
