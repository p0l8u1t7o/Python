import { useEffect, useMemo, useRef, useState } from "react";
import * as THREE from "three";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";
import { GLTFLoader } from "three/examples/jsm/loaders/GLTFLoader.js";
import { modulePreviewUrl } from "../api";
import type { FrameInfo, ModuleAxisInfo } from "../types";
import {
  applyAxisValue,
  captureRestTransforms,
  findSceneNode,
  type RestTransforms,
} from "../viewer-core";

type ViewBounds = { center: THREE.Vector3; span: number };
type Metrics = { dimensions: THREE.Vector3; triangles: number };
type Runtime = {
  moduleRoot: THREE.Object3D;
  camera: THREE.PerspectiveCamera;
  controls: OrbitControls;
  rest: RestTransforms;
  visualMeshes: THREE.Mesh[];
  collisionNodes: THREE.Object3D[];
  frameHelpers: THREE.Group[];
};

const FRAME_AXIS_LENGTH_MM = 50;
const AXIS_SLIDER_STEPS = 200;

export function ModulePreview({
  projectId,
  moduleId,
  axes,
  frames,
  assetRevision = 0,
}: {
  projectId: string;
  moduleId: string;
  axes: ModuleAxisInfo[];
  frames: Record<string, FrameInfo>;
  assetRevision?: number;
}) {
  const host = useRef<HTMLDivElement>(null);
  const runtime = useRef<Runtime>();
  const bounds = useRef<ViewBounds>();
  const [axisValues, setAxisValues] = useState<Record<string, number>>(() =>
    defaultAxisValues(axes),
  );
  const [collisionVisible, setCollisionVisible] = useState(false);
  const [framesVisible, setFramesVisible] = useState(false);
  const [wireframe, setWireframe] = useState(false);
  const [metrics, setMetrics] = useState<Metrics>();
  const [loaded, setLoaded] = useState(0);
  const [error, setError] = useState<string>();
  const [hover, setHover] = useState<{ name: string; x: number; y: number }>();
  const previewUrl = useMemo(
    () => `${modulePreviewUrl(projectId, moduleId)}?revision=${assetRevision}`,
    [assetRevision, projectId, moduleId],
  );

  useEffect(() => {
    setAxisValues(defaultAxisValues(axes));
    setCollisionVisible(false);
    setFramesVisible(false);
    setWireframe(false);
    setMetrics(undefined);
    setError(undefined);
  }, [axes, moduleId]);

  useEffect(() => {
    if (!host.current) return;
    const container = host.current;
    const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
    renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
    renderer.outputColorSpace = THREE.SRGBColorSpace;
    renderer.setClearColor(0x0a1118, 1);
    container.prepend(renderer.domElement);

    const scene = new THREE.Scene();
    scene.up.set(0, 0, 1);
    scene.add(new THREE.HemisphereLight(0xe9f4ff, 0x17202a, 2.5));
    const keyLight = new THREE.DirectionalLight(0xffffff, 3);
    keyLight.position.set(-1200, -1800, 2600);
    scene.add(keyLight);

    const camera = new THREE.PerspectiveCamera(38, 1, 0.5, 50000);
    camera.up.set(0, 0, 1);
    const controls = new OrbitControls(camera, renderer.domElement);
    controls.enableDamping = true;

    const resize = () => {
      renderer.setSize(container.clientWidth, container.clientHeight);
      camera.aspect = container.clientWidth / Math.max(container.clientHeight, 1);
      camera.updateProjectionMatrix();
    };
    const observer = new ResizeObserver(resize);
    observer.observe(container);
    resize();

    let disposed = false;
    const loader = new GLTFLoader();
    loader
      .loadAsync(previewUrl)
      .then((gltf) => {
        if (disposed) return;
        const moduleRoot = gltf.scene.getObjectByName(moduleId) ?? gltf.scene;
        const visualMeshes: THREE.Mesh[] = [];
        const collisionNodes: THREE.Object3D[] = [];
        gltf.scene.traverse((object) => {
          if (object.userData.hidden === true) {
            object.visible = false;
            collisionNodes.push(object);
          }
          if (object instanceof THREE.Mesh) {
            const materials = (
              Array.isArray(object.material) ? object.material : [object.material]
            ).map((material) => material.clone());
            object.material = Array.isArray(object.material) ? materials : materials[0];
            if (!hasHiddenAncestor(object)) visualMeshes.push(object);
          }
        });
        scene.add(gltf.scene);
        const rest = captureRestTransforms(gltf.scene);
        gltf.scene.updateMatrixWorld(true);
        const frameHelpers = createFrameHelpers(moduleRoot, moduleId, frames, axes);
        for (const axis of axes)
          applyAxisValue(
            findSceneNode(gltf.scene, `${moduleId}.${axis.id}`),
            defaultAxisValue(axis),
            rest,
          );
        gltf.scene.updateMatrixWorld(true);

        const measured = measureVisuals(visualMeshes);
        const viewBounds = boundsFromBox(measured.box);
        bounds.current = viewBounds;
        const groundSize = Math.max(viewBounds.span * 2.5, 500);
        const divisions = Math.max(10, Math.round(groundSize / 100));
        const grid = new THREE.GridHelper(groundSize, divisions, 0x506276, 0x263440);
        grid.rotation.x = Math.PI / 2;
        grid.position.set(viewBounds.center.x, viewBounds.center.y, 0);
        scene.add(grid);
        const plane = new THREE.Mesh(
          new THREE.PlaneGeometry(groundSize, groundSize),
          new THREE.MeshBasicMaterial({
            color: 0x6f8596,
            transparent: true,
            opacity: 0.06,
            side: THREE.DoubleSide,
            depthWrite: false,
          }),
        );
        plane.position.set(viewBounds.center.x, viewBounds.center.y, -0.2);
        scene.add(plane);
        camera.near = Math.max(0.5, viewBounds.span / 10000);
        camera.far = Math.max(5000, viewBounds.span * 12);
        camera.updateProjectionMatrix();
        applyCamera(camera, controls, viewBounds, "iso");
        runtime.current = {
          moduleRoot: gltf.scene,
          camera,
          controls,
          rest,
          visualMeshes,
          collisionNodes,
          frameHelpers,
        };
        setMetrics({
          dimensions: measured.box.getSize(new THREE.Vector3()),
          triangles: measured.triangles,
        });
        setLoaded((value) => value + 1);
      })
      .catch((reason) => setError(reason instanceof Error ? reason.message : String(reason)));

    const raycaster = new THREE.Raycaster();
    raycaster.params.Line.threshold = 6;
    const pointer = new THREE.Vector2();
    const handlePointer = (event: PointerEvent) => {
      const current = runtime.current;
      if (!current || !current.frameHelpers.some((helper) => helper.visible)) {
        setHover(undefined);
        return;
      }
      const rect = renderer.domElement.getBoundingClientRect();
      pointer.set(
        ((event.clientX - rect.left) / rect.width) * 2 - 1,
        -((event.clientY - rect.top) / rect.height) * 2 + 1,
      );
      raycaster.setFromCamera(pointer, camera);
      const hit = raycaster.intersectObjects(current.frameHelpers, true)[0];
      const name = hit && frameName(hit.object);
      setHover(
        name ? { name, x: event.clientX - rect.left, y: event.clientY - rect.top } : undefined,
      );
    };
    renderer.domElement.addEventListener("pointermove", handlePointer);
    renderer.domElement.addEventListener("pointerleave", () => setHover(undefined));

    let animationFrame = 0;
    const render = () => {
      animationFrame = requestAnimationFrame(render);
      controls.update();
      renderer.render(scene, camera);
    };
    render();
    return () => {
      disposed = true;
      cancelAnimationFrame(animationFrame);
      observer.disconnect();
      renderer.domElement.removeEventListener("pointermove", handlePointer);
      controls.dispose();
      renderer.dispose();
      renderer.domElement.remove();
      runtime.current = undefined;
    };
  }, [axes, frames, moduleId, previewUrl]);

  useEffect(() => {
    const current = runtime.current;
    if (!current) return;
    for (const axis of axes)
      applyAxisValue(
        findSceneNode(current.moduleRoot, `${moduleId}.${axis.id}`),
        axisValues[axis.id],
        current.rest,
      );
    current.moduleRoot.updateMatrixWorld(true);
    const measured = measureVisuals(current.visualMeshes);
    bounds.current = boundsFromBox(measured.box);
    setMetrics({
      dimensions: measured.box.getSize(new THREE.Vector3()),
      triangles: measured.triangles,
    });
  }, [axes, axisValues, loaded, moduleId]);

  useEffect(() => {
    for (const node of runtime.current?.collisionNodes ?? []) node.visible = collisionVisible;
  }, [collisionVisible, loaded]);

  useEffect(() => {
    for (const helper of runtime.current?.frameHelpers ?? []) helper.visible = framesVisible;
    if (!framesVisible) setHover(undefined);
  }, [framesVisible, loaded]);

  useEffect(() => {
    for (const mesh of runtime.current?.visualMeshes ?? [])
      for (const material of meshMaterials(mesh)) material.wireframe = wireframe;
  }, [wireframe, loaded]);

  const setView = (preset: string) => {
    if (!runtime.current || !bounds.current) return;
    applyCamera(runtime.current.camera, runtime.current.controls, bounds.current, preset);
  };

  return (
    <section className="module-preview" aria-label={`${moduleId} 單模組 3D 預覽`}>
      <div className="module-preview-stage" ref={host}>
        <div className="module-preview-views">
          {[
            ["iso", "ISO"],
            ["front", "前"],
            ["side", "側"],
            ["top", "上"],
          ].map(([preset, label]) => (
            <button key={preset} onClick={() => setView(preset)}>
              {label}
            </button>
          ))}
        </div>
        <div className="module-preview-toggles">
          <button
            className={collisionVisible ? "active" : ""}
            onClick={() => setCollisionVisible((value) => !value)}
          >
            碰撞體
          </button>
          <button
            className={framesVisible ? "active" : ""}
            onClick={() => setFramesVisible((value) => !value)}
          >
            Frames
          </button>
          <button
            className={wireframe ? "active" : ""}
            onClick={() => setWireframe((value) => !value)}
          >
            線框
          </button>
        </div>
        {hover && (
          <span className="module-frame-tooltip" style={{ left: hover.x + 9, top: hover.y + 9 }}>
            {hover.name}
          </span>
        )}
        {error && <div className="module-preview-error">3D 載入失敗：{error}</div>}
        {!metrics && !error && <div className="module-preview-loading">正在載入 3D…</div>}
      </div>
      {axes.length > 0 && (
        <div className="module-axis-controls">
          {axes.map((axis) => {
            const range = axisRange(axis);
            const value = axisValues[axis.id] ?? defaultAxisValue(axis);
            const unit = axis.type === "revolute" ? "°" : "mm";
            return (
              <label key={axis.id}>
                <span>{axis.id}</span>
                <input
                  aria-label={`${axis.id} 軸值`}
                  type="range"
                  min={range[0]}
                  max={range[1]}
                  step={Math.max((range[1] - range[0]) / AXIS_SLIDER_STEPS, Number.EPSILON)}
                  value={value}
                  onChange={(event) =>
                    setAxisValues((current) => ({
                      ...current,
                      [axis.id]: Number(event.target.value),
                    }))
                  }
                />
                <output>
                  {value.toFixed(1)} {unit}
                </output>
              </label>
            );
          })}
        </div>
      )}
      <footer>
        <span>
          包圍盒：
          {metrics
            ? `${metrics.dimensions.x.toFixed(1)} × ${metrics.dimensions.y.toFixed(1)} × ${metrics.dimensions.z.toFixed(1)} mm`
            : "—"}
        </span>
        <span>三角形：{metrics ? metrics.triangles.toLocaleString("zh-TW") : "—"}</span>
      </footer>
    </section>
  );
}

