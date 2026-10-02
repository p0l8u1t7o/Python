// 主視角追蹤與可拖曳的相機子視窗。無儲存副作用；resize 後限制在 3D 畫布內。
export function createFocusTracking({camera,controls,getTarget,getOffset,onFocus}) {
  const select=document.getElementById('focusTarget'), toggle=document.getElementById('focusTrack'), status=document.getElementById('focusStatus');
  let enabled=false;
  const buttonState=()=>{toggle.setAttribute('aria-pressed',String(enabled));toggle.textContent=enabled?'停止追蹤':'追蹤焦點';controls.enablePan=!enabled;};
  function update(dt=0,instant=false){
    if(!enabled&&!instant)return;
    const target=getTarget(select.value);
    if(!target){status.textContent='目標已離開產線';return;}
    const offset=camera.position.clone().sub(controls.target);
    controls.target.lerp(target,instant?1:1-Math.exp(-dt*9)); camera.position.copy(controls.target).add(offset);
    status.textContent=(enabled?'追蹤中 · ':'焦點 · ')+select.selectedOptions[0].textContent;
  }
  function stop(){enabled=false;buttonState();status.textContent='自由視角';}
  function focusOnce(){onFocus();if(getTarget(select.value)&&camera.position.distanceTo(controls.target)>6000)camera.position.copy(controls.target).add(getOffset(select.value));update(0,true);controls.update();}
  function start(key=select.value){select.value=key;enabled=true;buttonState();focusOnce();}
  select.onchange=()=>{if(enabled)focusOnce();};
  toggle.onclick=()=>enabled?stop():start(); document.getElementById('focusNow').onclick=focusOnce;
  buttonState();
  return {update,stop,start,snap(){if(enabled)update(0,true);},get enabled(){return enabled;},get target(){return select.value;}};
}

export function createCameraWindow(canvas,checkbox){
  const el=document.getElementById('pip'), header=document.getElementById('pipHeader'), viewport=document.getElementById('pipViewport');
  const restore=document.getElementById('pipRestore'), minimize=document.getElementById('pipMinimize'), handle=document.getElementById('pipResize');
  const state={x:16,y:12,w:360,h:286,minimized:false};
  const clamp=(n,a,b)=>Math.max(a,Math.min(b,n));
  function layout(){
    const c=canvas.getBoundingClientRect(),maxW=Math.max(1,c.width-8),maxH=Math.max(1,c.height-8);
    state.w=clamp(state.w,Math.min(240,maxW),maxW);state.h=clamp(state.h,Math.min(180,maxH),maxH);
    const h=state.minimized?38:state.h;
    state.x=clamp(state.x,4,Math.max(4,c.width-state.w-4));state.y=clamp(state.y,4,Math.max(4,c.height-h-4));
    Object.assign(el.style,{left:`${c.left+state.x}px`,top:`${c.top+state.y}px`,width:`${state.w}px`,height:`${h}px`});
    el.classList.toggle('minimized',state.minimized);el.hidden=!checkbox.checked;restore.hidden=checkbox.checked;
    restore.style.left=`${c.left+12}px`;restore.style.top=`${c.top+12}px`;
    minimize.textContent=state.minimized?'▢':'−';minimize.setAttribute('aria-label',state.minimized?'展開相機視窗':'收合相機視窗');
  }
  function hide(){checkbox.checked=false;layout();restore.focus();}
  document.getElementById('pipClose').onclick=hide;
  restore.onclick=()=>{checkbox.checked=true;state.minimized=false;layout();};
  checkbox.onchange=layout;
  document.getElementById('pipReset').onclick=()=>{Object.assign(state,{x:16,y:12,w:360,h:286,minimized:false});layout();};
  minimize.onclick=()=>{state.minimized=!state.minimized;layout();};
  function drag(node,resizing){
    let origin=null;
    node.addEventListener('pointerdown',e=>{
      if(e.button!==0||(!resizing&&e.target.closest('button,select')))return;
      e.preventDefault();e.stopPropagation();node.setPointerCapture(e.pointerId);
      origin={px:e.clientX,py:e.clientY,...state};
    });
    node.addEventListener('pointermove',e=>{if(!origin)return;const dx=e.clientX-origin.px,dy=e.clientY-origin.py;
      if(resizing){state.w=origin.w+dx;state.h=origin.h+dy;}else{state.x=origin.x+dx;state.y=origin.y+dy;}layout();
    });
    const end=()=>{origin=null;};node.addEventListener('pointerup',end);node.addEventListener('pointercancel',end);node.addEventListener('lostpointercapture',end);
    node.addEventListener('keydown',e=>{
      if(e.target!==node)return;
      if(e.key==='Escape'){hide();return;}
      const delta={ArrowLeft:[-1,0],ArrowRight:[1,0],ArrowUp:[0,-1],ArrowDown:[0,1]}[e.key];if(!delta)return;
      e.preventDefault();const step=e.shiftKey?30:10;
      if(resizing){state.w+=delta[0]*step;state.h+=delta[1]*step;}else{state.x+=delta[0]*step;state.y+=delta[1]*step;}layout();
    });
  }
  drag(header,false);drag(handle,true);addEventListener('resize',layout);new ResizeObserver(layout).observe(canvas);layout();
  return {layout,get state(){return {...state,visible:checkbox.checked};},get viewport(){return viewport.getBoundingClientRect();},get source(){return document.getElementById('pipSource').value;},get visible(){return checkbox.checked&&!state.minimized;}};
}
