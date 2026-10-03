// Reference reconstruction, millimetres. Positions are estimates, not OEM CAD.
import * as THREE from 'three';
import { finish } from '@core/geom/finish.js';
import { block, cylinder, rounded, profile, decal } from '@core/geom/primitives.js';
export const NB = { W: 300, D: 210, H: 36 };
// 護蓋開度：100° 時門緣仍高於載具框 12 mm，鉤爪與壓頭在門緣作業不碰載具框
export const DOOR_OPEN_DEG = 100;
const material=(color,roughness=.7,metalness=.2)=>new THREE.MeshStandardMaterial({color,roughness,metalness});
const body=material(0x242829),lid=material(0x393e3e),rubber=material(0x111416,.94,0),doorMat=material(0x252a2b),steel=material(0x8b9294,.32,.85),dark=material(0x080b0d),gold=material(0xd0aa53,.32,.8),blue=material(0x1476a3);
for (const m of [body,lid,doorMat]) finish(m,'polymer',.025);
finish(rubber,'polymer',.045); finish(steel,'metal',.008);
// 側門（L/R）限制在 |z|≤74：避開四角護角（z 79～109）與載具 PU 承載墊（開門時門緣下垂）；
// 後側門（B）限制在 27≤|x|≤124：避開護角（x≥126）與螢幕轉軸（x≤24）。夾墊只壓護角，不壓護蓋。
const standard=[
  {id:'D1',side:'L',u:-39,w:70,h:23,name:'HDMI / USB 3.1 ×2',ports:['hdmi','usb','usb'],icon:'HDMI   SS   SS'},
  {id:'D2',side:'L',u:15,w:32,h:23,name:'AC 電源',ports:['ac'],icon:'DC IN'},
  {id:'D3',side:'R',u:-5,w:40,h:23,name:'Type-C / 耳機麥克風',ports:['typec','audio'],icon:'USB-C   AUDIO'},
  {id:'D4',side:'R',u:-51,w:46,h:23,name:'Smart Card',ports:['card'],icon:'SMART CARD'},
  {id:'D5',side:'B',u:-75,w:96,h:23,name:'COM / 千兆網口',ports:['com','lan'],icon:'COM       LAN'},
  {id:'BAT1',side:'L',u:54,w:40,h:23,name:'電池 1 封印',ports:['battery'],icon:'1   LOCK',sealed:true},
  {id:'BAT2',side:'R',u:46,w:56,h:23,name:'電池 2 封印',ports:['battery'],icon:'2   LOCK',sealed:true},
  {id:'HDD',side:'B',u:75.5,w:96,h:23,name:'HDD 保護門（不拆拔）',ports:['hdd'],icon:'HDD    LOCK'},
];
export const SKUS={'V110-STND':standard,'V110-RF':standard.map(d=>({...d}))};
export let DOOR_DEFS=standard;
let selectedSku='V110-STND';
export function selectSku(name){selectedSku=SKUS[name]?name:'V110-STND';DOOR_DEFS=SKUS[selectedSku];return DOOR_DEFS;}
function screw(parent,x,y,z,r=1.8){
  const g=new THREE.Group();g.position.set(x,y,z);if(y<0)g.rotation.x=Math.PI;parent.add(g);
  cylinder(g,r+.6,.3,[0,0,0],dark);cylinder(g,r,.65,[0,.2,0],steel);
  block(g,[r*1.3,.15,.45],[0,.59,0],dark);block(g,[.45,.15,r*1.3],[0,.59,0],dark);return g;
}
function port(type){
  const g=new THREE.Group();
  if(['usb','hdmi','typec','com','lan','card'].includes(type)){
    const sizes={usb:[13,6],hdmi:[15,6],typec:[9,4],com:[22,9],lan:[14,12],card:[40,3]},[w,h]=sizes[type];
    // Stamped shell has an actual opening and inner walls, not a black face on a solid box.
    const outline=(ww,hh)=>{
      const s=new THREE.Shape(),r=type==='typec'?hh/2:Math.min(.7,hh/3);
      if(type==='hdmi'||type==='com'){
        s.moveTo(-ww/2,hh/2);s.lineTo(ww/2,hh/2);s.lineTo(ww/2-2,-hh/2);s.lineTo(-ww/2+2,-hh/2);s.closePath();
      }else{
        s.moveTo(-ww/2+r,-hh/2);s.lineTo(ww/2-r,-hh/2);s.quadraticCurveTo(ww/2,-hh/2,ww/2,-hh/2+r);
        s.lineTo(ww/2,hh/2-r);s.quadraticCurveTo(ww/2,hh/2,ww/2-r,hh/2);s.lineTo(-ww/2+r,hh/2);
        s.quadraticCurveTo(-ww/2,hh/2,-ww/2,hh/2-r);s.lineTo(-ww/2,-hh/2+r);s.quadraticCurveTo(-ww/2,-hh/2,-ww/2+r,-hh/2);
      }return s;
    };
    const shell=outline(w+1.2,h+1.2);shell.holes.push(new THREE.Path(outline(w,h).getPoints(16)));
    const metalShell=new THREE.Mesh(new THREE.ExtrudeGeometry(shell,{depth:2.8,bevelEnabled:false,curveSegments:12}),steel);
    metalShell.position.z=-.8;metalShell.castShadow=metalShell.receiveShadow=true;g.add(metalShell);
    block(g,[w,h,.25],[0,0,0],dark);   // 插座底板：與金屬殼後緣、機身側面錯開 ≥0.6 mm，避免重合面閃爍
    if(type==='usb'||type==='typec')block(g,[w-2,1,2],[0,0,.25],type==='usb'?blue:dark);
    if(type==='com'){for(let row=0;row<2;row++)for(let i=0;i<(row?4:5);i++)cylinder(g,.5,2,[-6+i*3+row*1.5,1.5-row*3,2],gold,'z',8);}
    else {
      const count={usb:9,hdmi:19,typec:12,lan:8,card:8}[type];
      for(let i=0;i<count;i++)block(g,[Math.min(.45,w*.7/count*.55),type==='lan'?3:.2,1.2],[-w*.35+i*w*.7/(count-1),type==='usb'||type==='typec'?.57:-h*.22,.8],gold);
    }
    if(type==='com')for(const x of [-15,15])cylinder(g,2,3,[x,0,0],steel,'z',6);
    if(type==='lan')block(g,[6,2,2],[0,-6,1.5],dark);
  }else if(type==='ac'||type==='audio'){
    cylinder(g,type==='ac'?3.5:3,3,[0,0,0],steel,'z');cylinder(g,2,1,[0,0,2],dark,'z');
    if(type==='ac')cylinder(g,.8,2,[0,0,2.5],gold,'z');
  }else{block(g,[28,13,3],[0,0,0],rubber);decal(g,25,10,[0,0,2.15],[0,0,0],type==='hdd'?['SSD','PULL TAB']:['SEALED','BATTERY']);}
  return g;
}
function makeDoor(def){
  const group=new THREE.Group(),hinge=new THREE.Group();group.add(hinge);
  const panel=rounded(hinge,def.w,def.h,2.4,2,[0,def.h/2,1],doorMat);panel.rotation.x=Math.PI/2;
  for(const y of [3,def.h-3])block(hinge,[def.w-5,1.2,1],[0,y,-.4],rubber);
  for(const x of [-def.w/2+3,def.w/2-3])block(hinge,[1.2,def.h-6,1],[x,def.h/2,-.4],rubber);
  const seal=decal(hinge,def.w-12,8,[0,def.h/2,-1.05],[0,Math.PI,0],'LOCK / UNLOCK',{color:'#a9b8ba'});
  decal(hinge,def.w-8,6,[0,def.h*.44,4.5],[0,0,0],def.icon,{center:true,color:def.id==='D1'?'#dc776b':'#d1d9d7'});
  const latchPivot=new THREE.Group();latchPivot.position.set(0,def.h-2,4);hinge.add(latchPivot);
  block(latchPivot,[Math.min(22,def.w*.4),3,2],[0,0,0],steel);block(latchPivot,[Math.min(19,def.w*.35),1.2,2.3],[0,1,1],rubber);
  for(const x of [-def.w/2+5,def.w/2-5])cylinder(group,1.5,8,[x,0,1],steel,'x');
  // 門內黑色底板：前緣凸出機身側面 0.65 mm、上緣低於上蓋膠條，避免與機身／膠條／上蓋重合面閃爍
  const cavity=block(group,[def.w-2,def.h-5,2],[0,(def.h-5)/2+1,-4.4],dark);
  // Recess the ports behind the closed door's inner face (z=.55).
  const portGroup=new THREE.Group();portGroup.position.set(0,def.h/2,-3.2);group.add(portGroup);
  def.ports.forEach((p,i)=>{const m=port(p);m.position.x=(i-(def.ports.length-1)/2)*(def.w-14)/def.ports.length;portGroup.add(m);});
  if(def.side==='L'){group.position.set(-NB.W/2-.5,3,def.u);group.rotation.y=-Math.PI/2;}
  if(def.side==='R'){group.position.set(NB.W/2+.5,3,def.u);group.rotation.y=Math.PI/2;}
  if(def.side==='B'){group.position.set(def.u,3,-NB.D/2-.5);group.rotation.y=Math.PI;}
  const api={def,group,hinge,latchPivot,portGroup,seal,cavity,open:0,latchUp:0,
    set(open,latchUp){this.open=open;this.latchUp=latchUp;hinge.rotation.x=open*THREE.MathUtils.degToRad(DOOR_OPEN_DEG);latchPivot.position.y=def.h-2+3*latchUp;},
    normalWorld(out=new THREE.Vector3()){return out.set(0,0,1).transformDirection(group.matrixWorld);},
    upWorld(out=new THREE.Vector3()){return out.set(0,1,0).transformDirection(group.matrixWorld);},
    movingNormal(open,out=new THREE.Vector3()){const a=open*THREE.MathUtils.degToRad(DOOR_OPEN_DEG);return out.set(0,-Math.sin(a),Math.cos(a)).transformDirection(group.matrixWorld);},
    latchWorld(out=new THREE.Vector3()){return latchPivot.getWorldPosition(out);},
    edgeWorldAt(open,latch=1,out=new THREE.Vector3()){const a=open*THREE.MathUtils.degToRad(DOOR_OPEN_DEG),h=def.h-2+3*latch;return group.localToWorld(out.set(0,h*Math.cos(a)-4*Math.sin(a),h*Math.sin(a)+4*Math.cos(a)));},
    centerWorld(out=new THREE.Vector3()){return group.localToWorld(out.set(0,def.h/2,1));}
  };api.set(0,0);return api;
}
export function createNotebook(){
  const root=new THREE.Group();root.name='V110-reference-model';const {W,D}=NB;
  rounded(root,W-8,D-8,23,7,[0,0,0],body);rounded(root,W-5,D-5,1.4,7,[0,23,0],rubber);rounded(root,W-7,D-7,10.6,6,[0,24.4,0],lid);
  for(const sign of [-1,1])profile(root,[[-128,-80],[-80,-80],[-71,-70],[-78,70],[-92,81],[-127,81],[-104,60],[-99,-34],[-127,-46]].map(([x,z])=>[x*sign,z]),35.4,.65,lid);
  profile(root,[[-31,-66],[31,-66],[40,-55],[40,-18],[29,-8],[-29,-8],[-40,-18],[-40,-55]],35.4,.65,lid);
  profile(root,[[-42,33],[42,33],[52,42],[52,78],[39,90],[-39,90],[-52,78],[-52,42]],35.4,.65,lid);
  decal(root,54,17,[0,36.7,14],[-Math.PI/2,0,Math.PI],'Getac',{center:true,bold:true});
  for(const sx of [-1,1])for(const sz of [-1,1]){
    rounded(root,25,29,38,6,[sx*139,-1,sz*94],rubber).name='corner guard';
    for(let k=0;k<3;k++)block(root,[26,1.2,1],[sx*139,7+k*6,sz*109.25],doorMat);
    screw(root,sx*140,38,sz*94,2.1);cylinder(root,5,2.5,[sx*136,-2,sz*91],rubber);
  }
  cylinder(root,7,48,[0,28,-104],steel,'x');block(root,[42,14,12],[0,27,106],rubber);block(root,[22,5,3],[0,30,113],steel);
  for(let i=0;i<6;i++)cylinder(root,2.8,1,[-65+i*13,24,107],rubber,'z');
  decal(root,88,5,[-40,29,108],[0,0,0],'POWER   -   +    P1    P2',{center:true});
  for(const x of [-100,100])block(root,[12,8,12],[x,6,108],rubber);
  block(root,[190,4,12],[0,3,125],rubber);for(const x of [-96,96])block(root,[8,4,24],[x,3,116],rubber);
  const bottomScrews=[];
  const points=[[-127,-77],[-68,-88],[0,-88],[66,-88],[126,-77],[-127,0],[127,0],[-127,76],[-70,88],[0,88],[70,88],[127,76]];
  points.forEach(([x,z])=>{bottomScrews.push(screw(root,x,-.8,z));screw(root,x,36,z,1.5);});
  profile(root,[[-23,-12],[91,-12],[106,0],[106,57],[93,71],[29,71],[12,87],[-29,87],[-43,73],[-43,3]],-.9,.4,rubber,.3);
  profile(root,[[-22,-10],[90,-10],[103,1],[103,56],[92,68],[28,68],[10,84],[-28,84],[-40,72],[-40,4]],-1.55,.35,body,.3);
  [[-33,6],[46,-4],[97,5],[97,56],[42,66],[-30,70],[4,80]].forEach(([x,z])=>bottomScrews.push(screw(root,x,-1.9,z,1.4)));
  const printing=new THREE.Group();root.add(printing);
  decal(printing,103,46,[66,-1.1,-55],[Math.PI/2,0,0],['Getac     V110','MODEL / INPUT : SEE WORK ORDER','REGULATORY MARKING','CE   FCC   UL   EAC','REFERENCE RECONSTRUCTION'],{color:'#c8cbc5'});
  decal(printing,74,14,[-47,-1.1,-79],[Math.PI/2,0,0],['V110 SERIES','WHITE INK INSPECTION']);
  const labels={safety:printing.children[0]};
  labels.sn=decal(root,45,15,[61,-1.8,-31],[Math.PI/2,0,0],['','SN: DEMO-0001'],{bg:'#d7e4da',color:'#151a1b',barcode:true});
  labels.coin=decal(root,59,19,[-68,-1.1,-43],[Math.PI/2,0,0],['WARNING','INGESTION HAZARD','WORK ORDER LABEL'],{bg:'#dcd4b9',color:'#191c1c'});
  const dock=new THREE.Group();dock.position.set(-89,-1.4,61);dock.rotation.x=Math.PI/2;root.add(dock);
  block(dock,[18,34,1],[0,0,0],rubber);
  for(let r=0;r<9;r++)for(let c=0;c<3;c++)cylinder(dock,r===0?1.7:1.05,.6,[-5+c*5,-13+r*3.2,.9],gold,'z',10);
  block(dock,[8,21,1],[19,0,0],gold);
  if(selectedSku==='V110-RF')for(let i=0;i<3;i++)cylinder(root,2,1,[-88+i*8,-1.8,34],gold);
  for(let k=0;k<9;k++)block(root,[18,.4,1.1],[-124,-1.2,48+k*2.7],dark);
  const doors=DOOR_DEFS.map(d=>{const api=makeDoor(d);root.add(api.group);return api;});
  root.userData={doors,labels,printing,bottomScrews,dock};return {root,doors,labels,printing,bottomScrews,dock};
}
