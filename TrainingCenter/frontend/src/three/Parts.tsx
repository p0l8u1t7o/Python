import { createContext, useContext, useRef, type ReactNode } from 'react';
import { useFrame } from '@react-three/fiber';
import * as THREE from 'three';

/** 3D 場景共用狀態：目前選取／滑過的 mesh 名稱與動畫開關。 */
export interface SceneState {
  selected: string | null;
  hovered: string | null;
  playing: boolean;
  onSelect?: (mesh: string) => void;
  onHover?: (mesh: string | null) => void;
  /** 場景回報目前的動作步驟名稱，由 Viewer 顯示在畫面上。 */
  onStep?: (name: string) => void;
}
export const SceneCtx = createContext<SceneState>({ selected: null, hovered: null, playing: true });

// ---------------------------------------------------------------------------
// 機台循環：讓同一個場景裡的模組照同一條時間軸動作，而不是各自跑各自的正弦波
// ---------------------------------------------------------------------------

export interface CycleStep {
  /** 顯示在畫面上的步驟名稱，例如「擋停」 */
  name: string;
  /** 這一步持續幾秒 */
  dur: number;
}

export interface CycleState {
  /** 目前第幾步 */
  i: number;
  /** 這一步內的進度 0..1 */
  p: number;
  name: string;
}

/** S 形加減速：起步與停止都平順，用在載台、輸送這類有慣量的運動。 */
export const ease = (x: number) => (x <= 0 ? 0 : x >= 1 ? 1 : x * x * (3 - 2 * x));

/**
 * 氣缸的行程曲線：快速衝出、末端被緩衝器吸收。
 * 對應教材 MEC-22（油壓緩衝器）與「速度靠出口節流控制」。
 */
export const cushion = (x: number) => {
  if (x <= 0) return 0;
  if (x >= 1) return 1;
  const out = 1 - Math.pow(1 - x, 2.6);           // 前段快
  return out - Math.exp(-6 * x) * Math.sin(12 * x) * 0.06; // 末端輕微沉降
};

/** 把整體進度 t（0..1）換算成某一段區間內的 0..1。 */
export const seg = (t: number, from: number, to: number) =>
  Math.min(1, Math.max(0, (t - from) / (to - from)));

/**
 * 依步驟表推進的循環計時器。回傳 ref（不觸發重繪），場景在自己的 useFrame 裡讀。
 * 步驟名稱改變時透過 SceneCtx.onStep 回報，讓 Viewer 顯示「現在在做什麼」。
 */
export function useCycle(steps: CycleStep[]): React.RefObject<CycleState> {
  const { playing, onStep } = useContext(SceneCtx);
  const state = useRef<CycleState>({ i: 0, p: 0, name: steps[0]?.name ?? '' });
  const clock = useRef(0);
  const total = steps.reduce((s, x) => s + x.dur, 0) || 1;

  useFrame((_, dt) => {
    if (!playing) return;
    clock.current = (clock.current + Math.min(dt, 0.1)) % total;
    let acc = 0;
    for (let i = 0; i < steps.length; i++) {
      if (clock.current < acc + steps[i].dur) {
        state.current.i = i;
        state.current.p = (clock.current - acc) / steps[i].dur;
        if (state.current.name !== steps[i].name) {
          state.current.name = steps[i].name;
          onStep?.(steps[i].name);
        }
        return;
      }
      acc += steps[i].dur;
    }
  });
  return state;
}

interface PartProps {
  name: string;
  position?: [number, number, number];
  rotation?: [number, number, number];
  color?: string;
  metalness?: number;
  roughness?: number;
  children: ReactNode; // geometry
}

