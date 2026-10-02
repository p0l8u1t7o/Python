import * as THREE from "three";

export const TESSELLATION = Object.freeze({
  linearUnit: "millimeter",
  linearDeflectionType: "absolute_value",
  linearDeflection: 0.08,
  angularDeflection: 0.22,
});

export function occtMesh(source, index) {
  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute(
    "position",
    new THREE.Float32BufferAttribute(source.attributes.position.array, 3),
  );
  if (source.attributes.normal)
    geometry.setAttribute(
      "normal",
      new THREE.Float32BufferAttribute(source.attributes.normal.array, 3),
    );
  geometry.setIndex(Array.from(source.index.array));
  if (!source.attributes.normal) geometry.computeVertexNormals();
  const materials = [],
    palette = new Map();
  const materialIndex = (color) => {
    const rgb = color || source.color || [0.58, 0.64, 0.68];
    const key = rgb.join(",");
    if (!palette.has(key)) {
      const material = new THREE.MeshStandardMaterial({
        color: new THREE.Color(...rgb),
        metalness: 0.6,
        roughness: 0.3,
      });
      material.userData.materialSource =
        color || source.color ? "cad-color" : "unspecified";
      palette.set(key, materials.length);
      materials.push(material);
    }
    return palette.get(key);
  };
  const base = materialIndex(source.color);
  const total = geometry.index.count / 3;
  const faces = [...(source.brep_faces || [])]
    .filter(
      (f) =>
        Number.isInteger(f.first) &&
        Number.isInteger(f.last) &&
        f.first >= 0 &&
        f.last >= f.first &&
        f.last < total,
    )
    .sort((a, b) => a.first - b.first);
  let triangle = 0;
  function group(start, count, material) {
    const last = geometry.groups.at(-1);
    if (
      last &&
      last.materialIndex === material &&
      last.start + last.count === start
    )
      last.count += count;
    else if (count > 0) geometry.addGroup(start, count, material);
  }
  for (const face of faces) {
    if (face.first < triangle) continue;
    group(triangle * 3, (face.first - triangle) * 3, base);
    group(
      face.first * 3,
      (face.last - face.first + 1) * 3,
      materialIndex(face.color),
    );
    triangle = face.last + 1;
  }
  group(triangle * 3, (total - triangle) * 3, base);
  const mesh = new THREE.Mesh(
    geometry,
    materials.length === 1 ? materials[0] : materials,
  );
  mesh.name = source.name || `Part ${index + 1}`;
  mesh.userData.sourceIndex = index;
  return mesh;
}

export function occtScene(result) {
  if (!result.success || !result.meshes?.length)
    throw new Error("CAD 沒有可解析的實體。");
  const empty = result.meshes.filter(
    (m) => !m.attributes?.position?.array?.length || !m.index?.array?.length,
  );
  if (empty.length)
    throw new Error(
      `CAD 解析器未能產生 ${empty.length} 個實體的三角網格，請使用本機精細轉換或重新匯出 STEP。`,
    );
  const used = new Set();
  function node(record) {
    const group = new THREE.Group();
    group.name = record.name || "Assembly";
    for (const index of record.meshes || []) {
      if (!result.meshes[index]) continue;
      group.add(occtMesh(result.meshes[index], index));
      used.add(index);
    }
    for (const child of record.children || []) group.add(node(child));
    return group;
  }
  const root = node(result.root || {});
  // Do not silently drop meshes omitted by an incomplete assembly tree.
  result.meshes.forEach((mesh, index) => {
    if (!used.has(index)) root.add(occtMesh(mesh, index));
  });
  root.userData.geometrySource = "cad-tessellation";
  root.userData.tessellation = TESSELLATION;
  return root;
}
