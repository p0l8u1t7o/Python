import { objectRegion } from './vision-overlay.js';
export function notebookResults(nb,S,exposure,T) {
  const marks=[],door=nb.doors.find(d=>S.action.startsWith(d.def.id+' '));
  const add=(object,label)=>marks.push({points:objectRegion(object),label,status:exposure?'ok':'pending'});
  // Only this exposure's target is annotated; no stale results while the arm moves.
  if(exposure){
    if(door){
      if(S.action.includes('連接器'))door.portGroup.children.forEach((p,i)=>add(p,`${door.def.id} ${door.def.ports[i].toUpperCase()} · 模型存在`));
      else {add(door.hinge,door.def.id+' 護蓋 ROI');add(door.latchPivot,'鎖扣 ROI');if(door.def.sealed)add(door.seal,'封印 ROI');}
    }else if(S.action.includes('Docking'))add(nb.dock,'Docking · 接點排列 ROI');
    else if(S.action.includes('法規'))add(nb.printing,'法規印刷 · OCR 待接入');
    else if(S.action.includes('SN')){add(nb.labels.sn,'SN · OCR 待接入');add(nb.labels.coin,'警語 ROI');}
    else if(S.action.includes('螺絲'))nb.bottomScrews.forEach((s,i)=>add(s,`S${i+1} 螺絲 ROI`));
    else add(nb.root,'外觀檢查 ROI');
  }
  return {title:'外觀檢測區域',state:exposure?'本幀示意／非瑕疵判定':'待到位取像',time:T,marks};
}
