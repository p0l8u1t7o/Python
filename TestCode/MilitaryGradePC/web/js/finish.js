// Deterministic, offline micro-finish. Linear data maps never tint the base colour.
import * as THREE from 'three';
const cache = new Map();
export function finish(material, kind = 'polymer', relief = .018) {
  if (!cache.has(kind)) {
    const n = 128, data = new Uint8Array(n*n*4);
    for(let y=0;y<n;y++)for(let x=0;x<n;x++){
      const hash = ((Math.imul(x+17,1973)^Math.imul(y+31,9277)^Math.imul(x*y,26699))>>>0)%256;
      const v=kind==='metal'?218+12*Math.sin(y*11.7)+hash*.055:210+hash*.15;
      const i=(y*n+x)*4;data[i]=data[i+1]=data[i+2]=v;data[i+3]=255;
    }
    const t=new THREE.DataTexture(data,n,n);t.wrapS=t.wrapT=THREE.RepeatWrapping;
    t.magFilter=THREE.LinearFilter;t.minFilter=THREE.LinearMipmapLinearFilter;
    t.generateMipmaps=true;t.anisotropy=8;t.repeat.set(6,6);t.needsUpdate=true;cache.set(kind,t);
  }
  material.bumpMap=material.roughnessMap=cache.get(kind);material.bumpScale=relief;
  return material;
}

