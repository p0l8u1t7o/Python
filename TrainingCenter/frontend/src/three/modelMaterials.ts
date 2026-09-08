import * as THREE from 'three';

/** Clone materials per instance; the useGLTF cache must remain untouched. */
export function prepareModel(source: THREE.Object3D): THREE.Object3D {
  const model = source.clone(true);
  model.traverse(object => {
    const mesh = object as THREE.Mesh;
    if (!mesh.isMesh) return;
    mesh.castShadow = true;
    mesh.receiveShadow = true;
    const prepare = (original: THREE.Material) => {
      const material = original.clone() as THREE.MeshStandardMaterial;
      if (!material.isMeshStandardMaterial) return material;
      const color = material.color;
      const max = Math.max(color.r, color.g, color.b);
      const min = Math.min(color.r, color.g, color.b);
      // Neutral silver = machined metal; dark/colored housings = polymer or paint.
      // Do not turn every plastic enclosure and cable into reflective metal.
      const metal = max - min < 0.09 && max > 0.3 && max < 0.78;
      material.metalness = metal ? 0.72 : 0.06;
      material.roughness = metal ? 0.3 : 0.48;
      material.envMapIntensity = 1.1;
      return material;
    };
    mesh.material = Array.isArray(mesh.material) ? mesh.material.map(prepare) : prepare(mesh.material);
  });
  return model;
}

/** Geometries/textures belong to the loader cache; dispose only owned materials. */
export function disposeModelMaterials(model: THREE.Object3D) {
  model.traverse(object => {
    const mesh = object as THREE.Mesh;
    if (mesh.isMesh) (Array.isArray(mesh.material) ? mesh.material : [mesh.material]).forEach(material => material.dispose());
  });
}

/** Present optics face-on; CAD bodies are authored along their mounting axis. */
export function orientComponentModel(model: THREE.Object3D, url: string) {
  if (/\/component-visuals\/(industrial_camera|lens|ring_light|led_bar|calib_board|pcb)\.glb$/.test(url)) {
    model.rotation.x = -Math.PI / 2;
  }
  return model;
}
