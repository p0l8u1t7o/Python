// 共用材質表：所有專案與共用模型用同一份基本材質（鋼、鋁、烤漆、塑膠、指示燈…）。
// 產品專屬的外觀（特定顏色的外殼、PCB、標籤）留在專案裡；常用的新材質請加在這裡，不要各專案各寫一份。
import * as THREE from 'three';

// 標準 PBR 材質：顏色、粗糙度、金屬度、其他參數
export const std = (color, roughness = .6, metalness = .1, extra = {}) => new THREE.MeshStandardMaterial({ color, roughness, metalness, ...extra });

export const MAT = {
  floor: std(0x899696, .8, .04), floorOut: std(0x3a4148, .95),
  wall: std(0xdfe3e6, .9, 0, { transparent: true, opacity: .16, depthWrite: false, side: THREE.DoubleSide }),
  wallBase: std(0xc9ced2, .85), column: std(0xb7b2a8, .85),
  door: std(0x8e9aa6, .5, .3), window: std(0x9fc7e6, .1, 0, { transparent: true, opacity: .45 }),
  steelBlue: std(0x1f4e8c, .5, .4), steelOrange: std(0xe0781f, .5, .35), steel: std(0x9aa3ab, .4, .7),
  steelDark: std(0x3a4148, .5, .5), alu: std(0xc4ccd3, .35, .6), black: std(0x1d2126, .6, .2),
  yellow: std(0xf2c230, .45, .15), fanuc: std(0xf5c400, .4, .15), fanucDark: std(0x2d3136, .5, .4),
  pallet: std(0x4a5560, .8), palletEmpty: std(0x56626e, .8),
  drum: new THREE.MeshPhysicalMaterial({ color: 0x1250bc, roughness: .36, metalness: 0, clearcoat: .28, clearcoatRoughness: .4 }), drumLid: std(0x1b58c0, .5, 0), cap: std(0xf2f4f6, .5, 0), hole: std(0x0d1726, .9),
  roller: std(0xb5bec6, .3, .8), belt: std(0x2a2f35, .9), pu: std(0xd9a441, .9),
  pp: std(0xd8dfe3, .52, 0, { side: THREE.DoubleSide }),
  ppSolid: std(0xc9d3d8, .75), ppDark: std(0x7b8a94, .7),
  fence: std(0xf2c230, .5, .2), mesh: std(0x2b3036, .7, .2, { transparent: true, opacity: .22, depthWrite: false, side: THREE.DoubleSide }),
  glass: new THREE.MeshPhysicalMaterial({ color: 0x9cc8ff, roughness: .05, transmission: .5, transparent: true, opacity: .55 }),
  water: std(0x6fc4ff, .1, 0, { transparent: true, opacity: .6, depthWrite: false, emissive: 0x0a3a66, emissiveIntensity: .4 }),
  waste: std(0xd88a3c, .3, 0, { transparent: true, opacity: .75 }),
  tankW: std(0xe7e3d6, .45, 0),
  tankWaste: std(0xc77b34, .4, 0), tankAlkali: std(0x8c6bd6, .4, 0), tankClean: std(0x58b6f2, .4, 0), tankFresh: std(0x8fd3ff, .4, 0),
  agv: std(0xee8a26, .45, .2), agvDark: std(0x2b3036, .5, .4),
  cabinet: std(0xd9dde0, .5, .2), screen: std(0x10283a, .3, 0, { emissive: 0x1e6fa8, emissiveIntensity: .6 }),
  green: std(0x3dd68c, .4, 0, { emissive: 0x3dd68c, emissiveIntensity: .8 }),
  red: std(0xff4d4d, .4, 0, { emissive: 0xff4d4d, emissiveIntensity: .8 }),
  amber: std(0xffb020, .4, 0, { emissive: 0xffb020, emissiveIntensity: .8 }),
};
