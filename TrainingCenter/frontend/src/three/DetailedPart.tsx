import { Component as ErrorBoundaryBase, Suspense, useContext, useEffect, useMemo, type ReactNode } from 'react';
import { useGLTF } from '@react-three/drei';
import * as THREE from 'three';
import type { Component } from '../api';
import { componentVisual } from '../componentVisuals';
import { Box, SceneCtx } from './Parts';
import { prepareModel, disposeModelMaterials } from './modelMaterials';

class PartBoundary extends ErrorBoundaryBase<{ children: ReactNode; fallback: ReactNode }, { failed: boolean }> {
  state = { failed: false };
  static getDerivedStateFromError() { return { failed: true }; }
  render() { return this.state.failed ? this.props.fallback : this.props.children; }
}

function Part({ url, name }: { url: string; name: string }) {
  const { scene } = useGLTF(url);
  const context = useContext(SceneCtx);
  const model = useMemo(() => {
    const instance = prepareModel(scene);
    const bounds = new THREE.Box3().setFromObject(instance);
    const center = bounds.getCenter(new THREE.Vector3());
    const size = bounds.getSize(new THREE.Vector3());
    const scale = 0.16 / Math.max(size.x, size.y, size.z);
    instance.scale.multiplyScalar(scale);
    instance.position.copy(center).multiplyScalar(-scale);
    return instance;
  }, [scene]);
  useEffect(() => () => disposeModelMaterials(model), [model]);
  useEffect(() => {
    model.traverse(object => {
      const mesh = object as THREE.Mesh;
      if (!mesh.isMesh) return;
      for (const material of Array.isArray(mesh.material) ? mesh.material : [mesh.material]) {
        const mat = material as THREE.MeshStandardMaterial;
        if (!mat.isMeshStandardMaterial) continue;
        mat.emissive.set(context.selected === name ? '#00cccc' : context.hovered === name ? '#ffb100' : '#000000');
        mat.emissiveIntensity = 0.45;
      }
    });
  }, [context.selected, context.hovered, model, name]);
  return <primitive object={model} dispose={null}
    onClick={(e: { stopPropagation: () => void }) => { e.stopPropagation(); context.onSelect?.(name); }}
    onPointerOver={(e: { stopPropagation: () => void }) => { e.stopPropagation(); context.onHover?.(name); }}
    onPointerOut={() => context.onHover?.(null)} />;
}

/** Detailed bodies for selectable components absent from the assembly scene. */
export function DetailedPart({ component }: { component: Component }) {
  const visual = componentVisual(component);
  const fallback = <Box name={component.mesh_name} size={[0.08, 0.06, 0.06]} color="#7d8790" />;
  return <group position={component.pos} userData={{ autoPart: true }}>
    <PartBoundary fallback={fallback}><Suspense fallback={fallback}>
      {visual ? <Part url={visual.model} name={component.mesh_name} /> : fallback}
    </Suspense></PartBoundary>
  </group>;
}
