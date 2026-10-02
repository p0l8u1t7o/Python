import { objectRegion, planeRegion } from '@core/ui/vision-overlay.js';
import { PRODUCT } from './layout.js';
export function copperResults(src,T,plan,M,boards) {
  const H=src.endsWith('B')?'B':'A';let marks=[],state='預覽';
  if(src.startsWith('feed')){
    const s=plan.feeders[H].tr.sample(T),shot=!!s.seg?.flash&&!s.done;state=shot?'本幀取像':'預覽／待取像';
    let gi=0,bi=0;
    marks=plan.feeders[H].coins.filter(c=>c.t0<=T&&T<c.t1).map(c=>{
      const mesh=c.good?M.feeders[H].coins[gi++]:M.feeders[H].backs[bi++];
      return {points:objectRegion(mesh),status:shot?(c.good?'ok':'ng'):'preview',label:shot?`#${c.id+1} ${c.good?'可取':'翻面'} ${c.theta.toFixed(1)}°`:''};
    });
  }else if(src.startsWith('up')){
    const e=plan.events.find(e=>e.type==='upcam'&&e.H===H&&Math.abs(e.t-T)<.03);state=e?'本幀取像':'等待飛越取像';
    if(e){const hold=plan.heads[H].hold[e.k].find(h=>h.t0<=T&&T<h.t1),o=hold?.coin.pickOffset;
      if(o)marks.push({points:objectRegion(M.heads[H].nozzles[e.k].coin),status:'ok',label:`N${e.k+1} ΔX ${o.dx.toFixed(3)} ΔZ ${o.dz.toFixed(3)} mm / θ ${o.dt.toFixed(1)}°`});}
  }else if(src.startsWith('down')){
    const s=plan.heads[H].tr.sample(T),shot=!!s.seg?.flash&&!s.done;state=shot?'基準點取像':'預覽／待取像';
    marks=PRODUCT.fiducials.map(([x,z],i)=>({points:planeRegion(boards.s1.group,x,PRODUCT.board.t+PRODUCT.board.adhesive,z,3,3),status:shot?'ok':'preview',label:`F${i+1} ${shot?'定位':'ROI'}`}));
  }else{
    const scan=src==='s1',s=(scan?plan.s1:plan.s3).tr.sample(T),shot=!!s.seg?.flash&&!s.done;
    state=shot?'本幀取像':'預覽／待取像';const board=scan?boards.s0:boards.s2;
    marks=plan.holes.map(h=>({points:planeRegion(board.group,h.x,PRODUCT.board.t+PRODUCT.board.adhesive,h.z,PRODUCT.hole.w,PRODUCT.hole.l),
      status:shot?(scan||h.err<=PRODUCT.spec?'ok':'ng'):'preview',
      label:shot?(scan?`H${h.id+1} 定位`:`H${h.id+1} ${h.err<=PRODUCT.spec?'OK':'NG'} ${h.err.toFixed(3)} mm`):''}));
  }
  return {title:src.toUpperCase(),state,time:T,marks};
}
