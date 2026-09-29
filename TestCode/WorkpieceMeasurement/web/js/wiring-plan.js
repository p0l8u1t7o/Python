// Shared drawing/check geometry, mm. Bend radii are planning targets, not OEM approvals.
import * as THREE from 'three';
import {X2,YS} from './spec.js';
const V=a=>new THREE.Vector3(...a);
class Bend extends THREE.Curve {
  constructor(map,c,r,sign){super();Object.assign(this,{map,c,r,sign});}
  getPoint(t,target=new THREE.Vector3()){return target.copy(V(this.map(this.c+this.sign*this.r*Math.sin(Math.PI*t),this.r*(1-Math.cos(Math.PI*t)))));}
  getLength(){return Math.PI*this.r;}
}
class Quarter extends THREE.Curve {
 constructor(map,r){super();Object.assign(this,{map,r});}
 getPoint(t,target=new THREE.Vector3()){return target.copy(V(this.map(t*Math.PI/2)));}
 getLength(){return Math.PI*this.r/2;}
}
function opticalLead(c,h,lower=false){
 const p=new THREE.CurvePath(),line=(a,b)=>p.add(new THREE.LineCurve3(V(a),V(b))),arc=(f,r)=>p.add(new Quarter(f,r));
 if(!lower){
  line([c,h,0],[c,h+20,0]);arc(a=>[c,h+20+30*Math.sin(a),30-30*Math.cos(a)],30);
  line([c,h+50,30],[c,h+50,35]);arc(a=>[c+25-25*Math.cos(a),h+50,35+25*Math.sin(a)],25);
  arc(a=>[c+25+25*Math.sin(a),h+25+25*Math.cos(a),60],25);
 }else{
  line([c,947,14],[c,947,15]);arc(a=>[c+20-20*Math.cos(a),947,15+20*Math.sin(a)],20);
  line([c+20,947,35],[c+85,947,35]);arc(a=>[c+85+20*Math.sin(a),947,55-20*Math.cos(a)],20);
  arc(a=>[c+105,972-25*Math.cos(a),55+25*Math.sin(a)],25);line([c+105,972,80],[c+105,1192,80]);
  arc(a=>[c+85+20*Math.cos(a),1192+20*Math.sin(a),80],20);
 }return p;
}
function upperRiser(r){const p=new THREE.CurvePath();p.add(new THREE.LineCurve3(V([320+r,1180,60]),V([320+r,1200,60])));p.add(new Quarter(a=>[300+r+20*Math.cos(a),1200+20*Math.sin(a),60],20));return p;}
export function fold(a,b,r,length,map,sign=1){
 const c=(a+b+sign*(length-Math.PI*r))/2;
 if(sign*(c-a)<0||sign*(c-b)<0)throw Error('Carrier too short for stroke');
 const path=new THREE.CurvePath();
 path.add(new THREE.LineCurve3(V(map(a,0)),V(map(c,0))));path.add(new Bend(map,c,r,sign));path.add(new THREE.LineCurve3(V(map(c,2*r)),V(map(b,2*r))));
 return path;
}
export function routed(points,trim=16){
 const p=points.map(V),path=new THREE.CurvePath();let last=p[0];
 for(let i=1;i<p.length-1;i++){
   const u=p[i].clone().sub(p[i-1]),v=p[i+1].clone().sub(p[i]);const d=Math.min(trim,u.length()*.42,v.length()*.42);
   const a=p[i].clone().addScaledVector(u.normalize(),-d),b=p[i].clone().addScaledVector(v.normalize(),d);
   if(last.distanceTo(a)>.001)path.add(new THREE.LineCurve3(last,a));path.add(new THREE.QuadraticBezierCurve3(a,p[i],b));last=b;
 }
 if(last.distanceTo(p.at(-1))>.001)path.add(new THREE.LineCurve3(last,p.at(-1)));return path;
}
const route=(id,points,radius=1.8,extra={})=>({id,path:routed(points),radius,points,...extra});
export const STATIC_ROUTES=[
 route('CAM-A',[[130,1043,173],[147,1043,225],[147,918,225],[290,918,225],[290,865,231]],1.8,{attachments:['camA'],guide:true}),
 route('CAM-B',[[-185,1043,0],[-228,1043,0],[-228,1043,72],[-228,918,72],[-228,918,225],[-290,918,225],[-290,865,231]],1.8,{attachments:['camB'],guide:true}),
 route('CAM-C',[[30,1290,0],[30,1310,0],[75,1310,0],[75,1310,180],[75,918,180],[75,918,225],[290,918,225],[290,865,231]],1.8,{attachments:['camC'],guide:true}),
 route('X-FEED',[[-280,960,-222],[-318,960,-222],[-318,918,-222],[-318,918,225],[-290,918,225],[-290,865,231]],2.5,{guide:true}),
 route('OPT-UP-FIXED',[[320,1220,140],[320,1220,225],[320,918,225],[290,918,225],[290,865,231]],1.3,{guide:true}),
 route('OPT-DN-FIXED',[[320,1212,160],[312,1212,160],[312,1212,217],[312,910,217],[282,910,217],[282,850,231],[290,850,231]],1.3,{guide:true}),
];
export function movingRoutes(S,s){
 const x=S.tx,y=S.zt,c=X2+S.r2,head=YS+s.base+s.wd+70+S.headLift;
 return [
 {id:'X-CHAIN',path:fold(-280,x,35,650,(u,v)=>[u,960+v,-222]),radius:3,carrier:true,bend:35,designLength:650},
 {id:'Z-CHAIN',path:fold(1030,y+25,22,180,(u,v)=>[x,u,-222+v]),radius:2.5,carrier:true,bend:22,designLength:180},
 route('Z-TO-VALVE',[[x,y+25,-178],[x-34,y+25,-178],[x-34,y+25,-121],[x+20,y+25,-121]],1.8,{attachments:['zplate'],frame:'tool'}),
 {id:'TOOL-HOSE',path:fold(-125,-55-S.a,12,150,(u,v)=>[x+34,y+34-v,u],-1),radius:1,carrier:false,bend:12,designLength:150},
 route('HOSE-LEAD',[[x+34,y+10,-55-S.a],[x+8,y+10,-55-S.a],[x+8,y+10,-45-S.a],[x+5,y+8,-45-S.a]],1,{attachments:['armBody'],frame:'tool'}),
 {id:'HEAD-LEAD',path:opticalLead(c,head),radius:1.3,bend:25,attachments:['sensorUp'],frame:'head'},
 {id:'HEAD-LOOP',path:fold(1180,head+25,27.5,240,(u,v)=>[320+S.r2-v,u,60],-1),radius:1.3,bend:27.5,designLength:240},
 {id:'HEAD-R-RISER',path:upperRiser(S.r2),radius:1.3,bend:20,frame:'cframe'},
 {id:'LOWER-LEAD',path:opticalLead(c,0,true),radius:1.3,bend:20,attachments:['sensorDn'],frame:'cframe'},
 {id:'UP-R-LOOP',path:fold(320,300+S.r2,40,230,(u,v)=>[u,1220,140-v],-1),radius:1.3,bend:40,designLength:230},
 {id:'DN-R-LOOP',path:fold(320,300+S.r2,40,230,(u,v)=>[u,1212,160-v],-1),radius:1.3,bend:40,designLength:230},
 ];
}

