// Deterministic 1080p movie: the application renders each frame before uploading it.
// No realtime screen recording, dropped frames, or dependency on monitor refresh rate.
import * as THREE from 'three';

export function installVideo({steps, sample, renderer, camera, controls, render, nb, getState}) {
  const FPS=30, W=1920, H=1080, shots=[];
  let duration=0;
  const append=(s,seconds,view,label=s.action)=>{shots.push({videoStart:duration,duration:seconds,simStart:s.start,simDuration:s.dur,station:s.station,view,label,detail:s.sub});duration+=seconds;};
  append({...steps[0],dur:0},3,'overview','軍規電腦 · 自動化光學 QC');
  for(const s of steps){
    let view=['infeed','surface','door','flip','outfeed'][s.station];
    if(s.action.startsWith('輸送'))view='transfer';
    if(s.station===1 && /側面/.test(s.action))view='surface';
    if(s.station===2 && /上方轉位|手臂退出/.test(s.action))view='robot';
    if(s.station===3 && /相機定位|取像：|影像確認/.test(s.action))view='bottom';
    // Keep contact, hinge and fixture movements legible; compress free positioning.
    const important=s.contact || /翻面|翻回|抬升|推出|拉入|平台|托叉/.test(s.action);
    const seconds=s.exposure?Math.max(.7,s.dur):Math.max(.22,s.dur*(important?.85:.43));
    append(s,seconds,view);
  }
  const last=steps.at(-1);
  append({...last,start:last.start+last.dur,dur:0},3,'overview','本台檢測流程完成');

  const overlay=document.createElement('div');overlay.id='movie';
  overlay.innerHTML='<canvas id="movieCanvas" width="1920" height="1080"></canvas><div id="movieControls"><button id="movieExport">輸出 1080p / 30 fps MP4</button><span id="movieStatus">影片預覽</span></div>';
  document.body.appendChild(overlay);
  const output=overlay.querySelector('canvas'),ctx=output.getContext('2d',{alpha:false});
  const status=overlay.querySelector('#movieStatus'),button=overlay.querySelector('button');
  const stageNames=['入料與定位','外觀拍照','護蓋開閉與端子拍照','翻面與底部拍照','出料堆疊'];
  const v=(...a)=>new THREE.Vector3(...a);
  function frame(vt){
    vt=THREE.MathUtils.clamp(vt,0,duration);
    const sh=shots.find(s=>vt<s.videoStart+s.duration)||shots.at(-1);
    const u=THREE.MathUtils.clamp((vt-sh.videoStart)/sh.duration,0,1);
    sample(sh.simStart+sh.simDuration*u);
    const state=getState(),x=state.palletX,y=845+state.lift;
    let p,t;
    if(sh.view==='overview'){p=v(3350,2780,4200);t=v(0,700,-100);}
    else if(sh.view==='infeed'){p=v(-2870,1750,1620);t=v(-1830,1030,0);}
    else if(sh.view==='outfeed'){p=v(2870,1750,1620);t=v(1830,1030,0);}
    else if(sh.view==='transfer'){p=v(x+1100,1900,2400);t=v(x,870,-120);}
    else if(sh.view==='robot'){p=v(x+950,1510,1450);t=v(x,970,-150);}
    else if(sh.view==='flip'){p=v(1850,1510,1310);t=v(1150,1020,0);}   // S3 在 x=1150
    else if(sh.view==='bottom'){p=v(x+320,y+510,390);t=v(x,y,0);}
    else if(sh.view==='door'){
      const door=nb.doors.find(d=>sh.label.startsWith(d.def.id+' '));
      if(door){t=door.centerWorld();const n=door.normalWorld(),tangent=v(0,1,0).cross(n);p=t.clone().addScaledVector(n,340).addScaledVector(tangent,205).add(v(0,165,0));}
      else{p=v(x+700,1400,1000);t=v(x,850,0);}
    } else {p=v(x+520,1490,760);t=v(x,890,-80);}
    camera.position.copy(p);controls.target.copy(t);camera.lookAt(t);
    renderer.setPixelRatio(1);renderer.setSize(W,H,false);camera.aspect=W/H;camera.updateProjectionMatrix();
    render();
    ctx.drawImage(renderer.domElement,0,0,W,H);
    const gradient=ctx.createLinearGradient(0,0,0,210);gradient.addColorStop(0,'#08121cf5');gradient.addColorStop(1,'#08121c00');
    ctx.fillStyle=gradient;ctx.fillRect(0,0,W,210);
    ctx.fillStyle='#6edbd4';ctx.font='600 18px "Microsoft JhengHei",sans-serif';ctx.fillText('V110  /  AUTOMATED QC CELL',54,46);
    ctx.fillStyle='#ecf4f8';ctx.font='600 32px "Microsoft JhengHei",sans-serif';ctx.fillText(sh.view==='overview'?sh.label:`S${sh.station}  ·  ${stageNames[sh.station]}`,54,93);
    ctx.textAlign='right';ctx.fillStyle='#aabecb';ctx.font='18px "Microsoft JhengHei",sans-serif';ctx.fillText('第一階段工程模擬  ·  動作節錄 / 變速',W-54,46);ctx.fillText('1920 × 1080  /  30 FPS',W-54,78);ctx.textAlign='left';
    ctx.fillStyle='#0b1825ed';ctx.fillRect(38,H-164,W-76,128);
    ctx.fillStyle=state.flashTool||state.flashTop||state.flashSn?'#71edbb':'#62cbd0';ctx.fillRect(38,H-164,5,128);
    ctx.font='600 28px "Microsoft JhengHei",sans-serif';ctx.fillStyle='#f1f6fa';ctx.fillText(sh.label,64,H-118);
    ctx.font='19px "Microsoft JhengHei",sans-serif';ctx.fillStyle='#9eb4c2';ctx.fillText(sh.detail,64,H-79,W-420);
    ctx.textAlign='right';ctx.fillStyle='#71dcd2';ctx.font='600 20px "Microsoft JhengHei",sans-serif';ctx.fillText(state.flashTool||state.flashTop||state.flashSn?'● 相機曝光中':'● 動作序列',W-66,H-117);ctx.font='18px monospace';ctx.fillStyle='#9eb4c2';ctx.fillText(`${Math.floor(vt/60).toString().padStart(2,'0')}:${Math.floor(vt%60).toString().padStart(2,'0')} / ${Math.floor(duration/60).toString().padStart(2,'0')}:${Math.ceil(duration%60).toString().padStart(2,'0')}`,W-66,H-78);ctx.textAlign='left';
    ctx.fillStyle='#233b49';ctx.fillRect(38,H-35,W-76,3);ctx.fillStyle='#68d8cd';ctx.fillRect(38,H-35,(W-76)*vt/duration,3);
    return sh;
  }
  async function request(path,body,headers={}){
    for(let attempt=0;attempt<6;attempt++){
      let r;
      try{r=await fetch('/render/'+path,{method:'POST',headers,body});}
      catch(error){if(attempt===5)throw error;await new Promise(resolve=>setTimeout(resolve,1000*(attempt+1)));continue;}
      if(!r.ok)throw Error(await r.text());return r.json();
    }
  }
  button.addEventListener('click',async()=>{
    button.disabled=true;
    try{
      await document.fonts.ready;
      const frames=Math.ceil(duration*FPS),gl=renderer.getContext(),ext=gl.getExtension('WEBGL_debug_renderer_info');
      const gpu=ext?gl.getParameter(ext.UNMASKED_RENDERER_WEBGL):gl.getParameter(gl.RENDERER);
      const job=await request('start',JSON.stringify({fps:FPS,width:W,height:H,frames,duration,shots,gpu}),{'Content-Type':'application/json'});
      for(let i=job.nextFrame||0;i<frames;i++){
        frame(i/FPS);
        // Synchronous serialization avoids idle-encoder throttling in background tabs.
        const encoded=atob(output.toDataURL('image/jpeg',.95).split(',')[1]);
        const bytes=Uint8Array.from(encoded,c=>c.charCodeAt(0));
        await request('frame',bytes,{'X-Render-Token':job.token,'X-Frame-Index':String(i)});
        status.textContent=`逐格輸出 ${i+1} / ${frames} · ${((i+1)/frames*100).toFixed(1)}%`;
      }
      status.textContent='正在完成 MP4 封裝…';
      const result=await request('finish','',{'X-Render-Token':job.token});
      status.textContent='輸出完成：'+result.file;
    }catch(error){status.textContent='輸出失敗：'+error.message;button.disabled=false;}
  });
  frame(Number(new URLSearchParams(location.search).get('vt')||0));
  return {duration,shots,renderAt:frame};
}
