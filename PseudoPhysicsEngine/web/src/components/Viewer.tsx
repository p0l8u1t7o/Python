import { useEffect, useRef, useState } from "react";
import * as THREE from "three";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";
import { GLTFLoader } from "three/examples/jsm/loaders/GLTFLoader.js";

type Timeline = {
  duration_s: number;
  stations: { id: string; name?: string; t0: number; t1: number }[];
  nodes: Record<string, { joints_deg?: number[][]; value_deg?: number[][]; value_mm?: number[][] }>;
};
export type Check = {
  id: string;
  severity: "red" | "yellow" | "green";
  type: string;
  t?: number;
  detail?: string;
  objects?: string[];
};

export function Viewer({
  projectId,
  version,
  overlayVersion,
  checks = [],
  sceneUrl,
  timelineUrl,
  initialTime = 0,
  initialCamera = "iso",
  snapshotMode = false,
  onChangeRequest,
}: {
  projectId?: string;
  version?: string;
  overlayVersion?: string;
  checks?: Check[];
  sceneUrl?: string;
  timelineUrl?: string;
  initialTime?: number;
  initialCamera?: string;
  snapshotMode?: boolean;
  onChangeRequest?: (object: string, time: number, instruction: string) => void;
}) {
  const host = useRef<HTMLDivElement>(null);
  const modelRef = useRef<THREE.Object3D>();
  const timelineRef = useRef<Timeline>();
  const cameraRef = useRef<THREE.PerspectiveCamera>();
  const controlsRef = useRef<OrbitControls>();
  const boundsRef = useRef<{ center: THREE.Vector3; span: number }>();
  const [time, setTime] = useState(initialTime);
  const [duration, setDuration] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [speed, setSpeed] = useState(1);
  const [collision, setCollision] = useState(false);
  const [error, setError] = useState<string>();
  const [selected, setSelected] = useState<string>();
  const [menu, setMenu] = useState<{ x: number; y: number; object: string }>();

  useEffect(() => {
    if (!host.current || (!version && !sceneUrl)) return;
    const container = host.current;
    const renderer = new THREE.WebGLRenderer({ antialias: true });
    renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
    renderer.outputColorSpace = THREE.SRGBColorSpace;
    renderer.setClearColor(0x0b1118);
    container.prepend(renderer.domElement);
    const scene = new THREE.Scene();
    scene.up.set(0, 0, 1);
    scene.add(new THREE.HemisphereLight(0xe6f1ff, 0x17212c, 2.4));
    const sun = new THREE.DirectionalLight(0xffffff, 2.8);
    sun.position.set(-4000, -4500, 7000);
    scene.add(sun);
    const grid = new THREE.GridHelper(10000, 40, 0x526072, 0x222e3a);
    grid.rotation.x = Math.PI / 2;
    scene.add(grid);
    const camera = new THREE.PerspectiveCamera(38, 1, 1, 50000);
    camera.up.set(0, 0, 1);
    const controls = new OrbitControls(camera, renderer.domElement);
    cameraRef.current = camera;
    controlsRef.current = controls;
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
    const base =
      projectId && version
        ? `/api/projects/${encodeURIComponent(projectId)}/versions/${version}`
        : "";
    const loader = new GLTFLoader();
    Promise.all([
      loader.loadAsync(sceneUrl ?? `${base}/scene.glb`),
      fetch(timelineUrl ?? `${base}/timeline.json`).then((response) => {
        if (!response.ok) throw new Error(`timeline HTTP ${response.status}`);
        return response.json() as Promise<Timeline>;
      }),
    ])
      .then(async ([gltf, timeline]) => {
        if (disposed) return;
        modelRef.current = gltf.scene;
        timelineRef.current = timeline;
        setDuration(timeline.duration_s);
        gltf.scene.traverse((object) => {
          if (object.name === "collision") object.visible = false;
          if (object.userData.trust === "inferred") tint(object, 0xf6ad55);
        });
        scene.add(gltf.scene);
        if (overlayVersion && projectId && overlayVersion !== version) {
          const overlay = await loader.loadAsync(
            `/api/projects/${encodeURIComponent(projectId)}/versions/${overlayVersion}/scene.glb`,
          );
          overlay.scene.traverse((object) => {
            object.renderOrder = 2;
            if (object instanceof THREE.Mesh) {
              const material = new THREE.MeshBasicMaterial({
                color: 0x63b3ed,
                wireframe: true,
                transparent: true,
                opacity: 0.5,
              });
              object.material = material;
            }
          });
          scene.add(overlay.scene);
        }
        const box = new THREE.Box3().setFromObject(gltf.scene);
        const center = box.getCenter(new THREE.Vector3());
        const span = Math.max(...box.getSize(new THREE.Vector3()).toArray());
        boundsRef.current = { center, span };
        camera.near = Math.max(1, span / 10000);
        camera.far = span * 10;
        camera.updateProjectionMatrix();
        applyCameraPreset(camera, controls, center, span, initialCamera);
        if (snapshotMode)
          requestAnimationFrame(
            () => ((window as Window & { cellforgeReady?: boolean }).cellforgeReady = true),
          );
      })
      .catch((reason) => setError(reason instanceof Error ? reason.message : String(reason)));
    const raycaster = new THREE.Raycaster();
    const pointer = new THREE.Vector2();
    const pick = (event: MouseEvent) => {
      const rect = renderer.domElement.getBoundingClientRect();
      pointer.set(
        ((event.clientX - rect.left) / rect.width) * 2 - 1,
        -((event.clientY - rect.top) / rect.height) * 2 + 1,
      );
      raycaster.setFromCamera(pointer, camera);
      const hit = raycaster.intersectObject(modelRef.current ?? scene, true)[0];
      if (!hit) return;
      const object = moduleName(hit.object);
      setSelected(object);
      if (event.type === "contextmenu") {
        event.preventDefault();
        setMenu({ x: event.clientX - rect.left, y: event.clientY - rect.top, object });
      }
    };
    renderer.domElement.addEventListener("click", pick);
    renderer.domElement.addEventListener("contextmenu", pick);
    let frame = 0;
    const render = () => {
      frame = requestAnimationFrame(render);
      controls.update();
      renderer.render(scene, camera);
    };
    render();
    return () => {
      disposed = true;
      cancelAnimationFrame(frame);
      observer.disconnect();
      renderer.domElement.removeEventListener("click", pick);
      renderer.domElement.removeEventListener("contextmenu", pick);
      controls.dispose();
      renderer.dispose();
      renderer.domElement.remove();
    };
  }, [initialCamera, projectId, sceneUrl, snapshotMode, timelineUrl, version, overlayVersion]);

  useEffect(() => {
    modelRef.current?.traverse((object) => {
      if (object.name === "collision") object.visible = collision;
    });
  }, [collision]);

  useEffect(() => {
    if (!playing || !duration) return;
    let previous = performance.now();
    let frame = 0;
    const tick = (now: number) => {
      setTime((value) => (value + ((now - previous) / 1000) * speed) % duration);
      previous = now;
      frame = requestAnimationFrame(tick);
    };
    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  }, [playing, duration, speed]);

  useEffect(() => {
    const model = modelRef.current;
    const timeline = timelineRef.current;
    if (!model || !timeline) return;
    for (const [id, track] of Object.entries(timeline.nodes)) {
      const object = model.getObjectByName(id.split(".")[0]);
      if (!object) continue;
      if (track.joints_deg?.length)
        object.rotation.z = THREE.MathUtils.degToRad(interpolate(track.joints_deg, time)[0]);
      if (track.value_deg?.length)
        object.rotation.x = THREE.MathUtils.degToRad(interpolate(track.value_deg, time)[0]);
      if (track.value_mm?.length) object.position.z = interpolate(track.value_mm, time)[0];
    }
  }, [time]);

  const camera = (preset: string) => {
    if (cameraRef.current && controlsRef.current && boundsRef.current)
      applyCameraPreset(
        cameraRef.current,
        controlsRef.current,
        boundsRef.current.center,
        boundsRef.current.span,
        preset,
      );
  };
  return (
    <div className="viewer" ref={host} onClick={() => menu && setMenu(undefined)}>
      {error && (
        <div className="viewer-message error-card">
          3D 載入失敗：{error}
          <br />
          <button onClick={() => location.reload()}>重新載入</button>
        </div>
      )}
      {!version && !sceneUrl && <div className="viewer-message">尚無可檢視版本</div>}
      <div className="viewer-tools">
        <button onClick={() => camera("iso")}>ISO</button>
        <button onClick={() => camera("top")}>俯視</button>
        <button
          className={collision ? "active" : ""}
          onClick={() => setCollision((value) => !value)}
        >
          碰撞體
        </button>
        <button title="琥珀色為 inferred，藍色為 confirmed">信任色</button>
      </div>
      <div className="check-markers">
        {checks
          .filter((item) => item.severity !== "green")
          .map((item) => (
            <button
              key={item.id}
              className={item.severity}
              title={item.detail}
              onClick={() => setTime(item.t ?? 0)}
            >
              {item.id}
            </button>
          ))}
      </div>
      {selected && <div className="selection-label">已選取：{selected}</div>}
      {menu && (
        <div
          className="context-menu"
          style={{ left: menu.x, top: menu.y }}
          onClick={(event) => event.stopPropagation()}
        >
          <b>{menu.object}</b>
          <button
            onClick={() => {
              onChangeRequest?.(menu.object, time, "法蘭退 20 mm");
              setMenu(undefined);
            }}
          >
            法蘭退 20 mm
          </button>
          <button
            onClick={() => {
              const text = prompt("修改指令");
              if (text) onChangeRequest?.(menu.object, time, text);
              setMenu(undefined);
            }}
          >
            其他修改…
          </button>
        </div>
      )}
      <div className="timeline">
        <button className="play" onClick={() => setPlaying((value) => !value)}>
          {playing ? "暫停" : "播放"}
        </button>
        <input
          aria-label="動畫時間"
          type="range"
          min="0"
          max={duration || 1}
          step="0.02"
          value={time}
          onChange={(event) => setTime(Number(event.target.value))}
        />
        <select value={speed} onChange={(event) => setSpeed(Number(event.target.value))}>
          <option value={0.5}>0.5×</option>
          <option value={1}>1×</option>
          <option value={2}>2×</option>
        </select>
        <b>
          {time.toFixed(1)} / {duration.toFixed(1)} s
        </b>
      </div>
    </div>
  );
}