function axisRange(axis: ModuleAxisInfo): [number, number] {
  return axis.type === "revolute" ? (axis.range_deg ?? [0, 0]) : (axis.range_mm ?? [0, 0]);
}

function defaultAxisValue(axis: ModuleAxisInfo): number {
  const [minimum, maximum] = axisRange(axis);
  return Math.min(maximum, Math.max(minimum, 0));
}

function defaultAxisValues(axes: ModuleAxisInfo[]): Record<string, number> {
  return Object.fromEntries(axes.map((axis) => [axis.id, defaultAxisValue(axis)]));
}

function createFrameHelpers(
  moduleRoot: THREE.Object3D,
  moduleId: string,
  frames: Record<string, FrameInfo>,
  axes: ModuleAxisInfo[],
): THREE.Group[] {
  const helpers: THREE.Group[] = [];
  moduleRoot.updateMatrixWorld(true);
  for (const [name, frame] of Object.entries(frames)) {
    const group = new THREE.Group();
    group.name = `__cellforge_frame_${name}`;
    group.userData.frameName = name;
    group.position.fromArray(frame.xyz);
    group.quaternion.copy(fixedAxisQuaternion(frame.rpy_deg));
    const triad = new THREE.AxesHelper(FRAME_AXIS_LENGTH_MM);
    triad.userData.frameName = name;
    triad.renderOrder = 5;
    group.add(triad);
    moduleRoot.add(group);
    moduleRoot.updateMatrixWorld(true);
    const linkedAxis = axes.find((axis) => (axis.child ?? axis.id) === frame.link);
    const linkedNode = linkedAxis
      ? findSceneNode(moduleRoot, `${moduleId}.${linkedAxis.id}`)
      : undefined;
    if (linkedNode) {
      linkedNode.updateWorldMatrix(true, false);
      linkedNode.attach(group);
    }
    group.visible = false;
    helpers.push(group);
  }
  return helpers;
}

