import * as THREE from "three";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";
import { GLTFLoader } from "three/examples/jsm/loaders/GLTFLoader.js";
import { mergeVertices } from "three/examples/jsm/utils/BufferGeometryUtils.js";
import type { Check, Timeline } from "./types";
import { applyTimeline, captureRestTransforms } from "./viewer-core";

declare global {
  interface Window {
    CELLFORGE_DATA: {
      scene: string;
      timeline: Timeline;
      checks: { items: Check[] };
      title: string;
    };
    cellforgeOfflineReady?: boolean;
  }
}

const data = window.CELLFORGE_DATA;
const canvas = document.querySelector<HTMLCanvasElement>("#view")!;
const renderer = new THREE.WebGLRenderer({ canvas, antialias: true });
renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
renderer.outputColorSpace = THREE.SRGBColorSpace;
renderer.setClearColor(0x0b1118);
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
const controls = new OrbitControls(camera, canvas);
controls.enableDamping = true;
let model: THREE.Object3D;
let rest = captureRestTransforms(new THREE.Group());
let time = 0;
let speed = 1;
let playing = false;
let previous = performance.now();

function resize() {
  const width = canvas.clientWidth;
  const height = Math.max(canvas.clientHeight, 1);
  renderer.setSize(width, height, false);
  camera.aspect = width / height;
  camera.updateProjectionMatrix();
}
new ResizeObserver(resize).observe(canvas);
resize();

const binary = atob(data.scene);
const bytes = new Uint8Array(binary.length);
for (let index = 0; index < binary.length; index += 1) bytes[index] = binary.charCodeAt(index);
new GLTFLoader().parse(
  bytes.buffer,
  "",
  (gltf) => {
    model = gltf.scene;
    model.traverse((object) => {
      if (object.userData.hidden === true) object.visible = false;
      if (object instanceof THREE.Mesh) {
        const wasArray = Array.isArray(object.material);
        const source = (wasArray ? object.material : [object.material]) as THREE.Material[];
        const materials = source.map((material: THREE.Material) => material.clone());
        object.material = wasArray ? materials : materials[0];
      }
    });
    addTrustOutlines(model);
    rest = captureRestTransforms(model);
    applyTimeline(model, data.timeline, time, rest);
    scene.add(model);
    const bounds = new THREE.Box3().setFromObject(model);
    const center = bounds.getCenter(new THREE.Vector3());
    const span = Math.max(...bounds.getSize(new THREE.Vector3()).toArray(), 100);
    controls.target.copy(center);
    camera.position.set(center.x + span * 0.9, center.y - span * 0.9, center.z + span * 0.68);
    camera.near = Math.max(1, span / 10000);
    camera.far = span * 10;
    camera.lookAt(center);
    camera.updateProjectionMatrix();
    controls.update();
    window.cellforgeOfflineReady = true;
  },
  (error) => {
    document.querySelector("#status")!.textContent = `3D 載入失敗：${String(error)}`;
  },
);

const slider = document.querySelector<HTMLInputElement>("#time")!;
const timeLabel = document.querySelector<HTMLElement>("#time-label")!;
slider.max = String(data.timeline.duration_s);
slider.addEventListener("input", () => {
  time = Number(slider.value);
  updateTime();
});
document.querySelector("#play")!.addEventListener("click", () => {
  playing = !playing;
  document.querySelector("#play")!.textContent = playing ? "暫停" : "播放";
});
document.querySelector<HTMLSelectElement>("#speed")!.addEventListener("change", (event) => {
  speed = Number((event.target as HTMLSelectElement).value);
});

function updateTime() {
  slider.value = String(time);
  timeLabel.textContent = `${time.toFixed(1)} / ${data.timeline.duration_s.toFixed(1)} s`;
  if (model) applyTimeline(model, data.timeline, time, rest);
}