// Structural support bars: intentional attachment contact, not free-floating cable geometry.
export const FIXED_SUPPORTS=[
 ['rear chain tray',[570,4,30],[-5,951,-222]],
 ['rear tray left bracket',[25,8,45],[-290,945,-213]],
 ['rear tray right bracket',[40,8,45],[290,945,-213]],
 ['front loom rail with open exit ends',[532,8,12],[0,910,225]],
 ['front rail mount left',[20,20,32],[-240,902,213]],
 ['front rail mount right',[20,20,32],[240,902,213]],
 ['CAM A drop support',[16,96,8],[147,970,233]],
 ['CAM A post bracket',[24,6,90],[131,1006,192]],
 ['CAM B drop support',[10,90,10],[-228,988,81]],
 ['CAM B post bracket',[18,6,50],[-211,1028,61]],
 ['CAM B carrier tip',[14,6,6],[-226,1028,83]],
 ['CAM C vertical carrier',[10,360,10],[75,1120,190]],
 ['CAM C column bracket low',[23,8,39],[52.5,956,173]],
 ['CAM C column bracket high',[23,8,39],[52.5,1260,173]],
 ['CAM C support tip low',[20,8,6],[72,956,190]],
 ['CAM C support tip high',[20,8,6],[72,1260,190]],
 ['optical side carrier',[12,374,10],[320,1098,234]],
 ['optical carrier bracket low',[33,6,20],[330,936,239]],
 ['optical carrier bracket high',[33,6,20],[330,1254,239]],
 ['optical stationary loop anchor',[8,4,66],[320,1206,167]],
 ['optical anchor side arm',[20,4,6],[328,1206,197]],
 ['optical anchor post arm',[8,4,40],[338,1206,217]],
 ['optical upper anchor standoff',[8,9,8],[320,1212.5,140]],
];
export function movingSupports(S,s){
 const x=S.tx,y=S.zt,r=S.r2,head=YS+s.base+s.wd+70+S.headLift;
 return [
 ['X chain carriage anchor',[10,12,80],[x-21,1030,-196],['zcol']],
 ['X chain endpoint seat',[18,8,6],[x-10,1020,-231],[]],
 ['Z chain endpoint seat',[36,4,8],[x-14,y+19,-184],[]],
 ['Z chain side bracket',[6,4,46],[x-30,y+19,-165],[]],
 ['Z chain plate attachment',[14,4,10],[x-24,y+19,-143],['zplate']],
 ['valve / vacuum manifold',[12,16,20],[x+20,y+25,-121],[]],
 ['manifold bolted bracket',[26,4,40],[x+23,y+18,-128],['zplate']],
 ['hose anchor',[7,8,10],[x+34,y+34,-125],[]],
 ['fiber routing upright',[8,285,8],[320+r,1084.5,88],[]],
 ['fiber clamp support upper',[12,8,65],[300+r,1180,55],['colC']],
 ['fiber clamp support lower',[12,8,65],[300+r,955,55],['colC']],
 ['fiber clamp support R',[12,8,65],[300+r,1190,55],['colC']],
 ['fiber support tip upper',[30,8,8],[313+r,1180,88],[]],
 ['fiber support tip lower',[30,8,8],[313+r,955,88],[]],
 ['fiber support tip R',[30,8,8],[313+r,1190,88],[]],
 ['head collar bracket',[30,6,8],[X2+r+20,head-15,12],['sensorUp']],
 ['head lead upright',[8,40,8],[X2+r+35,head+5,12],[]],
 ['head lead support',[8,6,52],[X2+r+35,head+25,36],[]],
 ['head loop moving anchor',[12,6,8],[X2+r+41,head+25,60],[]],
 ];
}
