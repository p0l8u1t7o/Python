// 從 Browser 技能已連線的 tab 呼叫，不啟動其他瀏覽器。
import {mkdirSync,writeFileSync} from 'node:fs';
import {join} from 'node:path';
export async function runCameraReview(cdp,tab,out){
  mkdirSync(out,{recursive:true});const checks=[];
  const evaluate=async expression=>{const r=await cdp.send('Runtime.evaluate',{expression,returnByValue:true,awaitPromise:true});if(r.exceptionDetails)throw Error(JSON.stringify(r.exceptionDetails));return r.result.value;};
  const check=(name,ok,detail)=>checks.push({name,ok,detail});
  const settle=()=>evaluate('new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(()=>r(true))))');
  const state=()=>evaluate('({focus:sim.focus.enabled,target:sim.focus.target,camera:sim.camera.position.toArray(),look:sim.controls.target.toArray(),pip:sim.cameraWindow.state})');
  const rect=id=>tab.playwright.evaluate(id=>document.getElementById(id).getBoundingClientRect().toJSON(),id);
  const button=name=>tab.playwright.getByRole('button',{name,exact:true});
  await evaluate('sim.pause();sim.seekTo(0);sim.setView("iso",true)');
  await tab.playwright.getByLabel('焦點追蹤目標',{exact:true}).selectOption('agv');await button('對準焦點').click();
  check('全景可單次對準並拉近目標',await evaluate('!sim.focus.enabled&&sim.controls.target.distanceTo(sim.focusPosition("agv"))<.01&&sim.camera.position.distanceTo(sim.controls.target)<6000'));
  await button('追蹤焦點').click();
  for(const key of ['agv','gantry','drum0','drum1','drum2','drum3','auto','gripper']){
    await evaluate('sim.seekTo(140)');await tab.playwright.getByLabel('焦點追蹤目標',{exact:true}).selectOption(key);
    const before=await evaluate('sim.camera.position.clone().sub(sim.controls.target).toArray()');
    await evaluate('sim.seekTo(145)');
    check('追蹤及跳轉 · '+key,await evaluate(`sim.focus.enabled&&sim.controls.target.distanceTo(sim.focusPosition(${JSON.stringify(key)}))<.01&&sim.camera.position.clone().sub(sim.controls.target).distanceTo({x:${before[0]},y:${before[1]},z:${before[2]}})<.01`));
  }
  await button('停止追蹤').click();const stopped=await state();await evaluate('sim.seekTo(150)');
  check('停止追蹤後跳轉不移動相機',JSON.stringify((await state()).camera)===JSON.stringify(stopped.camera));
  await tab.playwright.getByLabel('焦點追蹤目標',{exact:true}).selectOption('drum0');await button('追蹤焦點').click();
  const beforeGone=await state();await evaluate('sim.seekTo(sim.total)');await settle();
  check('桶離線時保留視角並提示',JSON.stringify((await state()).camera)===JSON.stringify(beforeGone.camera)&&await tab.playwright.getByRole('status').innerText()==='目標已離開產線');
  await evaluate('sim.seekTo(140)');check('倒退跳轉恢復追蹤',await evaluate('sim.controls.target.distanceTo(sim.focusPosition("drum0"))<.01'));
  await button('夾具特寫').click();await evaluate('sim.setView("gripper",true)');
  check('預設視角可退出追蹤',!(await state()).focus);
  await evaluate('sim.seekTo(sim.total);sim.setView("iso",true)');
  await tab.playwright.getByLabel('焦點追蹤目標',{exact:true}).selectOption('drum0');
  const absentStart=await state();await button('對準焦點').click();
  check('對準已離線目標不改變相機位置',JSON.stringify((await state()).camera)===JSON.stringify(absentStart.camera));
  await button('追蹤焦點').click();
  check('從全景追蹤已離線目標不突然拉近',JSON.stringify((await state()).camera)===JSON.stringify(absentStart.camera)&&(await state()).focus);
  await evaluate('sim.seekTo(140);sim.setView("gripper",true)');
  await button('重設位置').click();await settle();
  const initial=await state(),header=await rect('pipHeader');
  await tab.cua.drag({path:[{x:header.x+70,y:header.y+18},{x:header.x+140,y:header.y+48},{x:header.x+210,y:header.y+78}]});
  const moved=await state();check('標題列可拖曳且不旋轉主相機',moved.pip.x>initial.pip.x+100&&moved.pip.y>initial.pip.y+40&&JSON.stringify(moved.camera)===JSON.stringify(initial.camera),moved.pip);
  const handle=await rect('pipResize');
  await tab.cua.drag({path:[{x:handle.x+5,y:handle.y+5},{x:handle.x+45,y:handle.y+30},{x:handle.x+85,y:handle.y+55}]});
  const resized=await state();check('拖曳右下角調整視窗大小',resized.pip.w>moved.pip.w+60&&resized.pip.h>moved.pip.h+30,resized.pip);
  await button('收合相機視窗').click();check('收合保留標題列',!(await evaluate('sim.cameraWindow.visible'))&&(await state()).pip.minimized);
  await button('展開相機視窗').click();check('展開恢復畫面',await evaluate('sim.cameraWindow.visible'));
  await button('隱藏相機視窗').click();check('隱藏與顯示設定同步',await button('顯示相機視窗').isVisible()&&!await evaluate('document.getElementById("showPip").checked'));
  await button('顯示相機視窗').click();check('一鍵恢復視窗',await evaluate('!document.getElementById("pip").hidden&&sim.cameraWindow.visible'));
  for(const [source,title]of [['gripper','清洗夾具'],['label','貼標相機'],['decap','桶口相機'],['auto','貼標相機']]){
    if(source==='auto')await evaluate('sim.seekTo(0)');
    await tab.playwright.getByLabel('相機視窗來源',{exact:true}).selectOption(source);await settle();
    check('相機來源 · '+source,(await tab.playwright.locator('#pipTitle').innerText()).includes(title));
  }
  await button('重設位置').click();await tab.playwright.locator('#pipHeader').press('ArrowRight');
  check('鍵盤可移動視窗',(await state()).pip.x===26);
  await tab.playwright.locator('#pipResize').press('ArrowRight');check('鍵盤可調整尺寸',(await state()).pip.w===370);
  await tab.playwright.locator('#pipHeader').press('Escape');check('Escape 隱藏視窗',await button('顯示相機視窗').isVisible());
  await button('顯示相機視窗').click();await button('重設位置').click();
  const report={ok:checks.every(c=>c.ok),checks,logs:await tab.dev.logs({levels:['error','warn'],limit:100})};
  report.ok=report.ok&&!report.logs.some(l=>l.level==='error');writeFileSync(join(out,'camera-review.json'),JSON.stringify(report,null,2));return report;
}