function fixedAxisQuaternion(rpyDeg: [number, number, number]): THREE.Quaternion {
  const [roll, pitch, yaw] = rpyDeg.map(THREE.MathUtils.degToRad);
  const qx = new THREE.Quaternion().setFromAxisAngle(new THREE.Vector3(1, 0, 0), roll);
  const qy = new THREE.Quaternion().setFromAxisAngle(new THREE.Vector3(0, 1, 0), pitch);
  const qz = new THREE.Quaternion().setFromAxisAngle(new THREE.Vector3(0, 0, 1), yaw);
  return qz.multiply(qy).multiply(qx);
}

function frameName(object: THREE.Object3D): string | undefined {
  let current: THREE.Object3D | null = object;
  while (current) {
    if (typeof current.userData.frameName === "string") return current.userData.frameName;
    current = current.parent;
  }
  return undefined;
}

function hasHiddenAncestor(object: THREE.Object3D): boolean {
  let current: THREE.Object3D | null = object;
  while (current) {
    if (current.userData.hidden === true) return true;
    current = current.parent;
  }
  return false;
}

function meshMaterials(mesh: THREE.Mesh): THREE.MeshStandardMaterial[] {
  const materials = Array.isArray(mesh.material) ? mesh.material : [mesh.material];
  return materials.filter(
    (material): material is THREE.MeshStandardMaterial =>
      material instanceof THREE.MeshStandardMaterial,
  );
}

