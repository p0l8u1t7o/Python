import { useContext, useEffect, useMemo, useRef } from 'react';
import { useFrame } from '@react-three/fiber';
import { useGLTF } from '@react-three/drei';
import * as THREE from 'three';
import { SceneCtx, useAnimationClock } from './Parts';
import { disposeModelMaterials, prepareModel } from './modelMaterials';
import { rotateAroundPivot, translateAlongAxis } from './modelAnimation';

/**
 * 載入 text-to-cad（cadgen）匯出的設備 glb，並提供與程序化場景相同的互動：
 * - 節點名稱 = seed 的 mesh_name：hover 高亮、點擊選取（往上找最近的已知節點名）
 * - 子節點 `_pivot`／`_axis`／`_anim_<kind>` 是隱形基準點：據此做關節擺動、氣缸往復、載具循環、風扇旋轉
 */

type Kind = 'rev' | 'spin' | 'rod' | 'carrier' | 'blink';
interface Anim { node: THREE.Object3D; kind: Kind; pivot: THREE.Vector3; axis: THREE.Vector3; phase: number; range: number; position: THREE.Vector3; rotation: THREE.Quaternion }

const HIGHLIGHT = new THREE.Color('#00cccc');
const HOVER = new THREE.Color('#ffb100');

function hashPhase(s: string) {
  let h = 0;
  for (let i = 0; i < s.length; i++) h = (h * 31 + s.charCodeAt(i)) | 0;
  return (Math.abs(h) % 628) / 100;
}

