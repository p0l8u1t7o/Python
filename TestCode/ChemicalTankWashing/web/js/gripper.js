// 清洗用側進式平行夾具。工具 +Z 朝桶心，+Y 為桶軸；所有承力件連回法蘭。
import * as THREE from 'three';
import { DRUM, ROBOT } from './layout.js';
import { block, cylinder } from '@core/geom/shapes.js';
import { MAT } from '@core/geom/materials.js';
import { bolts, housing } from '@core/geom/hardware.js';

export const GRIPPER = { stroke: 30, padRadius: DRUM.R, padThickness: 12, padHalfAngle: .38, jawX: 340, railZ: 125, railHalf: 420, driveZ: 205.5 };
function arcBand(parent, ri, ro, height, y, theta, mat) {
  const shape = new THREE.Shape(), span = GRIPPER.padHalfAngle;
  shape.absarc(0,0,ro,theta-span,theta+span,false);
  shape.absarc(0,0,ri,theta+span,theta-span,true); shape.closePath();
  const geo = new THREE.ExtrudeGeometry(shape,{depth:height,bevelEnabled:false,curveSegments:24});
  // Shape X/Y → 工具 X/Z，厚度沿 Y。
  geo.rotateX(Math.PI / 2); geo.translate(0,y+height/2,ROBOT.grip);
  const mesh = new THREE.Mesh(geo,mat); mesh.castShadow = mesh.receiveShadow = true; parent.add(mesh); return mesh;
}
export function createWashGripper(tool) {
  const root = new THREE.Group(); root.name = '完整清洗夾具'; tool.add(root);
  const solids = [], pads = [], slides = [], rods = [], hooks = [], carriages = [], rails = [], crossbars = [], cylinders = [], glands = [];
  const mark = mesh => { solids.push(mesh); return mesh; };
  mark(cylinder(root, 125, 30, [0, 0, 15], MAT.steelDark, 'z', 36));
  mark(housing(root,200,250,75,MAT.alu,0,0,67,10));
  // 鋁背板留出檢修窗，氣缸固定座、法蘭與導軌螺接處仍保留完整腹板。
  const plateShape=new THREE.Shape();plateShape.moveTo(-380,-180);plateShape.lineTo(380,-180);plateShape.lineTo(380,180);plateShape.lineTo(-380,180);plateShape.closePath();
  for(const s of [-1,1])for(const x of [155,275]) {
    const hole=new THREE.Path(),cx=s*x;hole.moveTo(cx-30,-85);hole.lineTo(cx-30,85);hole.lineTo(cx+30,85);hole.lineTo(cx+30,-85);hole.closePath();plateShape.holes.push(hole);
  }
  const plateGeo=new THREE.ExtrudeGeometry(plateShape,{depth:24,bevelEnabled:false});plateGeo.translate(0,0,98);
  const backplate=mark(new THREE.Mesh(plateGeo,MAT.alu));backplate.castShadow=backplate.receiveShadow=true;root.add(backplate);
  bolts(root,[-1,1].flatMap(x=>[-1,1].map(y=>[x*85,y*95,124])),12,'z');
  for(const y of [-130,130]) {
    rails.push(mark(block(root, [840, 40, 38], [0, y, 125], MAT.alu)));
    rails.push(mark(block(root, [840, 16, 18], [0, y, 153], MAT.steel)));
    for(const s of [-1,1]) mark(block(root, [24, 65, 67], [s*409, y, 131], MAT.black));
  }
  for(const s of [-1,1]) {
    const slide = new THREE.Group(); slide.name = s<0?'左移動夾爪':'右移動夾爪'; root.add(slide); slides.push({slide,s});
    for(const y of [-130,130]) {
      // U 形滑座：背面開槽包住支承梁，側面軸承襯塊貼合導軌，不能用實心方塊穿過導軌。
      const carriage = new THREE.Group(); carriage.position.set(s*340,y,155); slide.add(carriage); carriages.push(carriage);
      for(const side of [-1,1]) {
        mark(block(carriage, [50, 11, 65], [0, side*28.5, 0], MAT.alu));
        mark(block(carriage, [46, 15, 19], [0, side*15.5, -1.5], MAT.steelDark));
      }
      mark(block(carriage, [50, 46, 24.5], [0, 0, 20.25], MAT.alu));
      mark(block(slide, [35, 60, ROBOT.grip-170], [s*340, y, (ROBOT.grip+170)/2], MAT.alu));
      bolts(slide,[-1,1].map(k=>[s*340+k*8,Math.sign(y)*117,GRIPPER.driveZ+24]),5,'z');
    }
    mark(block(slide, [40, 670, 45], [s*340, 140, ROBOT.grip], MAT.alu));
    // 寬面 PU 分成上下兩區，避開桶身 ±140–180mm 的凸箍。
    for(const y of [-70,70]) {
      const theta=s>0?0:Math.PI;
      const pad=arcBand(slide,DRUM.R,DRUM.R+12,96,y,theta,MAT.pu); pads.push(pad);
      mark(arcBand(slide,DRUM.R+12,DRUM.R+28,112,y,theta,MAT.steel));
      mark(block(slide, [34, 80, 47], [s*324, y, ROBOT.grip], MAT.steel));
    }
    // C 形防脫扣：上下包住頂部 L 環，全部隨側爪退開，沒有固定橫桿穿過桶頂。
    const hook = new THREE.Group(); slide.add(hook); hooks.push(hook);
    mark(block(hook, [40, 30, 65], [s*323, 466, ROBOT.grip], MAT.steel));
    mark(block(hook, [18, 94, 48], [s*311, 443, ROBOT.grip], MAT.steel));
    mark(block(hook, [23, 8, 48], [s*305.5, 400, ROBOT.grip], MAT.steel));
    mark(block(hook, [32, 10, 48], [s*299, 484, ROBOT.grip], MAT.steel));
    bolts(hook,[[s*324,487,ROBOT.grip]],9);
    // 各爪的雙作用氣缸與推桿，軸線真的連到滑座。
    const driveZ=GRIPPER.driveZ;
    cylinders.push(mark(cylinder(root, 38, 180, [s*130, 0, driveZ], MAT.alu, 'x', 24)));
    for(const x of [40,220]) {
      // 固定座從背板正面連到端蓋背面；缸體不再埋入背板。
      mark(block(root, [16, 88, 39.5], [s*x, 0, 141.75], MAT.alu));
      const shape=new THREE.Shape();shape.moveTo(-44,-44);shape.lineTo(44,-44);shape.lineTo(44,44);shape.lineTo(-44,44);shape.closePath();
      if(x===220){const bore=new THREE.Path();bore.absarc(0,0,18,0,Math.PI*2,true);shape.holes.push(bore);}
      const geo=new THREE.ExtrudeGeometry(shape,{depth:16,bevelEnabled:false,curveSegments:20});geo.translate(0,0,-8);geo.rotateY(Math.PI/2);
      const cap=mark(new THREE.Mesh(geo,MAT.steelDark));cap.position.set(s*x,0,driveZ);cap.castShadow=cap.receiveShadow=true;root.add(cap);
      if(x===220)glands.push({cap,s});
    }
    const piston=mark(cylinder(root, 16, 1, [0, 0, driveZ], MAT.steel, 'x', 20)); rods.push({piston,s});
    crossbars.push(mark(block(slide, [32, 260, 36], [s*340, 0, driveZ], MAT.alu)));
    cylinder(slide, 25, 54, [s*340, 0, driveZ], MAT.steelDark, 'z', 28);
    // 雙作用氣缸的兩個供氣口，固定管路連到背板上的分配塊。
    for(const x of [60,200]) {
      mark(cylinder(root, 8, 16, [s*x, -44, driveZ], MAT.steel, 'y', 28));
      const route=[[s*x,-52,driveZ],[s*x,-65,driveZ],[s*x,-65,160],[s*30,-95,152]].map(p=>new THREE.Vector3(...p));
      const hose=mark(new THREE.Mesh(new THREE.TubeGeometry(new THREE.CatmullRomCurve3(route),20,4,8,false),MAT.black));root.add(hose);
    }
    const sensor=block(slide, [25, 38, 20], [s*340, 182, 156], MAT.black);
    const led=cylinder(sensor, 4, 3, [0, 0, 12], MAT.green, 'z', 8); led.material=MAT.green.clone();
    slide.userData.led=led;
  }
  mark(block(root, [90, 40, 2], [0, -95, 123], MAT.steel));
  mark(block(root, [90, 36, 28], [0, -95, 138], MAT.alu));
  const set = value => {
    const v=THREE.MathUtils.clamp(value,0,1), offset=(1-v)*GRIPPER.stroke;
    for(const {slide,s}of slides){slide.position.x=s*offset;slide.userData.led.material.emissiveIntensity=v>.99?1:.05;}
    for(const {piston,s}of rods){const end=GRIPPER.jawX+offset;piston.scale.y=end-220;piston.position.x=s*(end+220)/2;}
    root.userData.closed=v;
  };
  set(0);
  return {root,set,solids,pads,slides,hooks,rods,carriages,rails,crossbars,cylinders,glands,backplate};
}
