"""Build an isolated movie version of each demo in ignored TEMP."""
from pathlib import Path
import shutil

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / 'TEMP' / 'movie-site'
PROJECTS = ['AutomaticAcid-BaseTitration', 'MilitaryGradePC', 'PCB-CopperAssembly', 'RobotArmPressSSD', 'shutter assembly']
for name in PROJECTS:
    target = OUT / name
    shutil.copytree(ROOT / name / 'web', target, dirs_exist_ok=True)
    shutil.copy2(Path(__file__).with_name('movie.js'), target / 'js/movie.js')
    p = target / 'js/main.js'
    code = p.read_text(encoding='utf-8')
    code = code.replace('function frame() {', 'function frame() { if (qp.has("movie")) return;').replace('function frame(){', 'function frame(){ if (qp.has("movie")) return;')
    common = 'scene,renderer,camera,controls,render,setView,total,project:' + repr(name)
    if name == 'AutomaticAcid-BaseTitration':
        specific = 'steps:plan.steps,sample(t){T=t;info=sim.apply(T);},focus:()=>{const bal=/天平|秤重|歸零|讀重|推把/.test(info.step.label); if(bal)return new THREE.Vector3(ST.balance.x,Y0+ST.balance.pan+45,ST.balance.z);return activeProduct();},offset:()=>/天平|秤重|歸零|讀重|推把/.test(info.step.label)?[260,190,190]:[-160,180,240]'
    elif name == 'PCB-CopperAssembly':
        specific = 'steps:[{start:0,dur:total,label:"雙頭植入與五站同步"}],sample(t){T=t;info=sim.apply(T);},focus:()=>focusPoint(false),offset:[200,235,450]'
    elif name == 'MilitaryGradePC':
        specific = 'steps:sequence.steps,sample(t){T=t;current=sequence.sample(t);robot.snap();},focus:()=>carrier.getWorldPosition(new THREE.Vector3()),offset:[-430,370,560]'
    elif name == 'RobotArmPressSSD':
        specific = 'steps:sequence.steps,sample(t){T=t;current=sequence.sample(t);robot.snap();},focus:()=>product.root.getWorldPosition(new THREE.Vector3()).add(new THREE.Vector3(0,recipe.pallet.t+5,0)),offset:[-recipe.pallet.w*.55,recipe.pallet.w*.85,recipe.pallet.d*.95]'
    else:
        specific = '''steps:sequence.steps,sample(t){T=t;current=sequence.sample(t);robot.snap();st.sync();},focus:()=>{
          const held=Object.entries(S.loc).find(([id,loc])=>/^T[123]$/.test(loc));
          if(held)return st.pose(held[0]).p;
          const next=current.step.end.loc;
          const pick=Object.keys(next).find(id=>/^T[123]$/.test(next[id]));
          return pick?st.pose(pick).p:st.pose('base').p;
        },offset:[-32,42,53]'''
    code = code.replace('workspace.renderOverview(renderer,scene)', "scene.children.filter(o=>o.type==='Box3Helper').forEach(o=>o.visible=false);workspace.renderOverview(renderer,scene)")
    code += '\nif(qp.has("movie")){ playing=false; const {installMovie}=await import("./movie.js"); installMovie({' + common + ',' + specific + '});}\n'
    p.write_text(code, encoding='utf-8')
print(OUT)
