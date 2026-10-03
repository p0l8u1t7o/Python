// Millimetres; cabinet planning envelopes, not vendor CAD or construction wiring.
import * as THREE from 'three';
const mat=(color,metalness=.15)=>new THREE.MeshStandardMaterial({color,metalness,roughness:.48});
const metal=mat(0xaab8bf,.7),black=mat(0x25333d),white=mat(0xd8ddd9),green=mat(0x32887b),yellow=mat(0xdfba35),blue=mat(0x346b94);
export const CIRCUITS={ac:{label:'動力／AC',color:0xe8a052},dc:{label:'24 VDC',color:0x4d9cec},network:{label:'通訊',color:0x53d3ba},safety:{label:'安全交握',color:0xefda57},signal:{label:'感測／I/O',color:0xc293ec}};
function box(p,n,s,at,m=metal){const o=new THREE.Mesh(new THREE.BoxGeometry(...s),m);o.name=n;o.position.set(...at);o.castShadow=true;p.add(o);return o;}
function badge(p,text,w,h,at){
  if(typeof document==='undefined')return;
  const c=document.createElement('canvas'),ctx=c.getContext('2d');if(!ctx?.measureText)return;
  c.width=512;c.height=128;ctx.fillStyle='#102733';ctx.fillRect(0,0,512,128);ctx.fillStyle='#eaf9fc';ctx.font='bold 46px sans-serif';ctx.textAlign='center';ctx.textBaseline='middle';ctx.fillText(text,256,64,490);
  const t=new THREE.CanvasTexture(c);t.colorSpace=THREE.SRGBColorSpace;
  const m=new THREE.Mesh(new THREE.PlaneGeometry(w,h),new THREE.MeshBasicMaterial({map:t}));m.position.set(...at);p.add(m);
}
const part=(id,kind,title,size,role,description,source,category='dc',model='配置估算，型號待選')=>({id,kind,title,size,role,description,source,category,model});
function supply(compact=false){return [
  part('QS1','isolator','總電源隔離開關',[compact?36:54,75,65],'power','檢修時隔離設備電源；額定電流與現場電源待確認。',null,'ac'),
  part('QF1','breaker','控制支路保護',[compact?18:36,75,65],'power','分支保護後供應 24 V 電源，與伺服動力分路。','QS1','ac'),
  part('PS1','psu','24 VDC 電源',[compact?50:65,95,100],'power','供應 PLC、I/O、光源控制及感測器；容量需依負載表確認。','QF1','ac'),
  part('GC1','safety','安全控制器',[60,90,95],'safety','收集急停與防護裝置訊號，交握驅動停止及重啟允許；此畫面僅呈現規劃。','PS1','dc','GC-1000 規劃平台；外形 60×90×95 mm'),
  part('K1','contactor','監控接觸器',[compact?32:50,75,70],'safety','安全輸出控制動力支路，輔助接點回授；回路需另做風險評估與設計。','GC1','safety')];}
function logic(compact=false){return [
  part('PLC1','plc','設備 PLC',[compact?80:100,90,85],'control','管理站序、到位互鎖與配方交握。','PS1','dc','KV-X 系列規劃平台；模組外形估算'),
  part('IO1','io','分散式 I/O',[compact?50:70,80,65],'io','接收止擋、夾緊、到位與壓力訊號，輸出電磁閥及指示燈。','PLC1','signal'),
  part('SW1','switch','工業乙太網交換器',[40,80,70],'network','連接 PLC、視覺電腦、手臂及上位系統。','PS1','dc'),
  part('LC1','light','頻閃光源控制器',[compact?45:70,70,70],'vision','配合相機觸發時序驅動光源，檢視狀態隨主時間軸。','IO1','signal')];}