function tint(object: THREE.Object3D, color: number) {
  if (!(object instanceof THREE.Mesh)) return;
  const material = Array.isArray(object.material) ? object.material[0] : object.material;
  if (material instanceof THREE.MeshStandardMaterial)
    material.color.lerp(new THREE.Color(color), 0.35);
}
function moduleName(object: THREE.Object3D) {
  let current: THREE.Object3D | null = object;
  while (current?.parent && current.parent.name) current = current.parent;
  return current?.name || object.name || "unknown";
}
function applyCameraPreset(
  camera: THREE.PerspectiveCamera,
  controls: OrbitControls,
  center: THREE.Vector3,
  span: number,
  preset: string,
) {
  controls.target.copy(center);
  if (preset.toLowerCase() === "top") {
    camera.up.set(0, 1, 0);
    camera.position.set(center.x, center.y, center.z + span * 1.55);
  } else {
    camera.up.set(0, 0, 1);
    camera.position.set(center.x + span * 0.75, center.y - span * 0.9, center.z + span * 0.62);
  }
  camera.lookAt(center);
  controls.update();
}
function interpolate(keys: number[][], time: number): number[] {
  if (time <= keys[0][0]) return keys[0].slice(1);
  for (let i = 1; i < keys.length; i += 1)
    if (time <= keys[i][0]) {
      const a = keys[i - 1],
        b = keys[i];
      const mix = (time - a[0]) / Math.max(b[0] - a[0], 1e-9);
      return a.slice(1).map((value, j) => THREE.MathUtils.lerp(value, b[j + 1], mix));
    }
  return keys.at(-1)!.slice(1);
}
