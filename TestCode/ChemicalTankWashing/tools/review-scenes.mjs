// 由 Browser 技能的 Node 工作階段呼叫：runReview(cdp, tab, outputDirectory)。
// 不啟動外部瀏覽器、不讀取使用者 profile；產物限於呼叫端指定的專案目錄。
import {mkdirSync,writeFileSync} from 'node:fs';
import {join} from 'node:path';
export async function runReview(cdp, tab, out) {
  mkdirSync(out,{recursive:true});
  const evaluate=async expression=>{const r=await cdp.send('Runtime.evaluate',{expression,returnByValue:true,awaitPromise:true});if(r.exceptionDetails)throw Error(r.exceptionDetails.text);return r.result?.value;};
  const state=await evaluate('({total:window.sim.total,events:window.sim.seq.events})');
  const at=(name,offset=0)=>{const e=state.events.find(e=>e.label.includes(name));if(!e)throw Error('Missing event: '+name);return e.time+offset;};
  const shots=[['overview',0,'iso'],['storage',at('抬起棧板',.4),'storage'],['gantry',at('0001 翻轉放倒',1.7),'gantry'],['label',at('0001 讀碼',.3),'label'],['upender',at('0001 翻正',2),'upender'],['decap',at('拆 2" 桶蓋',1),'decap'],['robot',at('手臂開始取桶',3.7),'robot'],['spray',at('沖洗水由 TK-R 供應',5),'booth'],['pour',at('倒液進集液漏斗',2),'booth'],['dry',at('熱風吹乾內壁附著水',8),'booth'],['waste',at('末道沖洗水回收至 TK-R',1),'waste'],['inbound',at('懸臂吊上棧板',2),'inbound'],['scale',at('秤重確認殘水 < 100 g',.7),'weigh']];
  const report={total:state.total,shots:[],checks:{}};
  for(const [name,t,view]of shots){
    await evaluate(`window.sim.pause();window.sim.seekTo(${t});window.sim.setView(${JSON.stringify(view)},true);new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)))`);
    const bytes=await tab.screenshot({});writeFileSync(join(out,name+'.png'),bytes);report.shots.push({name,time:t,view});
  }
  report.checks.stateSamples=await evaluate(`(()=>{const bad=[];for(let t=0;t<=window.sim.total;t+=2){window.sim.seekTo(t);const s=window.sim.state;if(JSON.stringify(s.st).includes(':null'))bad.push({t,nan:true});if(s.robot.err?.position>1)bad.push({t,ik:s.robot.err});}return bad;})()`);
  report.checks.layout=await evaluate('document.getElementById("chkCount").textContent');
  report.checks.pip=await evaluate(`window.sim.seekTo(${at('0001 讀碼',.3)});new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(()=>r(!document.getElementById('pip').hidden))))`);
  report.logs=await tab.dev.logs({levels:['error','warn'],limit:100});
  report.ok=report.checks.stateSamples.length===0&&report.checks.pip&&report.logs.every(l=>l.level!=='error');
  await evaluate('window.sim.seekTo(0);window.sim.setView("iso",true)');
  writeFileSync(join(out,'browser-review.json'),JSON.stringify(report,null,2));return report;
}