/** 可被高亮／點選的零件；children 放 geometry。 */
export function Part({ name, position, rotation, color = '#9aa3ad', metalness = 0.6, roughness = 0.35, children }: PartProps) {
  const ctx = useContext(SceneCtx);
  const active = ctx.selected === name;
  const hover = ctx.hovered === name;
  return (
    <mesh
      name={name}
      position={position}
      rotation={rotation}
      castShadow
      receiveShadow
      onClick={(e) => { e.stopPropagation(); ctx.onSelect?.(name); }}
      onPointerOver={(e) => { e.stopPropagation(); ctx.onHover?.(name); document.body.style.cursor = 'pointer'; }}
      onPointerOut={() => { ctx.onHover?.(null); document.body.style.cursor = 'auto'; }}
    >
      {children}
      <meshStandardMaterial
        color={color}
        metalness={metalness}
        roughness={roughness}
        envMapIntensity={1.2}
        emissive={active ? '#00cccc' : hover ? '#ffb100' : '#000'}
        emissiveIntensity={active ? 0.7 : hover ? 0.5 : 0}
      />
    </mesh>
  );
}

type Vec3 = [number, number, number];
export const Box = (p: Omit<PartProps, 'children'> & { size: Vec3 }) => (
  <Part {...p}><boxGeometry args={p.size} /></Part>
);
export const Cyl = (p: Omit<PartProps, 'children'> & { r: number; h: number; r2?: number }) => (
  <Part {...p}><cylinderGeometry args={[p.r, p.r2 ?? p.r, p.h, 32]} /></Part>
);
export const Sphere = (p: Omit<PartProps, 'children'> & { r: number }) => (
  <Part {...p}><sphereGeometry args={[p.r, 24, 24]} /></Part>
);
/** 圓角方塊（手臂連桿用）。 */
export const Capsule = (p: Omit<PartProps, 'children'> & { r: number; len: number }) => (
  <Part {...p}><capsuleGeometry args={[p.r, p.len, 8, 16]} /></Part>
);

/** 靜態裝飾（不可點選）。 */
export function Static({ position, rotation, color = '#4a525c', size, roughness = 0.7, metalness = 0.3 }: { position?: Vec3; rotation?: Vec3; color?: string; size: Vec3; roughness?: number; metalness?: number }) {
  return (
    <mesh position={position} rotation={rotation} castShadow receiveShadow>
      <boxGeometry args={size} />
      <meshStandardMaterial color={color} roughness={roughness} metalness={metalness} envMapIntensity={0.8} />
    </mesh>
  );
}
export function StaticCyl({ position, rotation, color = '#7a828c', r, h, roughness = 0.4, metalness = 0.7 }: { position?: Vec3; rotation?: Vec3; color?: string; r: number; h: number; roughness?: number; metalness?: number }) {
  return (
    <mesh position={position} rotation={rotation} castShadow receiveShadow>
      <cylinderGeometry args={[r, r, h, 24]} />
      <meshStandardMaterial color={color} roughness={roughness} metalness={metalness} envMapIntensity={0.9} />
    </mesh>
  );
}

/** 鋁擠型機架（四支腳 + 上下橫樑）。 */
export function Frame({ position, size, color = '#8a9096', legR = 0.03 }: { position: Vec3; size: Vec3; color?: string; legR?: number }) {
  const [w, h, d] = size;
  const [x, y, z] = position;
  const legs: Vec3[] = [[-w / 2, 0, -d / 2], [w / 2, 0, -d / 2], [-w / 2, 0, d / 2], [w / 2, 0, d / 2]];
  return (
    <group position={[x, y, z]}>
      {legs.map((p, i) => <Static key={i} position={[p[0], h / 2, p[2]]} size={[legR * 2, h, legR * 2]} color={color} metalness={0.6} roughness={0.4} />)}
      {[-d / 2, d / 2].map((zz) => <Static key={`x${zz}`} position={[0, h - legR, zz]} size={[w, legR * 2, legR * 2]} color={color} metalness={0.6} roughness={0.4} />)}
      {[-w / 2, w / 2].map((xx) => <Static key={`z${xx}`} position={[xx, h - legR, 0]} size={[legR * 2, legR * 2, d]} color={color} metalness={0.6} roughness={0.4} />)}
      {[-d / 2, d / 2].map((zz) => <Static key={`bx${zz}`} position={[0, 0.12, zz]} size={[w, legR * 2, legR * 2]} color={color} metalness={0.6} roughness={0.4} />)}
      {legs.map((p, i) => <StaticCyl key={`f${i}`} position={[p[0], 0.02, p[2]]} r={0.05} h={0.04} color="#222" metalness={0.2} roughness={0.8} />)}
    </group>
  );
}

