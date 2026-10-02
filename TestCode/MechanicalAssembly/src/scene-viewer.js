import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import { studioEnvironment } from "./studio-lighting.js";
import { RenderPipeline } from "./render-pipeline.js";
import {
  CSS2DRenderer,
  CSS2DObject,
} from "three/addons/renderers/CSS2DRenderer.js";
import { assemblyIndex, installAmount } from "./core.js";
import { displayMaterial } from "./materials.js";
const materialList = (mesh) =>
  Array.isArray(mesh.material) ? mesh.material : [mesh.material];
const SELECT_GLOW = new THREE.Color("#124438");
const STEP_GLOW = new THREE.Color("#7a4a00");
const AXIS_VECTORS = {
  x: [1, 0, 0],
  "-x": [-1, 0, 0],
  y: [0, 1, 0],
  "-y": [0, -1, 0],
  z: [0, 0, 1],
  "-z": [0, 0, -1],
};
/** 步驟的展開方向：auto 用推論方向、radial 由站中心向外、其餘為座標軸。 */
export function stepDirection(step, center) {
  if (step.axis === "auto" && step.dir)
    return new THREE.Vector3(...step.dir).normalize();
  if (step.axis === "radial") {
    const v = center.clone();
    if (v.length() < 0.15) v.set(0.25, 0.8, 0.25);
    return v.normalize();
  }
  return new THREE.Vector3(...(AXIS_VECTORS[step.axis] || [0, 1, 0]));
}

