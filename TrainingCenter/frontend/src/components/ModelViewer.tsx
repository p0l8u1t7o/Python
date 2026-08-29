import { Suspense, useEffect } from 'react';
import { Canvas } from '@react-three/fiber';
import { Bounds, Center, Environment, Lightformer, OrbitControls, useGLTF } from '@react-three/drei';
import * as THREE from 'three';

function Model({ url }: { url: string }) {
  const { scene } = useGLTF(url);
  useEffect(() => {
    // 保留 glb 自帶的顏色（cadgen 匯出的 GLB 有 srgb 顏色）；沒有材質或只是 Basic 材質時才套金屬材質
    scene.traverse((o) => {
      const m = o as THREE.Mesh;
      if (!m.isMesh) return;
      m.castShadow = true;
      const mat = m.material as THREE.Material | undefined;
      if (!mat || (mat as THREE.MeshBasicMaterial).isMeshBasicMaterial) {
        m.material = new THREE.MeshStandardMaterial({ color: '#b9c0c7', metalness: 0.7, roughness: 0.35 });
      } else if ((mat as THREE.MeshStandardMaterial).isMeshStandardMaterial) {
        const sm = mat as THREE.MeshStandardMaterial;
        sm.metalness = Math.max(sm.metalness, 0.4);
        sm.roughness = Math.min(sm.roughness, 0.5);
        sm.envMapIntensity = 1.2;
      }
    });
  }, [scene]);
  return <primitive object={scene} />;
}

/** 元件 3D CAD 小型檢視器（glb），自動置中縮放到視野。 */
export function ModelViewer({ url }: { url: string }) {
  return (
    <div className="model-viewer">
      <Canvas dpr={[1, 2]} camera={{ fov: 40, position: [2, 1.5, 2] }} gl={{ antialias: true, toneMapping: THREE.ACESFilmicToneMapping }}>
        <color attach="background" args={['#1a1f26']} />
        <hemisphereLight args={['#dfe8f5', '#3a3f47', 0.6]} />
        <directionalLight position={[3, 5, 2]} intensity={2} />
        <Environment resolution={128} frames={1}>
          <Lightformer form="rect" intensity={3} position={[0, 4, -4]} scale={[8, 3, 1]} />
          <Lightformer form="rect" intensity={2} position={[4, 2, 4]} scale={[4, 2, 1]} rotation-y={-Math.PI / 4} />
        </Environment>
        <Suspense fallback={null}>
          <Bounds fit clip observe margin={1.2}>
            <Center>
              <Model url={url} />
            </Center>
          </Bounds>
        </Suspense>
        <OrbitControls makeDefault autoRotate autoRotateSpeed={2} enableDamping />
      </Canvas>
    </div>
  );
}
