// 從 Three.js 模型抽出推論器需要的純資料（可傳進 Worker，也可在 Node 建庫時使用）。
// 只讀取幾何與世界矩陣，不修改來源模型。

/**
 * @param {import("three").Object3D} root 已呼叫 describeParts 的站別模型
 * @returns {{nodes: object[], meshes: object[], geometries: Map<string, object>}}
 */
export function extractAssembly(root) {
  root.updateMatrixWorld(true);
  const nodes = [],
    meshes = [],
    geometries = new Map();
  const visit = (o, parent) => {
    const index = nodes.length;
    const node = { name: o.name || "", parent, children: [], mesh: -1 };
    nodes.push(node);
    if (parent >= 0) nodes[parent].children.push(index);
    if (o.isMesh) {
      const g = o.geometry;
      if (!geometries.has(g.uuid)) {
        const position = g.attributes.position.array;
        geometries.set(g.uuid, {
          key: g.uuid,
          positions:
            position instanceof Float32Array
              ? position
              : new Float32Array(position),
          index: g.index ? Uint32Array.from(g.index.array) : null,
        });
      }
      node.mesh = meshes.length;
      meshes.push({
        partId: o.userData.partId,
        name: o.name || "",
        geometry: g.uuid,
        matrix: Array.from(o.matrixWorld.elements),
      });
    }
    for (const child of o.children) visit(child, index);
  };
  visit(root, -1);
  return { nodes, meshes, geometries };
}

/** 轉成可 postMessage 的形式；幾何陣列以 transfer 方式搬移副本。 */
export function serializeAssembly(data) {
  const transfer = [];
  const geometries = [...data.geometries.values()].map((g) => {
    const positions = g.positions.slice();
    const index = g.index ? g.index.slice() : null;
    transfer.push(positions.buffer);
    if (index) transfer.push(index.buffer);
    return { key: g.key, positions, index };
  });
  return {
    message: { nodes: data.nodes, meshes: data.meshes, geometries },
    transfer,
  };
}

export function deserializeAssembly(message) {
  return {
    nodes: message.nodes,
    meshes: message.meshes,
    geometries: new Map(message.geometries.map((g) => [g.key, g])),
  };
}