function highlight(check: Check) {
  if (!model) return;
  model.traverse((object) => {
    if (!(object instanceof THREE.Mesh)) return;
    const materials = Array.isArray(object.material) ? object.material : [object.material];
    for (const material of materials)
      if (material instanceof THREE.MeshStandardMaterial) {
        material.emissive.set(0x000000);
        material.emissiveIntensity = 1;
      }
  });
  for (const name of check.objects ?? []) {
    model.getObjectByName(name)?.traverse((object) => {
      if (!(object instanceof THREE.Mesh)) return;
      const materials = Array.isArray(object.material) ? object.material : [object.material];
      for (const material of materials)
        if (material instanceof THREE.MeshStandardMaterial) {
          material.emissive.set(0xff1f32);
          material.emissiveIntensity = 1.4;
        }
    });
  }
}

function inheritedTrust(object: THREE.Object3D): unknown {
  let current: THREE.Object3D | null = object;
  while (current) {
    if (current.userData.trust != null) return current.userData.trust;
    current = current.parent;
  }
  return undefined;
}

function addTrustOutlines(root: THREE.Object3D) {
  const meshes: THREE.Mesh[] = [];
  root.traverse((object) => {
    if (
      object instanceof THREE.Mesh &&
      inheritedTrust(object) === "inferred" &&
      !hasCollisionAncestor(object)
    )
      meshes.push(object);
  });
  for (const mesh of meshes) {
    const positions = new THREE.BufferGeometry();
    positions.setAttribute("position", mesh.geometry.getAttribute("position").clone());
    if (mesh.geometry.index) positions.setIndex(mesh.geometry.index.clone());
    const outline = new THREE.LineSegments(
      new THREE.EdgesGeometry(mergeVertices(positions), 35),
      new THREE.LineBasicMaterial({ color: 0xf6ad55, transparent: true, opacity: 0.5 }),
    );
    outline.name = "__cellforge_trust_outline";
    outline.raycast = () => undefined;
    outline.renderOrder = 1;
    mesh.add(outline);
  }
}

function hasCollisionAncestor(object: THREE.Object3D) {
  let current: THREE.Object3D | null = object;
  while (current) {
    if (current.userData.hidden === true) return true;
    current = current.parent;
  }
  return false;
}

const segments = document.querySelector<HTMLElement>("#segments")!;
for (const station of data.timeline.stations) {
  const button = document.createElement("button");
  button.textContent = station.id;
  button.style.left = `${(station.t0 / data.timeline.duration_s) * 100}%`;
  button.style.width = `${((station.t1 - station.t0) / data.timeline.duration_s) * 100}%`;
  button.onclick = () => {
    time = station.t0;
    updateTime();
  };
  segments.append(button);
}
const markers = document.querySelector<HTMLElement>("#markers")!;
const checkList = document.querySelector<HTMLElement>("#checks")!;
for (const check of data.checks.items) {
  if (check.severity !== "green" && typeof check.t === "number") {
    const marker = document.createElement("button");
    marker.className = check.severity;
    marker.title = `${check.id}: ${check.detail ?? ""}`;
    marker.style.left = `${(check.t / data.timeline.duration_s) * 100}%`;
    marker.onclick = () => {
      time = check.t ?? 0;
      updateTime();
      highlight(check);
    };
    markers.append(marker);
  }
  const row = document.createElement("button");
  row.className = `check ${check.severity}`;
  row.innerHTML = `<b>${check.id} · ${check.type}</b><span>${check.detail ?? ""}</span>`;
  row.onclick = () => {
    if (typeof check.t === "number") time = check.t;
    updateTime();
    highlight(check);
  };
  checkList.append(row);
}

function render(now: number) {
  if (playing && data.timeline.duration_s > 0) {
    time = (time + ((now - previous) / 1000) * speed) % data.timeline.duration_s;
    updateTime();
  }
  previous = now;
  controls.update();
  renderer.render(scene, camera);
  requestAnimationFrame(render);
}
updateTime();
requestAnimationFrame(render);