/** 電控櫃：門面帶把手、HMI、急停、警示燈座等可命名子件。 */
export function Cabinet({ position, size = [0.8, 1.8, 0.5], names }: { position: Vec3; size?: Vec3; names: { body: string; hmi?: string; estop?: string } }) {
  const [w, h, d] = size;
  return (
    <group position={position}>
      <Box name={names.body} size={[w, h, d]} position={[0, h / 2, 0]} color="#c9ced3" metalness={0.4} roughness={0.5} />
      <Static position={[0, h / 2, d / 2 + 0.005]} size={[w * 0.9, h * 0.94, 0.01]} color="#b5bbc1" roughness={0.4} />
      {/* 門把、鉸鏈、底座、通風口 */}
      <Static position={[w * 0.38, h * 0.5, d / 2 + 0.02]} size={[0.02, 0.18, 0.02]} color="#222" roughness={0.5} />
      {[0.2, 0.5, 0.8].map((f) => <Static key={f} position={[-w * 0.46, h * f, d / 2 + 0.005]} size={[0.02, 0.06, 0.02]} color="#555" />)}
      <Static position={[0, 0.05, 0]} size={[w, 0.1, d]} color="#2b3038" roughness={0.8} />
      {[0.15, 0.85].map((f) => <Static key={f} position={[0, h * f, d / 2 + 0.008]} size={[w * 0.5, 0.06, 0.004]} color="#8a9096" roughness={0.6} />)}
      {names.hmi && <Box name={names.hmi} size={[0.3, 0.22, 0.03]} position={[0, h * 0.72, d / 2 + 0.03]} color="#1b2430" metalness={0.1} roughness={0.2} />}
      {names.estop && <Cyl name={names.estop} r={0.03} h={0.04} position={[w * 0.3, h * 0.78, d / 2 + 0.03]} rotation={[Math.PI / 2, 0, 0]} color="#d62020" metalness={0.2} roughness={0.4} />}
      {names.estop && <StaticCyl position={[w * 0.3, h * 0.78, d / 2 + 0.012]} r={0.045} h={0.01} rotation={[Math.PI / 2, 0, 0]} color="#ffd400" metalness={0.1} roughness={0.6} />}
    </group>
  );
}

/**
 * 六軸機械手臂（程序化）。每個關節都有關節殼（Cyl）＋連桿（Capsule）互相重疊，
 * 關節轉動時不會露出空隙。prefix 例如 "r1-"。
 */
