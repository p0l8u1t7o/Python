import * as THREE from "three";
import { GLTFLoader } from "three/addons/loaders/GLTFLoader.js";
import { STLLoader } from "three/addons/loaders/STLLoader.js";
import { OBJLoader } from "three/addons/loaders/OBJLoader.js";
import { mergeGeometries } from "three/addons/utils/BufferGeometryUtils.js";
import { occtScene } from "./cad-geometry.js";
import { repairNames } from "../project/names.js";

export function normalizeGltf(gltf) {
  const groups = [];
  gltf.scene.traverse((o) => {
    if (
      o.isGroup &&
      gltf.parser.associations.get(o)?.meshes !== undefined &&
      o.children.length &&
      o.children.every((c) => c.isMesh && !c.isSkinnedMesh)
    )
      groups.push(o);
  });
  for (const group of groups) {
    const geometries = group.children.map((c) => {
      c.updateMatrix();
      const g = c.geometry.clone();
      g.applyMatrix4(c.matrix);
      return g;
    });
    const merged = mergeGeometries(geometries, true);
    geometries.forEach((g) => g.dispose());
    if (!merged) continue;
    const material = group.children.flatMap((c) =>
      Array.isArray(c.material) ? c.material : [c.material],
    );
    const mesh = new THREE.Mesh(merged, material);
    mesh.name = group.name;
    mesh.userData = { ...group.userData };
    group.clear();
    group.add(mesh);
  }
  return repairNames(gltf.scene);
}
export const formats = [
  "step",
  "stp",
  "igs",
  "iges",
  "brep",
  "stl",
  "obj",
  "glb",
];
export async function importModel(file) {
  const ext = file.name.split(".").pop().toLowerCase();
  if (file.size > 200 * 1024 * 1024)
    throw new Error("單檔上限 200 MB；大型設備請按站別輸出。");
  const buffer = await file.arrayBuffer();
  let root;
  if (["step", "stp", "igs", "iges", "brep"].includes(ext)) {
    const result = await new Promise((resolve, reject) => {
      const worker = new Worker("/cad-worker.js");
      const timeout = setTimeout(() => {
        worker.terminate();
        reject(
          new Error("CAD 解析超過 180 秒，請降低模型複雜度或按站別匯出。"),
        );
      }, 180000);
      const end = () => {
        clearTimeout(timeout);
        worker.terminate();
      };
      worker.onmessage = ({ data }) => {
        end();
        data.error ? reject(new Error(data.error)) : resolve(data.result);
      };
      worker.onerror = (e) => {
        end();
        reject(new Error(e.message || "CAD 解析器載入失敗。"));
      };
      worker.postMessage({ buffer, ext }, [buffer]);
    });
    root = occtScene(result);
  } else if (ext === "glb")
    root = normalizeGltf(await new GLTFLoader().parseAsync(buffer, ""));
  else if (ext === "stl") {
    root = new THREE.Group();
    root.add(
      new THREE.Mesh(
        new STLLoader().parse(buffer),
        new THREE.MeshStandardMaterial({
          color: "#b1c3ce",
          metalness: 0.3,
          roughness: 0.45,
        }),
      ),
    );
    root.rotation.x = -Math.PI / 2;
  } else if (ext === "obj")
    root = new OBJLoader().parse(new TextDecoder().decode(buffer));
  else
    throw new Error(
      "此格式需要轉換成 STEP 或 GLB；SolidWorks 原生檔可使用本機轉換服務。",
    );
  return repairNames(root);
}
// 模型哪一個軸朝上：CAD 常見 Y 朝上（SolidWorks 預設）或 Z 朝上（以上視基準面建模）
export const UP_AXES = ["y", "z", "x", "-y", "-z", "-x"];
const UP_ROTATION = {
  y: [0, 0, 0],
  "-y": [Math.PI, 0, 0],
  z: [-Math.PI / 2, 0, 0],
  "-z": [Math.PI / 2, 0, 0],
  x: [0, 0, Math.PI / 2],
  "-x": [0, 0, -Math.PI / 2],
};
/** 旋轉根節點，讓指定的模型軸朝上（+Y）。設定絕對旋轉，重複呼叫不會累加。 */
export function orientRoot(root, up = "y") {
  const axis = UP_ROTATION[up] ? up : "y";
  root.rotation.set(...UP_ROTATION[axis]);
  root.userData.up = axis;
  root.updateMatrixWorld(true);
  return root;
}
export async function loadSample(url, upAxis = "z") {
  const gltf = await new GLTFLoader().loadAsync(url);
  return orientRoot(normalizeGltf(gltf), upAxis);
}
export function describeParts(root, stationId) {
  const parts = [];
  root.updateMatrixWorld(true);
  root.traverse((o) => {
    if (o.isMesh) {
      const id = `${stationId}-p${parts.length}`;
      o.userData.partId = id;
      parts.push({
        id,
        name: o.name || `零件 ${parts.length + 1}`,
        group: o.parent?.name || "未分組",
        center: new THREE.Box3()
          .setFromObject(o)
          .getCenter(new THREE.Vector3())
          .toArray(),
      });
    }
  });
  return parts.sort((a, b) => a.center[1] - b.center[1]);
}