export class AssemblyViewer {
  constructor(container, onSelect) {
    this.container = container;
    this.onSelect = onSelect;
    this.meshes = [];
    this.labels = [];
    this.labelsOn = false;
    this.wire = false;
    this.selected = null;
    this.isolate = false;
    this.geometryCache = new Map();
    this.edgeCache = new Map();
    this.theme = "light";
    this.quality = "detailed";
    this.materialContext = {};
    this.scene = new THREE.Scene();
    this.camera = new THREE.PerspectiveCamera(36, 1, 0.01, 500);
    this.renderer = new THREE.WebGLRenderer({
      antialias: true,
      preserveDrawingBuffer: true,
      powerPreference: "high-performance",
    });
    this.renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
    this.renderer.outputColorSpace = THREE.SRGBColorSpace;
    this.renderer.toneMapping = THREE.ACESFilmicToneMapping;
    this.renderer.toneMappingExposure = 1.05;
    this.renderer.shadowMap.enabled = true;
    this.renderer.shadowMap.type = THREE.PCFShadowMap;
    container.append(this.renderer.domElement);
    this.environment = studioEnvironment(this.renderer);
    this.scene.environment = this.environment.texture;
    this.labelRenderer = new CSS2DRenderer();
    Object.assign(this.labelRenderer.domElement.style, {
      position: "absolute",
      inset: "0",
      pointerEvents: "none",
    });
    container.append(this.labelRenderer.domElement);
    this.controls = new OrbitControls(this.camera, this.renderer.domElement);
    this.controls.enableDamping = true;
    this.controls.minDistance = 0.08;
    this.controls.maxDistance = 120;
    this.scene.add(new THREE.HemisphereLight("#dceaff", "#303943", 0.22));
    this.sun = new THREE.DirectionalLight("#fff2df", 2.1);
    this.sun.position.set(-3, 7, 5);
    this.sun.castShadow = true;
    this.sun.shadow.mapSize.set(2048, 2048);
    Object.assign(this.sun.shadow.camera, {
      left: -8,
      right: 8,
      top: 8,
      bottom: -8,
      near: 0.1,
      far: 35,
    });
    this.sun.shadow.normalBias = 0.012;
    this.sun.shadow.bias = -0.00015;
    this.sun.shadow.radius = 3;
    this.scene.add(this.sun);
    const fill = new THREE.DirectionalLight("#bdd6fc", 0.65);
    fill.position.set(5, 2, -4);
    this.scene.add(fill);
    this.ground = new THREE.Mesh(
      new THREE.PlaneGeometry(200, 200),
      new THREE.MeshStandardMaterial({ roughness: 0.95, metalness: 0 }),
    );
    this.ground.rotation.x = -Math.PI / 2;
    this.ground.receiveShadow = true;
    this.scene.add(this.ground);
    this.grid = new THREE.GridHelper(20, 40, "#9eafb9", "#c6d0d6");
    this.grid.material.transparent = true;
    this.grid.material.opacity = 0.18;
    this.grid.material.depthWrite = false;
    this.scene.add(this.grid);
    this.group = new THREE.Group();
    // 裝入方向箭頭：一律畫在最上層，不被零件遮住
    this.arrows = new THREE.Group();
    this.arrows.renderOrder = 10;
    this.arrowMaterial = new THREE.MeshBasicMaterial({
      color: "#e8930c",
      transparent: true,
      opacity: 0.92,
      depthTest: false,
      depthWrite: false,
    });
    this.arrowStep = null;
    this.scene.add(this.arrows);
    this.scene.add(this.group);
    this.pipeline = new RenderPipeline(this.renderer, this.scene, this.camera);
    this.camera.position.set(7, 5, 7);
    this.ground.position.y = -2.5;
    this.grid.position.y = -2.498;
    this.raycaster = new THREE.Raycaster();
    this.pointer = new THREE.Vector2();
    let start;
    this.renderer.domElement.addEventListener(
      "pointerdown",
      (e) => (start = [e.clientX, e.clientY]),
    );
    this.renderer.domElement.addEventListener("pointerup", (e) => {
      if (!start || Math.hypot(e.clientX - start[0], e.clientY - start[1]) > 5)
        return;
      const r = this.renderer.domElement.getBoundingClientRect();
      this.pointer.set(
        ((e.clientX - r.left) / r.width) * 2 - 1,
        (-(e.clientY - r.top) / r.height) * 2 + 1,
      );
      this.raycaster.setFromCamera(this.pointer, this.camera);
      const hit = this.raycaster.intersectObjects(
        this.meshes.filter((m) => m.visible && !m.userData.ghost),
        false,
      )[0];
      this.onSelect(hit?.object.userData.partId || null);
    });
    this.resizeObserver = new ResizeObserver(() => this.resize());
    this.resizeObserver.observe(container);
    this.resize();
    this.setTheme("light");
    this.ghostMaterial = new THREE.MeshStandardMaterial({
      color: "#8fb3c9",
      transparent: true,
      opacity: 0.1,
      depthWrite: false,
      roughness: 0.6,
      metalness: 0,
    });
    this.controls.addEventListener("start", () => (this.tween = null));
    this.renderFrame = (now = performance.now()) => {
      this.stepTween(now);
      this.controls.update();
      this.pipeline.render();
      this.labelRenderer.render(this.scene, this.camera);
    };
    this.setActive(true);
  }
  setTheme(theme) {
    this.theme = theme;
    this.scene.background = new THREE.Color(
      theme === "dark" ? "#111921" : "#d9dfe5",
    );
    this.ground.material.color.set(theme === "dark" ? "#172029" : "#a7b3bf");
    this.scene.environmentIntensity = 1;
    this.grid.material.opacity = theme === "dark" ? 0.045 : 0.07;
  }
  resize() {
    const w = this.container.clientWidth,
      h = this.container.clientHeight;
    if (!w || !h) return;
    this.camera.aspect = w / h;
    this.camera.updateProjectionMatrix();
    this.renderer.setSize(w, h);
    this.pipeline?.resize(w, h);
    this.labelRenderer.setSize(w, h);
  }
  clear() {
    this.showArrows(-1);
    this.assembly = null;
    this.tween = null;
    for (const m of this.meshes) {
      this.setGhost(m, false);
      materialList(m).forEach((mat) => mat.dispose());
      m.userData.edge?.material.dispose();
    }
    for (const g of this.geometryCache.values()) g.dispose();
    for (const g of this.edgeCache.values()) g.dispose();
    this.geometryCache.clear();
    this.edgeCache.clear();
    this.labels.forEach((l) => l.element.remove());
    this.meshes = [];
    this.labels = [];
    this.group.clear();
    this.triangles = 0;
    this.pipeline.configure(this.quality === "detailed", 0);
  }
  load(root, parts, materialContext = {}) {
    this.clear();
    this.materialContext = materialContext;
    this.selected = null;
    this.isolate = false;
    this.triangles = 0;
    if (!root) return;
    root.updateMatrixWorld(true);
    const box = new THREE.Box3().setFromObject(root),
      center = box.getCenter(new THREE.Vector3()),
      extent = box.getSize(new THREE.Vector3()),
      scale = 4 / Math.max(extent.x, extent.y, extent.z, 0.001);
    const normalization = new THREE.Matrix4()
        .makeScale(scale, scale, scale)
        .multiply(
          new THREE.Matrix4().makeTranslation(-center.x, -center.y, -center.z),
        ),
      byId = new Map(parts.map((p) => [p.id, p]));
    root.traverse((o) => {
      if (!o.isMesh) return;
      if (!this.geometryCache.has(o.geometry.uuid)) {
        const geo = o.geometry.clone();
        if (!geo.attributes.normal) geo.computeVertexNormals();
        geo.computeBoundingBox();
        this.geometryCache.set(o.geometry.uuid, geo);
      }
      const geometry = this.geometryCache.get(o.geometry.uuid),
        part = byId.get(o.userData.partId),
        sourceMaterials = materialList(o),
        materials = sourceMaterials.map((mat) =>
          displayMaterial(
            mat,
            o.name,
            part?.material || "auto",
            this.materialContext,
          ),
        );
      const mesh = new THREE.Mesh(
        geometry,
        Array.isArray(o.material) ? materials : materials[0],
      );
      mesh.name = o.name;
      mesh.applyMatrix4(normalization.clone().multiply(o.matrixWorld));
      mesh.updateMatrixWorld(true);
      const bounds = geometry.boundingBox
          .clone()
          .applyMatrix4(mesh.matrixWorld),
        centroid = bounds.getCenter(new THREE.Vector3());
      mesh.userData = {
        partId: o.userData.partId,
        basePosition: mesh.position.clone(),
        baseMinY: bounds.min.y,
        bounds,
        center: centroid,
        chain: [],
        sourceMaterials,
        localCenter: geometry.boundingBox.getCenter(new THREE.Vector3()),
        edge: null,
      };
      mesh.castShadow = !materials.some((m) => m.transparent);
      mesh.receiveShadow = true;
      this.meshes.push(mesh);
      this.group.add(mesh);
      this.triangles +=
        (geometry.index?.count || geometry.attributes.position.count) / 3;
    });
    this.setQuality(this.quality);
    this.ground.position.y = (-extent.y * scale) / 2 - 0.025;
    this.grid.position.y = this.ground.position.y + 0.002;
    if (this.wire) this.setWire(true);
    this.fit();
  }
  setAppearance(id, override) {
    for (const mesh of this.meshes) {
      if (mesh.userData.partId !== id) continue;
      const ghost = !!mesh.userData.ghost;
      this.setGhost(mesh, false);
      materialList(mesh).forEach((m) => m.dispose());
      const materials = mesh.userData.sourceMaterials.map((s) =>
        displayMaterial(s, mesh.name, override, this.materialContext),
      );
      mesh.material = Array.isArray(mesh.material) ? materials : materials[0];
      mesh.castShadow = !materials.some((m) => m.transparent);
      this.setGhost(mesh, ghost);
    }
  }
  setQuality(quality) {
    this.quality = quality;
    const detailed = quality === "detailed";
    this.renderer.shadowMap.enabled = detailed && this.triangles < 4_000_000;
    this.pipeline.configure(detailed, this.triangles || 0);
  }
  label(mesh) {
    if (mesh.userData.label) return mesh.userData.label;
    const div = document.createElement("div");
    div.className = "part-label";
    div.textContent = mesh.name;
    const label = new CSS2DObject(div);
    label.position.copy(mesh.userData.localCenter);
    mesh.add(label);
    mesh.userData.label = label;
    this.labels.push(label);
    return label;
  }
  /** 依站別的組裝節點樹計算每個節點的展開向量（正規化後的場景座標）。 */
  setAssembly(station) {
    this.showArrows(-1);
    this.assembly = null;
    for (const mesh of this.meshes) mesh.userData.chain = [];
    if (!station?.nodes?.length || !this.meshes.length) return;
    const index = assemblyIndex(station);
    const meshesOf = new Map();
    for (const mesh of this.meshes)
      for (const id of index.chains.get(mesh.userData.partId) || []) {
        if (!meshesOf.has(id)) meshesOf.set(id, []);
        meshesOf.get(id).push(mesh);
      }
    const vectors = new Map();
    const size = new THREE.Vector3();
    for (const [id, meshes] of meshesOf) {
      const step = station.plan[index.stepOf.get(id)];
      if (!step) continue;
      const box = new THREE.Box3();
      meshes.forEach((m) => box.union(m.userData.bounds));
      const center = box.getCenter(new THREE.Vector3());
      const dir = stepDirection(step, center);
      box.getSize(size);
      const extent =
        Math.abs(dir.x) * size.x +
        Math.abs(dir.y) * size.y +
        Math.abs(dir.z) * size.z;
      // 展開距離：節點沿方向的長度再加固定間隙，乘上步驟倍率
      vectors.set(id, dir.multiplyScalar((extent * 1.1 + 0.3) * step.distance));
    }
    for (const mesh of this.meshes)
      mesh.userData.chain = (index.chains.get(mesh.userData.partId) || [])
        .filter((id) => vectors.has(id))
        .map((id) => ({
          id,
          step: index.stepOf.get(id),
          vector: vectors.get(id),
        }));
    this.assembly = { index, meshesOf, plan: station.plan };
  }
  offsetAt(mesh, amountOf, target = new THREE.Vector3()) {
    target.set(0, 0, 0);
    for (const link of mesh.userData.chain)
      target.addScaledVector(link.vector, 1 - amountOf(link));
    return target;
  }
  /**
   * @param {number} progress 時間軸進度（第 k 步在 [k, k+1)）
   * @param {{mode?: "solid"|"explode"|"assemble", explode?: number, future?: "ghost"|"hide"|"show"}} options
   */
  update(progress = 0, options = {}) {
    const mode = options.mode || "solid",
      explode = options.explode ?? 0.65,
      future = options.future || "ghost";
    const current =
      mode === "assemble" && this.assembly
        ? Math.min(Math.floor(progress), this.assembly.plan.length - 1)
        : -1;
    const amountOf =
      mode === "solid"
        ? () => 1
        : mode === "explode"
          ? () => 1 - explode
          : (link) => installAmount(link.step, progress);
    // 預組步驟：只顯示該預組件本身，其他零件淡化，如同在工作台另外組裝
    const context = new Set();
    if (current >= 0)
      for (const id of this.assembly.plan[current].nodeIds) {
        const parent = this.assembly.index.nodes.get(id)?.parentId;
        if (parent && parent !== "root") context.add(parent);
      }
    const offset = new THREE.Vector3();
    let floorY = Infinity;
    for (const mesh of this.meshes) {
      const chain = mesh.userData.chain;
      this.offsetAt(mesh, amountOf, offset);
      mesh.position.copy(mesh.userData.basePosition).add(offset);
      const own = chain.length ? chain[0].step : -1;
      // 尚未輪到的零件：淡影顯示在完成位置，或隱藏，或停在展開位置
      const pending = mode === "assemble" && own >= 0 && progress < own;
      if (pending && future === "ghost")
        mesh.position.copy(mesh.userData.basePosition);
      const outside =
        context.size > 0 && !chain.some((l) => context.has(l.id));
      const active = current >= 0 && chain.some((l) => l.step === current);
      const selected = mesh.userData.partId === this.selected;
      this.setGhost(mesh, (pending && future === "ghost") || (outside && !pending));
      for (const mat of materialList(mesh)) {
        if (!mat.userData.baseEmissive) continue;
        mat.emissive.copy(mat.userData.baseEmissive);
        if (selected && !this.isolate) mat.emissive.add(SELECT_GLOW);
        else if (active) mat.emissive.add(STEP_GLOW);
      }
      mesh.visible =
        (!this.isolate || selected) &&
        !(pending && (future === "hide" || (outside && future === "show")));
      if (mesh.visible && !mesh.userData.ghost)
        floorY = Math.min(
          floorY,
          mesh.userData.baseMinY +
            mesh.position.y -
            mesh.userData.basePosition.y,
        );
      const visible =
        mesh.visible &&
        !mesh.userData.ghost &&
        ((selected && !this.isolate) ||
          (this.labelsOn && this.meshes.length <= 100));
      if (visible || mesh.userData.label) this.label(mesh).visible = visible;
    }
    this.showArrows(mode === "assemble" && options.arrows !== false ? current : -1);
    if (Number.isFinite(floorY)) {
      this.ground.position.y = floorY - 0.025;
      this.grid.position.y = floorY - 0.023;
    }
  }
  setGhost(mesh, ghost) {
    if (!!mesh.userData.ghost === ghost) return;
    mesh.userData.ghost = ghost;
    if (ghost) {
      mesh.userData.solidMaterial = mesh.material;
      mesh.material = Array.isArray(mesh.material)
        ? mesh.material.map(() => this.ghostMaterial)
        : this.ghostMaterial;
      mesh.castShadow = false;
      if (mesh.userData.edge) mesh.userData.edge.visible = false;
    } else {
      mesh.material = mesh.userData.solidMaterial;
      mesh.castShadow = !materialList(mesh).some((m) => m.transparent);
      if (mesh.userData.edge) mesh.userData.edge.visible = this.wire;
    }
  }
  /** 第 step 步的零件（起點與終點）加上同單元已裝零件的範圍，用於鏡頭跟隨。 */
  stepBounds(step) {
    if (!this.assembly) return null;
    const { index, meshesOf, plan } = this.assembly;
    const ids = plan[step]?.nodeIds || [];
    const moving = new Set(ids.flatMap((id) => meshesOf.get(id) || []));
    const parents = new Set(ids.map((id) => index.nodes.get(id)?.parentId));
    const box = new THREE.Box3(),
      offset = new THREE.Vector3(),
      part = new THREE.Box3();
    const at = (p) => (link) => installAmount(link.step, p);
    for (const mesh of this.meshes) {
      const chain = mesh.userData.chain;
      const sibling =
        !moving.has(mesh) &&
        chain.length &&
        chain[0].step < step &&
        chain.some((l) => parents.has(index.nodes.get(l.id)?.parentId));
      if (!moving.has(mesh) && !sibling) continue;
      for (const p of moving.has(mesh) ? [step, step + 1] : [step]) {
        this.offsetAt(mesh, at(p), offset);
        part.copy(mesh.userData.bounds).translate(offset);
        box.union(part);
      }
    }
    return box.isEmpty() ? null : box;
  }
  /** 第 step 步每個移動節點一支箭頭：由展開位置指向完成位置。 */
  showArrows(step) {
    if (this.arrowStep === step) return;
    this.arrowStep = step;
    for (const child of [...this.arrows.children]) {
      child.traverse((o) => o.geometry?.dispose());
      this.arrows.remove(child);
    }
    if (step < 0 || !this.assembly) return;
    const { meshesOf, plan } = this.assembly;
    const at = (p) => (link) => installAmount(link.step, p);
    const offset = new THREE.Vector3();
    for (const id of plan[step].nodeIds.slice(0, 24)) {
      const meshes = meshesOf.get(id) || [];
      if (!meshes.length) continue;
      const box = new THREE.Box3();
      meshes.forEach((m) => box.union(m.userData.bounds));
      const center = box.getCenter(new THREE.Vector3());
      const from = center.clone().add(this.offsetAt(meshes[0], at(step), offset));
      const to = center.clone().add(this.offsetAt(meshes[0], at(step + 1), offset));
      const length = from.distanceTo(to);
      if (length < 0.05) continue;
      const radius = THREE.MathUtils.clamp(length * 0.02, 0.006, 0.03);
      const head = Math.min(radius * 5, length * 0.35);
      const arrow = new THREE.Group();
      const shaft = new THREE.Mesh(
        new THREE.CylinderGeometry(radius, radius, length - head, 12),
        this.arrowMaterial,
      );
      shaft.position.y = (length - head) / 2;
      const tip = new THREE.Mesh(
        new THREE.ConeGeometry(radius * 2.6, head, 16),
        this.arrowMaterial,
      );
      tip.position.y = length - head / 2;
      for (const m of [shaft, tip]) {
        m.renderOrder = 10;
        m.raycast = () => {};
        arrow.add(m);
      }
      arrow.position.copy(from);
      arrow.quaternion.setFromUnitVectors(
        new THREE.Vector3(0, 1, 0),
        to.clone().sub(from).normalize(),
      );
      this.arrows.add(arrow);
    }
  }
  /** 平滑移動鏡頭到指定範圍，保留目前的觀看方向；immediate 時直接到位（輸出圖片用）。 */
  focusBox(box, minRadius = 0.7, immediate = false) {
    if (!box) return;
    const center = box.getCenter(new THREE.Vector3());
    const radius = Math.max(
      box.getSize(new THREE.Vector3()).length() / 2,
      minRadius,
    );
    const vertical = THREE.MathUtils.degToRad(this.camera.fov / 2),
      horizontal = Math.atan(Math.tan(vertical) * this.camera.aspect),
      distance = (radius / Math.sin(Math.min(vertical, horizontal))) * 1.15;
    const direction = this.camera.position
      .clone()
      .sub(this.controls.target)
      .normalize();
    this.tween = {
      start: performance.now(),
      fromTarget: this.controls.target.clone(),
      fromPosition: this.camera.position.clone(),
      toTarget: center,
      toPosition: center.clone().addScaledVector(direction, distance),
    };
    this.camera.near = Math.max(0.001, distance / 1000);
    this.camera.far = Math.max(100, distance * 10);
    this.camera.updateProjectionMatrix();
    if (immediate) {
      this.stepTween(this.tween.start + 1e6);
      this.controls.update();
    }
  }
  stepTween(now) {
    const t = this.tween;
    if (!t) return;
    const k = Math.min(1, (now - t.start) / 700);
    const e = k * k * (3 - 2 * k);
    this.controls.target.lerpVectors(t.fromTarget, t.toTarget, e);
    this.camera.position.lerpVectors(t.fromPosition, t.toPosition, e);
    if (k >= 1) this.tween = null;
  }
  fit(direction = new THREE.Vector3(1, 0.65, 1)) {
    const bounds = new THREE.Box3();
    for (const mesh of this.meshes) {
      if (!mesh.visible) continue;
      mesh.updateWorldMatrix(true, false);
      bounds.union(
        mesh.geometry.boundingBox.clone().applyMatrix4(mesh.matrixWorld),
      );
    }
    if (bounds.isEmpty()) return;
    const center = bounds.getCenter(new THREE.Vector3()),
      size = bounds.getSize(new THREE.Vector3()),
      radius = size.length() / 2,
      vertical = THREE.MathUtils.degToRad(this.camera.fov / 2),
      horizontal = Math.atan(Math.tan(vertical) * this.camera.aspect),
      distance = (radius / Math.sin(Math.min(vertical, horizontal))) * 1.08;
    this.controls.target.copy(center);
    this.camera.position
      .copy(center)
      .add(direction.normalize().multiplyScalar(distance));
    this.camera.near = Math.max(0.001, distance / 1000);
    this.camera.far = Math.max(100, distance * 10);
    this.camera.updateProjectionMatrix();
    this.controls.update();
  }
  view(axis) {
    this.fit(
      new THREE.Vector3(
        ...{
          front: [0, 0, 1],
          top: [0, 1, 0.001],
          side: [1, 0, 0],
          iso: [1, 0.65, 1],
        }[axis],
      ),
    );
  }
  setWire(value) {
    this.wire = value;
    for (const mesh of this.meshes) {
      if (value && !mesh.userData.edge) {
        if (!this.edgeCache.has(mesh.geometry.uuid))
          this.edgeCache.set(
            mesh.geometry.uuid,
            new THREE.EdgesGeometry(mesh.geometry, 28),
          );
        const edge = new THREE.LineSegments(
          this.edgeCache.get(mesh.geometry.uuid),
          new THREE.LineBasicMaterial({
            color: "#273f50",
            transparent: true,
            opacity: 0.22,
          }),
        );
        edge.raycast = () => {};
        mesh.add(edge);
        mesh.userData.edge = edge;
      }
      if (mesh.userData.edge)
        mesh.userData.edge.visible = value && !mesh.userData.ghost;
    }
  }
  screenshot(type = "image/png", quality) {
    this.pipeline.render();
    return this.renderer.domElement.toDataURL(type, quality);
  }
  /** 輸出時暫時提高算圖解析度；scale = null 恢復螢幕設定。 */
  setOutputScale(scale) {
    this.renderer.setPixelRatio(scale ?? Math.min(devicePixelRatio, 2));
    this.resize();
  }
  /** 立即算圖一次（錄影時讓畫面與進度同步）。 */
  renderNow() {
    this.controls.update();
    this.pipeline.render();
  }
  setActive(active) {
    this.renderer.setAnimationLoop(active ? this.renderFrame : null);
  }
  dispose() {
    this.setActive(false);
    this.resizeObserver.disconnect();
    this.controls.dispose();
    this.clear();
    this.pipeline.dispose();
    this.environment.dispose();
    this.ghostMaterial.dispose();
    this.arrowMaterial.dispose();
    this.ground.geometry.dispose();
    this.ground.material.dispose();
    this.grid.geometry.dispose();
    this.grid.material.dispose();
    this.sun.shadow.map?.dispose();
    this.renderer.dispose();
    this.renderer.domElement.remove();
    this.labelRenderer.domElement.remove();
  }
}
