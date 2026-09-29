"""Build an isolated movie version of each demo in ignored TEMP."""
from pathlib import Path
import argparse, shutil

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / 'TEMP' / 'movie-site'
PROJECTS = ['AutomaticAcid-BaseTitration', 'MilitaryGradePC', 'PCB-CopperAssembly', 'RobotArmPressSSD', 'shutter assembly', 'WorkpieceMeasurement']
parser=argparse.ArgumentParser()
parser.add_argument('--project',choices=PROJECTS)
args=parser.parse_args()
if args.project: PROJECTS=[args.project]
for name in PROJECTS:
    target = OUT / name
    shutil.copytree(ROOT / name / 'web', target, dirs_exist_ok=True)
    shutil.copy2(Path(__file__).with_name('movie.js'), target / 'js/movie.js')
    shutil.copy2(Path(__file__).with_name('camera-path.mjs'), target / 'js/camera-path.mjs')
    p = target / 'js/main.js'
    code = p.read_text(encoding='utf-8')
    if 'logarithmicDepthBuffer:' not in code:
        code = code.replace("powerPreference: 'high-performance'", "powerPreference: 'high-performance', logarithmicDepthBuffer: true")
    code = code.replace('function frame() {', 'function frame() { if (qp.has("movie")) return;').replace('function frame(){', 'function frame(){ if (qp.has("movie")) return;')
    common = 'scene,renderer,camera,controls,render,setView,total,project:' + repr(name)
    if name == 'WorkpieceMeasurement':
        # Keep the original website untouched; recording owns its fixed buffer
        # and absolute-time clock in this isolated copy.
        code=code.replace('function resize() {', 'function resize() { if(qp.has("movie")) return;')
        common='scene,renderer,camera,controls,render,setView:movieView,total,project:'+repr(name)
        code+='''
function movieView(name,instant){
  const poses={
    'film-st1':[[-275,1180,-430],[-120,1090,0]],
    'film-st2':[[90,1210,460],[215,1070,0]],
    'film-gland':[[20,1100,700],[290,822,231]],
  };
  if(poses[name]){const [p,t]=poses[name];camera.position.set(...p);controls.target.set(...t);camera.lookAt(controls.target);return;}
  setView(name,instant);
}
'''
        specific='''steps:sequence.steps,sample(t){T=t;current=sequence.sample(t);},
          focus:()=>machine.partWorld(),offset:[-580,400,850],
          electricalMode:(_,mode)=>machine.details.setMode(mode),keepGuards:true,
          detailShots:(()=>{
            const span=(station,view,label)=>{const a=sequence.steps.filter(x=>x.station===station);return {view,label,simStart:a[0].start,simDuration:a.at(-1).start+a.at(-1).dur-a[0].start};};
            return [span(1,'film-st1','ST1 · 夾持、旋轉與三通道取像（重播）'),
              span(3,'film-st2','ST2 · 上頭避讓、落座與上下共焦量測（重播）'),
              {view:'carriers',label:'X／Z 拖鏈 · 全行程折返與兩端固定（重播）',simStart:0,simDuration:total},
              span(3,'fibers','光纖整線 · 升降補償環與徑向補償環（重播）'),
              {view:'film-gland',label:'桌板穿線護口 · 線材通往下方電盤',simStart:total,simDuration:0}];
          })()'''
    elif name == 'AutomaticAcid-BaseTitration':
        specific = 'steps:plan.steps,sample(t){T=t;info=sim.apply(T);},focus:()=>{const bal=/天平|秤重|歸零|讀重|推把/.test(info.step.label); if(bal)return new THREE.Vector3(ST.balance.x,Y0+ST.balance.pan+45,ST.balance.z);return activeProduct();},offset:[-420,470,680]'
    elif name == 'PCB-CopperAssembly':
        specific = '''steps:[{start:0,dur:total,label:"雙頭植入與五站同步"}],sample(t){T=t;info=sim.apply(T);},focus:()=>new THREE.Vector3(0,1050,0),offset:[-2150,1350,2650],
          detailShots:(()=>{
            const active=tr=>tr.segs.filter(s=>s.label!=='待命');
            const window=(view,label,start,end)=>({view,label,simStart:Math.max(0,start),simDuration:Math.min(total,end)-Math.max(0,start)});
            const load=active(plan.s0),unload=active(plan.s4);
            const vibration=plan.feeders.A.tr.segs.find(s=>s.to.vib===1);
            const placement=plan.events.find(e=>e.type==='place'&&e.H==='A');
            return [window('load','S0 上料 · 原速流程',load[0].t0,load.at(-1).t1),
              window('s1','S1 孔位定位 · 掃描細節',plan.s1.shots[0].t,plan.s1.shots[0].t+8),
              window('feeder','銅片供料 · 震動翻面',vibration.t0-1,vibration.t1+2),
              window('head','吸嘴取放 · 對位與輕壓',placement.t-2,placement.t+3),
              window('s3','S3 植入檢查 · 掃描細節',plan.s3.shots[0].t,plan.s3.shots[0].t+8),
              window('unload','S4 成品下料 · 原速流程',unload[0].t0,unload.at(-1).t1)];
          })()'''
    elif name == 'MilitaryGradePC':
        specific = 'steps:sequence.steps,sample(t){T=t;current=sequence.sample(t);robot.snap();},focus:()=>carrier.getWorldPosition(new THREE.Vector3()),offset:[-650,620,1050]'
    elif name == 'RobotArmPressSSD':
        specific = 'steps:sequence.steps,sample(t){T=t;current=sequence.sample(t);robot.snap();},focus:()=>product.root.getWorldPosition(new THREE.Vector3()).add(new THREE.Vector3(0,recipe.pallet.t+5,0)),offset:[-recipe.pallet.w*1.1,recipe.pallet.w*1.65,recipe.pallet.d*1.9]'
    else:
        specific = '''steps:sequence.steps,sample(t){T=t;current=sequence.sample(t);robot.snap();st.sync();},focus:()=>{
          const held=Object.entries(S.loc).find(([id,loc])=>/^T[123]$/.test(loc));
          if(held)return st.pose(held[0]).p;
          const next=current.step.end.loc;
          const pick=Object.keys(next).find(id=>/^T[123]$/.test(next[id]));
          return pick?st.pose(pick).p:st.pose('base').p;
        },offset:[-130,200,270]'''
    code = code.replace('workspace.renderOverview(renderer,scene)', "scene.children.filter(o=>o.type==='Box3Helper').forEach(o=>o.visible=false);workspace.renderOverview(renderer,scene)")
    code += '\nif(qp.has("movie")){ playing=false; const {installMovie}=await import("./movie.js"); installMovie({' + common + ',' + specific + '});}\n'
    p.write_text(code, encoding='utf-8')
print(OUT)