export function RobotArm({ position, rotation = [0, 0, 0], prefix, phase = 0, color = '#e8e8e8', tool = 'gripper', pose }: {
  position: Vec3; rotation?: Vec3; prefix: string; phase?: number; color?: string;
  tool?: 'gripper' | 'vacuum' | 'screwdriver';
  /** 由場景驅動的關節角度 [J1, J2, J3, J4, J5, 夾爪開度 0..1] */
  pose?: () => [number, number, number, number, number, number];
}) {
  const { playing } = useContext(SceneCtx);
  const j1 = useRef<THREE.Group>(null);
  const j2 = useRef<THREE.Group>(null);
  const j3 = useRef<THREE.Group>(null);
  const j4 = useRef<THREE.Group>(null);
  const j5 = useRef<THREE.Group>(null);
  const fingers = useRef<THREE.Group>(null);
  useFrame(({ clock }) => {
    if (!playing) return;
    // 場景給了 pose 就照教好的點位走；否則沿用自由擺動（純展示用）
    const t = clock.getElapsedTime() + phase;
    const p = pose?.() ?? [
      Math.sin(t * 0.6) * 0.8,
      -0.4 + Math.sin(t * 0.8) * 0.35,
      0.9 + Math.cos(t * 0.8) * 0.4,
      Math.sin(t * 0.9) * 0.6,
      -0.5 + Math.sin(t * 1.2) * 0.3,
      Math.max(0, Math.sin(t * 2)),
    ];
    if (j1.current) j1.current.rotation.y = p[0];
    if (j2.current) j2.current.rotation.z = p[1];
    if (j3.current) j3.current.rotation.z = p[2];
    if (j4.current) j4.current.rotation.x = p[3];
    if (j5.current) j5.current.rotation.z = p[4];
    if (fingers.current) fingers.current.scale.x = 1 + p[5] * 0.6;   // 夾爪開合：0 夾緊、1 張開
  });
  const dark = '#3b4048';
  const L2 = 0.55; // 下臂長
  const L3 = 0.5; // 上臂長
  return (
    <group position={position} rotation={rotation}>
      {/* 底座：法蘭盤 + 螺栓 + 圓柱殼 */}
      <Cyl name={`${prefix}base`} r={0.2} h={0.03} position={[0, 0.015, 0]} color={dark} />
      <Cyl name={`${prefix}base`} r={0.16} h={0.12} position={[0, 0.08, 0]} color={dark} />
      {[0, 1, 2, 3].map((i) => (
        <StaticCyl key={i} position={[Math.cos((i / 4) * Math.PI * 2 + 0.4) * 0.185, 0.035, Math.sin((i / 4) * Math.PI * 2 + 0.4) * 0.185]} r={0.012} h={0.012} color="#222" />
      ))}
      <group ref={j1} position={[0, 0.14, 0]}>
        {/* J1 腰部：圓柱殼 + 肩部支架 */}
        <Cyl name={`${prefix}j1`} r={0.13} h={0.22} position={[0, 0.11, 0]} color={color} />
        <Box name={`${prefix}j1`} size={[0.2, 0.16, 0.26]} position={[0, 0.28, 0]} color={color} />
        <group ref={j2} position={[0, 0.3, 0]}>
          {/* J2 關節殼（橫向圓柱，重疊肩部與下臂） */}
          <Cyl name={`${prefix}j2`} r={0.12} h={0.3} rotation={[Math.PI / 2, 0, 0]} color={dark} />
          <Cyl name={`${prefix}j2`} r={0.06} h={0.34} rotation={[Math.PI / 2, 0, 0]} color="#888" metalness={0.9} roughness={0.2} />
          {/* 下臂連桿：由 J2 到 J3 的膠囊體 + 側板 */}
          <Capsule name={`${prefix}j2`} r={0.085} len={L2 - 0.1} position={[0, L2 / 2, 0]} color={color} />
          <Box name={`${prefix}j2`} size={[0.12, L2, 0.2]} position={[0, L2 / 2, 0]} color={color} />
          <group ref={j3} position={[0, L2, 0]}>
            {/* J3 肘關節殼 */}
            <Cyl name={`${prefix}j3`} r={0.105} h={0.26} rotation={[Math.PI / 2, 0, 0]} color={dark} />
            <Cyl name={`${prefix}j3`} r={0.05} h={0.3} rotation={[Math.PI / 2, 0, 0]} color="#888" metalness={0.9} roughness={0.2} />
            {/* 上臂：膠囊體 + 箱體 + 線纜管線包（Dress pack） */}
            <Capsule name={`${prefix}j3`} r={0.075} len={L3 - 0.1} position={[L3 / 2, 0, 0]} rotation={[0, 0, Math.PI / 2]} color={color} />
            <Box name={`${prefix}j3`} size={[L3, 0.14, 0.16]} position={[L3 / 2, 0, 0]} color={color} />
            <Cyl name={`${prefix}j3`} r={0.02} h={L3 * 0.9} position={[L3 / 2, 0.1, 0.06]} rotation={[0, 0, Math.PI / 2]} color="#222" metalness={0.1} roughness={0.9} />
            {/* J4 前臂旋轉 */}
            <group ref={j4} position={[L3, 0, 0]}>
              <Cyl name={`${prefix}wrist`} r={0.075} h={0.16} rotation={[0, 0, Math.PI / 2]} color={dark} />
              <Cyl name={`${prefix}wrist`} r={0.065} h={0.1} position={[0.1, 0, 0]} rotation={[0, 0, Math.PI / 2]} color={color} />
              {/* J5 腕擺動 */}
              <group ref={j5} position={[0.15, 0, 0]}>
                <Cyl name={`${prefix}wrist`} r={0.06} h={0.15} rotation={[Math.PI / 2, 0, 0]} color={dark} />
                <Cyl name={`${prefix}wrist`} r={0.05} h={0.08} position={[0.07, 0, 0]} rotation={[0, 0, Math.PI / 2]} color={color} />
                {/* J6 法蘭 */}
                <Cyl name={`${prefix}flange`} r={0.05} h={0.025} position={[0.12, 0, 0]} rotation={[0, 0, Math.PI / 2]} color="#9a9a9a" metalness={0.9} roughness={0.2} />
                {[0, 1, 2, 3].map((i) => (
                  <StaticCyl key={i} position={[0.134, Math.cos((i / 4) * Math.PI * 2) * 0.035, Math.sin((i / 4) * Math.PI * 2) * 0.035]} r={0.005} h={0.006} rotation={[0, 0, Math.PI / 2]} color="#222" />
                ))}
                {tool === 'gripper' && (
                  <group position={[0.16, 0, 0]}>
                    <Box name={`${prefix}gripper`} size={[0.08, 0.1, 0.1]} color="#2a7f8f" />
                    <group ref={fingers}>
                      <Box name={`${prefix}gripper`} size={[0.1, 0.02, 0.03]} position={[0.08, 0, 0.03]} color="#c0c0c0" metalness={0.9} roughness={0.2} />
                      <Box name={`${prefix}gripper`} size={[0.1, 0.02, 0.03]} position={[0.08, 0, -0.03]} color="#c0c0c0" metalness={0.9} roughness={0.2} />
                    </group>
                  </group>
                )}
                {tool === 'vacuum' && (
                  <group position={[0.16, 0, 0]}>
                    <Box name={`${prefix}gripper`} size={[0.06, 0.12, 0.12]} color="#2a7f8f" />
                    {[[-0.04, 0.04], [0.04, 0.04], [-0.04, -0.04], [0.04, -0.04]].map(([y, z], i) => (
                      <Cyl key={i} name={`${prefix}gripper`} r={0.015} h={0.04} position={[0.05, y, z]} rotation={[0, 0, Math.PI / 2]} color="#222" metalness={0.1} roughness={0.9} />
                    ))}
                  </group>
                )}
                {tool === 'screwdriver' && (
                  <group position={[0.16, 0, 0]}>
                    <Cyl name={`${prefix}tool`} r={0.03} h={0.2} position={[0.06, 0, 0]} rotation={[0, 0, Math.PI / 2]} color="#2a7f8f" />
                    <Cyl name={`${prefix}tool`} r={0.008} h={0.08} position={[0.2, 0, 0]} rotation={[0, 0, Math.PI / 2]} color="#c0c0c0" metalness={0.9} roughness={0.2} />
                    <Box name={`${prefix}cam`} size={[0.05, 0.04, 0.04]} position={[0, 0.07, 0]} color="#1b2430" />
                  </group>
                )}
              </group>
            </group>
          </group>
        </group>
      </group>
    </group>
  );
}

