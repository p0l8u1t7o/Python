// 單台循環的動作序列：通用的步驟排程（起訖快照、插值、stationStart、total、events）由 core 的 createStepSequence 處理，
// 本檔只加上本站專屬的一層：手臂位姿（每步起訖位姿、PTP／直線、偏軸 TCP 轉向、低位退離）、護蓋開度插值與力值曲線。
import * as THREE from 'three';
import { createStepSequence } from '@core/anim/sequence.js';
import { smooth } from '@core/anim/track.js';
import { NB, DOOR_OPEN_DEG } from './notebook.js';
import { LAYOUT } from './cell.js';
export { smooth };   // 五次 S 曲線（起訖速度、加速度為 0）；project.js、main.js 沿用
const clone=s=>JSON.parse(JSON.stringify(s));
// 開關量：步驟開始時切換，不插值（force 另由 forceCurve 覆寫）
const DISCRETE=['station','flashTool','flashTop','flashSn','laserTool','seamLaser','force'];

export function createSequence({nb,robot,apply}){
  const base={palletX:-2000,lift:0,palletLift:0,flip:0,clamp:0,cradleClamp:0,cradleLift:LAYOUT.cradlePark,inStackY:0,outStackY:0,inLift:0,outLift:0,pushIn:0,pushOut:550,inFork:1,outFork:1,located:false,s1Head:0,
    doors:nb.doors.map(()=>({open:0,latch:0})),force:0,zone:'free',flashTop:0,flashSn:0,flashTool:0,laserTool:0,seamLaser:-1,tower:'yellow',station:0,action:'',sub:''};
  // apply 由本層呼叫（要在建立步驟前先算終點位姿與退離判斷），core 不重複套用
  const seq=createStepSequence({base,discrete:DISCRETE,ease:smooth,stations:[0,1,2,3,4]});
  const {steps,stationStart}=seq,top=LAYOUT.conveyorTop+6+LAYOUT.palletH+LAYOUT.padH+LAYOUT.footOffset;
  const down=new THREE.Vector3(0,-1,0),v=(x,y,z)=>new THREE.Vector3(x,y,z);
  const pose=(tcp,target,dir=down,rail=0)=>robot.poseFor(tcp,target,dir,rail);
  // 偏軸 TCP（鉤爪、壓頭、線雷射）繞工具軸轉動，讓相機與環形光位於 TCP 正上方：
  // 在門的高度作業時，環形光、鏡頭、輪廓儀不會壓到載具框、四角側夾與堆疊柱。
  const TCP={cam:robot.tcpCam,hook:robot.tcpHook,press:robot.tcpPress,laser:robot.tcpLaser},RING=v(0,0,130);
  const up=(tcp,target,dir,rail)=>{
    const p=pose(tcp,target,dir,rail),o=RING.clone().sub(TCP[tcp].position),roll=Math.atan2(o.x,o.y);
    const rotation=p.rotation.clone().multiply(new THREE.Quaternion().setFromAxisAngle(v(0,0,1),roll));
    return {...p,rotation,origin:target.clone().sub(TCP[tcp].position.clone().applyQuaternion(rotation))};
  };
  // 待命位姿：TCP 在 y=1150、z=-220（離滑軌 340 mm）。手腕折疊 J5≈91°，
  // 側裝工具在 J2 上方，手腕本體也不碰前臂端蓋（舊位姿 z=-380 時 J5≈115° 會自我干涉）。
  const park=x=>({...pose('cam',v(x,1150,-220),down,x),fresh:true});
  let lastPose=park(-1000);
  // 與 core add 相同的參數，另加 motion(t, state)：手臂位姿路徑（null＝維持上一步的位姿）
  function add(st,dur,action,sub,values={},motion=null,extra={}){
    // 預先組出終點狀態（與 core add 的結果相同），套用到場景後才能算護蓋座標與終點位姿
    const end=clone(seq.state);
    for(const [key,value] of Object.entries(values))end[key]=clone(value);
    end.station=st;end.action=action;end.sub=sub;
    apply(end);const destination=motion?motion(1,end):lastPose;
    // Before rotating a low tool, withdraw along its existing optical/tool
    // axis. Camera poses already have 150 mm working distance; extra outward
    // travel there would enter the neighboring flip motor. The shorter laser
    // and contact TCPs need this withdrawal before turning away.
    if(motion&&!extra.path&&!extra.contact&&!extra.retracted&&end.zone==='free'&&lastPose.tcp!=='cam'&&lastPose.origin.y<1000&&lastPose.rotation.angleTo(destination.rotation)>.2){
      const from=lastPose,away=from.origin.clone().addScaledVector(v(0,0,1).applyQuaternion(from.rotation),-120);
      add(st,1.4,'直線退離：'+action,'保持工具朝向，沿法線退出 120 mm 後才轉腕',{zone:'slow',force:0,flashTool:0,laserTool:0},
        t=>({origin:from.origin.clone().lerp(away,smooth(t)),rotation:from.rotation.clone(),tcp:from.tcp,rail:from.rail}),{path:true});
      return add(st,dur,action,sub,{...values,zone:'free'},motion,{...extra,retracted:true});
    }
    const s=seq.add(st,dur,action,sub,values,{pose0:lastPose,motion,...extra});
    s.ptp=!s.path&&!s.contact&&end.zone==='free';
    // Door world coordinates must be evaluated after installing this endpoint state.
    lastPose=destination;s.pose1=lastPose;
    return s;
  }
  // 在門的高度作業完後，先保持朝向垂直上升，再以關節插值轉位：避免 PTP 從低位掃過載具堆疊柱與皮帶
  function liftAway(st,label){
    if(lastPose.origin.y>=1000)return;
    const from=lastPose;
    add(st,1.2,'直線上升：'+label,'保持工具朝向，垂直上升 150 mm 後才轉腕',{force:0,flashTool:0,laserTool:0},
      t=>({origin:from.origin.clone().add(v(0,150*smooth(t),0)),rotation:from.rotation.clone(),tcp:from.tcp,rail:from.rail}),{path:true});
  }
  function doorsAt(index,open,latch){const values=clone(seq.state.doors);values[index]={open,latch};return values;}
  const surface=(x,y,z,s)=>v(s.palletX+x,top+y+s.lift,z);
  const lower=(x,z,s)=>v(s.palletX+x,top+s.lift+NB.H,-z);
  const photo=(st,label,point,sub,extra={})=>{
    add(st,2.5,'相機定位：'+label,'沿預定接近路徑移動，等待 TCP 到位',{},(t,s)=>pose('cam',point(s),down,s.palletX));
    add(st,.55,'取像：'+label,sub,{flashTool:1},null,{...extra,exposure:true});
    add(st,.25,'影像確認：'+label,'模擬影像事件；缺陷演算法待導入',{flashTool:0});
  };
  // Magazine: separate upper stack, drive one pallet, retract then index.
  add(0,.6,'上層托叉承重確認','托叉支承上層載具；升降平台支承最底層',{inFork:1,located:true});
  add(0,2.8,'推出最底層載具','推板與載具後緣同步前進 550 mm，上層載具保持支承',{palletX:-1450,pushIn:550,located:false});
  add(0,1.6,'推料氣缸復歸','推桿完全退出後才允許升降平台動作',{pushIn:0,located:true});
  add(0,.8,'升降平台接住上層','平台上升至托叉承載面',{inStackY:0,palletLift:0,inLift:110});
  add(0,.45,'托叉退出','升降平台已承重，解除上層托叉',{inFork:0});
  add(0,1.4,'進料堆下降一個間距','上層載具隨平台下降 110 mm，下一台進入推料高度',{inStackY:-110,inLift:0});
  add(0,.45,'托叉重新承重','插入下一層載具下方，準備下一循環',{inFork:1});
  add(0,.65,'讀取底面 SN','底視讀碼器穿過載具開口；本次 SN 為 DEMO-0001',{flashSn:1},null,{done:'sn',exposure:true});
  add(0,.7,'四角側夾定位','四個 PU 接觸墊夾住護角，避開側面護蓋',{flashSn:0,clamp:1},null,{done:'locate'});
  add(0,2.4,'輸送至 S1','止擋下降 → 雙帶同步輸送 → 到站減速',{palletX:-1000,located:false});
  add(1,.5,'S1 止擋定位','載具到位感測 ON，止擋上升，等待振動衰減',{located:true});
  add(1,1.6,'取像頭移入','頂視相機＋穹頂光沿懸臂滑軌移到產品正上方，穹頂底緣距產品 80 mm',{s1Head:1});
  add(1,.7,'頂視外蓋取像','QII §12.1 / 工單前 PI：Logo、麥拉、外蓋掉漆／破損與螺絲',{flashTop:1},null,{done:'lid',exposure:true});
  add(1,.3,'頂光關閉','準備側面相機巡拍',{flashTop:0});
  add(1,1.6,'取像頭退出','取像頭退回前側，讓出手臂巡拍空間',{s1Head:0});
  // 前、後側與手臂滑軌平行：VM-60B1 手腕 ±120°，無法水平回頭取像，改由斜上方 35° 取像；
  // 後側緊鄰肩部，滑軌再錯開 REAR_RAIL，讓肩部離開產品正後方。
  const oblique=(z)=>[0,Math.sin(35*Math.PI/180),z*Math.cos(35*Math.PI/180)];
  const REAR_RAIL=500;
  const sides=[['左側',[-150,18,0],[-1,0,0],'相機與產品保持 150 mm 工作距離',0],['後側',[0,18,-107],oblique(-1),`斜上方 35° 取像，工作距離 150 mm；滑軌錯開 ${REAR_RAIL} mm`,REAR_RAIL],['右側',[150,18,0],[1,0,0],'相機與產品保持 150 mm 工作距離',0],['前側',[0,26,108],oblique(1),'斜上方 35° 取像，工作距離 150 mm',0]];
  sides.forEach(([name,p,n,note,railShift],i)=>{
    add(1,2.8,'退至上方再轉向：'+name,'工具先離開產品包絡，轉腕後接近下一側',{},()=>park(-1000));
    add(1,2.6,'側面定位：'+name,note,{},(t,s)=>pose('cam',surface(...p,s),v(...n).normalize().negate(),-1000+railShift));
    add(1,.6,'側面取像：'+name,'門扣、圖示、按鍵外觀；功能與彈性測試留待後續階段',{flashTool:1},null,{exposure:true,done:i===3?'sides':null});
    add(1,.2,'關閉環形光','曝光完成',{flashTool:0});
  });
  add(1,2.8,'接縫掃描準備','工具退至上方，切換線雷射 TCP',{},()=>park(-1000));
  // 接縫掃描：雷射 TCP 在外蓋上方 8 mm（量測範圍 25 mm 內），比 TCP 低 5 mm 的鉤爪尖端不刮外蓋
  add(1,2.4,'線雷射起點定位','QII §10.1：LCD cover / AB 接縫 Gap 與 Step ≤ 0.5 mm；實際 ROI 待確認',{},(t,s)=>pose('laser',surface(-125,44,-94,s),down,-1000));
  add(1,5,'沿外蓋後緣掃描','保留輪廓與高度差；不將通用外觀表套用到所有接縫',{laserTool:1,seamLaser:1},(t,s)=>pose('laser',surface(-125+250*smooth(t),44,-94,s),down,-1000),{path:true,done:'seam'});
  add(1,2.8,'手臂退讓至安全高度','掃描完成、光源關閉；輸送許可等待手臂到位',{laserTool:0,seamLaser:-1},()=>park(0));
  add(1,3.5,'輸送至 S2','止擋下降後輸送，四角側夾保持夾緊',{palletX:0,located:false});
  add(2,.5,'S2 止擋定位','載具到位、相機配方與工單一致',{located:true});
  nb.doors.forEach((d,i)=>{
    const def=d.def,rail=def.side==='L'?-350:def.side==='R'?575:-450;   // 右側門滑軌 575：手臂在門的正後方，前臂沿 z 伸出，不靠近 S3 翻轉治具
    // 線雷射一律由斜上方 20° 掃描：面向手臂的護蓋避免手腕超過 ±120°；左右側護蓋讓 TCP 後方 105 mm 的輪廓儀抬高，不壓到載具框。
    const N=()=>d.normalWorld(),dir=()=>N().negate(),laserDir=()=>dir().add(v(0,-Math.tan(20*Math.PI/180),0)).normalize(),edge=(open,latch,offset=0)=>d.edgeWorldAt(open,latch).addScaledVector(N(),offset);
    liftAway(2,def.id+' 上方轉位');
    add(2,2.5,def.id+' 上方轉位',def.name+'｜在產品上方轉腕與滑軌移位',{},()=>park(rail));
    if(def.side==='R'){
      add(2,2,def.id+' 側面預備點','先在門面上方 300 mm 完成轉腕，避開 S3 立柱',{},()=>pose('cam',d.centerWorld().add(v(0,300,0)),dir(),rail));
      add(2,2.5,def.id+' 視覺定位',def.name+'｜保持朝向，直線下降至門面取像高度',{},t=>pose('cam',d.centerWorld().add(v(0,300*(1-smooth(t)),0)),dir(),rail),{path:true});
    }else add(2,2.5,def.id+' 視覺定位',def.name+'｜相機確認門扣／圖示／封印',{},()=>pose('cam',d.centerWorld(),dir(),rail));
    add(2,.5,def.id+' 門面取像',def.sealed?'封印與外觀檢查；本階段不拆拔模組':'確認門扣關閉、取得視覺修正位置',{flashTool:1},null,{exposure:true,done:def.sealed?def.id:null});
    add(2,.25,def.id+' 關閉取像光','曝光完成',{flashTool:0});
    if(def.sealed)return;
    add(2,1.8,def.id+' 切換鉤爪 TCP','相機退離後鉤爪接近至門扣外 100 mm',{},()=>up('hook',edge(0,0,100),dir(),rail));
    add(2,3.6,def.id+' 減速接近門扣','100 → 6 mm；五次曲線峰值速度小於 50 mm/s',{zone:'slow'},()=>up('hook',edge(0,0,6),dir(),rail));
    add(2,.9,def.id+' 力控接觸','鉤尖接觸門扣；2 N 為工程模擬設定',{zone:'contact',force:2},()=>up('hook',edge(0,0),dir(),rail),{contact:true});
    add(2,.8,def.id+' 抬起門扣 3 mm','QII §12.1：先拉起門上邊沿，再打開',{doors:doorsAt(i,0,1),force:3},(t,s)=>up('hook',edge(0,s.doors[i].latch),dir(),rail),{path:true,contact:true});
    add(2,2.2,def.id+' 沿鉸鏈弧線開門',`鉤尖跟隨同一門緣座標；示意開度 ${DOOR_OPEN_DEG}°`,{doors:doorsAt(i,1,1),force:2},(t,s)=>up('hook',edge(s.doors[i].open,1),dir(),rail),{path:true,contact:true});
    add(2,1.2,def.id+' 鉤爪脫離','沿外法線退出 100 mm，再切換相機',{force:0,zone:'slow'},()=>up('hook',edge(1,1,100),dir(),rail));
    add(2,2.4,def.id+' 連接器對焦','相機工作距離 150 mm；曝光前等待到位',{},()=>pose('cam',d.centerWorld(),dir(),rail));
    add(2,.65,def.id+' 連接器取像','端子數量、異物、損 pin、門內麥拉；不執行通電介面測試',{flashTool:1},null,{exposure:true});
    add(2,.3,def.id+' 取像完成','關閉環形光',{flashTool:0});
    add(2,1.4,def.id+' 鉤爪預備','鉤爪 TCP 移到開啟的門緣外 100 mm',{},()=>up('hook',edge(1,1,100),dir(),rail));
    add(2,2.2,def.id+' 返回開門邊緣','重新以鉤爪 TCP 對準護蓋上緣（直線減速接近）',{zone:'slow'},()=>up('hook',edge(1,1),dir(),rail));
    add(2,2.2,def.id+' 保持門扣拉起並閉門','依 QII 關門順序：拉起上邊沿 → 關緊 → 按下鎖定',{doors:doorsAt(i,0,1),force:2,zone:'contact'},(t,s)=>up('hook',edge(s.doors[i].open,1),dir(),rail),{path:true,contact:true});
    add(2,1.2,def.id+' 鉤爪退出換壓頭','先退離再切換壓頭接觸點',{force:0,zone:'slow'},()=>up('press',edge(0,1,18),dir(),rail));
    add(2,.9,def.id+' 壓頭接觸門扣','PU 壓頭到位後才允許下壓鎖扣',{zone:'contact'},()=>up('press',edge(0,1),dir(),rail),{contact:true});
    add(2,1,def.id+' 按下鎖定','壓頭隨門扣下行；8 N 峰值為示意值，需實測校正',{doors:doorsAt(i,0,0)},(t,s)=>up('press',edge(0,s.doors[i].latch),dir(),rail),{path:true,contact:true,forceCurve:t=>8*Math.sin(Math.PI*t)});
    add(2,2.2,def.id+' 閉合量測定位','壓頭退出，切換線雷射至護蓋外表面',{force:0,zone:'free'},()=>up('laser',d.centerWorld(),laserDir(),rail));
    add(2,.7,def.id+' 閉合確認','外觀、鎖扣回位、膠條未外露；保留輪廓待配方判定',{laserTool:1},null,{done:def.id,exposure:true});
    add(2,.2,def.id+' 掃描關閉','準備下一個護蓋',{laserTool:0});
  });
  liftAway(2,'手臂退出翻轉包絡');
  add(2,3,'手臂退出翻轉包絡','所有護蓋閉合，工具移到翻轉治具外上方',{force:0,zone:'free'},()=>park(1000));
  add(2,3.5,'輸送至 S3','四角側夾保持夾緊；翻轉治具停在上方、夾臂張開',{palletX:LAYOUT.stationX[3],located:false});
  add(3,.5,'S3 止擋定位','載具到位與翻轉軸原點確認',{located:true});
  add(3,1.4,'翻轉治具下降',`夾臂張開，從待命高度下降 ${LAYOUT.cradlePark} mm 至夾持高度`,{cradleLift:0});
  add(3,.85,'翻轉夾臂先夾緊','PU 夾墊接触護角，夾持完成後才鬆開載具側夾',{cradleClamp:1});
  add(3,.7,'載具側夾鬆開','翻轉夾持仍保持，交接期間不失去約束',{clamp:0});
  add(3,1.8,`抬升 ${LAYOUT.flipLift} mm`,'清出定位銷、堆疊柱與旋轉掃掠包絡',{lift:LAYOUT.flipLift,cradleLift:LAYOUT.flipLift});
  add(3,2.8,'翻面 180°','S 曲線起停，繞輸送 X 軸旋轉；手臂維持退讓',{flip:1},null,{done:'flip'});
  add(3,.5,'旋轉軸煞車確認','停穩後才允許近距離取像',{});
  photo(3,'底殼法規印刷',s=>lower(66,-55,s),'QII §10.2 / 工單前 PI：白色字體、法規標誌與可辨識性',{done:'print'});
  photo(3,'SN 與警語',s=>lower(-5,-40,s),'依工單核對安規、SN、鈕扣電池警語；OS／CPU 位於閉合機內，待後續工位',{done:'labels'});
  photo(3,'外露 Docking 接點',s=>lower(-82,61,s),'實機照片為外露接點，直接檢查翹 pin／損 pin／異物；無底面開蓋動作',{done:'dock'});
  for(const [i,x,z] of [[0,-108,60],[1,75,52],[2,-60,-72],[3,85,-73]])photo(3,'螺絲／腳墊區域 '+(i+1),s=>lower(x,z,s),'QII §16：檢查螺絲頭十字 R 角；照片建模數量不代替 BOM',{done:i===3?'screws':null});
  add(3,3,'相機退離翻轉治具','確認工具已離開旋轉包絡，再解除旋轉軸煞車',{},()=>park(1100));
  add(3,2.8,'翻回 0°','護蓋保持閉合，夾臂保持夾持',{flip:0});
  add(3,1.8,'下降至載具承載墊','平順下降，落座後才重新夾緊',{lift:0,cradleLift:0});
  add(3,.7,'載具四角側夾夾緊','承載墊落座、定位到位',{clamp:1});
  add(3,.85,'翻轉夾臂鬆開','載具側夾完成後解除翻轉夾持',{cradleClamp:0},null,{done:'return'});
  add(3,1.4,'翻轉治具上升',`夾臂張開上升 ${LAYOUT.cradlePark} mm，讓出輸送通道`,{cradleLift:LAYOUT.cradlePark});
  add(3,2.8,'手臂回待命位置','工具退回後開放 S4 輸送',{},()=>park(0));
  add(3,2.4,'輸送至 S4','出料區到位，等待彙整判定',{palletX:1450,located:false});
  add(4,1,'彙整第一階段結果','模擬 OK／NG 與影像索引；MES 尚未連接',{located:true},null,{done:'judge'});
  add(4,.7,'出料側夾鬆開','完成工單前 PI 範圍，保留未涵蓋項目待人工檢驗',{clamp:0});
  add(4,2.8,'載具拉入出料堆料架','上層托叉承重，拉料鞋與載具前緣同步移動',{palletX:2000,pushOut:0,located:false});
  add(4,.8,'出料平台接管上層重量','先抬高 4 mm，使上層載具離開托叉',{palletLift:4,outStackY:4,outLift:4});
  add(4,.45,'出料托叉退出','平台承重後才退出托叉',{outFork:0});
  add(4,1.8,'出料平台上升一個間距','已檢載具與上層載具共同上升 110 mm',{palletLift:110,outStackY:110,outLift:110});
  add(4,.45,'出料托叉承重','托叉伸入最下方載具，支承整疊',{outFork:1},null,{done:'stack'});
  add(4,1.4,'出料平台下降復歸','整疊留在托叉，平台獨立回到入料高度',{outLift:0});
  add(4,1,'單台循環完成','第一階段示意完成；未執行開機、LCD、鍵盤與模組拆拔',{});

  // Choose nearby equivalent wrist solutions in sequence order before seeking.
  robot.plan(steps.flatMap(s=>[s.pose0,s.pose1]));
  // core sample 給出插值後的狀態；本層補上護蓋（巢狀陣列）插值、力值曲線、套用場景與手臂位姿
  function sample(sec){
    const {state,step:s,index:idx,u:t,e}=seq.sample(sec);
    state.doors=s.end.doors.map((d,i)=>({open:THREE.MathUtils.lerp(s.initial.doors[i].open,d.open,e),latch:THREE.MathUtils.lerp(s.initial.doors[i].latch,d.latch,e)}));
    state.force=s.forceCurve?s.forceCurve(t):state.force;
    apply(state);
    const destination=s.motion?s.motion(t,state):s.pose1;
    // 自由移位走關節插值（PTP）；接近、接觸、減速與掃描走直線。
    const p=s.path?destination:s.ptp?{ptp:{from:s.pose0,to:s.pose1,e}}:{origin:s.pose0.origin.clone().lerp(destination.origin,e),rotation:s.pose0.rotation.clone().slerp(destination.rotation,e),rail:THREE.MathUtils.lerp(s.pose0.rail,destination.rail,e),tcp:destination.tcp};
    if(!p.ptp)p.ref=s.pose0;
    robot.setPose(p);robot.goal.speed=s.contact?50:900;
    const completed=new Set(steps.slice(0,idx).map(s=>s.done).filter(Boolean));if(t===1&&s.done)completed.add(s.done);
    return {state,step:s,index:idx,t,completed};
  }
  return {sample,steps,total:seq.total,stationStart,base,events:seq.events};
}