const ipc=()=>part('IPC1','ipc','視覺工業電腦',[160,95,100],'vision','相機取像、配方辨識、補正與結果紀錄；與 PLC 交換 Ready／Busy／OK／NG。','SW1','network');
const force=()=>part('FT1','io','力覺介面',[50,70,65],'force','接收末端 F/T 訊號，提供接觸力監看與製程判斷。','IO1','signal');
const drive=(id,title)=>part(id,'drive',title,[45,100,110],'motion','伺服功率級、回授及運動命令介面；軸功率、編碼器與煞車選型待確認。','QF2','ac');
export function panelSchedule(profile){
  const qf2=()=>part('QF2','breaker','動力支路保護',[36,75,65],'power','獨立供應驅動器／馬達支路；與控制电源分區。','QS1','ac');
  if(profile==='acid')return [{y:20,items:supply(true).map(d=>d.id==='PS1'?{...d,description:'供應儀器交握 I/O、序列介面與夾座控制；天平與滴定儀保留原廠電源。'}:d)},{y:-110,items:[
    part('IO1','io','儀器交握 I/O',[50,75,65],'io','由桌面整合電腦指揮，接收杯到位、液位與夾座狀態。','PS1','dc'),
    part('SW1','switch','儀器網路交換器',[40,75,65],'network','連接整合電腦與 CRC9；滴定儀原廠軟體負責分析。','PS1','dc'),
    part('SER1','gateway','天平序列介面',[40,70,55],'weigh','天平穩定、去皮與重量資料經序列介面回傳整合電腦。','IO1','signal'),
    part('REM1','io','Metrohm Remote 交握',[60,70,65],'analysis','tiamo 主案：Start／Ready／Busy 交握與樣品表、結果檔整合；OMNIS 為替代介面。','IO1','signal','Remote Box 功能包絡，型號待確認'),
    part('PIP1','gateway','移液 RS-485 介面',[40,70,55],'pipette','傳送吸液、吐液、吹出與退吸頭命令，回讀移液完成。','IO1','signal')]}];
  if(profile==='military')return [{y:40,items:supply(true)},{y:-100,items:[...logic(true),force()]}];
  if(profile==='military-motion')return [{y:40,items:[...['手臂直線軌道','S0 進料升降','S4 出料升降','S1 取像頭'].map((s,i)=>drive('D'+(i+1),s+'驅動'))]},{y:-100,items:[drive('D5','S3 翻轉驅動'),drive('D6','輸送驅動'),part('EC1','plc','周邊運動交握',[70,85,75],'motion','與主 PLC 同步滑軌、堆料升降、取像頭、翻轉與輸送；周邊驅動數量為規劃假設。',null,'network')]},{y:-185,items:[{...ipc(),size:[160,40,95]}]}];
  if(profile==='pcb'){
    const axes=[];for(const head of ['A','B'])for(const axis of ['X','Y','Z1','T1','Z2','T2','Z3','T3','Z4','T4'])axes.push(drive(head+axis,head+' 頭 '+axis.replace('T','θ')+' 驅動'));
    for(const axis of ['S1X','S1Y','S3X','S3Y','LOADX','LOADZ','UNLOADX','UNLOADZ'])axes.push(drive(axis,axis+' 驅動'));
    return [{y:95,items:[...supply(),qf2(),...logic(),ipc(),part('EC1','plc','EtherCAT 運動主控',[110,95,90],'motion','雙頭各 XY＋4 組 Z/θ，共 20 軸；另規劃定位、檢查與上下料 8 軸。','SW1','network')]},{y:-120,items:axes}];
  }
  return [{y:45,items:[...supply(),qf2()]},{y:-110,items:[...logic(),ipc(),...(profile==='ssd'?[force()]:[part('VAC1','io','真空／壓力介面',[65,75,65],'vacuum','確認 T1/T2 吸附與破真空、T3 夾持及治具夾緊；對應閥島與壓力開關。','IO1','signal')])]}];
}

export function electricalActivity(role,state){
  const activity={force:/壓|按|力|接觸|撥|開門/,vacuum:/吸|取|移|放|夾/,pipette:/吸液|吐液|移液|潤洗|吸頭/,weigh:/秤|稱|天平/,analysis:/滴定|分析|進樣|等待/};
  if(role==='vision')return !!state.vision;
  if(role==='motion')return state.motion!==false&&!/待命|等待|完成|判定|取像|保壓/.test(state.action||'');
  if(activity[role])return activity[role].test(state.action||'');
  if(role==='io')return !!state.action;
  return ['power','control','network','safety'].includes(role);
}

