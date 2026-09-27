// Shared geometric installation details; component sizes are illustrative.
import * as THREE from 'three';
import {cable,CABLE} from './cable-routing.js';
import {populatePanel} from './electrical-components.js';
const steel=new THREE.MeshStandardMaterial({color:0xa7b1bc,metalness:.65,roughness:.38});
const dark=new THREE.MeshStandardMaterial({color:0x303944,roughness:.65});
const paint=new THREE.MeshStandardMaterial({color:0xd5dadd,roughness:.6});
const rubber=new THREE.MeshStandardMaterial({color:0x171d22,roughness:.85});
const blue=new THREE.MeshStandardMaterial({color:0x438aab,roughness:.5});
function box(parent,name,size,pos,mat=steel){const m=new THREE.Mesh(new THREE.BoxGeometry(...size),mat);m.name=name;m.position.set(...pos);m.castShadow=m.receiveShadow=true;parent.add(m);return m;}

/** Real circular through-holes, local Y normal, centred thickness. */
export function entryPlate(parent,name,size,pos,holes,material=paint){
  const [w,h,d]=size,s=new THREE.Shape();s.moveTo(-w/2,-d/2);s.lineTo(w/2,-d/2);s.lineTo(w/2,d/2);s.lineTo(-w/2,d/2);s.closePath();
  for(const [x,z,r] of holes){const p=new THREE.Path();p.absarc(x,-z,r,0,Math.PI*2,true);s.holes.push(p);}
  const geo=new THREE.ExtrudeGeometry(s,{depth:h,bevelEnabled:false,curveSegments:40});geo.rotateX(-Math.PI/2);geo.translate(0,-h/2,0);
  const m=new THREE.Mesh(geo,material);m.name=name;m.position.set(...pos);m.userData.serviceBores=holes;m.userData.entryPlate=true;m.castShadow=m.receiveShadow=true;parent.add(m);return m;
}
function annulus(parent,name,outer,inner,h,y,material,sides=40){
  const s=new THREE.Shape();for(let i=0;i<=sides;i++){const a=i/sides*Math.PI*2;i?s.lineTo(outer*Math.cos(a),outer*Math.sin(a)):s.moveTo(outer,0);}s.closePath();
  const p=new THREE.Path();p.absarc(0,0,inner,0,Math.PI*2,true);s.holes.push(p);
  const geo=new THREE.ExtrudeGeometry(s,{depth:h,bevelEnabled:false,curveSegments:40});geo.rotateX(-Math.PI/2);
  const m=new THREE.Mesh(geo,material);m.name=name;m.position.y=y;m.castShadow=true;parent.add(m);return m;
}
/** Hollow gland: sleeve, upper compression nut, lower locknut, rubber seal. */
export function entryGland(parent,name,{at,hole=12,wire=4,thickness=20}){
  const g=new THREE.Group();g.name=name;g.position.set(...at);parent.add(g);
  const inner=wire+1.5;
  if(inner>=hole-1)throw new Error(name+': cable does not fit gland');
  annulus(g,name+' / through sleeve',hole-.7,inner,thickness+4,-thickness-2,steel);
  annulus(g,name+' / upper hex nut',hole+3,inner,6,0,steel,6);
  annulus(g,name+' / lower locknut',hole+2,inner,4,-thickness-4,steel,6);
  annulus(g,name+' / elastomer seal',hole+1,wire+.8,1.2,6,rubber);
  g.userData.feedThrough={innerRadius:wire+.8,holeRadius:hole,wireRadius:wire,top:7.2,bottom:-thickness-4};
  return g;
}

/** Hollow cabinet. Entries use cabinet-local X/Z; top stays visible in cutaway. */
export function cabinetShell(parent,name,{center,size,entries=[],thickness=12,material=paint}){
  const g=new THREE.Group();g.name=name;g.position.set(...center);parent.add(g);
  const [w,h,d]=size,solids=[];
  g.userData.electricalEnclosure={min:[-w/2+3,-h/2+4,-d/2+3],max:[w/2-3,h/2-thickness,d/2-3]};
  const top=entryPlate(g,name+' / bored roof',[w,thickness,d],[0,h/2-thickness/2,0],entries.map(e=>[e.x,e.z,e.hole]),material);solids.push(top);
  solids.push(box(g,name+' / floor',[w,4,d],[0,-h/2+2,0],material));
  solids.push(box(g,name+' / back',[w-6,h-thickness-4,3],[0,-thickness/2,-d/2+1.5],material));
  for(const x of [-w/2+1.5,w/2-1.5]){const m=box(g,name+' / side',[3,h-thickness-4,d],[x,-thickness/2,0],material);m.userData.electricalCover=true;solids.push(m);}
  const doors=Math.max(1,Math.ceil(w/650));
  for(let i=0;i<doors;i++){
    const dg=new THREE.Group();dg.name=name+' / removable door '+i;dg.userData.electricalCover=true;g.add(dg);
    const x=-w/2+(i+.5)*w/doors;
    solids.push(box(dg,name+' / door',[w/doors-3,h-thickness-6,3],[x,-thickness/2,d/2-1.5],material));
    box(dg,'door latch',[8,Math.min(42,h*.2),8],[x+w/doors*.35,0,d/2+3],dark);
    for(const y of [-h*.3,h*.3])box(dg,'door hinge',[9,22,6],[x-w/doors*.45,y,d/2+2],steel);
  }
  // Backplate bolts and cabinet feet remain visible when doors are removed.
  for(const x of [-w*.4,w*.4])for(const z of [-d*.35,d*.35])box(g,'cabinet plinth',[36,8,36],[x,-h/2+4,z],dark);
  return {group:g,solids,top,entries};
}

