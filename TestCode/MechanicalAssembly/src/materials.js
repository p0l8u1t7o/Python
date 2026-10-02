import * as THREE from "three";
import { addSurfaceDetail } from "./surface-detail.js";
export const MATERIAL_PRESETS = {
  auto: { label: "保留來源／自動外觀" },
  aluminum: {
    label: "霧面鋁合金",
    color: "#c3cbd1",
    metalness: 0.96,
    roughness: 0.32,
    finish: "brushed",
  },
  steel: {
    label: "不鏽鋼",
    color: "#bec5cb",
    metalness: 1,
    roughness: 0.17,
    finish: "brushed",
  },
  darkSteel: {
    label: "黑化鋼",
    color: "#343c44",
    metalness: 0.88,
    roughness: 0.29,
    finish: "brushed",
  },
  plastic: {
    label: "工程塑膠",
    color: "#333b43",
    metalness: 0,
    roughness: 0.47,
    clearcoat: 0.16,
    clearcoatRoughness: 0.32,
    finish: "molded",
  },
  rubber: {
    label: "橡膠",
    color: "#20242a",
    metalness: 0,
    roughness: 0.86,
    finish: "rubber",
  },
  glass: {
    label: "透明護罩",
    color: "#c8e4eb",
    metalness: 0,
    roughness: 0.12,
    transmission: 0.9,
    thickness: 0.025,
    ior: 1.49,
    transparent: true,
    opacity: 0.72,
  },
  brass: {
    label: "黃銅",
    color: "#d3ae66",
    metalness: 1,
    roughness: 0.23,
    finish: "brushed",
  },
  paint: {
    label: "烤漆鈑金",
    color: "#e0e6e8",
    metalness: 0,
    roughness: 0.34,
    clearcoat: 0.4,
    clearcoatRoughness: 0.25,
    finish: "paint",
  },
};
export function inferredMaterial(name) {
  if (/橡膠|優力膠|rubber|urethane|tire|belt|皮帶/i.test(name)) return "rubber";
  if (/玻璃|壓克力|acrylic|glass|polycarbonate/i.test(name)) return "glass";
  if (
    /塑膠|plastic|nylon|pom\b|pa66|frame.cap|cover.*HCH|HFCB8|HFCL8|sensor|keyence|omron|光電/i.test(
      name,
    )
  )
    return "plastic";
  if (/黃銅|brass|copper|銅/i.test(name)) return "brass";
  if (
    /螺栓|螺絲|bolt|screw|nut|nezi|bearing|軸承|不鏽鋼|shaft|導桿|鋼管|caster.stopper|pivot.pin|retaining|frame.plate|\bpin[_-]/i.test(
      name,
    )
  )
    return "steel";
  return "aluminum";
}
export function displayMaterial(
  source,
  name,
  override = "auto",
  { cadSource = false } = {},
) {
  const material = source?.isMeshPhysicalMaterial
    ? source.clone()
    : new THREE.MeshPhysicalMaterial();
  if (source) {
    if (source.color) material.color.copy(source.color);
    for (const key of [
      "map",
      "normalMap",
      "roughnessMap",
      "metalnessMap",
      "aoMap",
      "alphaMap",
      "emissiveMap",
      "bumpMap",
      "side",
      "opacity",
      "transparent",
      "alphaTest",
      "depthWrite",
      "vertexColors",
    ])
      if (source[key] !== undefined) material[key] = source[key];
    if (source.emissive) material.emissive.copy(source.emissive);
    if (source.normalScale) material.normalScale.copy(source.normalScale);
    for (const key of ["bumpScale", "aoMapIntensity", "emissiveIntensity"])
      if (source[key] !== undefined) material[key] = source[key];
    material.roughness = source.roughness ?? 0.35;
    material.metalness = source.metalness ?? 0.6;
    if (source.isMeshPhysicalMaterial)
      for (const key of [
        "ior",
        "transmission",
        "thickness",
        "clearcoat",
        "clearcoatRoughness",
      ])
        material[key] = source[key];
  }
  // Desktop CAD exports can contain no material at all. GLTFLoader supplies
  // white/metalness=1/roughness=1, which is a fallback, not authored CAD PBR.
  // Limit this recovery to known catalog CAD; arbitrary imported PBR stays intact.
  const catalogDefault =
    cadSource &&
    source &&
    !source.isMeshPhysicalMaterial &&
    source.color?.getHex() === 0xffffff &&
    source.metalness === 1 &&
    source.roughness === 1 &&
    !source.map &&
    !source.vertexColors &&
    !source.normalMap &&
    !source.roughnessMap &&
    !source.metalnessMap;
  const inferred =
    !source ||
    source.userData?.materialSource === "unspecified" ||
    catalogDefault;
  const cadColor = source?.userData?.materialSource === "cad-color";
  const profile =
    override !== "auto"
      ? override
      : inferred || cadColor
        ? inferredMaterial(name)
        : "auto";
  const preset = MATERIAL_PRESETS[profile] || MATERIAL_PRESETS.auto;
  if (preset.color) {
    if (override !== "auto" || !cadColor) material.color.set(preset.color);
    for (const key of [
      "metalness",
      "roughness",
      "transmission",
      "thickness",
      "transparent",
      "opacity",
      "clearcoat",
      "clearcoatRoughness",
    ])
      material[key] =
        preset[key] ??
        (key === "opacity" ? 1 : key === "transparent" ? false : 0);
    material.depthWrite = !material.transparent;
    material.ior = preset.ior ?? 1.5;
    if (override === "auto" && cadColor) {
      material.opacity = source.opacity;
      material.transparent = source.transparent;
      material.depthWrite = source.depthWrite;
    }
    addSurfaceDetail(material, preset.finish);
  }
  material.envMapIntensity = 1;
  material.userData.baseEmissive = material.emissive.clone();
  material.userData.appearanceSource =
    override !== "auto"
      ? "user"
      : inferred
        ? "inferred"
        : cadColor
          ? "cad-color-inferred-finish"
          : "source";
  return material;
}