export function electricalDevice(parent,spec,at){
  const g=new THREE.Group();g.position.set(...at);g.name=spec.id+' / '+spec.title;parent.add(g);
  const [w,h,d]=spec.size,bodyMat=spec.kind==='safety'?yellow:spec.kind==='valve'?blue:['psu','ipc','robot'].includes(spec.kind)?metal:['breaker','isolator'].includes(spec.kind)?white:black;
  const body=box(g,g.name+' / body',[w,h,d],[0,0,d/2],bodyMat);body.userData.electricalBody=true;
  // DIN latch / bolted mounting block joins the mounting plane to the housing.
  box(g,'mounting shoe',[Math.min(w-4,30),Math.min(h-6,25),7],[0,0,-3.5],metal);
  if(['isolator','breaker','contactor'].includes(spec.kind)){
    box(g,'switch recess',[w*.6,h*.4,2],[0,0,d+1],black);
    if(spec.kind==='isolator'){
      const dial=new THREE.Mesh(new THREE.CylinderGeometry(w*.25,w*.25,3,24),yellow);dial.rotation.x=Math.PI/2;dial.position.z=d+3;g.add(dial);
      box(g,'rotary isolator grip',[w*.14,h*.28,9],[0,0,d+8],mat(0xba483e));
    }else box(g,'switch handle',[w*.4,h*.16,8],[0,h*.07,d+5],blue);
  }else{
    if(spec.kind==='valve')for(let i=0;i<6;i++)box(g,'solenoid coil / '+(i+1),[17,18,4],[-w/2+13+i*23,7,d+2],black);
    for(let i=0;i<5;i++)box(g,'vent slot',[w*.65,1.5,1],[0,h*.23-i*4,d+.5],black);
    if(['plc','safety','drive','light'].includes(spec.kind))box(g,'status display',[w*.55,h*.18,1],[0,h*.03,d+1.3],mat(0x123a47));   // 比通風槽前凸 0.8 mm，不共面
    if(['psu','ipc','drive'].includes(spec.kind))for(let i=0;i<5;i++)box(g,'heat sink fin',[2,h*.68,5],[-w*.4+i*w*.2,0,d+2.5],metal);
    if(['switch','ipc','robot','gateway'].includes(spec.kind))for(let i=0;i<Math.max(2,Math.min(5,Math.floor(w/22)));i++){
      const x=-w*.35+i*16;box(g,'RJ45 / service socket',[12,9,2],[x,-h*.15,d+1],metal);box(g,'socket aperture',[9,6,1],[x,-h*.15,d+2.4],black);   // 前面比插座外殼凸 0.9 mm
    }
  }
  for(const x of [-w*.28,w*.28]){
    box(g,'terminal plug',[Math.min(12,w*.25),8,12],[x,-h/2+4.8,d*.65],green);   // 底面高於機身底面 0.8 mm
    const ferrule=new THREE.Mesh(new THREE.CylinderGeometry(1.8,1.8,4,8),metal);ferrule.position.set(x,-h/2-1,d*.65);g.add(ferrule);
  }
  const ledMaterial=new THREE.MeshStandardMaterial({color:0x297f60,emissive:0x35e2a1,emissiveIntensity:.12});
  const led=['isolator','breaker','contactor'].includes(spec.kind)?null:box(g,'RUN / activity lamp',[3,3,1],[-w*.34,h*.34,d+1],ledMaterial);
  badge(g,spec.id,w*.82,Math.min(15,h*.18),[0,-h*.34,d+3]);
  g.userData.electrical={...spec};g.userData.electricalLed=led;return g;
}

