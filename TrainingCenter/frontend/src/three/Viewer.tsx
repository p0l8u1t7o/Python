import { Suspense, useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import { Canvas, useThree } from '@react-three/fiber';
import { ContactShadows, Environment, Grid, Html, Lightformer, OrbitControls } from '@react-three/drei';
import type { OrbitControls as OrbitControlsImpl } from 'three-stdlib';
import * as THREE from 'three';
import { IxButton, IxIconButton } from '@siemens/ix-react';
import { iconPause, iconPlay } from '@siemens/ix-icons/icons';
import { Box, SceneCtx } from './Parts';
import { GltfScene } from './GltfScene';
import { FuelCellScene } from './scenes/FuelCell';
import { AoiScene } from './scenes/Aoi';
import { TransferScene } from './scenes/Transfer';
import { RobotCellScene } from './scenes/RobotCell';
import { type Component, type Domain, DOMAIN_COLOR, DOMAIN_LABEL } from '../api';

const SCENES: Record<string, () => ReactNode> = {
  fuelcell: () => <FuelCellScene />,
  aoi: () => <AoiScene />,
  transfer: () => <TransferScene />,
  robotcell: () => <RobotCellScene />,
};

/** 預設視角（多角度觀察）。 */
const VIEWS: Record<string, { label: string; pos: [number, number, number] }> = {
  iso: { label: '等角', pos: [5, 3.5, 5] },
  front: { label: '前視', pos: [0, 1.5, 7] },
  side: { label: '側視', pos: [7, 1.5, 0] },
  top: { label: '俯視', pos: [0.01, 8, 0] },
  back: { label: '後視', pos: [0, 1.5, -7] },
};

/** 燈光＋程序化環境貼圖（Lightformer 不需要外部 HDR，離線可用），讓金屬有反射。 */
function Lighting() {
  return (
    <>
      <hemisphereLight args={['#dfe8f5', '#3a3f47', 0.5]} />
      <directionalLight
        position={[5, 8, 4]}
        intensity={2.4}
        castShadow
        shadow-mapSize={[2048, 2048]}
        shadow-bias={-0.0002}
        shadow-camera-left={-6}
        shadow-camera-right={6}
        shadow-camera-top={6}
        shadow-camera-bottom={-6}
      />
      <directionalLight position={[-6, 4, -3]} intensity={0.5} color="#9ec5ff" />
      <Environment resolution={256} frames={1}>
        <Lightformer form="rect" intensity={3} position={[0, 5, -5]} scale={[10, 4, 1]} color="#ffffff" />
        <Lightformer form="rect" intensity={2} position={[5, 3, 5]} scale={[6, 3, 1]} rotation-y={-Math.PI / 4} color="#e8f0ff" />
        <Lightformer form="rect" intensity={1.5} position={[-6, 2, 2]} scale={[4, 3, 1]} rotation-y={Math.PI / 3} color="#ffe9d0" />
        <Lightformer form="ring" intensity={1} position={[0, 8, 0]} scale={6} rotation-x={Math.PI / 2} color="#ffffff" />
      </Environment>
    </>
  );
}

function CameraRig({ view, focus }: { view: string; focus: [number, number, number] | null }) {
  const { camera } = useThree();
  const controls = useRef<OrbitControlsImpl>(null);
  useEffect(() => {
    camera.position.set(...VIEWS[view].pos);
    controls.current?.target.set(0, 0.8, 0);
    controls.current?.update();
  }, [view, camera]);
  useEffect(() => {
    if (!focus || !controls.current) return;
    controls.current.target.set(...focus);
    controls.current.update();
  }, [focus]);
  return <OrbitControls ref={controls} makeDefault enableDamping dampingFactor={0.1} maxPolarAngle={Math.PI / 2 - 0.02} minDistance={1.5} maxDistance={15} />;
}


export interface HotspotItem { component: Component; domain: Domain }

/**
 * 場景中沒有對應 mesh 的元件（例如接頭、端子台、斷路器），
 * 在其座標自動補一個小型 3D 實體，讓每個元件都能在 3D 上被指到與高亮。
 */
function AutoParts({ hotspots }: { hotspots: HotspotItem[] }) {
  const { scene } = useThree();
  const [missing, setMissing] = useState<HotspotItem[]>([]);
  useEffect(() => {
    const t = setTimeout(() => {
      const names = new Set<string>();
      scene.traverse((o) => { if (o.name) names.add(o.name); });
      const seen = new Set<string>();
      setMissing(
        hotspots.filter((h) => {
          const n = h.component.mesh_name;
          if (!n || names.has(n) || seen.has(n)) return false;
          seen.add(n);
          return true;
        }),
      );
    }, 50);
    return () => clearTimeout(t);
  }, [hotspots, scene]);
  return (
    <>
      {missing.map(({ component: c, domain }) => (
        <Box
          key={c.mesh_name}
          name={c.mesh_name}
          size={[0.08, 0.06, 0.06]}
          position={c.pos}
          color={domain === 'utility' ? '#d4a017' : '#7d8790'}
          metalness={0.8}
          roughness={0.3}
        />
      ))}
    </>
  );
}

/** 滑鼠移到零件上時顯示的標籤（跟著該元件座標）。 */
function HoverLabel({ item, active }: { item: HotspotItem | null; active: boolean }) {
  if (!item) return null;
  const { component: c, domain } = item;
  return (
    <Html position={c.pos} zIndexRange={[10, 0]} style={{ pointerEvents: 'none' }} center>
      <div className={`part-label ${active ? 'active' : ''}`} style={{ borderColor: DOMAIN_COLOR[domain] }}>
        <span className="domain-dot" style={{ background: DOMAIN_COLOR[domain] }} />
        {c.name}
        <span className="sub">{DOMAIN_LABEL[domain]} · {c.install_location}</span>
      </div>
    </Html>
  );
}

interface ViewerProps {
  sceneKey: string;
  modelFile?: string | null;
  /** 全部元件（跨分頁都可點選） */
  hotspots: HotspotItem[];
  /** 目前分頁；沒有專屬 mesh 的元件只在自己的分頁補實體，避免畫面雜亂 */
  activeDomain?: Domain;
  selected: Component | null;
  onSelect: (c: Component) => void;
}

/** 設備 3D 檢視器：軌道旋轉、預設視角、滑鼠指到零件高亮並顯示名稱、點擊選取、動畫播放。 */
export function Viewer({ sceneKey, modelFile, hotspots, activeDomain, selected, onSelect }: ViewerProps) {
  const [view, setView] = useState('iso');
  const [playing, setPlaying] = useState(true);
  // 目前的動作步驟（由場景的 useCycle 回報），讓學員看得懂機台正在做什麼
  const [step, setStep] = useState('');
  const [hovered, setHovered] = useState<string | null>(null);
  const Scene = SCENES[sceneKey];

  const byMesh = useMemo(() => {
    const m = new Map<string, HotspotItem>();
    hotspots.forEach((h) => { if (h.component.mesh_name && !m.has(h.component.mesh_name)) m.set(h.component.mesh_name, h); });
    return m;
  }, [hotspots]);
  const knownNames = useMemo(() => new Set(byMesh.keys()), [byMesh]);
  const hoveredItem = hovered ? byMesh.get(hovered) ?? null : null;
  const selectedItem = selected ? hotspots.find((h) => h.component.id === selected.id) ?? null : null;

  const selectByMesh = (mesh: string) => {
    const hit = byMesh.get(mesh);
    if (hit) onSelect(hit.component);
  };

  return (
    <div className="viewer">
      <div className="viewer-toolbar">
        {Object.entries(VIEWS).map(([k, v]) => (
          <IxButton key={k} variant={view === k ? 'primary' : 'subtle-secondary'} onClick={() => setView(k)}>
            {v.label}
          </IxButton>
        ))}
        <IxIconButton size="24" variant="subtle-secondary" icon={playing ? iconPause : iconPlay} onClick={() => setPlaying((p) => !p)} />
      </div>
      {step && (
        <div className="viewer-step">
          <span className="viewer-step-dot" />
          {step}
        </div>
      )}
      <div className="viewer-legend">拖曳旋轉 · 滾輪縮放 · 右鍵平移 · 滑鼠移到零件上會高亮並顯示名稱，點擊查看說明</div>
      <Canvas
        shadows
        dpr={[1, 2]}
        camera={{ fov: 45, position: VIEWS.iso.pos }}
        gl={{ antialias: true, toneMapping: THREE.ACESFilmicToneMapping, toneMappingExposure: 1.0 }}
        onPointerMissed={() => setHovered(null)}
      >
        <color attach="background" args={['#1f242b']} />
        <fog attach="fog" args={['#1f242b', 12, 30]} />
        <Lighting />
        <SceneCtx.Provider value={{ selected: selected?.mesh_name ?? null, hovered, playing, onSelect: selectByMesh, onHover: setHovered, onStep: setStep }}>
          <Suspense fallback={null}>
            {modelFile ? (
              /* text-to-cad 整機 glb：節點名稱即 mesh_name，所有元件都有實體，不需 AutoParts */
              <GltfScene url={modelFile} knownNames={knownNames} />
            ) : (
              <>
                {Scene ? <Scene /> : null}
                <AutoParts hotspots={activeDomain ? hotspots.filter((h) => h.domain === activeDomain || h.component.id === selected?.id) : hotspots} />
              </>
            )}
          </Suspense>
        </SceneCtx.Provider>
        <ContactShadows position={[0, 0.001, 0]} opacity={0.5} scale={14} blur={2} far={4} />
        <Grid position={[0, 0.002, 0]} args={[20, 20]} cellColor="#3a424c" sectionColor="#4d5865" fadeDistance={18} infiniteGrid />
        {hoveredItem && hoveredItem.component.id !== selected?.id && <HoverLabel item={hoveredItem} active={false} />}
        {selectedItem && <HoverLabel item={selectedItem} active />}
        <CameraRig view={view} focus={selected ? selected.pos : null} />
      </Canvas>
    </div>
  );
}

/** 首頁卡片用的小型自轉預覽。 */
export function ScenePreview({ sceneKey }: { sceneKey: string }) {
  const Scene = SCENES[sceneKey];
  if (!Scene) return null;
  return (
    <Canvas dpr={[1, 1.5]} camera={{ fov: 40, position: [5, 3.5, 5] }} style={{ pointerEvents: 'none' }}>
      <Lighting />
      <SceneCtx.Provider value={{ selected: null, hovered: null, playing: true }}>
        <Scene />
      </SceneCtx.Provider>
      <OrbitControls autoRotate autoRotateSpeed={1.5} enableZoom={false} enablePan={false} target={[0, 0.8, 0]} />
    </Canvas>
  );
}
