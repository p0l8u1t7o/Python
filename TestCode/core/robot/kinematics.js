import * as THREE from 'three';

// 阻尼最小平方 IK：同時追 TCP 位置與工具姿態，6 軸（j1 繞 Y，j2/j3/j5 繞 Z，j4/j6 繞 X）。單位 mm。
// 預設值為 DENSO 系列專案的調校；大型手臂可加大 weight／lambda、收緊 tol（見 ChemicalTankWashing/web/js/robot.js）。
//   weight：姿態誤差換算成 mm 的權重；iterations：solve 預設迭代數；lambda：[前 4 次, 之後] 阻尼；
//   step：單次關節變化上限（rad）；tol：[位置 mm, 角度 rad] 收斂門檻
export function createIK({q,j,tool,apply,limits,weight=180,iterations=16,lambda:damping=[6,2],step=.22,tol=[.08,.001]}) {
  const names=['j1','j2','j3','j4','j5','j6'];
  const axes=[new THREE.Vector3(0,1,0),new THREE.Vector3(0,0,1),new THREE.Vector3(0,0,1),new THREE.Vector3(1,0,0),new THREE.Vector3(0,0,1),new THREE.Vector3(1,0,0)];
  const pos=new THREE.Vector3(),origin=new THREE.Vector3(),axis=new THREE.Vector3(),lever=new THREE.Vector3(),linear=new THREE.Vector3();
  const rotation=new THREE.Quaternion(),delta=new THREE.Quaternion(),jointRot=new THREE.Quaternion();
  const lim=Object.fromEntries(names.map(n=>[n,limits[n].map(x=>x*Math.PI/180)]));
  function solve(tcp,target,desired,iters=iterations) {
    for(let iteration=0;iteration<iters;iteration++){
      apply();tcp.getWorldPosition(pos);tool.getWorldQuaternion(rotation);
      delta.copy(desired).multiply(rotation.invert()).normalize();if(delta.w<0)delta.set(-delta.x,-delta.y,-delta.z,-delta.w);
      const angle=2*Math.acos(THREE.MathUtils.clamp(delta.w,-1,1)),sin=Math.sqrt(Math.max(0,1-delta.w*delta.w));
      const f=sin<1e-8?2:angle/sin;
      const e=[target.x-pos.x,target.y-pos.y,target.z-pos.z,delta.x*f*weight,delta.y*f*weight,delta.z*f*weight];
      if(Math.hypot(e[0],e[1],e[2])<tol[0]&&angle<tol[1])break;
      const cols=names.map((name,k)=>{
        j[name].getWorldPosition(origin);j[name].getWorldQuaternion(jointRot);axis.copy(axes[k]).applyQuaternion(jointRot);
        linear.crossVectors(axis,lever.copy(pos).sub(origin));
        return [linear.x,linear.y,linear.z,axis.x*weight,axis.y*weight,axis.z*weight];
      });
      // (J J^T + lambda^2 I) y = error; dq = J^T y.
      const lambda=iteration<4?damping[0]:damping[1];
      const a=Array.from({length:6},(_,r)=>Array.from({length:7},(_,c)=>c===6?e[r]:cols.reduce((sum,v)=>sum+v[r]*v[c],0)+(r===c?lambda*lambda:0)));
      for(let k=0;k<6;k++){
        let pivot=k;for(let r=k+1;r<6;r++)if(Math.abs(a[r][k])>Math.abs(a[pivot][k]))pivot=r;
        [a[k],a[pivot]]=[a[pivot],a[k]];const d=a[k][k];if(Math.abs(d)<1e-12)continue;
        for(let c=k;c<7;c++)a[k][c]/=d;
        for(let r=0;r<6;r++)if(r!==k){const v=a[r][k];for(let c=k;c<7;c++)a[r][c]-=v*a[k][c];}
      }
      names.forEach((name,k)=>{const change=cols[k].reduce((sum,v,r)=>sum+v*a[r][6],0);q[name]=THREE.MathUtils.clamp(q[name]+THREE.MathUtils.clamp(change,-step,step),...lim[name]);});
    }
    apply();
  }
  return {solve};
}