function measureVisuals(meshes: THREE.Mesh[]): { box: THREE.Box3; triangles: number } {
  const box = new THREE.Box3();
  let triangles = 0;
  for (const mesh of meshes) {
    mesh.geometry.computeBoundingBox();
    if (mesh.geometry.boundingBox)
      box.union(mesh.geometry.boundingBox.clone().applyMatrix4(mesh.matrixWorld));
    triangles += mesh.geometry.index
      ? mesh.geometry.index.count / 3
      : mesh.geometry.getAttribute("position").count / 3;
  }
  if (box.isEmpty())
    box.setFromCenterAndSize(new THREE.Vector3(), new THREE.Vector3(100, 100, 100));
  return { box, triangles: Math.round(triangles) };
}

function boundsFromBox(box: THREE.Box3): ViewBounds {
  return {
    center: box.getCenter(new THREE.Vector3()),
    span: Math.max(...box.getSize(new THREE.Vector3()).toArray(), 100),
  };
}

function applyCamera(
  camera: THREE.PerspectiveCamera,
  controls: OrbitControls,
  bounds: ViewBounds,
  preset: string,
) {
  const { center, span } = bounds;
  controls.target.copy(center);
  camera.up.set(0, 0, 1);
  if (preset === "front") camera.position.set(center.x, center.y - span * 1.8, center.z);
  else if (preset === "side") camera.position.set(center.x + span * 1.8, center.y, center.z);
  else if (preset === "top") {
    camera.up.set(0, 1, 0);
    camera.position.set(center.x, center.y, center.z + span * 1.8);
  } else
    camera.position.set(center.x + span * 0.95, center.y - span * 0.95, center.z + span * 0.72);
  camera.lookAt(center);
  controls.update();
}
