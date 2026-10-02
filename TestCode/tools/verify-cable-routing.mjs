import { REGISTER } from '../core/tools/run.mjs';
import {spawn} from 'node:child_process';
import {readFile,readdir,mkdir,writeFile} from 'node:fs/promises';
import {createHash} from 'node:crypto';
import {fileURLToPath} from 'node:url';
import {join} from 'node:path';
const root=fileURLToPath(new URL('../',import.meta.url));
const projects=['AutomaticAcid-BaseTitration','MilitaryGradePC','PCB-CopperAssembly','RobotArmPressSSD','shutter assembly'];
const source=await readFile(join(root,'tools/cable-routing.js'));
for(const p of projects)if(!source.equals(await readFile(join(root,p,'web/js/cable-routing.js'))))throw new Error(p+': run node tools/sync-cable-routing.mjs');
for(const file of ['electrical-cabinet.js','electrical-components.js','electrical-inspector.js']){
const electricalSource=await readFile(join(root,'tools',file));
for(const p of projects)if(!electricalSource.equals(await readFile(join(root,p,'web/js',file))))throw new Error(p+': run node tools/sync-electrical-cabinet.mjs');
}
async function hash(project) {
  const h=createHash('sha256'),dir=join(root,project,'web/js');
  for(const name of (await readdir(dir)).filter(n=>n.endsWith('.js')).sort())h.update(name).update(await readFile(join(dir,name)));
  h.update(await readFile(join(root,'tools/verify-cables.mjs')));h.update(await readFile(join(root,'tools/check-feedthroughs.mjs')));return h.digest('hex');
}
const startedAt=new Date().toISOString();
const results=await Promise.all(projects.map(async project=>{
  const before=await hash(project),start=Date.now();
  const code=await new Promise(resolve=>{
    const child=spawn(process.execPath,['--no-warnings','--import',REGISTER,'../tools/verify-cables.mjs',project],{cwd:join(root,project),windowsHide:true,env:{...process.env,CABLE_INTERVAL:'.05'},stdio:['ignore','pipe','pipe']});
    let output='';child.stdout.on('data',b=>output+=b);child.stderr.on('data',b=>output+=b);
    child.on('error',e=>{output+=e.message;});
    child.on('close',async code=>{await mkdir(join(root,project,'review/checks'),{recursive:true});await writeFile(join(root,project,'review/checks/cables.log'),output);resolve(code);});
  });
  const sourceHash=await hash(project),passed=code===0&&before===sourceHash;
  console.log((passed?'PASS ':'FAIL ')+project+' cable routing');
  return {project,passed,sourceHash,sourceChangedDuringRun:before!==sourceHash,seconds:+((Date.now()-start)/1000).toFixed(2),report:project+'/review/cables.json'};
}));
await writeFile(join(root,'tools/review/cable-checks.json'),JSON.stringify({startedAt,finishedAt:new Date().toISOString(),scope:'sampled visible cable routes and carrier kinematics; not dynamic flexible-body or machine certification',passed:results.every(r=>r.passed),results},null,2));
if(results.some(r=>!r.passed))process.exitCode=1;