/** 皮帶輸送機，沿 X 軸：頭尾滾輪、皮帶（上下段）、側框、機架與馬達；帶動一個載具往前移動。 */
export function BeltConveyor({ position, length = 1.5, width = 0.3, names, carrierColor = '#ffb100', run, showCarrier = true }: { position: Vec3; length?: number; width?: number; names: { belt: string; motor?: string; carrier?: string }; carrierColor?: string; run?: () => boolean; showCarrier?: boolean }) {
  const { playing } = useContext(SceneCtx);
  const carrier = useRef<THREE.Group>(null);
  const pulleys = useRef<THREE.Group>(null);
  const travelled = useRef(0);
  useFrame((_, dt) => {
    if (!playing) return;
    // 停線時皮帶與滾輪一起停：現場看到的就是「線停了，帶子也不動」
    if (run && !run()) return;
    const d = Math.min(dt, 0.1);
    travelled.current += d * 0.25;
    if (carrier.current) carrier.current.position.x = (travelled.current % length) - length / 2;
    pulleys.current?.children.forEach((c) => (c.rotation.y += d * 5));
  });
  const pr = 0.04;
  return (
    <group position={position}>
      {/* 皮帶上段、下段（回程） */}
      <Box name={names.belt} size={[length, 0.012, width]} position={[0, 0, 0]} color="#2f6b3a" metalness={0.05} roughness={0.9} />
      <Box name={names.belt} size={[length, 0.012, width]} position={[0, -pr * 2, 0]} color="#245530" metalness={0.05} roughness={0.9} />
      {/* 頭尾滾輪 */}
      <group ref={pulleys}>
        {[-length / 2, length / 2].map((x) => (
          <Cyl key={x} name={names.belt} r={pr} h={width} position={[x, -pr, 0]} rotation={[Math.PI / 2, 0, 0]} color="#b8bec5" metalness={0.8} roughness={0.25} />
        ))}
      </group>
      {/* 側框（鋁擠）與托板 */}
      {[width / 2 + 0.02, -width / 2 - 0.02].map((z) => (
        <Static key={z} position={[0, -pr, z]} size={[length + 0.1, pr * 2 + 0.04, 0.03]} color="#8a9096" metalness={0.6} roughness={0.4} />
      ))}
      <Static position={[0, -pr, 0]} size={[length, 0.02, width]} color="#555c66" />
      {/* 機架 */}
      <Frame position={[0, -position[1], 0]} size={[length - 0.3, position[1] - pr * 2 - 0.03, width]} />
      {/* 減速馬達（含接線盒與風扇罩） */}
      {names.motor && (
        <group position={[length / 2, -pr, width / 2 + 0.12]}>
          <Cyl name={names.motor} r={0.05} h={0.14} rotation={[0, 0, Math.PI / 2]} color="#3b4048" />
          <Box name={names.motor} size={[0.08, 0.08, 0.08]} position={[-0.11, 0, 0]} color="#3b4048" />
          <Box name={names.motor} size={[0.05, 0.04, 0.06]} position={[0, 0.06, 0]} color="#5a6470" />
          <Cyl name={names.motor} r={0.045} h={0.02} position={[0.08, 0, 0]} rotation={[0, 0, Math.PI / 2]} color="#222" />
        </group>
      )}
      {showCarrier && (
        <group ref={carrier}>
          <Box name={names.carrier ?? names.belt} size={[0.22, 0.03, width * 0.7]} position={[0, 0.02, 0]} color={carrierColor} metalness={0.2} roughness={0.6} />
        </group>
      )}
    </group>
  );
}

