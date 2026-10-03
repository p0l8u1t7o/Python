import test from 'node:test';
import assert from 'node:assert/strict';
import {smooth,filterTargets,atFrame} from '../../core/movie/camera-path.mjs';

test('a workpiece handoff is smoothed without overshoot or a one-frame jump',()=>{
  const raw=Array.from({length:100},(_,i)=>[i<50?0:1000,700,20]);
  const filtered=filterTargets(raw);
  const poses=Array.from({length:595},(_,i)=>atFrame(filtered,i));
  let maxStep=0;
  for(let i=1;i<poses.length;i++){
    const dx=poses[i][0]-poses[i-1][0];assert(dx>=-1e-9);
    maxStep=Math.max(maxStep,dx);
    assert(poses[i][0]>=0&&poses[i][0]<=1000+1e-9);
    assert(Math.abs(poses[i][1]-700)<1e-9);
  }
  assert(maxStep<20,'1000 mm handoff must not become an instantaneous camera jump');
  const middle=atFrame(filtered,291);
  atFrame(filtered,540);atFrame(filtered,0);
  assert.deepEqual(atFrame(filtered,291),middle,'seeking must not alter camera history');
});

test('opening holds the complete machine then eases continuously into tracking',()=>{
  const zoom=frame=>smooth((frame/30-3)/(9-1/30));
  for(let i=0;i<=90;i++)assert.equal(zoom(i),0);
  assert.equal(zoom(359),1);
  for(let i=1;i<=359;i++){
    assert(zoom(i)>=zoom(i-1));
    assert(zoom(i)-zoom(i-1)<.008);
  }
  assert(zoom(91)<.000001);
  assert(1-zoom(358)<.000001);
});
