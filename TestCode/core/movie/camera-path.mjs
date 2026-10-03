// Pure absolute-time camera filtering: preview and recording give the same pose.
export const smooth=x=>{const t=Math.max(0,Math.min(1,x));return t*t*t*(t*(t*6-15)+10);};
export const lerp=(a,b,t)=>a.map((v,i)=>v+(b[i]-v)*t);
export function filterTargets(points,radius=10){
  return points.map((_,i)=>{const sum=[0,0,0];let weight=0;
    for(let k=-radius;k<=radius;k++){
      const p=points[Math.max(0,Math.min(points.length-1,i+k))],w=Math.exp(-.5*(k/(radius/2))**2);weight+=w;
      for(let j=0;j<3;j++)sum[j]+=p[j]*w;
    }return sum.map(v=>v/weight);
  });
}
export function atFrame(points,frame,stride=6){
  const i=Math.max(0,Math.min(points.length-1,Math.floor(frame/stride)));
  return lerp(points[i],points[Math.min(i+1,points.length-1)],(frame-i*stride)/stride);
}