/** 動力滾筒輸送機，沿 X 軸；每根滾筒各自繞軸自轉，含側框、機架與電動滾筒控制卡。 */
export function RollerConveyor({ position, length = 2, width = 0.4, name, rotationY = 0, run }: { position: Vec3; length?: number; width?: number; name: string; rotationY?: number; run?: () => boolean }) {
  const { playing } = useContext(SceneCtx);
  const grp = useRef<THREE.Group>(null);
  useFrame((_, dt) => {
    if (!playing || !grp.current) return;
    if (run && !run()) return;   // 累積式輸送：載具停下來時滾筒也停
    const d = Math.min(dt, 0.1);
    grp.current.children.forEach((c) => (c.rotation.y += d * 4)); // cylinder 幾何軸為 Y
  });
  const n = Math.floor(length / 0.08);
  return (
    <group position={position} rotation={[0, rotationY, 0]}>
      <group ref={grp}>
        {Array.from({ length: n }).map((_, i) => (
          <Cyl key={i} name={name} r={0.025} h={width} position={[-length / 2 + 0.04 + i * 0.08, 0, 0]} rotation={[Math.PI / 2, 0, 0]} color="#b8bec5" metalness={0.85} roughness={0.2} />
        ))}
      </group>
      {[width / 2 + 0.02, -width / 2 - 0.02].map((z) => (
        <Static key={z} position={[0, -0.03, z]} size={[length, 0.12, 0.03]} color="#8a9096" metalness={0.6} roughness={0.4} />
      ))}
      <Frame position={[0, -position[1], 0]} size={[length - 0.3, position[1] - 0.09, width]} />
    </group>
  );
}

