import { Component, Suspense, useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import { Canvas, useFrame, useThree } from '@react-three/fiber';
import { Bounds, Center, Html, OrbitControls, useGLTF } from '@react-three/drei';
import * as THREE from 'three';
import { RoomEnvironment } from 'three/addons/environments/RoomEnvironment.js';
import { disposeModelMaterials, prepareModel, orientComponentModel } from '../three/modelMaterials';

function Model({ url }: { url: string }) {
  const { scene } = useGLTF(url);
  const model = useMemo(() => orientComponentModel(prepareModel(scene), url), [scene, url]);
  useEffect(() => () => disposeModelMaterials(model), [model]);
  return <primitive object={model} dispose={null} />;
}

class ModelBoundary extends Component<{ children: ReactNode; fallback: ReactNode }, { failed: boolean }> {
  state = { failed: false };
  static getDerivedStateFromError() { return { failed: true }; }
  render() { return this.state.failed ? this.props.fallback : this.props.children; }
}

function Rotation({ playing }: { playing: boolean }) {
  const invalidate = useThree(state => state.invalidate);
  useEffect(() => { invalidate(); }, [playing, invalidate]);
  useFrame(() => { if (playing) invalidate(); });
  return <OrbitControls makeDefault autoRotate={playing} autoRotateSpeed={1.2} enableDamping enablePan={false} />;
}

function StudioEnvironment() {
  const { gl, scene, invalidate } = useThree();
  useEffect(() => {
    const generator = new THREE.PMREMGenerator(gl);
    const room = new RoomEnvironment();
    const environment = generator.fromScene(room, 0.04);
    const previous = scene.environment;
    scene.environment = environment.texture;
    invalidate();
    room.dispose();
    generator.dispose();
    return () => { scene.environment = previous; environment.dispose(); };
  }, [gl, scene, invalidate]);
  return null;
}

/** 單一元件可互動檢視；進入可見範圍才建立 Canvas，靜止時不持續重繪。 */
export function ModelViewer({ url, fallbackUrl }: { url: string; fallbackUrl?: string }) {
  const [playing, setPlaying] = useState(false);
  const [reset, setReset] = useState(0);
  const [visible, setVisible] = useState(false);
  const container = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const observer = new IntersectionObserver(entries => setVisible(entries.some(e => e.isIntersecting)), { rootMargin: '120px' });
    if (container.current) observer.observe(container.current);
    return () => observer.disconnect();
  }, []);
  const unavailable = <Html center><span className="model-status">模型暫時無法載入</span></Html>;
  return (
    <div className="component-model" ref={container}>
      <div className="model-toolbar">
        <button type="button" onClick={() => setPlaying(value => !value)} aria-pressed={playing}>{playing ? '停止旋轉' : '自動旋轉'}</button>
        <button type="button" onClick={() => setReset(value => value + 1)}>重設視角</button>
        <span>拖曳旋轉 · 滾輪縮放</span>
      </div>
      <div className="model-viewer">
      {visible && <Canvas key={reset} frameloop="demand" dpr={[1, 1.5]} camera={{ fov: 38, position: [2.8, 1.8, 3.2] }} gl={{ antialias: true, toneMapping: THREE.ACESFilmicToneMapping, toneMappingExposure: 1.2 }}>
        <color attach="background" args={['#202d38']} />
        <hemisphereLight args={['#ffffff', '#8598ac', 2]} />
        <directionalLight position={[3, 5, 4]} intensity={3} color="#fff5e9" />
        <directionalLight position={[-3, 2, -2]} intensity={1.5} color="#b3d7ff" />
        <StudioEnvironment />
        <Suspense fallback={<Html center><span className="model-status">載入 3D 模型…</span></Html>}>
          <Bounds fit clip observe margin={1.3}>
            <Center>
              <ModelBoundary fallback={fallbackUrl && fallbackUrl !== url ? <ModelBoundary fallback={unavailable}><Model url={fallbackUrl} /></ModelBoundary> : unavailable}>
                <Model url={url} />
              </ModelBoundary>
            </Center>
          </Bounds>
        </Suspense>
        <Rotation playing={playing} />
      </Canvas>}
      </div>
    </div>
  );
}
