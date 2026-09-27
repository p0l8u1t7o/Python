import * as THREE from 'three';

/** Shared presentation controls. The simulation remains the only time source. */
export function createViewerWorkspace({camera, controls, canvas, resize, getFocus, focusOffset, focusNear = 1, onFocus, focusOccluders = []}) {
  const $ = id => document.getElementById(id);
  const css = document.createElement('link'); css.rel = 'stylesheet'; css.href = new URL('../css/viewer-workspace.css', import.meta.url); document.head.append(css);
  document.body.classList.add('viewer-workspace');
  const app = $('app'), bar = document.createElement('div'); bar.className = 'viewer-tools'; bar.setAttribute('aria-label', '視窗與追隨控制'); app.append(bar);
  const button = (parent, icon, label, action) => {
    const b = document.createElement('button'); b.type = 'button'; b.textContent = icon; b.title = label; b.setAttribute('aria-label', label); b.onclick = action; parent.append(b); return b;
  };
  const panelButtons = [];
  for (const [id, icon, label] of [['left', '◧', '左側資訊'], ['side', '◨', '右側資訊']]) {
    const panel = $(id); if (!panel) continue;
    // The old narrow-screen rule hides the left table; its icon can restore it.
    panel.hidden = getComputedStyle(panel).display === 'none';
    const b = button(bar, icon, '切換' + label, () => { panel.hidden = !panel.hidden; layout(); });
    b.setAttribute('aria-controls', id); panelButtons.push([panel, b]);
  }
  let frame = $('pipFrame');
  if (!frame) {
    frame = document.createElement('section'); frame.id = 'pipFrame';
    frame.innerHTML = '<div id="pipTitle" class="pipTitle">相機預覽</div><div id="pipImage"></div><div id="pipResult" class="pipResult"></div>'; app.append(frame);
  }
  frame.setAttribute('aria-label', '可拖曳相機視窗');
  const title = $('pipTitle'), image = $('pipImage'), result = $('pipResult');
  let show = $('showPip');
  if (!show) { show = document.createElement('input'); show.type = 'checkbox'; show.id = 'showPip'; show.checked = true; show.hidden = true; app.append(show); }
  const imageCanvas = document.createElement('canvas'); imageCanvas.className = 'sensor-image'; imageCanvas.setAttribute('aria-label', '同步相機影像'); image.append(imageCanvas);
  const imageContext = imageCanvas.getContext('2d');
  const actions = document.createElement('div'); actions.className = 'camera-actions'; title.before(actions);
  frame.querySelector('.pipExpand')?.remove();
  const status = document.createElement('div'); status.className = 'viewer-status'; status.setAttribute('role', 'status'); status.hidden = true; app.append(status);
  let popup = null, popupCanvas = null, popupContext = null, popupBadge = null, popupClock = null;
  let expanded = new URLSearchParams(location.search).get('cameraSize') === 'large', moved = false;
  let target = null, hdrTarget = null, pixels = null, imageData = null, attachedVision = null;
  // Offscreen targets bypass Three's display tone mapping. Resolve HDR through
  // the same ACES exposure and sRGB transfer before copying to a 2D canvas.
  const resolveScene = new THREE.Scene(), resolveCamera = new THREE.OrthographicCamera(-1,1,1,-1,0,1);
  const resolveMaterial = new THREE.ShaderMaterial({toneMapped:false,depthTest:false,depthWrite:false,
    uniforms:{sensor:{value:null},toneMappingExposure:{value:1}},
    vertexShader:'varying vec2 uvOut; void main(){uvOut=uv;gl_Position=vec4(position.xy,0.,1.);}',
    fragmentShader:'#include <tonemapping_pars_fragment>\nuniform sampler2D sensor; varying vec2 uvOut; void main(){vec4 c=texture2D(sensor,uvOut);gl_FragColor=sRGBTransferOETF(vec4(ACESFilmicToneMapping(c.rgb),c.a));}'});
  const resolveQuad = new THREE.Mesh(new THREE.PlaneGeometry(2,2),resolveMaterial); resolveScene.add(resolveQuad);
  let tracking = false, lastTarget = null;
  const cameraButton = button(bar, '▣', '顯示／隱藏相機視窗', () => {
    if (popup && !popup.closed) dock(); else { show.checked = !show.checked; updateVisibility(); }
  });
  const focusButton = button(bar, '◎', '追隨產品焦點', () => setFollowing(!tracking));
  focusButton.id = 'followProduct'; focusButton.setAttribute('aria-pressed', 'false');
  const expandButton = button(actions, '⛶', '放大／縮小相機視窗', () => { expanded = !expanded; sizeFrame(); });
  button(actions, '↗', '以獨立視窗顯示相機', detach);
  button(actions, '×', '隱藏相機視窗', () => { show.checked = false; updateVisibility(); });
  title.tabIndex = 0; title.title = '拖曳移動；方向鍵微調位置';
  function setFollowing(on) {
    tracking = on; lastTarget = null; focusButton.setAttribute('aria-pressed', String(on));
    focusButton.title = on ? '解除產品焦點追隨' : '追隨產品焦點';
    if (on) {
      onFocus(); const p = getFocus().clone(); camera.near = focusNear; camera.updateProjectionMatrix();
      controls.target.copy(p); camera.position.copy(p).add(new THREE.Vector3(...focusOffset)); lastTarget = p;
      controls.update();
    }
  }
  function follow() {
    if (!tracking) return;
    const p = getFocus().clone();
    if (lastTarget) { const delta = p.clone().sub(lastTarget); camera.position.add(delta); controls.target.add(delta); }
    lastTarget = p; camera.lookAt(controls.target);
    focusButton.dataset.target = p.toArray().join(',');
  }
  function stopFollowing() { if (tracking) setFollowing(false); }
  function renderOverview(renderer, scene) {
    const visibility = focusOccluders.map(o=>o.visible);
    if(tracking) focusOccluders.forEach(o=>o.visible=false);
    try { renderer.render(scene,camera); } finally { focusOccluders.forEach((o,i)=>o.visible=visibility[i]); }
  }
  function layout() {
    for (const [panel, b] of panelButtons) b.setAttribute('aria-expanded', String(!panel.hidden));
    const l = $('left'), r = $('side');
    const left = l && !l.hidden ? l.getBoundingClientRect().right + 12 : 0;
    const right = r && !r.hidden ? innerWidth - r.getBoundingClientRect().left + 12 : 0;
    app.style.setProperty('--viewer-left', left + 'px'); app.style.setProperty('--viewer-right', right + 'px');
    bar.style.top = ($('topbar').getBoundingClientRect().bottom + 10) + 'px';
    if (moved) clampFrame(); else { frame.style.left = Math.max(12, left + 12) + 'px'; frame.style.top = Math.max(190, $('topbar').getBoundingClientRect().bottom + 60) + 'px'; clampFrame(); }
    resize();
  }
  function sizeFrame() { frame.classList.toggle('expanded', expanded); expandButton.setAttribute('aria-pressed', String(expanded)); clampFrame(); }
  function clampFrame() {
    const b = frame.getBoundingClientRect(); if (!b.width) return;
    frame.style.left = Math.max(6, Math.min(parseFloat(frame.style.left) || b.left, innerWidth - b.width - 6)) + 'px';
    frame.style.top = Math.max(6, Math.min(parseFloat(frame.style.top) || b.top, innerHeight - b.height - 6)) + 'px';
  }
  let drag = null;
  title.addEventListener('pointerdown', e => { if (e.button !== 0) return; const r = frame.getBoundingClientRect(); drag = {x:e.clientX-r.left,y:e.clientY-r.top}; title.setPointerCapture(e.pointerId); e.preventDefault(); });
  title.addEventListener('pointermove', e => { if (!drag) return; moved = true; frame.style.left = e.clientX-drag.x+'px'; frame.style.top = e.clientY-drag.y+'px'; clampFrame(); });
  const endDrag = () => { drag = null; }; title.addEventListener('pointerup', endDrag); title.addEventListener('pointercancel', endDrag); title.addEventListener('lostpointercapture', endDrag);
  title.addEventListener('keydown', e => { const d = {ArrowLeft:[-12,0],ArrowRight:[12,0],ArrowUp:[0,-12],ArrowDown:[0,12]}[e.key]; if (!d) return; e.preventDefault(); moved=true; const r=frame.getBoundingClientRect(); frame.style.left=r.left+d[0]+'px'; frame.style.top=r.top+d[1]+'px'; clampFrame(); });
  function updateVisibility() {
    frame.hidden = !show.checked || !!(popup && !popup.closed);
    cameraButton.setAttribute('aria-pressed', String(!frame.hidden || !!(popup && !popup.closed)));
    if(!popup || popup.closed) cameraButton.title='顯示／隱藏相機視窗';
    if (!frame.hidden) { sizeFrame(); clampFrame(); }
  }
  show.addEventListener('change', updateVisibility);
  function dock() {
    if (popup && !popup.closed) popup.close(); popup = null; popupCanvas = popupContext = popupBadge = popupClock = null;
    show.checked = true; updateVisibility();
  }
  function detach() {
    if (popup && !popup.closed) { popup.focus(); return; }
    popup = window.open('', '', 'popup,width=920,height=720,resizable=yes,scrollbars=no');
    if (!popup) { status.textContent = '瀏覽器封鎖了獨立視窗，請允許此網站開啟彈出式視窗後重試。'; status.hidden = false; return; }
    status.hidden = true;
    const d = popup.document; d.title = document.title + ' · 相機';
    d.head.innerHTML = '<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">';
    const style = d.createElement('style'); style.textContent = 'html,body{margin:0;height:100%;background:#080f18;color:#d8ecf7;font:14px system-ui}body{display:flex;flex-direction:column}header,footer{padding:12px;display:flex;align-items:center;gap:12px;flex-wrap:wrap}header b{flex:1}button{background:#193748;color:#e7f7ff;border:1px solid #56778b;border-radius:5px;padding:8px;cursor:pointer}main{flex:1;min-height:0;position:relative;display:flex;align-items:center;justify-content:center}canvas{width:100%;height:100%;object-fit:contain}.badge{position:absolute;left:12px;top:12px;background:#071720dd;white-space:pre-line;padding:6px;font:12px system-ui}footer{font-size:12px;color:#93b4c6}'; d.head.append(style);
    d.body.innerHTML = '<header><b></b></header><main><canvas aria-label="同步相機影像"></canvas><div class="badge"></div></main><footer><span id="cameraTime"></span><span>跟隨主頁播放、暫停與跳轉；關閉後回到主頁。主頁重新載入時關閉。</span></footer>';
    popupCanvas = d.querySelector('canvas'); popupContext = popupCanvas.getContext('2d'); popupBadge = d.querySelector('.badge'); popupClock = d.getElementById('cameraTime');
    button(d.querySelector('header'), '標記', '切換檢測標記', () => attachedVision?.host.querySelector('button')?.click());
    button(d.querySelector('header'), '↙ 回到主頁', '將相機視窗放回主頁', dock);
    updateVisibility();
  }
  const monitor = setInterval(() => { if (popup?.closed) dock(); }, 400);
  /** Render with the existing WebGL context, then copy the sensor frame. A
   * render target avoids scissor clipping when the panel crosses the main view. */
  function renderCamera({renderer, scene, camera: sensor, vision, marks, title: label, result: detail, aspect = 1.5}) {
    updateVisibility();
    if (frame.hidden && !(popup && !popup.closed)) { vision.hide(); return; }
    if (label !== undefined) title.textContent = label;
    if (detail !== undefined) result.textContent = detail;
    if (attachedVision !== vision) { attachedVision = vision; image.append(vision.host); vision.host.style.position = 'absolute'; }
    image.style.aspectRatio = String(aspect);
    const displayWidth = image.clientWidth || 480, displayHeight = displayWidth/aspect;
    const width = Math.min(960, Math.max(480, Math.round((popup ? popup.innerWidth : displayWidth)*Math.min(devicePixelRatio, 2))));
    const height = Math.round(width/aspect);
    if (!target || target.width !== width || target.height !== height) {
      target?.dispose(); hdrTarget?.dispose();
      hdrTarget = new THREE.WebGLRenderTarget(width,height,{type:THREE.HalfFloatType,depthBuffer:true});
      target = new THREE.WebGLRenderTarget(width, height, {depthBuffer:false});
      resolveMaterial.uniforms.sensor.value=hdrTarget.texture;
      pixels = new Uint8Array(width*height*4); imageData = new ImageData(width,height); imageCanvas.width=width; imageCanvas.height=height;
    }
    const oldTarget=renderer.getRenderTarget(),viewport=renderer.getViewport(new THREE.Vector4()),scissor=renderer.getScissor(new THREE.Vector4()),test=renderer.getScissorTest();
    try {
      renderer.setRenderTarget(hdrTarget); renderer.setViewport(0,0,width,height); renderer.setScissorTest(false);
      if (sensor.isPerspectiveCamera) { sensor.aspect=aspect; sensor.updateProjectionMatrix(); }
      renderer.render(scene,sensor); resolveMaterial.uniforms.toneMappingExposure.value=renderer.toneMappingExposure;
      renderer.setRenderTarget(target);renderer.render(resolveScene,resolveCamera);
      renderer.readRenderTargetPixels(target,0,0,width,height,pixels);
      const stride=width*4; for(let row=0;row<height;row++) imageData.data.set(pixels.subarray((height-1-row)*stride,(height-row)*stride),row*stride);
      imageContext.putImageData(imageData,0,0);
    } finally { renderer.setRenderTarget(oldTarget); renderer.setViewport(viewport); renderer.setScissor(scissor); renderer.setScissorTest(test); }
    vision.draw(sensor,{left:0,top:0,width:displayWidth,height:displayHeight},marks);
    frame.dataset.time=String(marks.time); frame.dataset.camera=title.textContent;
    if(popup && !popup.closed) {
      if(popupCanvas.width!==width || popupCanvas.height!==height){popupCanvas.width=width;popupCanvas.height=height;}
      popupContext.drawImage(imageCanvas,0,0); const overlay=vision.host.querySelector('canvas'); popupContext.drawImage(overlay,0,0,width,height);
      const badge=vision.host.querySelector('.vision-summary'); popupBadge.textContent=badge.hidden?'':badge.textContent; popupBadge.hidden=badge.hidden;
      popup.document.querySelector('header b').textContent=title.textContent;
      popupClock.textContent=`主時間軸 ${Number(marks.time).toFixed(2)} s · ${result.textContent}`;
      popup.document.body.dataset.time=String(marks.time);
      cameraButton.title=`獨立相機視窗 · ${Number(marks.time).toFixed(2)} s · 點選放回主頁`;
    }
  }
  css.addEventListener('load', layout); window.addEventListener('resize', layout);
  const observer = new ResizeObserver(() => resize()); observer.observe(canvas);
  window.addEventListener('beforeunload', () => { if(popup&&!popup.closed)popup.close(); target?.dispose(); hdrTarget?.dispose(); resolveMaterial.dispose(); resolveQuad.geometry.dispose(); clearInterval(monitor); observer.disconnect(); });
  sizeFrame(); updateVisibility();
  requestAnimationFrame(layout);
  return {follow, stopFollowing, renderOverview, renderCamera, get following(){return tracking;}};
}