/**
 * 往復動作的氣缸（沿本地 Y 軸伸縮）：缸體、前後蓋、活塞桿、安裝座、氣口。
 *
 * 給了 `drive` 就照命令走：活塞以有限速度移動並在末端被緩衝，
 * 實際位置透過 `onPos` 回報，場景據此點亮磁簧開關——也就是教材強調的
 * 「程式要等到位訊號，不是等時間」。沒給 drive 則沿用自由往復。
 */
export function Cylinder({
  position, rotation, name, stroke = 0.05, r = 0.02, len = 0.1, phase = 0,
  drive, travel = 0.35, onPos,
}: {
  position: Vec3; rotation?: Vec3; name: string; stroke?: number; r?: number; len?: number;
  phase?: number;
  /** 命令位置 0（縮回）～1（伸出） */
  drive?: () => number;
  /** 走完全行程要幾秒 */
  travel?: number;
  /** 每幀回報活塞的實際位置 0..1 */
  onPos?: (p: number) => void;
}) {
  const { playing } = useContext(SceneCtx);
  const rod = useRef<THREE.Group>(null);
  const actual = useRef(0);
  useFrame(({ clock }, dt) => {
    if (!playing || !rod.current) return;
    let p: number;
    if (drive) {
      const target = Math.min(1, Math.max(0, drive()));
      const step = Math.min(dt, 0.1) / travel;
      // 活塞不會瞬移：往命令位置逼近，最後一小段用緩衝曲線吃掉衝擊
      actual.current += Math.max(-step, Math.min(step, target - actual.current));
      p = target > actual.current - 1e-6 ? cushion(actual.current) : actual.current;
      onPos?.(actual.current);
    } else {
      p = Math.sin(clock.getElapsedTime() * 1.5 + phase) * 0.5 + 0.5;
    }
    rod.current.position.y = p * stroke;
  });
  return (
    <group position={position} rotation={rotation}>
      <Cyl name={name} r={r} h={len} color="#3b4048" metalness={0.5} roughness={0.4} />
      <Cyl name={name} r={r * 1.15} h={r * 0.8} position={[0, len / 2, 0]} color="#8a9096" metalness={0.8} roughness={0.3} />
      <Cyl name={name} r={r * 1.15} h={r * 0.8} position={[0, -len / 2, 0]} color="#8a9096" metalness={0.8} roughness={0.3} />
      <Box name={name} size={[r * 3, r * 0.8, r * 3]} position={[0, -len / 2 - r * 0.6, 0]} color="#5a6470" />
      <Cyl name={name} r={r * 0.3} h={r * 1.2} position={[r * 1.1, len * 0.3, 0]} rotation={[0, 0, Math.PI / 2]} color="#1e5aa8" metalness={0.3} roughness={0.5} />
      <group ref={rod}>
        <Cyl name={name} r={r * 0.45} h={len} position={[0, len * 0.6, 0]} color="#d0d4d8" metalness={0.95} roughness={0.15} />
        <Cyl name={name} r={r * 0.7} h={r * 0.6} position={[0, len * 1.1, 0]} color="#8a9096" metalness={0.8} roughness={0.3} />
      </group>
    </group>
  );
}