/** DIN rail / terminal / PLC mounting panel with genuinely connected wiring.
 * Coordinates are in the caller's frame, so feeds never attach to a moving axis.
 */
export function controlPanel(parent,name,{center,width=700,height=430,backZ,profile}){
  const g=new THREE.Group();g.name=name;g.position.set(...center);parent.add(g);
  box(g,name+' / mounting backplate',[width,height,4],[0,0,0]);
  if(!Number.isFinite(backZ)||backZ>=center[2]-2)throw new Error(name+': rear wall mounting surface required');
  const rear=backZ-center[2];
  for(const x of [-width*.42,width*.42])for(const y of [-height*.43,height*.43]){
    const spacer=new THREE.Mesh(new THREE.CylinderGeometry(5,5,-2-rear,12),steel);
    spacer.name='backplate standoff';spacer.rotation.x=Math.PI/2;spacer.position.set(x,y,(rear-2)/2);g.add(spacer);
    const screw=new THREE.Mesh(new THREE.CylinderGeometry(4,4,2,6),steel);
    screw.name='backplate fixing bolt';screw.rotation.x=Math.PI/2;screw.position.set(x,y,3);g.add(screw);
  }
  const row=height*.3,railWidth=width*.82;
  for(const y of [row]){
    for(const x of [-railWidth*.4,railWidth*.4])box(g,'DIN rail mounting foot',[10,12,2],[x,y,3]);
    box(g,'DIN rail spine',[railWidth,6,5],[0,y,6]);
    for(const dy of [-16,16])box(g,'DIN rail lip',[railWidth,3,9],[0,y+dy,8]);
  }
  const pitch=Math.min(25,width/18),terminalY=row+12;
  for(let i=0;i<12;i++){
    const x=(i-5.5)*pitch;
    box(g,'terminal '+(i+1),[pitch-2,30,22],[x,row,20],i<4?dark:blue);
    box(g,'terminal entry '+(i+1),[6,3,6],[x,terminalY,20],rubber);
    const screw=new THREE.Mesh(new THREE.CylinderGeometry(2.3,2.3,1,6),steel);screw.rotation.x=Math.PI/2;screw.position.set(x,row,31.5);g.add(screw);
  }
  if(profile)populatePanel(g,{profile,width,height});
  // Slotted side ducts, open at the front so wire placement can be inspected.
  for(const x of [-width*.45,width*.45]){
    for(const y of [-height*.35,height*.35])box(g,'duct mounting foot',[12,12,5],[x,y,4.5]);
    box(g,'slotted duct base',[25,height*.85,3],[x,0,8],dark);
    for(let y=-height*.4;y<height*.4;y+=16)for(const s of [-1,1])box(g,'duct finger',[2,10,22],[x+s*12,y,19],dark);
  }
  const ports=Array.from({length:12},(_,i)=>[center[0]+(i-5.5)*pitch,center[1]+terminalY+1.5,center[2]+20]);
  // Protective-earth bonding to the backplate stud; no simulated electrical logic.
  const stud=new THREE.Mesh(new THREE.CylinderGeometry(4,4,6,6),steel);
  stud.name='PE bonding stud';stud.rotation.x=Math.PI/2;stud.position.set(-width*.35,-height*.36,5);g.add(stud);
  cable(g,'PE / chassis bond',[[-width*.35,-height*.36,7],[-width*.42,-height*.32,28],[-width*.42,row,28],[-5.5*pitch,row+15,20]],{radius:1.5,color:CABLE.earth,clips:3,ends:false});
  g.userData.controlPanel={ports,width,height,backZ};return {group:g,ports};
}

/** Route through a desktop, through a cabinet roof, then to a terminal. */
export function panelFeed(parent,name,points,{radius=3,color=CABLE.signal}={}){
  const r=cable(parent,name,points,{radius,color,clips:Math.max(2,Math.ceil(points.length/2)),ends:false});r.userData.panelFeed=true;return r;
}
const coverMaterials=new WeakMap();
export function setElectricalMode(scene,mode,notify=true){
  scene.traverse(o=>{if(o.userData.electricalCover){
    o.visible=mode!=='cutaway';
    o.traverse(m=>{if(!m.isMesh)return;
      if(!coverMaterials.has(m)){const original=m.material;const fade=v=>{const c=v.clone();c.transparent=true;c.opacity=.12;c.depthWrite=false;return c;};coverMaterials.set(m,{original,ghost:Array.isArray(original)?original.map(fade):fade(original)});}
      m.material=coverMaterials.get(m)[mode==='xray'?'ghost':'original'];
    });
  }});
  if(typeof document!=='undefined'&&document.body)document.body.classList.toggle('electrical-cutaway',mode!=='shell');
  if(notify&&typeof window!=='undefined')window.dispatchEvent(new CustomEvent('electrical-view',{detail:{mode}}));
}
export function setElectricalCutaway(scene,open){setElectricalMode(scene,open?'cutaway':'shell');}