export function GltfScene({ url, knownNames }: { url: string; knownNames: Set<string> }) {
  const { scene: source } = useGLTF(url);
  const scene = useMemo(() => prepareModel(source), [source]);
  useEffect(() => () => disposeModelMaterials(scene), [scene]);
  const clock = useAnimationClock();
  const ctx = useContext(SceneCtx);
  const highlighted = useRef<string | null>(null);
  const hoveredRef = useRef<string | null>(null);

  // 準備：材質獨立化（避免共用材質一起變色）、找出動畫節點、隱藏基準點
  const anims = useMemo<Anim[]>(() => {
    const list: Anim[] = [];
    scene.updateMatrixWorld(true);
    scene.traverse((node) => {
      const animChild = node.children.find((c) => c.name.startsWith('_anim_'));
      if (!animChild) return;
      const kind = animChild.name.slice('_anim_'.length) as Kind;
      const pv = node.children.find((c) => c.name === '_pivot');
      const ax = node.children.find((c) => c.name === '_axis');
      if (!pv || !ax) return;
      const pivot = new THREE.Vector3();
      const axisPt = new THREE.Vector3();
      pv.getWorldPosition(pivot);
      ax.getWorldPosition(axisPt);
      // 轉到父節點的本地座標（父節點靜止時 = 世界座標）
      node.parent?.worldToLocal(pivot);
      node.parent?.worldToLocal(axisPt);
      const axis = axisPt.clone().sub(pivot).normalize();
      list.push({ node, kind, pivot, axis, phase: hashPhase(node.name), range: kind === 'rev' ? 0.35 : 0.02, position: node.position.clone(), rotation: node.quaternion.clone() });
    });
    // 隱藏所有基準點
    scene.traverse((o) => { if (o.name.startsWith('_pivot') || o.name.startsWith('_axis') || o.name.startsWith('_anim_')) o.visible = false; });
    return list;
  }, [scene]);

  // 名稱 → 該子樹所有 mesh
  const groups = useMemo(() => {
    const map = new Map<string, THREE.Mesh[]>();
    scene.traverse((o) => {
      if (knownNames.has(o.name)) {
        const meshes: THREE.Mesh[] = [];
        o.traverse((c) => { if ((c as THREE.Mesh).isMesh) meshes.push(c as THREE.Mesh); });
        map.set(o.name, [...(map.get(o.name) ?? []), ...meshes]);
      }
    });
    return map;
  }, [scene, knownNames]);

  const setEmissive = (name: string | null, color: THREE.Color | null, intensity: number) => {
    if (!name) return;
    groups.get(name)?.forEach((m) => {
      for (const material of Array.isArray(m.material) ? m.material : [m.material]) {
        const mat = material as THREE.MeshStandardMaterial;
        if (!mat.isMeshStandardMaterial) continue;
        mat.emissive.copy(color ?? new THREE.Color(0, 0, 0));
        mat.emissiveIntensity = intensity;
      }
    });
  };

  useEffect(() => {
    const prev = highlighted.current;
    if (prev && prev !== ctx.selected) setEmissive(prev, null, 0);
    if (ctx.selected) setEmissive(ctx.selected, HIGHLIGHT, 0.7);
    highlighted.current = ctx.selected;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ctx.selected, groups]);

  useEffect(() => {
    const prev = hoveredRef.current;
    if (prev && prev !== ctx.selected) setEmissive(prev, null, 0);
    if (ctx.hovered && ctx.hovered !== ctx.selected) setEmissive(ctx.hovered, HOVER, 0.5);
    hoveredRef.current = ctx.hovered;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ctx.hovered, ctx.selected, groups]);

  const q = useMemo(() => new THREE.Quaternion(), []);
  useFrame(() => {
    if (!ctx.playing) return;
    const t = clock.current;
    for (const a of anims) {
      if (a.kind === 'rev' || a.kind === 'spin') {
        const ang = a.kind === 'rev' ? (Math.sin(t * 0.8 + a.phase) - Math.sin(a.phase)) * a.range : (t * 6) % (Math.PI * 2);
        q.setFromAxisAngle(a.axis, ang);
        rotateAroundPivot(a.node, a.position, a.rotation, a.pivot, q);
      } else if (a.kind === 'rod') {
        const s = (1 - Math.cos(t * 1.5)) * 0.015; // 30 mm 行程，零位起動
        translateAlongAxis(a.node, a.position, a.axis, s);
      } else if (a.kind === 'carrier') {
        const L = 1.2;
        const s = Math.sin(t * 0.5) * L / 2;
        translateAlongAxis(a.node, a.position, a.axis, s);
      } else if (a.kind === 'blink') {
        a.node.traverse((o) => {
          const mesh = o as THREE.Mesh;
          if (!mesh.isMesh) return;
          // Selection highlighting takes precedence over status-light animation.
          if (groups.get(ctx.selected ?? '')?.includes(mesh) || groups.get(ctx.hovered ?? '')?.includes(mesh)) return;
          for (const material of Array.isArray(mesh.material) ? mesh.material : [mesh.material]) {
            const mat = material as THREE.MeshStandardMaterial;
            if (mat.isMeshStandardMaterial) { mat.emissive.copy(mat.color); mat.emissiveIntensity = 0.5 + Math.sin(t * 6 + a.phase) * 0.5; }
          }
        });
      }
    }
  });

  const findName = (o: THREE.Object3D | null): string | null => {
    let cur: THREE.Object3D | null = o;
    while (cur) {
      if (knownNames.has(cur.name)) return cur.name;
      cur = cur.parent;
    }
    return null;
  };

  return (
    <primitive
      object={scene}
      dispose={null}
      onClick={(e: { stopPropagation: () => void; object: THREE.Object3D }) => { e.stopPropagation(); const n = findName(e.object); if (n) ctx.onSelect?.(n); }}
      onPointerMove={(e: { stopPropagation: () => void; object: THREE.Object3D }) => { e.stopPropagation(); const n = findName(e.object); if (n !== hoveredRef.current) ctx.onHover?.(n); document.body.style.cursor = n ? 'pointer' : 'auto'; }}
      /* 跨 mesh 移動會先 out 再 move；同一幀內 React 批次更新，不會閃爍 */
      onPointerOut={() => { ctx.onHover?.(null); document.body.style.cursor = 'auto'; }}
    />
  );
}