/** 旋轉的風扇／葉輪（含護網與外殼）。 */
export function Fan({ position, rotation, name, r = 0.2 }: { position: Vec3; rotation?: Vec3; name: string; r?: number }) {
  const { playing } = useContext(SceneCtx);
  const g = useRef<THREE.Group>(null);
  useFrame((_, dt) => { if (playing && g.current) g.current.rotation.z += dt * 8; });
  return (
    <group position={position} rotation={rotation}>
      <Cyl name={name} r={r * 1.1} h={r * 0.5} rotation={[Math.PI / 2, 0, 0]} color="#222" metalness={0.4} roughness={0.6} />
      <Cyl name={name} r={r * 0.95} h={r * 0.52} rotation={[Math.PI / 2, 0, 0]} color="#2f343a" metalness={0.2} roughness={0.8} />
      <group ref={g} position={[0, 0, r * 0.05]}>
        <Cyl name={name} r={r * 0.25} h={r * 0.3} rotation={[Math.PI / 2, 0, 0]} color="#555" />
        {[0, 1, 2, 3, 4, 5, 6].map((i) => (
          <Box key={i} name={name} size={[r * 0.75, r * 0.28, 0.01]} position={[Math.cos((i / 7) * Math.PI * 2) * r * 0.55, Math.sin((i / 7) * Math.PI * 2) * r * 0.55, 0]} rotation={[0.5, 0, (i / 7) * Math.PI * 2]} color="#6a7078" />
        ))}
      </group>
      {[0, 1, 2, 3].map((i) => (
        <Static key={i} position={[0, 0, r * 0.27]} size={[r * 2.1, 0.006, 0.006]} rotation={[0, 0, (i / 4) * Math.PI]} color="#999" metalness={0.8} />
      ))}
    </group>
  );
}

/**
 * 燈／感測器指示。給了 `on` 就依實際狀態亮滅（訊號 ON/OFF），
 * 沒給則沿用閃爍（純裝飾用）。
 */
export function Blinker({ position, name, color = '#ffb100', r = 0.03, on }: { position: Vec3; name: string; color?: string; r?: number; on?: () => boolean }) {
  const { playing } = useContext(SceneCtx);
  const m = useRef<THREE.MeshStandardMaterial>(null);
  useFrame(({ clock }) => {
    if (!m.current) return;
    if (on) {
      // 訊號燈：ON 時亮起，OFF 時只留下微弱的本體色，方便一眼看出訊號狀態
      const target = on() ? 1.6 : 0.04;
      m.current.emissiveIntensity += (target - m.current.emissiveIntensity) * 0.35;
    } else if (playing) {
      m.current.emissiveIntensity = 0.5 + Math.sin(clock.getElapsedTime() * 6) * 0.5;
    }
  });
  const ctx = useContext(SceneCtx);
  return (
    <mesh position={position} name={name} onClick={(e) => { e.stopPropagation(); ctx.onSelect?.(name); }} onPointerOver={(e) => { e.stopPropagation(); ctx.onHover?.(name); }} onPointerOut={() => ctx.onHover?.(null)}>
      <sphereGeometry args={[r, 16, 16]} />
      <meshStandardMaterial ref={m} color={color} emissive={color} emissiveIntensity={1} />
    </mesh>
  );
}

/** 管路（沿兩點）。 */
export function Pipe({ from, to, r = 0.02, color = '#c7cbd0' }: { from: Vec3; to: Vec3; r?: number; color?: string }) {
  const a = new THREE.Vector3(...from);
  const b = new THREE.Vector3(...to);
  const mid = a.clone().add(b).multiplyScalar(0.5);
  const dir = b.clone().sub(a);
  const len = dir.length();
  const q = new THREE.Quaternion().setFromUnitVectors(new THREE.Vector3(0, 1, 0), dir.clone().normalize());
  return (
    <mesh position={mid} quaternion={q} castShadow>
      <cylinderGeometry args={[r, r, len, 12]} />
      <meshStandardMaterial color={color} metalness={0.8} roughness={0.3} envMapIntensity={1} />
    </mesh>
  );
}

export function Floor({ size = 8 }: { size?: number }) {
  return (
    <mesh rotation={[-Math.PI / 2, 0, 0]} receiveShadow>
      <planeGeometry args={[size, size]} />
      <meshStandardMaterial color="#2b3038" roughness={0.9} metalness={0} />
    </mesh>
  );
}
