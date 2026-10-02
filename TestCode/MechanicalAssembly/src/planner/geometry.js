// 推論器的幾何工具：每個幾何建一次 BVH，提供射線、最近點、取樣與形狀特徵。
import {
  Box3,
  BufferAttribute,
  BufferGeometry,
  DoubleSide,
  Matrix3,
  Matrix4,
  Ray,
  Vector3,
} from "three";
import { MeshBVH } from "three-mesh-bvh";

export function rng(seed = 1) {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

// 對稱 3×3 矩陣的 Jacobi 特徵分解；回傳由大到小排序的特徵值與特徵向量
export function eigenSymmetric(m) {
  const a = [
    [m[0], m[1], m[2]],
    [m[1], m[3], m[4]],
    [m[2], m[4], m[5]],
  ];
  const v = [
    [1, 0, 0],
    [0, 1, 0],
    [0, 0, 1],
  ];
  for (let sweep = 0; sweep < 32; sweep++) {
    let off = 0;
    for (let p = 0; p < 3; p++)
      for (let q = p + 1; q < 3; q++) off += a[p][q] * a[p][q];
    if (off < 1e-20) break;
    for (let p = 0; p < 3; p++)
      for (let q = p + 1; q < 3; q++) {
        if (Math.abs(a[p][q]) < 1e-30) continue;
        const theta = (a[q][q] - a[p][p]) / (2 * a[p][q]);
        const t =
          Math.sign(theta || 1) /
          (Math.abs(theta) + Math.sqrt(theta * theta + 1));
        const c = 1 / Math.sqrt(t * t + 1),
          s = t * c;
        for (let k = 0; k < 3; k++) {
          const akp = a[k][p],
            akq = a[k][q];
          a[k][p] = c * akp - s * akq;
          a[k][q] = s * akp + c * akq;
        }
        for (let k = 0; k < 3; k++) {
          const apk = a[p][k],
            aqk = a[q][k];
          a[p][k] = c * apk - s * aqk;
          a[q][k] = s * apk + c * aqk;
        }
        for (let k = 0; k < 3; k++) {
          const vkp = v[k][p],
            vkq = v[k][q];
          v[k][p] = c * vkp - s * vkq;
          v[k][q] = s * vkp + c * vkq;
        }
      }
  }
  return [0, 1, 2]
    .map((i) => ({
      value: a[i][i],
      vector: new Vector3(v[0][i], v[1][i], v[2][i]).normalize(),
    }))
    .sort((x, y) => y.value - x.value);
}

// 旋轉對稱使兩個特徵值幾乎相等（差 3% 內），第三個需明顯不同（差 5% 以上）
const same = (a, b) => Math.abs(a - b) <= 0.03 * Math.max(a, b);
const apart = (a, b) => Math.abs(a - b) > 0.05 * Math.max(a, b);
function axisOf(l1, l2, l3, eig) {
  if (!(l1 > 0)) return null;
  if (same(l1, l2) && apart(l2, l3)) return eig[2].vector;
  if (same(l2, l3) && apart(l1, l2)) return eig[0].vector;
  return null;
}

const sig = (x) => (x === 0 ? "0" : Number(x).toPrecision(3));

export class GeometryStore {
  constructor(data) {
    this.data = data;
    this.bvhs = new Map();
    this.localBoxes = new Map();
    this.meshes = data.meshes.map((m) => {
      const matrix = new Matrix4().fromArray(m.matrix);
      return {
        ...m,
        matrix,
        inverse: matrix.clone().invert(),
        normalMatrix: new Matrix3().getNormalMatrix(matrix),
      };
    });
    this.meshBoxes = this.meshes.map((m) =>
      this.localBox(m.geometry).clone().applyMatrix4(m.matrix),
    );
    this.features = new Map();
  }
  geometry(key) {
    return this.data.geometries.get(key);
  }
  localBox(key) {
    if (!this.localBoxes.has(key)) {
      const p = this.geometry(key).positions;
      const box = new Box3();
      const v = new Vector3();
      for (let i = 0; i < p.length; i += 3)
        box.expandByPoint(v.set(p[i], p[i + 1], p[i + 2]));
      this.localBoxes.set(key, box);
    }
    return this.localBoxes.get(key);
  }
  bvh(key) {
    if (!this.bvhs.has(key)) {
      const g = this.geometry(key);
      const geometry = new BufferGeometry();
      geometry.setAttribute("position", new BufferAttribute(g.positions, 3));
      if (g.index) geometry.setIndex(new BufferAttribute(g.index, 1));
      this.bvhs.set(key, new MeshBVH(geometry, { targetLeafSize: 12 }));
    }
    return this.bvhs.get(key);
  }
  box(entity) {
    if (!entity._box) {
      entity._box = new Box3();
      for (const m of entity.meshes) entity._box.union(this.meshBoxes[m]);
    }
    return entity._box;
  }
  // 以三角面迭代世界座標；callback(a, b, c) 收到可重複使用的向量
  forEachTriangle(meshIndex, callback) {
    const mesh = this.meshes[meshIndex];
    const g = this.geometry(mesh.geometry);
    const p = g.positions,
      idx = g.index;
    const count = idx ? idx.length / 3 : p.length / 9;
    const a = new Vector3(),
      b = new Vector3(),
      c = new Vector3();
    for (let t = 0; t < count; t++) {
      const i0 = idx ? idx[t * 3] : t * 3,
        i1 = idx ? idx[t * 3 + 1] : t * 3 + 1,
        i2 = idx ? idx[t * 3 + 2] : t * 3 + 2;
      a.set(p[i0 * 3], p[i0 * 3 + 1], p[i0 * 3 + 2]).applyMatrix4(mesh.matrix);
      b.set(p[i1 * 3], p[i1 * 3 + 1], p[i1 * 3 + 2]).applyMatrix4(mesh.matrix);
      c.set(p[i2 * 3], p[i2 * 3 + 1], p[i2 * 3 + 2]).applyMatrix4(mesh.matrix);
      callback(a, b, c);
    }
  }
  /**
   * 形狀特徵：面積、體積、法向量共變異（找軸向／板件法向）、表面取樣點與幾何指紋。
   * 取樣點沿法向往內縮 tol，避免貼合面被誤判為干涉。
   */
  analyze(entity, tol, sampleTarget) {
    if (entity._features) return entity._features;
    let area = 0,
      volume = 0,
      triangles = 0;
    const cov = [0, 0, 0, 0, 0, 0];
    const tris = [];
    const ab = new Vector3(),
      ac = new Vector3(),
      n = new Vector3();
    for (const m of entity.meshes)
      this.forEachTriangle(m, (a, b, c) => {
        ab.subVectors(b, a);
        ac.subVectors(c, a);
        n.crossVectors(ab, ac);
        const twice = n.length();
        triangles++;
        // 散度定理：封閉網格的有號體積 = Σ a·(b×c) / 6
        volume +=
          (a.x * (b.y * c.z - b.z * c.y) +
            a.y * (b.z * c.x - b.x * c.z) +
            a.z * (b.x * c.y - b.y * c.x)) /
          6;
        if (twice <= 1e-12) return;
        const ar = twice / 2;
        n.divideScalar(twice);
        area += ar;
        cov[0] += ar * n.x * n.x;
        cov[1] += ar * n.x * n.y;
        cov[2] += ar * n.x * n.z;
        cov[3] += ar * n.y * n.y;
        cov[4] += ar * n.y * n.z;
        cov[5] += ar * n.z * n.z;
        tris.push(
          ar,
          a.x, a.y, a.z,
          b.x, b.y, b.z,
          c.x, c.y, c.z,
          n.x, n.y, n.z,
        );
      });
    const stride = 13;
    const count = tris.length / stride;
    const eig = eigenSymmetric(cov.map((x) => x / Math.max(area, 1e-12)));
    const [l1, l2, l3] = eig.map((e) => Math.max(e.value, 0));
    // 取樣：面積加權亂數取點，固定亂數種子讓結果可重現
    const samples = Math.max(
      48,
      Math.min(sampleTarget, Math.round(48 + 5 * Math.sqrt(count))),
    );
    const cumulative = new Float64Array(count);
    let acc = 0;
    for (let t = 0; t < count; t++) {
      acc += tris[t * stride];
      cumulative[t] = acc;
    }
    const random = rng(count * 7919 + Math.round(area));
    const points = new Float32Array(samples * 3),
      normals = new Float32Array(samples * 3);
    for (let s = 0; s < samples && count; s++) {
      const r = random() * acc;
      let lo = 0,
        hi = count - 1;
      while (lo < hi) {
        const mid = (lo + hi) >> 1;
        if (cumulative[mid] < r) lo = mid + 1;
        else hi = mid;
      }
      const o = lo * stride;
      let u = random(),
        v = random();
      if (u + v > 1) {
        u = 1 - u;
        v = 1 - v;
      }
      const w = 1 - u - v;
      for (let k = 0; k < 3; k++) {
        const pos =
          w * tris[o + 1 + k] + u * tris[o + 4 + k] + v * tris[o + 7 + k];
        const nk = tris[o + 10 + k];
        points[s * 3 + k] = pos - nk * tol;
        normals[s * 3 + k] = nk;
      }
    }
    const box = this.box(entity);
    const size = box.getSize(new Vector3());
    const features = {
      area,
      volume: Math.abs(volume) > 1e-9 ? Math.abs(volume) : size.x * size.y * size.z * 0.3,
      triangles,
      points,
      normals,
      eigen: eig,
      // 軸對稱件（螺絲、銷、軸）：法向量分布在一個平面上
      axis: l1 > 0 && l2 / l1 > 0.6 && l3 < 0.6 * l2 ? eig[2].vector : null,
      // 較寬鬆的軸對稱判斷（短螺絲、螺帽、止付螺絲）：兩個特徵值相近、第三個不同
      symmetry: axisOf(l1, l2, l3, eig),
      // 板件：大部分面積朝同一個法向
      plate: l1 > 0 && l2 / l1 < 0.25 ? eig[0].vector : null,
      key: `${triangles}|${sig(area)}|${sig(l1)}|${sig(l2)}|${sig(l3)}`,
    };
    entity._features = features;
    return features;
  }
  /**
   * 薄環判斷（擋圈、墊圈、E 型扣環）：近似圓形、厚度遠小於外徑、中心為貫穿孔。
   * 尺寸上限以毫米計，對應 CAD 匯出的單位。
   */
  isThinRing(entity, features, maxDiameter = 80) {
    // 薄件的端面面積占多數，最大特徵值方向即為環的軸向
    const [e1, e2] = features.eigen;
    const n = e1.value >= 1.4 * e2.value ? e1.vector : features.axis;
    if (!n) return false;
    const u = Math.abs(n.x) < 0.9 ? new Vector3(1, 0, 0) : new Vector3(0, 1, 0);
    u.sub(n.clone().multiplyScalar(u.dot(n))).normalize();
    const w = new Vector3().crossVectors(n, u);
    const range = (axis) => {
      let min = Infinity,
        max = -Infinity;
      const p = features.points;
      for (let s = 0; s < p.length; s += 3) {
        const v = axis.x * p[s] + axis.y * p[s + 1] + axis.z * p[s + 2];
        if (v < min) min = v;
        if (v > max) max = v;
      }
      return max - min;
    };
    const thickness = range(n),
      a = range(u),
      b = range(w);
    const diameter = Math.max(a, b);
    if (!(diameter > 0) || diameter > maxDiameter) return false;
    if (thickness / diameter > 0.2 || Math.min(a, b) / diameter < 0.8) return false;
    const center = this.box(entity).getCenter(new Vector3());
    const ray = new Ray(center.clone().addScaledVector(n, -diameter), n.clone()),
      local = new Ray();
    for (const m of entity.meshes) {
      const mesh = this.meshes[m];
      local.copy(ray).applyMatrix4(mesh.inverse);
      if (this.bvh(mesh.geometry).raycastFirst(local, DoubleSide)) return false;
    }
    return true;
  }
  /** 從 points 沿 dir 射出，計算進入 target 的射線數（到達 limit 即停止）。 */
  enteringHits(points, dir, target, limit) {
    const targetBox = this.box(target);
    const ray = new Ray(),
      local = new Ray();
    const dirLocal = new Vector3();
    let hits = 0;
    for (let s = 0; s < points.length; s += 3) {
      ray.origin.set(points[s], points[s + 1], points[s + 2]);
      ray.direction.copy(dir);
      if (!ray.intersectsBox(targetBox) && !targetBox.containsPoint(ray.origin))
        continue;
      let hit = false;
      for (const m of target.meshes) {
        const box = this.meshBoxes[m];
        if (!ray.intersectsBox(box) && !box.containsPoint(ray.origin)) continue;
        const mesh = this.meshes[m];
        local.copy(ray).applyMatrix4(mesh.inverse);
        dirLocal.copy(local.direction);
        const found = this.bvh(mesh.geometry).raycast(local, DoubleSide);
        for (const h of found)
          if (h.face && h.face.normal.dot(dirLocal) < -1e-6) {
            hit = true;
            break;
          }
        if (hit) break;
      }
      if (hit && ++hits >= limit) return hits;
    }
    return hits;
  }
  /** points 中有幾點距離 target 小於 maxDistance。 */
  nearPoints(points, target, maxDistance, limit) {
    const box = this.box(target).clone().expandByScalar(maxDistance);
    const p = new Vector3(),
      local = new Vector3();
    let count = 0;
    for (let s = 0; s < points.length; s += 3) {
      p.set(points[s], points[s + 1], points[s + 2]);
      if (!box.containsPoint(p)) continue;
      for (const m of target.meshes) {
        if (this.meshBoxes[m].distanceToPoint(p) > maxDistance) continue;
        const mesh = this.meshes[m];
        local.copy(p).applyMatrix4(mesh.inverse);
        const scale = mesh.matrix.getMaxScaleOnAxis() || 1;
        const hit = this.bvh(mesh.geometry).closestPointToPoint(
          local,
          {},
          0,
          maxDistance / scale,
        );
        if (hit && hit.distance * scale <= maxDistance) {
          count++;
          break;
        }
      }
      if (count >= limit) return count;
    }
    return count;
  }
}
