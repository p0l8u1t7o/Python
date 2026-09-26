// 依配方組裝整站並把流程狀態套到場景（主程式與驗證共用，確保畫面與驗證看到同一個狀態）
import * as THREE from 'three';
import { createCell, LAYOUT, palletPlacement } from './cell.js';
import { createProduct } from './product.js';
import { createRobot } from './robot.js';
import { productState } from './sequence.js';

export function createStation(scene, recipe, insert = 'single') {
  const cell = createCell(scene, recipe), place = palletPlacement(recipe);
  const robot = createRobot(); robot.root.position.set(...LAYOUT.robot); scene.add(robot.root); robot.setInsert(insert); robot.apply();
  const product = createProduct(recipe); scene.add(product.root);
  // 前一盤（已壓合）與下一盤（翹起原樣），只作流向示意
  const prev = createProduct(recipe), next = createProduct(recipe); scene.add(prev.root, next.root);
  for (const id of prev.ids) { prev.setTilt(id, 0); next.setTilt(id, recipe.tilt0[id] || 0); }
  const opts = { ngHold: false }, halfW = recipe.pallet.w / 2;
  let last = null;
  function apply(s) {
    product.root.position.set(s.palletX, LAYOUT.conveyorTop + LAYOUT.liftStroke * s.lift, place.z);
    prev.root.position.set(s.prevX, LAYOUT.conveyorTop, place.z); prev.root.visible = s.prevX - halfW < 1600;
    next.root.position.set(s.nextX, LAYOUT.conveyorTop, place.z); next.root.visible = s.nextX + halfW > -1600;
    const ps = productState(s, recipe, opts);
    for (const id of product.ids) product.setTilt(id, ps.tilt[id]);
    robot.setPadCompression(ps.padComp);
    cell.setStop(s.stop); cell.setLift(s.lift); cell.setGlobalFlash(s.globalShot > 0);
    cell.updateTransport(s.palletX, sensor => Math.abs(s.palletX - sensor.x) < halfW);
    scene.updateMatrixWorld(true); last = ps;
  }
  /** 產品包絡（工具非接觸時不得進入）：載盤＋板面、每顆接頭、高於 2 mm 的零件 */
  function productBoxes(margin = 0) {
    const y0 = product.root.position.y, { w, d, t } = recipe.pallet, x = product.root.position.x, z = product.root.position.z;
    const boxes = [new THREE.Box3(new THREE.Vector3(x - w / 2, y0, z - d / 2), new THREE.Vector3(x + w / 2, y0 + t + recipe.pcbT + 1, z + d / 2))];
    for (const id of product.ids) boxes.push(new THREE.Box3().setFromObject(product.conns[id].mount));
    product.root.traverse(o => { if (o.isMesh && o.geometry.parameters?.height > 2 && o.parent !== product.root) { const b = new THREE.Box3().setFromObject(o); if (b.max.y - y0 < 30 && b.max.y - b.min.y > 2) boxes.push(b); } });
    return boxes.map(b => b.expandByScalar(margin));
  }
  return { cell, robot, product, apply, opts, productBoxes, place, get state() { return last; } };
}
