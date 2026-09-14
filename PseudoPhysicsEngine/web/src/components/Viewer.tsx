import { useEffect, useRef, useState } from "react";
import * as THREE from "three";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";
import { GLTFLoader } from "three/examples/jsm/loaders/GLTFLoader.js";
import type { Check, Timeline } from "../types";
import { applyTimeline, captureRestTransforms, type RestTransforms } from "../viewer-core";

export type { Check } from "../types";

type ViewBounds = { center: THREE.Vector3; span: number };
type Selection = {
  name: string;
  station: string;
  trust: string;
  vendor: string;
  position: THREE.Vector3;
};

export function Viewer({
  projectId,
  version,
  overlayVersion,
  checks = [],
  focusedCheck,
  sceneUrl,
  timelineUrl,
  initialTime = 0,
  initialCamera = "iso",
  snapshotMode = false,
  onCheckSelect,
  onChangeRequest,
}: {
  projectId?: string;
  version?: string;
  overlayVersion?: string;
  checks?: Check[];
  focusedCheck?: Check;
  sceneUrl?: string;
  timelineUrl?: string;
  initialTime?: number;
  initialCamera?: string;
  snapshotMode?: boolean;
  onCheckSelect?: (check: Check) => void;
  onChangeRequest?: (object: string, time: number, instruction: string) => void;
}) {
  const host = useRef<HTMLDivElement>(null);
  const modelRef = useRef<THREE.Object3D>();
  const timelineRef = useRef<Timeline>();
  const restRef = useRef<RestTransforms>(new Map());
  const cameraRef = useRef<THREE.PerspectiveCamera>();
  const controlsRef = useRef<OrbitControls>();
  const boundsRef = useRef<ViewBounds>();
  const stationBoundsRef = useRef<Map<string, ViewBounds>>(new Map());
  const materialColorsRef = useRef<Map<THREE.MeshStandardMaterial, THREE.Color>>(new Map());
  const materialEmissiveRef = useRef<Map<THREE.MeshStandardMaterial, THREE.Color>>(new Map());
  const [time, setTime] = useState(initialTime);
  const [duration, setDuration] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [speed, setSpeed] = useState(1);
  const [collision, setCollision] = useState(false);
  const [trustTint, setTrustTint] = useState(true);
  const [error, setError] = useState<string>();
  const [selection, setSelection] = useState<Selection>();
  const [localCheck, setLocalCheck] = useState<Check>();
  const [menu, setMenu] = useState<{ x: number; y: number; object: string }>();
  const [loaded, setLoaded] = useState(0);
  const activeCheck = focusedCheck ?? localCheck;

  useEffect(() => setTime(initialTime), [initialTime]);

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
        materialColorsRef.current.clear();
        materialEmissiveRef.current.clear();
        gltf.scene.traverse((object) => {
          if (object.name === "collision") object.visible = false;
          if (object instanceof THREE.Mesh) {
            const wasArray = Array.isArray(object.material);
            const sourceMaterials = (
              wasArray ? object.material : [object.material]
            ) as THREE.Material[];
            const materials = sourceMaterials.map(
              (material: THREE.Material) => material.clone() as THREE.MeshStandardMaterial,
            );
            object.material = wasArray ? materials : materials[0];
            for (const material of materials) {
              if (!(material instanceof THREE.MeshStandardMaterial)) continue;
              materialColorsRef.current.set(material, material.color.clone());
              materialEmissiveRef.current.set(material, material.emissive.clone());
            }
          }
        });
        modelRef.current = gltf.scene;
        timelineRef.current = timeline;
        restRef.current = captureRestTransforms(gltf.scene);
        setDuration(timeline.duration_s);
        applyTimeline(gltf.scene, timeline, initialTime, restRef.current);
        scene.add(gltf.scene);
        if (overlayVersion && projectId && overlayVersion !== version) {
          const overlay = await loader.loadAsync(
            `/api/projects/${encodeURIComponent(projectId)}/versions/${overlayVersion}/scene.glb`,
          );
          overlay.scene.traverse((object) => {
            object.renderOrder = 2;
            if (object instanceof THREE.Mesh)
              object.material = new THREE.MeshBasicMaterial({
                color: 0x63b3ed,
                wireframe: true,
                transparent: true,
                opacity: 0.5,
              });
          });
          scene.add(overlay.scene);
        }
        const globalBounds = boxBounds(new THREE.Box3().setFromObject(gltf.scene));
        boundsRef.current = globalBounds;
        stationBoundsRef.current = stationBounds(gltf.scene);
        camera.near = Math.max(1, globalBounds.span / 10000);
        camera.far = globalBounds.span * 10;
        camera.updateProjectionMatrix();
        applyCameraPreset(
          camera,
          controls,
          stationBoundsRef.current.get(initialCamera) ?? globalBounds,
          initialCamera,
        );
        setLoaded((value) => value + 1);
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
      const node = semanticNode(hit.object, modelRef.current);
      const metadata = inheritedMetadata(node);
      setSelection({
        name: node.name || "unknown",
        station: String(metadata.station ?? "—"),
        trust: String(metadata.trust ?? "—"),
        vendor: String(metadata.vendor ?? "—"),
        position: node.getWorldPosition(new THREE.Vector3()),
      });
      if (event.type === "contextmenu") {
        event.preventDefault();
        setMenu({
          x: Math.min(event.clientX - rect.left, rect.width - 210),
          y: Math.min(event.clientY - rect.top, rect.height - 220),
          object: node.name,
        });
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
      modelRef.current = undefined;
      timelineRef.current = undefined;
    };
  }, [
    initialCamera,
    initialTime,
    projectId,
    sceneUrl,
    snapshotMode,
    timelineUrl,
    version,
    overlayVersion,
  ]);

  useEffect(() => {
    modelRef.current?.traverse((object) => {
      if (object.name === "collision") object.visible = collision;
    });
  }, [collision, loaded]);

  useEffect(() => {
    modelRef.current?.traverse((object) => {
      if (!(object instanceof THREE.Mesh)) return;
      for (const material of standardMaterials(object)) {
        const original = materialColorsRef.current.get(material);
        if (original) material.color.copy(original);
        if (trustTint && inheritedMetadata(object).trust === "inferred")
          material.color.lerp(new THREE.Color(0xf6ad55), 0.35);
      }
    });
  }, [trustTint, loaded]);

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
    if (model && timeline) {
      applyTimeline(model, timeline, time, restRef.current);
      setSelection((current) => {
        const node = current && model.getObjectByName(current.name);
        return current && node
          ? { ...current, position: node.getWorldPosition(new THREE.Vector3()) }
          : current;
      });
    }
  }, [time, loaded]);

  useEffect(() => {
    if (typeof activeCheck?.t === "number") setTime(activeCheck.t);
    for (const [material, color] of materialEmissiveRef.current) {
      material.emissive.copy(color);
      material.emissiveIntensity = 1;
    }
    const model = modelRef.current;
    if (!model || !activeCheck?.objects) return;
    for (const name of activeCheck.objects) {
      model.getObjectByName(name)?.traverse((object) => {
        if (!(object instanceof THREE.Mesh)) return;
        for (const material of standardMaterials(object)) {
          material.emissive.set(0xff1f32);
          material.emissiveIntensity = 1.4;
        }
      });
    }
  }, [activeCheck, loaded]);

  const camera = (preset: string) => {
    if (!cameraRef.current || !controlsRef.current || !boundsRef.current) return;
    applyCameraPreset(
      cameraRef.current,
      controlsRef.current,
      stationBoundsRef.current.get(preset) ?? boundsRef.current,
      preset,
    );
  };
  const selectCheck = (check: Check) => {
    setLocalCheck(check);
    if (typeof check.t === "number") setTime(check.t);
    onCheckSelect?.(check);
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
        {timelineRef.current?.stations.map((station) => (
          <button key={station.id} onClick={() => camera(station.id)}>
            {station.id}
          </button>
        ))}
        <button
          className={collision ? "active" : ""}
          onClick={() => setCollision((value) => !value)}
        >
          碰撞體
        </button>
        <button
          className={trustTint ? "active-trust" : ""}
          title="琥珀色為 inferred"
          onClick={() => setTrustTint((value) => !value)}
        >
          信任色
        </button>
      </div>
      {selection && (
        <div className="selection-card">
          <b>{selection.name}</b>
          <span>站別：{selection.station}</span>
          <span>信任：{selection.trust}</span>
          <span>供應商：{selection.vendor}</span>
          <span>
            世界座標：{selection.position.x.toFixed(1)}, {selection.position.y.toFixed(1)},{" "}
            {selection.position.z.toFixed(1)} mm
          </span>
        </div>
      )}
      {menu && (
        <div
          className="context-menu"
          style={{ left: menu.x, top: menu.y }}
          onClick={(event) => event.stopPropagation()}
        >
          <b>{menu.object}</b>
          <button
            onClick={() => {
              const raw = prompt("沿逼近方向後退距離（mm）");
              const distance = raw === null ? Number.NaN : Number(raw);
              if (Number.isFinite(distance) && distance > 0)
                onChangeRequest?.(menu.object, time, `後退 ${String(distance)} mm`);
              setMenu(undefined);
            }}
          >
            沿逼近方向後退…
          </button>
          <button
            onClick={() => {
              const text = prompt("請描述這裡的問題");
              if (text) onChangeRequest?.(menu.object, time, text);
              setMenu(undefined);
            }}
          >
            這裡有問題
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
        <div className="timeline-track">
          <div className="station-segments">
            {timelineRef.current?.stations.map((station) => (
              <button
                key={station.id}
                style={{
                  left: `${(station.t0 / Math.max(duration, Number.EPSILON)) * 100}%`,
                  width: `${((station.t1 - station.t0) / Math.max(duration, Number.EPSILON)) * 100}%`,
                }}
                title={`跳到 ${station.id} ${station.t0.toFixed(2)} s`}
                onClick={() => setTime(station.t0)}
              >
                {station.id}
              </button>
            ))}
          </div>
          <div className="timeline-checks">
            {checks
              .filter(
                (item) => item.severity !== "green" && typeof item.t === "number" && duration > 0,
              )
              .map((item) => (
                <button
                  key={item.id}
                  className={item.severity}
                  style={{ left: `${((item.t ?? 0) / duration) * 100}%` }}
                  title={`${item.id}：${item.detail ?? ""}`}
                  onClick={() => selectCheck(item)}
                />
              ))}
          </div>
          <input
            aria-label="動畫時間"
            type="range"
            min="0"
            max={duration || 1}
            step="0.02"
            value={time}
            onChange={(event) => setTime(Number(event.target.value))}
          />
        </div>
        <select value={speed} onChange={(event) => setSpeed(Number(event.target.value))}>
          {[0.25, 0.5, 1, 2, 4].map((value) => (
            <option key={value} value={value}>
              {value}×
            </option>
          ))}
        </select>
        <b>
          {time.toFixed(1)} / {duration.toFixed(1)} s
        </b>
      </div>
    </div>
  );
}

function standardMaterials(object: THREE.Mesh): THREE.MeshStandardMaterial[] {
  const materials = Array.isArray(object.material) ? object.material : [object.material];
  return materials.filter(
    (material): material is THREE.MeshStandardMaterial =>
      material instanceof THREE.MeshStandardMaterial,
  );
}

function semanticNode(object: THREE.Object3D, root?: THREE.Object3D) {
  let current: THREE.Object3D | null = object;
  while (current && current !== root) {
    if (current.name && !["visual", "collision"].includes(current.name)) return current;
    current = current.parent;
  }
  return object;
}

function inheritedMetadata(object: THREE.Object3D): Record<string, unknown> {
  const metadata: Record<string, unknown> = {};
  let current: THREE.Object3D | null = object;
  while (current) {
    for (const key of ["station", "trust", "vendor"])
      if (metadata[key] === undefined && current.userData[key] != null)
        metadata[key] = current.userData[key];
    current = current.parent;
  }
  return metadata;
}

function stationBounds(root: THREE.Object3D) {
  const boxes = new Map<string, THREE.Box3>();
  for (const module of root.children) {
    const station = module.userData.station;
    if (!station) continue;
    const moduleBox = new THREE.Box3().setFromObject(module);
    const existing = boxes.get(String(station));
    if (existing) existing.union(moduleBox);
    else boxes.set(String(station), moduleBox);
  }
  return new Map([...boxes].map(([name, box]) => [name, boxBounds(box)]));
}

function boxBounds(box: THREE.Box3): ViewBounds {
  return {
    center: box.getCenter(new THREE.Vector3()),
    span: Math.max(...box.getSize(new THREE.Vector3()).toArray(), 100),
  };
}

function applyCameraPreset(
  camera: THREE.PerspectiveCamera,
  controls: OrbitControls,
  bounds: ViewBounds,
  preset: string,
) {
  const { center, span } = bounds;
  controls.target.copy(center);
  if (preset.toLowerCase() === "top") {
    camera.up.set(0, 1, 0);
    camera.position.set(center.x, center.y, center.z + span * 1.55);
  } else {
    camera.up.set(0, 0, 1);
    const isOverview = preset.toLowerCase() === "iso";
    const factor = isOverview ? 0.9 : 2.2;
    camera.position.set(
      center.x + span * factor,
      center.y - span * factor,
      center.z + span * (isOverview ? 0.68 : 1.2),
    );
  }
  camera.lookAt(center);
  controls.update();
}