function internalWire(parent,id,from,to,points,category){
  const path=new THREE.CurvePath();const vs=points.map(p=>new THREE.Vector3(...p));
  for(let i=1;i<vs.length;i++)if(vs[i].distanceTo(vs[i-1])>.01)path.add(new THREE.LineCurve3(vs[i-1],vs[i]));
  const m=new THREE.Mesh(new THREE.TubeGeometry(path,Math.max(24,vs.length*8),.8,6,false),mat(CIRCUITS[category].color));
  m.name=id;m.userData.electricalWire={from,to,category,points};parent.add(m);return m;
}
export function populatePanel(panel,{profile,width,height}){
  const rows=panelSchedule(profile),devices=new Map(),g=new THREE.Group();g.name='electrical planning / '+profile;panel.add(g);
  const rowBottom=new Map();
  for(const row of rows){
    const gap=14,total=row.items.reduce((a,x)=>a+x.size[0],0)+gap*(row.items.length-1);
    if(total>width*.83)throw new Error(profile+' equipment does not fit panel width');
    let x=-total/2;
    const bottom=row.y-Math.max(...row.items.map(x=>x.size[1]))/2-13;
    for(const item of row.items){x+=item.size[0]/2;const o=electricalDevice(g,item,[x,row.y,15]);devices.set(item.id,o);rowBottom.set(item.id,bottom);x+=item.size[0]/2+gap;}
    box(g,'device DIN rail',[Math.max(total,80),35,5],[0,row.y,5.5]);
    for(const x of [-total*.4,total*.4])box(g,'rail fixing spacer',[12,14,3],[x,row.y,3.5]);
    box(g,'horizontal wire duct base',[width*.87,18,3],[0,bottom,8.8],black);   // 與直立線槽底板錯開 0.8 mm
    {const lim=width*.45-19;for(let x=-lim;x<=lim;x+=24)for(const dy of [-8,8])box(g,'duct comb',[8,2,24],[x,bottom+dy,20],black);}   // 梳齒止於直立線槽指片內側；寬 8，側面不與上方元件機身齊平
    for(const x of [-width*.30,width*.30])box(g,'duct mounting spacer',[12,12,5],[x,bottom,4.5]);   // 讓開 PE 接地柱（x −0.35w）
  }
  const terminalY=height*.3-15,pitch=Math.min(25,width/18);
  let index=0;
  for(const [id,dst] of devices){
    const s=dst.userData.electrical,src=devices.get(s.source),category=s.category,side=(category==='ac'?-1:1)*width*.45,z=18+Object.keys(CIRCUITS).indexOf(category)*2;
    const pin=(o,sign)=>[o.position.x+sign*o.userData.electrical.size[0]*.28,o.position.y-o.userData.electrical.size[1]/2-3,15+o.userData.electrical.size[2]*.65];
    const b=pin(dst,-1),yb=rowBottom.get(id),a=src?pin(src,1):[(index%12-5.5)*pitch,terminalY,20],ya=src?rowBottom.get(s.source):terminalY-16;
    internalWire(g,'NET / '+(src?s.source:'X1')+' → '+id,src?s.source:'X1',id,[a,[a[0],ya,a[2]],[a[0],ya,z],[side,ya,z],[side,yb,z],[b[0],yb,z],[b[0],yb,b[2]],b],category);index++;
  }
  panel.userData.electricalProfile=profile;return devices;
}

export function robotController(parent,{at,crc=false,id='RC1',floor=4}){
  const size=crc?[420,200,360]:[357,94,320];
  const d=electricalDevice(parent,part(id,'robot',crc?'COBOTTA PRO 控制器':'手臂控制器',size,'motion',crc?'CRC9M 專用控制器，整合電腦下達任務；控制手臂及末端。':'RC8A 負責手臂軸控制，PLC 交握任務、完成與異常。',null,'ac',crc?'CRC9M 標準型；420×200×360 mm':'RC8A 標準型包絡；357×94×320 mm'),at);
  // Controller rests on a bolted shelf, not on a DIN rail.
  d.children.find(m=>m.name==='mounting shoe').visible=false;
  const bottom=at[1]-size[1]/2;
  box(parent,id+' shelf',[size[0]+12,4,size[2]+4],[at[0],bottom-2,at[2]+size[2]/2]);
  for(const x of [-size[0]*.4,size[0]*.4])for(const z of [18,size[2]-18])box(parent,id+' shelf foot',[14,bottom-4.8-floor,14],[at[0]+x,(bottom-4.8+floor)/2,at[2]+z]);   // 頂面低於腳座頂 0.8 mm
  return d;
}
export function controllerLeads(parent,controller,panel){
  const d=controller.userData.electrical,[w,h,depth]=d.size,at=controller.position;
  for(const [i,category] of ['ac','network'].entries()){
    const a=panel.ports[i],b=[at.x+(i?1:-1)*w*.28,at.y-h/2-3,at.z+depth*.65];
    const side=panel.group.position.x-panel.group.userData.controlPanel.width*.45-i*3;
    const z=panel.group.position.z+24+i*3,y=b[1]-1;
    internalWire(parent,'RC service / '+category,'X1',d.id,[a,[a[0],a[1]+28,a[2]],[side,a[1]+28,z],[side,y,z],[b[0],y,z],[b[0],y,b[2]],b],category);
  }
}
