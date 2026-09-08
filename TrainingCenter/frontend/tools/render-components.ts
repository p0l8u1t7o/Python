import * as THREE from 'three';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';
import { RoomEnvironment } from 'three/addons/environments/RoomEnvironment.js';
import { prepareModel, disposeModelMaterials, orientComponentModel } from '../src/three/modelMaterials';

// Build-time renderer: one WebGL context renders every icon sequentially.
const renderer = new THREE.WebGLRenderer({ antialias: true, preserveDrawingBuffer: true });
renderer.setSize(640, 480);
renderer.setPixelRatio(1);
renderer.toneMapping = THREE.ACESFilmicToneMapping;
renderer.toneMappingExposure = 1.2;
renderer.shadowMap.enabled = true;
renderer.shadowMap.type = THREE.PCFSoftShadowMap;
document.body.appendChild(renderer.domElement);
const scene = new THREE.Scene();
scene.background = new THREE.Color('#e8edf2');
const pmrem = new THREE.PMREMGenerator(renderer);
const room = new RoomEnvironment();
scene.environment = pmrem.fromScene(room, 0.04).texture;
room.dispose();
pmrem.dispose();
scene.add(new THREE.HemisphereLight('#ffffff', '#8b97a4', 2));
const light = new THREE.DirectionalLight('#fff5e9', 4);
light.position.set(-3, 5, 4);
light.castShadow = true;
light.shadow.mapSize.set(2048, 2048);
Object.assign(light.shadow.camera, { left: -2, right: 2, top: 2, bottom: -2, near: 0.1, far: 15 });
light.shadow.bias = -0.0003;
light.shadow.normalBias = 0.015;
scene.add(light);
const fill = new THREE.DirectionalLight('#d9ecff', 2);
fill.position.set(3, 2, -2);
scene.add(fill);
const floor = new THREE.Mesh(new THREE.PlaneGeometry(200, 200), new THREE.MeshStandardMaterial({ color: '#e8edf2', roughness: 1, metalness: 0 }));
floor.rotation.x = -Math.PI / 2;
floor.position.y = -0.005;
floor.receiveShadow = true;
scene.add(floor);
const camera = new THREE.OrthographicCamera(-1.5, 1.5, 1.125, -1.125, 0.01, 50);
const loader = new GLTFLoader();
let current: THREE.Object3D | undefined;

async function renderModel(url: string) {
  if (current) {
    scene.remove(current);
    disposeModelMaterials(current);
    // This offline loader owns its geometry; unlike useGLTF, it has no shared cache.
    current.traverse(o => { const mesh = o as THREE.Mesh; if (mesh.isMesh) mesh.geometry.dispose(); });
  }
  const gltf = await loader.loadAsync(url);
  const model = orientComponentModel(prepareModel(gltf.scene), url);
  const bounds = new THREE.Box3().setFromObject(model);
  const center = bounds.getCenter(new THREE.Vector3());
  const size = bounds.getSize(new THREE.Vector3());
  const scale = 1.65 / Math.max(size.x, size.y, size.z);
  model.scale.multiplyScalar(scale);
  model.position.set(-center.x * scale, -bounds.min.y * scale, -center.z * scale);
  scene.add(model);
  current = model;
  const target = new THREE.Vector3(0, size.y * scale * 0.48, 0);
  camera.position.copy(target).add(new THREE.Vector3(3, 2.2, 3.6));
  camera.lookAt(target);
  camera.updateMatrixWorld();
  renderer.render(scene, camera);
  const triangles = renderer.info.render.triangles;
  gltf.scene.traverse(o => { const m = o as THREE.Mesh; if (m.isMesh) (Array.isArray(m.material) ? m.material : [m.material]).forEach(mat => mat.dispose()); });
  return { triangles, width: 640, height: 480 };
}

Object.assign(window, { renderModel });
