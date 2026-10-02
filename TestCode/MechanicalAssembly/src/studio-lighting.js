import * as THREE from "three";

// Large luminous cards give metals broad highlights and dark reflected regions.
// This is a reflection environment, not extra geometry in the user's assembly.
export function studioEnvironment(renderer) {
  const scene = new THREE.Scene();
  scene.background = new THREE.Color("#535c69");
  const geometry = new THREE.PlaneGeometry(1, 1);
  const materials = [];
  const card = (position, size, color, intensity) => {
    const material = new THREE.MeshBasicMaterial({
      color: new THREE.Color(color).multiplyScalar(intensity),
      side: THREE.DoubleSide,
      toneMapped: false,
    });
    materials.push(material);
    const mesh = new THREE.Mesh(geometry, material);
    mesh.position.set(...position);
    mesh.scale.set(...size, 1);
    mesh.lookAt(0, 0, 0);
    scene.add(mesh);
  };
  card([-4, 4, 3], [4, 6], "#fff5e8", 5);
  card([4, 2, 1], [2, 5], "#d9e9ff", 3.5);
  card([1, 3, -4], [3, 5], "#edf4ff", 5);
  card([0, 6, 0], [5, 3], "#ffffff", 3);
  card([-1, 0.5, 5], [0.45, 3.5], "#ffffff", 2);
  card([0, 2, 6], [7, 5], "#eaf1ff", 1.25);
  card([-5, 1, 4], [3, 7], "#f4f2ed", 2.8);
  card([5, 0.5, -4], [3, 7], "#e0e7ee", 1.8);
  const generator = new THREE.PMREMGenerator(renderer);
  const environment = generator.fromScene(scene, 0.015, 0.1, 50);
  geometry.dispose();
  materials.forEach((m) => m.dispose());
  generator.dispose();
  return environment;
}
