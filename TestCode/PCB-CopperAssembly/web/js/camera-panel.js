// Enlarge the same sensor image, preserving its field of view and aspect ratio.
export function cameraPanel() {
  const frame=document.getElementById('pipFrame'),button=document.createElement('button');
  button.className='pipExpand';button.type='button';button.setAttribute('aria-label','放大相機畫面');
  function update(){const large=frame.classList.contains('expanded');button.textContent=large?'縮小':'放大';button.setAttribute('aria-pressed',String(large));}
  button.onclick=()=>{frame.classList.toggle('expanded');update();};frame.appendChild(button);
  if(new URLSearchParams(location.search).get('cameraSize')==='large')frame.classList.add('expanded');update();
}
