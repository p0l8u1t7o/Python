import "./style.css";
import "./themes.css";
import { sourceProject, createCatalogUI, catalogAssets } from "./catalog.js";
import { initializeTheme } from "./theme.js";
import { MATERIAL_PRESETS } from "./materials.js";
import { createEquipmentOverview } from "./equipment-overview.js";
import * as THREE from "three";
import { AssemblyViewer } from "./viewer.js";
import {
  loadSample,
  importModel,
  describeParts,
  formats,
  orientRoot,
} from "./importer.js";
import {
  uid,
  flatAssembly,
  applyPlannerResult,
  isUntouchedDraft,
  migrateProject,
  migrateStation,
  validateProject,
  validateStationAssembly,
  assemblyIndex,
  removePart,
  appendPart,
  SCHEMA_VERSION,
  STEP_TIMING,
  escapeHTML as h,
} from "./core.js";
import { runPlanner, loadPrecomputedPlan } from "./planner-client.js";
import { sopHtml, drawCaption, countNames, baseName } from "./exporters.js";
import { saveProject, listProjects, getProject } from "./storage.js";
const $ = (s) => document.querySelector(s);
const icons = {
  cube: "◇",
  import: "↥",
  play: "▶",
  pause: "Ⅱ",
  back: "‹",
  next: "›",
  save: "↓",
  fit: "⛶",
};
$("#app").innerHTML = `
<header class="header"><a class="brand" href="/" aria-label="Assembly Studio 首頁"><span class="brand-mark">A<span>◧</span></span><span>ASSEMBLY<span class="brand-sub">STUDIO / 組裝工作台</span></span></a><div class="project-title"><span class="eyebrow">PROJECT / 專案</span><select id="projects" aria-label="切換專案"></select></div><div class="header-actions"><span id="save-status" class="save-status">本機工作區</span><button id="new-project" class="button ghost">＋ 新專案</button><button id="save" class="button ghost">${icons.save} 儲存專案</button><button id="import" class="button primary">${icons.import} 匯入 CAD</button></div></header>
<div class="workspace"><aside class="station-panel"><div class="panel-heading"><div><span class="eyebrow">ASSEMBLY TREE</span><h2>設備站別</h2></div><span id="station-count" class="count"></span></div><div class="search-box"><span>⌕</span><input id="station-search" placeholder="搜尋站別或料號" aria-label="搜尋站別"></div><nav id="stations" aria-label="設備站別"></nav><button id="add-station" class="button add-button">＋ 新增站別</button><div class="source-card"><span class="eyebrow">SOURCE LIBRARY</span><strong id="source-count">原始設計資料</strong><p>依原始資料夾建立站別，保留來源與模型範圍。</p><button id="library" class="text-button">瀏覽 CAD 資料庫 ↗</button></div><footer class="sidebar-foot"><i></i> 模型在本機處理<span>v1.0</span></footer></aside>
<main class="main"><div class="main-heading"><div><div class="breadcrumb">專案 <span>/</span> <span id="breadcrumb"></span></div><h1 id="station-title"></h1></div><span class="status-badge" id="scope"></span></div><div class="viewer-shell"><div class="viewer-toolbar"><div class="segmented"><button id="mode-solid" class="active">組合視圖</button><button id="mode-explode">爆炸圖</button><button id="mode-assemble">組裝流程</button></div><label class="explode-control">展開程度 <input id="explode" type="range" min="0" max="100" value="65" aria-label="展開程度"><output id="explode-value">65%</output></label><div class="toolbar-right"><button id="wire" title="切換邊線" aria-label="切換邊線">▱</button><button id="labels" title="零件標籤（100 件以下顯示全部）" aria-label="零件標籤">Aa</button><button id="fit" title="重設視角" aria-label="重設視角">⛶</button><button id="capture" title="下載視角圖片" aria-label="下載視角圖片">▣</button></div></div><div class="canvas-wrap"><div id="viewport"></div><div class="viewport-caption"><span class="eyebrow">3D ASSEMBLY VIEW</span><span id="model-info"></span></div><div id="empty-state" class="empty-state" hidden><span>◇</span><h3>此站尚未有可顯示的模型</h3><p>匯入 STEP / GLB 組合件，或透過 SolidWorks 轉換原生檔。</p><button id="empty-import" class="button primary">匯入本站模型</button></div><div id="loading" class="loading" hidden><span class="spinner"></span><p>讀取模型中…</p></div><div id="recording" class="recording" hidden><i></i><span id="recording-text">錄影中</span><button id="recording-cancel" class="button ghost">停止</button></div><div id="step-caption" class="step-caption" hidden><span id="step-caption-index"></span><strong id="step-caption-name"></strong><p id="step-caption-text"></p></div><div class="view-buttons"><button data-view="iso" class="active">等角</button><button data-view="front">正面</button><button data-view="top">俯視</button><button data-view="side">側面</button></div><canvas class="axis-gizmo" width="96" height="96" aria-label="座標軸：Z 朝上，XY 為水平面"></canvas><div class="canvas-help">拖曳旋轉 · 滾輪縮放 · 右鍵平移 · 點選零件</div></div><div class="model-footer"><span><i class="dot"></i> <span id="part-summary"></span></span><span id="source-name"></span></div></div>
<section class="timeline"><div class="timeline-title"><div><span class="eyebrow">ASSEMBLY SEQUENCE</span><h2>逐步組裝</h2></div><span id="step-counter">00 / 00</span><div class="timeline-options"><label>速度 <select id="speed" aria-label="播放速度"><option value=".5">0.5×</option><option value="1" selected>1×</option><option value="2">2×</option></select></label><label>未裝零件 <select id="future" aria-label="尚未安裝的零件"><option value="ghost" selected>淡影</option><option value="hide">隱藏</option><option value="show">展開</option></select></label><label class="check-inline"><input id="pause-steps" type="checkbox" checked> 每步暫停</label><label class="check-inline"><input id="follow" type="checkbox" checked> 鏡頭跟隨</label></div></div><div class="timeline-controls"><button id="previous" class="round" aria-label="上一步">‹</button><button id="play" class="play-button" aria-label="播放組裝動畫">▶</button><button id="next" class="round" aria-label="下一步">›</button><div class="scrub-wrap"><input id="scrub" type="range" min="0" max="1" step=".01" value="0" aria-label="組裝進度"><div id="scrub-marks"></div></div><button id="restart" class="button ghost">↺ 重播</button><button id="export-sop" class="button ghost" title="每步截圖＋說明＋零件清單，可列印成 PDF">⇩ 作業指導書</button><button id="export-video" class="button ghost" title="錄製含步驟字卡的 WebM 影片">● 錄影</button></div><p id="sequence-note" class="sequence-note">自動順序為草稿，請依實際裝配工法審核。</p></section></main>
<aside class="instruction-panel"><div class="panel-heading"><div><span class="eyebrow">WORK INSTRUCTIONS</span><h2>組裝步驟</h2></div><div class="panel-actions"><button id="auto-plan" class="text-button" title="依幾何干涉與 CAD 階層重新推論組裝順序">自動推論</button><button id="edit-plan" class="text-button">編輯</button></div></div><div id="steps" class="steps"></div><section id="part-detail" class="part-detail"><span class="eyebrow">COMPONENT INSPECTOR</span><h3>零件檢視</h3><p>點選模型或搜尋零件，檢視裝配群組。</p></section><div class="parts-search"><input id="part-search" placeholder="搜尋零件名稱…" aria-label="搜尋零件"><div id="part-list"></div></div><div class="instruction-foot">步驟指引可保存並跨專案重用。<br>正式裝配前需完成工程審核。</div></aside></div>
<dialog id="modal"><div id="modal-body"></div></dialog><div id="toast" role="status" hidden></div>`;
let catalog,
  catalogUI,
  inventory,
  manifest,
  project,
  station,
  root = null,
  viewer;
let progress = 0,
  explode = 0.65,
  playing = false,
  mode = "solid",
  selected = null,
  busy = false,
  dirty = false,
  loadVersion = 0,
  lastFocus = null;
const roots = new Map();
// 每一步的播放秒數（1× 速度）：淡入、移動、停留閱讀
const STEP_SECONDS = 3.2;
// 開啟站別時自動推論的零件數上限；更大的模型請按「自動推論」
const AUTO_PLAN_LIMIT = 700;
function toast(message, error = false) {
  const el = $("#toast");
  el.textContent = message;
  el.classList.toggle("error", error);
  el.hidden = false;
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => (el.hidden = true), 5500);
}
function changed() {
  dirty = true;
  $("#save-status").textContent = "● 尚未儲存";
}
function busyState(value, message = "讀取模型中…") {
  busy = value;
  $("#loading").hidden = !value;
  $("#loading p").textContent = message;
  for (const id of [
    "import",
    "new-project",
    "add-station",
    "save",
    "projects",
    "edit-plan",
    "auto-plan",
    "export-sop",
    "export-video",
    "library",
    "equipment-overview-open",
  ])
    $("#" + id).disabled = value;
  if ($("#station-asset"))
    $("#station-asset").disabled =
      value || !catalog?.items.some((a) => a.stationId === station?.id);
}
function modal(content) {
  $("#modal-body").innerHTML =
    `<button class="modal-close" aria-label="關閉">×</button>${content}`;
  $("#modal .modal-close").onclick = () => $("#modal").close();
  if (!$("#modal").open) $("#modal").showModal();
}
// 朝上軸：站別自訂 > 資料庫設定 > Y
const upFor = (s) => s?.up || manifest?.[s?.sample]?.upAxis || "y";
// 指 CAD 原檔自身的座標軸（與畫面顯示的 Z 朝上座標不同）
const UP_LABELS = {
  y: "CAD Y 軸朝上",
  z: "CAD Z 軸朝上",
  x: "CAD X 軸朝上",
  "-y": "CAD −Y 軸朝上",
  "-z": "CAD −Z 軸朝上",
  "-x": "CAD −X 軸朝上",
};
function currentStep() {
  if (!station?.plan.length) return -1;
  return Math.min(Math.floor(progress), station.plan.length - 1);
}
function sync() {
  if (!station) return;
  viewer.selected = selected;
  viewer.update(progress, {
    mode,
    explode,
    future: $("#future").value,
  });
  const total = station.plan.length,
    step = currentStep(),
    finished = total > 0 && progress >= total;
  $("#explode-value").textContent = Math.round(explode * 100) + "%";
  $("#scrub").max = total || 1;
  $("#scrub").value = progress;
  $("#step-counter").textContent =
    `${String(total ? (finished ? total : step + 1) : 0).padStart(2, "0")} / ${String(total).padStart(2, "0")}`;
  $("#play").textContent = playing ? "Ⅱ" : "▶";
  $("#play").setAttribute(
    "aria-label",
    playing ? "暫停組裝動畫" : "播放組裝動畫",
  );
  $("#mode-solid").classList.toggle("active", mode === "solid");
  $("#mode-explode").classList.toggle("active", mode === "explode");
  $("#mode-assemble").classList.toggle("active", mode === "assemble");
  $("#explode").disabled = mode !== "explode";
  // 作業指引字卡：目前步驟的名稱與說明
  const caption = mode === "assemble" && total > 0;
  $("#step-caption").hidden = !caption;
  if (caption) {
    const s = station.plan[step];
    $("#step-caption-index").textContent = finished
      ? "組裝完成"
      : `步驟 ${String(step + 1).padStart(2, "0")} / ${String(total).padStart(2, "0")}`;
    $("#step-caption-name").textContent = finished
      ? station.name
      : s.name;
    $("#step-caption-text").textContent = finished
      ? "全部零件已就定位。"
      : s.instruction;
  }
  for (const el of document.querySelectorAll(".step-card")) {
    const i = Number(el.dataset.step);
    el.classList.toggle("complete", progress >= i + 1);
    el.classList.toggle(
      "current",
      mode === "assemble" && !finished && step === i,
    );
  }
  // 鏡頭跟隨：步驟改變時平滑移到本步零件
  const key = mode === "assemble" ? (finished ? "done" : step) : null;
  if (key !== lastFocus) {
    lastFocus = key;
    if (key !== null) {
      document
        .querySelector(`.step-card[data-step="${step}"]`)
        ?.scrollIntoView({ block: "nearest" });
      if ($("#follow").checked)
        finished ? viewer.fit() : viewer.focusBox(viewer.stepBounds(step));
    }
  }
}
/** 自動草稿未經編輯時，改用預先推論或即時推論的組裝順序。 */
async function ensurePlan(target, model, version) {
  const up = upFor(target);
  // 推論方向以當時的朝上軸為準；朝上軸改變且流程未編輯時重新推論
  if (target.planSource === "geometry" && (target.planUp || "y") !== up)
    flatAssembly(target);
  if (!isUntouchedDraft(target) || !target.parts.length) return;
  let planned = await loadPrecomputedPlan(target.sample, model, up);
  if (!planned && target.parts.length <= AUTO_PLAN_LIMIT) {
    try {
      planned = await runPlanner(model, {
        onProgress: ({ done, total }) =>
          version === loadVersion &&
          ($("#loading p").textContent =
            `推論組裝順序… ${Math.round((done / total) * 100)}%`),
      });
    } catch (e) {
      toast("組裝順序推論失敗，暫用高度分群草稿：" + e.message, true);
    }
  }
  if (!planned || version !== loadVersion) return;
  try {
    applyPlannerResult(target, planned.result, planned.partIds);
    target.planUp = up;
    validateStationAssembly(target);
  } catch (e) {
    flatAssembly(target);
    toast("推論結果無法套用：" + e.message, true);
  }
}
async function autoPlan() {
  if (!station?.parts.length || !root || busy) {
    toast("請先載入本站模型。");
    return;
  }
  const run = async () => {
    const version = loadVersion;
    playing = false;
    busyState(true, "推論組裝順序…");
    try {
      const planned =
        (await loadPrecomputedPlan(station.sample, root, upFor(station))) ||
        (await runPlanner(root, {
          onProgress: ({ done, total, label }) =>
            ($("#loading p").textContent =
              `推論組裝順序… ${Math.round((done / total) * 100)}% · ${label}`),
        }));
      if (version !== loadVersion) return;
      applyPlannerResult(station, planned.result, planned.partIds);
      station.planUp = upFor(station);
      validateStationAssembly(station);
      viewer.setAssembly(station);
      progress = 0;
      mode = "assemble";
      lastFocus = null;
      changed();
      renderSteps();
      const forced = station.plan.filter((s) => s.auto?.forced).length;
      toast(
        `已推論 ${station.plan.length} 個步驟` +
          (forced ? `；${forced} 步找不到無干涉方向，已標示 ⚠ 待審核。` : "。"),
      );
    } catch (e) {
      toast("推論失敗：" + e.message, true);
    } finally {
      busyState(false);
    }
  };
  if (isUntouchedDraft(station) || station.planSource === "geometry") return run();
  modal(
    '<span class="eyebrow">AUTO SEQUENCE</span><h2>以推論結果取代目前流程？</h2><p>目前的步驟包含手動編輯或審核紀錄，重新推論會取代它們。</p><div class="modal-actions"><button id="replan" class="button primary">重新推論</button><button id="keep-plan" class="button ghost">保留目前流程</button></div>',
  );
  $("#replan").onclick = () => {
    $("#modal").close();
    run();
  };
  $("#keep-plan").onclick = () => $("#modal").close();
}
function renderStations() {
  const q = $("#station-search").value.toLowerCase();
  $("#station-count").textContent = project.stations.length;
  $("#stations").innerHTML = project.stations
    .filter((s) => (s.name + s.id).toLowerCase().includes(q))
    .map(
      (s, i) =>
        `<button class="station-item ${s.id === station?.id ? "active" : ""}" data-id="${h(s.id)}"><span class="station-index">${String(i + 1).padStart(2, "0")}</span><span class="station-name">${h(s.name)}<small>${h(s.id)}</small></span><span class="station-indicator ${s.model || manifest[s.sample]?.url ? "ready" : ""}"></span></button>`,
    )
    .join("");
  $("#stations")
    .querySelectorAll("button")
    .forEach((b) => (b.onclick = () => selectStation(b.dataset.id)));
}
const KIND_LABEL = {
  base: "基座",
  part: "安裝",
  fasten: "鎖固",
};
function splitStepName(name) {
  const m = /^【(.+?)】(.*)$/.exec(name);
  return m ? { tag: m[1], title: m[2] } : { tag: "", title: name };
}
function renderSteps() {
  const index = station.nodes?.length ? assemblyIndex(station) : null;
  const partCount = (s) =>
    s.nodeIds.reduce(
      (n, id) => n + (index?.partsOf.get(id)?.length || 0),
      0,
    );
  $("#steps").innerHTML = station.plan.length
    ? station.plan
        .map((s, i) => {
          const { tag, title } = splitStepName(s.name);
          const unit = s.nodeIds.some(
            (id) => index?.nodes.get(id)?.kind === "unit",
          );
          return `<button class="step-card ${s.unitId && s.unitId !== "root" ? "sub" : ""} ${s.auto?.forced ? "warn" : ""}" data-step="${i}"><span class="step-number">${String(i + 1).padStart(2, "0")}</span><span class="step-content">${tag ? `<em class="step-tag">${h(tag)}</em>` : ""}<strong>${h(title)}</strong><small>${unit ? "預組件" : KIND_LABEL[s.kind] || "安裝"} · ${partCount(s)} 件零件 <span>· ${s.reviewed ? "已審核" : "待審核"}</span></small><p>${h(s.instruction)}</p></span><span class="step-check">✓</span></button>`;
        })
        .join("")
    : '<div class="no-steps">匯入模型後可生成並編輯組裝步驟。</div>';
  $("#steps")
    .querySelectorAll("button")
    .forEach(
      (b) =>
        (b.onclick = () => {
          playing = false;
          mode = "assemble";
          progress = Number(b.dataset.step);
          sync();
        }),
    );
  // 步驟很多時只標示約 24 個刻度，避免時間軸被撐開
  const stride = Math.max(1, Math.ceil(station.plan.length / 24));
  $("#scrub-marks").innerHTML = station.plan
    .map((s, i) =>
      i % stride === 0 || i === station.plan.length - 1
        ? `<span title="${h(s.name)}">${String(i + 1).padStart(2, "0")}</span>`
        : "",
    )
    .join("");
  const forced = station.plan.filter((s) => s.auto?.forced).length;
  $("#sequence-note").textContent =
    station.plan.length && station.plan.every((s) => s.reviewed)
      ? "所有步驟已標記審核。依核准的裝配工法執行。"
      : station.planSource === "geometry"
        ? `依 CAD 階層與干涉檢查推論的草稿：每步的移動方向不會穿過已裝零件${forced ? `；${forced} 步標示 ⚠ 需確認` : ""}。扭力、工具與實際工法仍需工程審核。`
        : "目前為依高度分群的草稿，未檢查干涉；按「自動推論」可依幾何重新排序。";
  renderParts();
  sync();
}
function renderParts() {
  const q = $("#part-search").value.toLowerCase();
  const parts = station.parts.filter((p) => p.name.toLowerCase().includes(q));
  $("#part-list").innerHTML =
    parts
      .slice(0, 80)
      .map(
        (p) =>
          `<button data-part="${h(p.id)}" class="${p.id === selected ? "active" : ""}"><span>◇</span>${h(p.name)}</button>`,
      )
      .join("") +
    (parts.length > 80
      ? "<small>顯示前 80 件，請輸入名稱縮小範圍。</small>"
      : "");
  $("#part-list")
    .querySelectorAll("button")
    .forEach((b) => (b.onclick = () => selectPart(b.dataset.part)));
}
function selectPart(id) {
  selected = id;
  const part = station.parts.find((p) => p.id === id);
  const index = part && station.nodes?.length ? assemblyIndex(station) : null;
  const chain = index?.chains.get(id) || [];
  const stepIndex = chain.length ? index.stepOf.get(chain[0]) : -1;
  const step = station.plan[stepIndex];
  const units = chain
    .slice(1)
    .map((n) => index.nodes.get(n)?.name)
    .filter(Boolean);
  $("#part-detail").innerHTML = part
    ? `<span class="eyebrow">COMPONENT INSPECTOR</span><h3>${h(part.name)}</h3><p>組裝步驟：${step ? `${String(stepIndex + 1).padStart(2, "0")} · ${h(step.name)}` : "未指派"}<br>所屬預組件：${h(units.join(" › ") || "（直接裝在本站）")}<br>模型群組：${h(part.group || "—")}</p><label class="part-material">顯示材質<select id="part-material" aria-label="零件顯示材質">${Object.entries(
        MATERIAL_PRESETS,
      )
        .map(
          ([key, value]) =>
            `<option value="${key}" ${key === (part.material || "auto") ? "selected" : ""}>${value.label}</option>`,
        )
        .join(
          "",
        )}</select><small>來源未含物理材質時，以名稱推估外觀；可手動指定。</small></label><button id="isolate" class="button ghost">${viewer.isolate ? "顯示全部" : "單獨檢視"}</button><button id="move-part" class="button ghost">移至其他站</button>`
    : '<span class="eyebrow">COMPONENT INSPECTOR</span><h3>零件檢視</h3><p>點選模型或搜尋零件，檢視裝配群組。</p>';
  if (part) {
    $("#isolate").onclick = () => {
      viewer.isolate = !viewer.isolate;
      selectPart(id);
      viewer.fit();
    };
    $("#move-part").onclick = () => movePartDialog(id);
    $("#part-material").onchange = (e) => {
      part.material = e.target.value;
      viewer.setAppearance(id, part.material);
      changed();
      sync();
    };
  } else viewer.isolate = false;
  renderParts();
  sync();
}
async function selectStation(id) {
  if (busy) return;
  const version = ++loadVersion;
  station = project.stations.find((s) => s.id === id);
  playing = false;
  progress = 0;
  selected = null;
  mode = "solid";
  explode = Number($("#explode").value) / 100;
  root = null;
  viewer.clear();
  renderStations();
  $("#station-title").textContent = station.name;
  $("#breadcrumb").textContent = station.id;
  $("#scope").textContent = station.scope || "待匯入模型";
  $("#source-name").textContent =
    station.source?.split("/").pop() || "尚未匯入";
  $("#empty-state").hidden = true;
  $("#part-summary").textContent = "—";
  $("#model-info").textContent = "";
  try {
    busyState(true);
    root = roots.get(`${project.id}:${station.id}`);
    if (!root && station.model)
      root = await new THREE.ObjectLoader().parseAsync(station.model);
    if (!root && station.sample && manifest[station.sample]?.url) {
      const m = manifest[station.sample];
      root = await loadSample("/" + m.url, upFor(station));
      describeParts(root, station.id);
      station.source = m.source;
      station.scope = m.scope;
    }
    if (version !== loadVersion) return;
    if (root) {
      orientRoot(root, upFor(station));
      roots.set(`${project.id}:${station.id}`, root);
      if (!station.parts.length) {
        station.parts = describeParts(root, station.id);
        flatAssembly(station);
      }
      migrateStation(station);
      viewer.load(root, station.parts, {
        cadSource: !!manifest[station.sample]?.geometrySource,
      });
      await ensurePlan(station, root, version);
      if (version !== loadVersion) return;
      viewer.setAssembly(station);
    }
    catalogUI.refresh(station);
    catalogUI.empty(station);
    $("#empty-state").hidden = !!root;
    $("#scope").textContent = station.scope || "待匯入模型";
    $("#source-name").textContent =
      station.source?.split("/").pop() || "尚未匯入";
    $("#part-summary").textContent =
      `${station.parts.length} 件零件 · ${station.plan.length} 個步驟`;
    $("#model-info").textContent = root
      ? `${manifest[station.sample]?.geometrySource === "saved-display" ? "原生顯示快取" : "CAD 精細網格"} · ${Math.round(viewer.triangles).toLocaleString()} 三角面`
      : "無幾何資料";
    $("#up-axis").value = upFor(station);
    $("#up-axis").disabled = !root;
    selectPart(null);
    renderSteps();
    viewer.fit();
  } catch (e) {
    $("#empty-state").hidden = false;
    toast(e.message, true);
  } finally {
    busyState(false);
  }
}
async function refreshProjects() {
  const saved = await listProjects();
  const projects = [project, ...saved.filter((p) => p.id !== project.id)];
  if (!projects.some((p) => p.id === "sat-source-project-v2"))
    projects.push(sourceProject(catalog, inventory.name));
  $("#projects").innerHTML = projects
    .map((p) => `<option value="${h(p.id)}">${h(p.name)}</option>`)
    .join("");
  $("#projects").value = project.id;
}
async function save() {
  try {
    for (const s of project.stations) {
      const r = roots.get(`${project.id}:${s.id}`);
      if (r && !s.sample) s.model = r.toJSON();
    }
    validateProject(project);
    project.updatedAt = new Date().toISOString();
    await saveProject(project);
    dirty = false;
    $("#save-status").textContent = "✓ 已儲存於本機";
    await refreshProjects();
    toast("專案與組裝步驟已儲存。");
  } catch (e) {
    toast("儲存失敗：" + e.message, true);
  }
}
function confirmDiscard(fn) {
  if (!dirty) {
    fn();
    return;
  }
  modal(
    '<span class="eyebrow">UNSAVED PROJECT</span><h2>目前專案尚未儲存</h2><p>切換前可保存目前的模型與組裝步驟。</p><div class="modal-actions"><button id="save-switch" class="button primary">儲存並繼續</button><button id="discard" class="button ghost">捨棄變更</button></div>',
  );
  $("#save-switch").onclick = async () => {
    await save();
    if (!dirty) {
      $("#modal").close();
      fn();
    }
  };
  $("#discard").onclick = () => {
    $("#modal").close();
    dirty = false;
    fn();
  };
}
function newProject() {
  confirmDiscard(() => {
    modal(
      '<span class="eyebrow">NEW PROJECT</span><h2>建立設備專案</h2><label class="field">專案名稱<input id="project-name" value="新設備專案" maxlength="100"></label><label class="field">第一個站別<input id="first-station" value="設備主組合" maxlength="100"></label><button id="create" class="button primary">建立專案</button>',
    );
    $("#create").onclick = async () => {
      const name = $("#project-name").value.trim(),
        sname = $("#first-station").value.trim();
      if (!name || !sname) return;
      project = {
        schemaVersion: SCHEMA_VERSION,
        id: uid(),
        name,
        stations: [{ id: uid(), name: sname, parts: [], plan: [] }],
      };
      dirty = false;
      $("#modal").close();
      await refreshProjects();
      await selectStation(project.stations[0].id);
      changed();
    };
  });
}
function importDialog() {
  modal(
    `<span class="eyebrow">IMPORT CAD</span><h2>讓設備設計動起來</h2><p>選擇模型或完整專案；可將多個檔案依資料夾分成不同站別。</p><div class="import-zone"><span>↥</span><strong>選擇 CAD 模型檔案</strong><p>STEP · IGES · BREP · GLB · STL · OBJ · SolidWorks</p><input id="files" type="file" multiple accept=".step,.stp,.igs,.iges,.brep,.glb,.stl,.obj,.sldasm,.sldprt,.x_t,.dwg,.json"><label for="files" class="button primary">選擇檔案</label><input id="folder" type="file" webkitdirectory multiple hidden><label for="folder" class="button ghost">選擇專案資料夾</label></div><label class="field">匯入方式<select id="import-target"><option value="stations">各檔案／資料夾建立新站別</option><option value="current">取代目前站別的模型</option></select></label><div class="import-info"><strong>格式說明</strong><p>STEP / IGES 保留可解析的零件與階層。STL 通常只有單一網格，無法還原零件關係。SolidWorks 原生檔需本機已安裝並授權 SolidWorks；請同時提供引用零件。Parasolid / DWG 請先轉為 STEP。自動步驟需工程審核。</p></div><div id="import-report" role="status"></div><div class="modal-actions"><button id="export-project" class="button ghost">匯出目前專案 JSON</button></div>`,
  );
  $("#files").onchange = (e) =>
    handleFiles([...e.target.files], $("#import-target").value);
  $("#folder").onchange = (e) =>
    handleFiles([...e.target.files], $("#import-target").value);
  $("#export-project").onclick = () => exportProject();
}
function handleFiles(files, target) {
  if (
    files.length === 1 &&
    files[0].name.toLowerCase().endsWith(".json") &&
    dirty
  ) {
    confirmDiscard(() => performImport(files, target));
  } else return performImport(files, target);
}
async function performImport(files, target) {
  if (!files.length || busy) return;
  const report = $("#import-report");
  report.textContent = "正在解析，請稍候…";
  busyState(true, "正在匯入 CAD…");
  playing = false;
  const errors = [],
    incoming = [];
  let success = 0;
  try {
    if (files.length === 1 && files[0].name.toLowerCase().endsWith(".json")) {
      if (files[0].size > 200 * 1024 * 1024)
        throw new Error("專案 JSON 超過 200 MB，請分割設備站別。");
      const p = validateProject(JSON.parse(await files[0].text()));
      // Parse all geometry before replacing the working project.
      const parsed = new Map();
      for (const s of p.stations) {
        if (s.model) {
          const r = await new THREE.ObjectLoader().parseAsync(s.model);
          const actual = new Set();
          r.traverse((o) => {
            if (o.isMesh) actual.add(o.userData.partId);
          });
          if (
            actual.size !== s.parts.length ||
            s.parts.some((x) => !actual.has(x.id))
          )
            throw new Error("專案模型與零件 ID 不一致。");
          parsed.set(s.id, r);
        } else if (s.parts.length && !s.sample)
          throw new Error("專案缺少模型幾何。");
      }
      project = { ...p, id: uid() };
      for (const [id, r] of parsed) roots.set(`${project.id}:${id}`, r);
      dirty = true;
      $("#modal").close();
      busyState(false);
      await refreshProjects();
      await selectStation(project.stations[0].id);
      changed();
      return;
    }
    let selectedFiles = files.filter((f) =>
      formats.includes(f.name.split(".").pop().toLowerCase()),
    );
    const natives = files.filter((f) => /\.(sldasm|sldprt)$/i.test(f.name));
    if (!selectedFiles.length && natives.length) {
      const service = await fetch("/api/converter");
      if (
        !service.ok ||
        !service.headers.get("content-type")?.includes("application/json")
      )
        throw new Error(
          "SolidWorks 轉換需使用 npm run dev 啟動本機服務，或先在 CAD 軟體輸出 STEP。",
        );
      const status = await service.json();
      if (!status.available)
        throw new Error(
          "此電腦未偵測到 SolidWorks。請在 SolidWorks 將組合件另存為 STEP（保留組合結構），再匯入。",
        );
      const session = uid();
      for (const f of natives) {
        const relative = f.webkitRelativePath || f.name;
        const response = await fetch(
          `/api/uploads/${session}/${relative.split("/").map(encodeURIComponent).join("/")}`,
          { method: "PUT", body: f },
        );
        if (!response.ok) throw new Error(await response.text());
      }
      const assemblies = natives.filter((f) => /\.sldasm$/i.test(f.name));
      const chosen = assemblies.length ? assemblies : natives;
      selectedFiles = [];
      for (const f of chosen) {
        report.textContent = `SolidWorks 正在轉換 ${f.name}…`;
        const response = await fetch(`/api/convert/${session}`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ path: f.webkitRelativePath || f.name }),
        });
        if (!response.ok) {
          errors.push(f.name + ": " + (await response.text()));
          continue;
        }
        selectedFiles.push(
          new File(
            [await response.blob()],
            f.name.replace(/\.[^.]+$/, ".step"),
          ),
        );
      }
    }
    if (!selectedFiles.length)
      throw new Error(
        "沒有可直接解析的 3D 檔案。DWG / Parasolid 需先由 CAD 軟體輸出 STEP。",
      );
    for (const [index, f] of selectedFiles.entries()) {
      report.textContent = `${index + 1} / ${selectedFiles.length} · ${f.name}`;
      try {
        const model = await importModel(f);
        const relative = f.webkitRelativePath || f.name;
        const seg = relative.split("/");
        const folder =
          seg.length > 1 ? seg.at(-2) : f.name.replace(/\.[^.]+$/, "");
        let item =
          target === "current"
            ? incoming[0]
            : incoming.find((s) => s.name === folder);
        if (!item) {
          item = {
            id: target === "current" ? station.id : uid(),
            name: target === "current" ? station.name : folder,
            parts: [],
            plan: [],
            source: relative,
            scope: "使用者匯入模型",
            _root: new THREE.Group(),
          };
          incoming.push(item);
        }
        item._root.add(model);
        success++;
      } catch (e) {
        errors.push(f.name + ": " + e.message);
      }
    }
    for (const s of incoming) {
      s.parts = describeParts(s._root, s.id);
      if (!s.parts.length) {
        errors.push(s.name + ": 沒有可用零件");
        continue;
      }
      flatAssembly(s);
      roots.set(`${project.id}:${s.id}`, s._root);
      delete s._root;
      const i = project.stations.findIndex((x) => x.id === s.id);
      if (i >= 0) project.stations[i] = s;
      else project.stations.push(s);
    }
    if (success) {
      changed();
      await refreshProjects();
    }
    if (
      natives.length &&
      files.some((f) => formats.includes(f.name.split(".").pop().toLowerCase()))
    )
      errors.push("已使用資料夾中的中性格式；未另行轉換 SolidWorks 原生檔。");
    const ignored = files.filter(
      (f) =>
        !formats.includes(f.name.split(".").pop().toLowerCase()) &&
        !/\.(sldasm|sldprt)$/i.test(f.name),
    );
    if (ignored.length)
      errors.push(
        `略過 ${ignored.length} 個非支援模型檔案（圖面／其他資料）。`,
      );
    report.textContent = `已匯入 ${success} 個模型。${errors.length ? "\n" + errors.join("\n") : ""}`;
    busyState(false);
    if (incoming.length) await selectStation(incoming[0].id);
  } catch (e) {
    report.textContent = e.message;
    toast(e.message, true);
  } finally {
    busyState(false);
  }
}
function download(name, data, type = "application/json") {
  const a = document.createElement("a");
  a.href =
    typeof data === "string" && data.startsWith("data:")
      ? data
      : URL.createObjectURL(new Blob([data], { type }));
  a.download = name;
  a.click();
  if (a.href.startsWith("blob:"))
    setTimeout(() => URL.revokeObjectURL(a.href), 1000);
}
async function exportProject() {
  busyState(true, "準備完整專案…");
  try {
    for (const s of project.stations) {
      let r = roots.get(`${project.id}:${s.id}`);
      if (!r && s.sample && manifest[s.sample]?.url) {
        r = await loadSample(
          "/" + manifest[s.sample].url,
          upFor(s),
        );
        const parts = describeParts(r, s.id);
        if (!s.parts.length) {
          s.parts = parts;
          flatAssembly(s);
        }
        roots.set(`${project.id}:${s.id}`, r);
      }
      if (r) s.model = r.toJSON();
    }
    validateProject(project);
    const portable = structuredClone(project);
    portable.stations.forEach((s) => delete s.sample);
    download(project.name + ".assembly.json", JSON.stringify(portable));
    toast("已匯出包含幾何與步驟的專案。");
  } catch (e) {
    toast(e.message, true);
  } finally {
    busyState(false);
  }
}
function editPlan() {
  if (!station.plan.length) {
    toast("請先匯入本站模型。");
    return;
  }
  const draft = structuredClone(station.plan);
  const index = assemblyIndex(station);
  let active = 0,
    error = "";
  // 顯示座標：Z 朝上、XY 為水平面（內部 Y 為上方，內部 −Z 為顯示 +Y）
  const AXIS_OPTIONS = [
    ["auto", "推論方向"],
    ["radial", "徑向自動"],
    ["y", "+Z（由上方）"],
    ["-y", "−Z（由下方）"],
    ["x", "+X"],
    ["-x", "−X"],
    ["-z", "+Y"],
    ["z", "−Y"],
  ];
  const draw = () => {
    const s = draft[active];
    const axes = AXIS_OPTIONS.filter(([v]) => v !== "auto" || s.dir);
    modal(
      `<span class="eyebrow">SEQUENCE EDITOR</span><h2>編輯組裝流程</h2><p>調整順序、步驟內容與移動方向。預組件內的零件必須排在該預組件安裝之前。</p><div class="plan-editor"><div class="editor-list">${draft
        .map(
          (x, i) =>
            `<button data-edit="${i}" class="${i === active ? "active" : ""} ${x.unitId && x.unitId !== "root" ? "sub" : ""}">${String(i + 1).padStart(2, "0")} ${h(x.name)}</button>`,
        )
        .join(
          "",
        )}<button id="add-step">＋ 新增步驟</button></div><div><label class="field">步驟名稱<input id="edit-name" value="${h(s.name)}" maxlength="160"></label><label class="field">裝配指引<textarea id="edit-instruction" rows="3">${h(s.instruction)}</textarea></label><div class="field-row"><label class="field">移動方向<select id="edit-axis">${axes
        .map(
          ([v, n]) =>
            `<option value="${v}" ${s.axis === v ? "selected" : ""}>${n}</option>`,
        )
        .join(
          "",
        )}</select></label><label class="field">展開距離倍率<input id="edit-distance" type="number" min="0" max="5" step=".1" value="${s.distance}"></label></div><label class="check-field"><input id="edit-reviewed" type="checkbox" ${s.reviewed ? "checked" : ""}> 已依實際裝配工法審核</label><div class="modal-actions"><button id="step-up" class="button ghost" ${active === 0 ? "disabled" : ""}>↑ 上移</button><button id="step-down" class="button ghost" ${active === draft.length - 1 ? "disabled" : ""}>↓ 下移</button><button id="delete-step" class="button ghost" ${draft.length === 1 ? "disabled" : ""}>合併至前／後步驟</button></div><div class="editor-parts">${s.nodeIds
        .map((id) => {
          const n = index.nodes.get(id);
          const count = index.partsOf.get(id)?.length || 0;
          return `<label>${h(n?.name)}${n?.kind === "unit" ? `（預組件 · ${count} 件）` : count > 1 ? `（${count} 個實體）` : ""}<select data-move="${h(id)}" aria-label="將 ${h(n?.name)} 移至步驟">${draft.map((x, i) => `<option value="${i}" ${i === active ? "selected" : ""}>${i + 1}. ${h(x.name)}</option>`).join("")}</select></label>`;
        })
        .join(
          "",
        )}</div></div></div><p id="plan-error" class="plan-error" ${error ? "" : "hidden"}>${h(error)}</p><div class="modal-actions"><button id="apply-plan" class="button primary">套用流程</button><button id="cancel-plan" class="button ghost">取消</button></div>`,
    );
    const read = () => {
      s.name = $("#edit-name").value.trim() || "組裝步驟";
      s.instruction = $("#edit-instruction").value;
      s.axis = $("#edit-axis").value;
      s.distance = Math.max(
        0,
        Math.min(5, Number($("#edit-distance").value) || 0),
      );
      s.reviewed = $("#edit-reviewed").checked;
    };
    const go = (fn) => () => {
      read();
      error = "";
      fn();
      draw();
    };
    document
      .querySelectorAll("[data-edit]")
      .forEach((b) => (b.onclick = go(() => (active = Number(b.dataset.edit)))));
    $("#step-up").onclick = go(() => {
      [draft[active - 1], draft[active]] = [draft[active], draft[active - 1]];
      active--;
    });
    $("#step-down").onclick = go(() => {
      [draft[active + 1], draft[active]] = [draft[active], draft[active + 1]];
      active++;
    });
    $("#add-step").onclick = go(() => {
      draft.push({
        id: uid(),
        name: "新組裝步驟",
        kind: "part",
        unitId: s.unitId || "root",
        nodeIds: [],
        instruction: "",
        axis: "radial",
        distance: 1,
        reviewed: false,
      });
      active = draft.length - 1;
    });
    $("#delete-step").onclick = go(() => {
      const dest = active > 0 ? active - 1 : 1;
      draft[dest].nodeIds.push(...s.nodeIds);
      draft[dest].reviewed = false;
      draft.splice(active, 1);
      active = Math.max(0, active - 1);
    });
    document.querySelectorAll("[data-move]").forEach(
      (b) =>
        (b.onchange = go(() => {
          s.nodeIds = s.nodeIds.filter((id) => id !== b.dataset.move);
          draft[Number(b.value)].nodeIds.push(b.dataset.move);
          s.reviewed = false;
          draft[Number(b.value)].reviewed = false;
        })),
    );
    $("#apply-plan").onclick = () => {
      read();
      const plan = draft.filter((x) => x.nodeIds.length);
      try {
        validateStationAssembly({ ...station, plan });
      } catch (e) {
        error = e.message;
        draw();
        return;
      }
      station.plan = plan;
      station.planSource =
        station.planSource === "geometry" ? "geometry-edited" : "edited";
      viewer.setAssembly(station);
      progress = 0;
      playing = false;
      lastFocus = null;
      changed();
      renderSteps();
      $("#modal").close();
    };
    $("#cancel-plan").onclick = () => $("#modal").close();
  };
  draw();
}
function movePartDialog(id) {
  const others = project.stations.filter((s) => s.id !== station.id);
  if (!others.length) {
    toast("請先新增另一個站別。");
    return;
  }
  modal(
    `<h2>將零件移至其他站別</h2><label class="field">目標站別<select id="move-target">${others.map((s) => `<option value="${h(s.id)}">${h(s.name)}</option>`).join("")}</select></label><button id="move-apply" class="button primary">移動零件</button>`,
  );
  $("#move-apply").onclick = async () => {
    const targetId = $("#move-target").value;
    const source = station;
    const sourceRoot = root;
    const target = project.stations.find((s) => s.id === targetId);
    $("#modal").close();
    busyState(true);
    try {
      let dest = roots.get(`${project.id}:${targetId}`);
      if (!dest && target.model)
        dest = await new THREE.ObjectLoader().parseAsync(target.model);
      if (!dest && manifest[target.sample]?.url) {
        dest = await loadSample(
          "/" + manifest[target.sample].url,
          upFor(target),
        );
        target.parts = describeParts(dest, target.id);
        flatAssembly(target);
      }
      if (!dest) dest = new THREE.Group();
      let mesh;
      sourceRoot.traverse((o) => {
        if (o.isMesh && o.userData.partId === id) mesh = o;
      });
      if (!mesh) throw new Error("找不到零件。");
      sourceRoot.updateMatrixWorld(true);
      dest.updateMatrixWorld(true);
      dest.attach(mesh);
      migrateStation(target);
      const moved = { ...source.parts.find((p) => p.id === id) };
      removePart(source, id);
      appendPart(target, moved);
      source.planSource = target.planSource = "edited";
      delete source.sample;
      delete target.sample;
      source.model = sourceRoot.toJSON();
      target.model = dest.toJSON();
      roots.set(`${project.id}:${targetId}`, dest);
      roots.set(`${project.id}:${source.id}`, sourceRoot);
      target.scope = "使用者分站模型";
      changed();
    } catch (e) {
      toast(e.message, true);
    } finally {
      busyState(false);
      await selectStation(source.id);
    }
  };
}
async function openCatalogAsset(asset) {
  if (!asset || busy) return;
  let target = project.stations.find((s) => s.id === asset.stationId);
  if (!target) {
    target = sourceProject(catalog, inventory.name).stations.find(
      (s) => s.id === asset.stationId,
    );
    project.stations.push(target);
  }
  if (target.sample !== asset.id) {
    target.variants ||= {};
    if (target.sample)
      target.variants[target.sample] = {
        parts: target.parts,
        plan: target.plan,
        nodes: target.nodes,
        planSource: target.planSource,
        planUp: target.planUp,
        up: target.up,
      };
    else if (target.parts.length) {
      const existingRoot = roots.get(`${project.id}:${target.id}`);
      const copy = {
        ...target,
        id: uid(),
        name: target.name + "（自訂模型）",
        model: existingRoot?.toJSON() || target.model,
      };
      project.stations.push(copy);
    }
    Object.assign(target, {
      sample: asset.id,
      source: asset.source,
      scope: asset.scope,
      parts: target.variants[asset.id]?.parts || [],
      plan: target.variants[asset.id]?.plan || [],
      nodes: target.variants[asset.id]?.nodes,
      planSource: target.variants[asset.id]?.planSource,
      planUp: target.variants[asset.id]?.planUp,
      up: target.variants[asset.id]?.up,
    });
    delete target.model;
    roots.delete(`${project.id}:${target.id}`);
    changed();
  }
  await selectStation(target.id);
}
// ---- 輸出：作業指導書與組裝影片 ----
const nextFrame = () => new Promise((r) => requestAnimationFrame(() => r()));
// 同形狀的零件合併計數（未命名實體以幾何指紋判斷）
function stepParts(step, index) {
  const groups = new Map();
  for (const id of step.nodeIds) {
    const node = index.nodes.get(id);
    const name =
      node?.kind === "unit" ? `${baseName(node.name)}（預組件）` : baseName(node?.name || id);
    const key = node?.geomKey ? `${node.kind}|${node.geomKey}` : name;
    const entry = groups.get(key) || [name, 0];
    entry[1]++;
    groups.set(key, entry);
  }
  return [...groups.values()];
}
// 依輸出需求暫時提高解析度：高度至少約 1080 像素
const outputScale = () =>
  Math.min(3, Math.max(1, 1080 / Math.max(1, viewer.container.clientHeight)));
function rangeDialog(title, extra, onRun) {
  const total = station.plan.length;
  if (!total || !root) {
    toast("請先載入本站模型與組裝步驟。");
    return;
  }
  const last = Math.min(total, extra.limit);
  modal(
    `<span class="eyebrow">EXPORT</span><h2>${title}</h2><p>${extra.note}</p><div class="field-row"><label class="field">從步驟<input id="range-from" type="number" min="1" max="${total}" value="1"></label><label class="field">到步驟<input id="range-to" type="number" min="1" max="${total}" value="${last}"></label></div>${extra.fields || ""}<p class="range-hint">本站共 ${total} 步${total > extra.limit ? `；步驟很多，預設只輸出前 ${extra.limit} 步，可分冊輸出` : ""}。</p><div class="modal-actions"><button id="range-run" class="button primary">開始</button><button id="range-cancel" class="button ghost">取消</button></div>`,
  );
  $("#range-cancel").onclick = () => $("#modal").close();
  $("#range-run").onclick = () => {
    const clamp = (v) => Math.max(1, Math.min(total, Math.round(Number(v) || 1)));
    const from = clamp($("#range-from").value) - 1,
      to = clamp($("#range-to").value) - 1;
    if (to < from) {
      toast("結束步驟不可小於起始步驟。", true);
      return;
    }
    const values = extra.read?.() || {};
    $("#modal").close();
    onRun(from, to, values);
  };
}
function saveView() {
  return { mode, progress, playing, explode, future: $("#future").value };
}
function restoreView(state) {
  ({ mode, progress, playing, explode } = state);
  $("#future").value = state.future;
  lastFocus = null;
  sync();
  viewer.fit();
}
function exportSop() {
  rangeDialog(
    "匯出作業指導書",
    {
      limit: 120,
      note: "每步擷取零件在起始位置、附裝入方向箭頭的畫面，加上說明與零件清單，輸出為可列印成 PDF 的 HTML。",
    },
    async (from, to) => {
      const state = saveView();
      const index = assemblyIndex(station);
      busyState(true, "產生作業指導書…");
      viewer.setOutputScale(Math.min(2, outputScale()));
      try {
        playing = false;
        mode = "solid";
        sync();
        viewer.fit();
        await nextFrame();
        const cover = viewer.screenshot("image/jpeg", 0.88);
        mode = "assemble";
        $("#future").value = "ghost";
        const steps = [];
        for (let k = from; k <= to; k++) {
          // 零件在起始位置、箭頭指向完成位置
          progress = k + STEP_TIMING.start * 0.5;
          lastFocus = null;
          sync();
          viewer.focusBox(viewer.stepBounds(k), 0.7, true);
          steps.push({
            index: k,
            step: station.plan[k],
            image: viewer.screenshot("image/jpeg", 0.85),
            parts: stepParts(station.plan[k], index),
          });
          $("#loading p").textContent = `產生作業指導書… ${k - from + 1} / ${to - from + 1}`;
          if ((k - from) % 4 === 3) await nextFrame();
        }
        const html = sopHtml({
          station,
          project,
          steps,
          cover,
          bom: countNames(station.parts.map((p) => p.name)),
          generated: new Date().toLocaleString("zh-TW", { hour12: false }),
          total: station.plan.length,
        });
        const range = from === 0 && to === station.plan.length - 1 ? "" : `-步驟${from + 1}-${to + 1}`;
        download(`${station.name}-組裝作業指導書${range}.html`, html, "text/html");
        const url = URL.createObjectURL(new Blob([html], { type: "text/html" }));
        window.open(url, "_blank");
        setTimeout(() => URL.revokeObjectURL(url), 60000);
        toast(`已輸出 ${steps.length} 步的作業指導書；在新分頁按「列印／另存 PDF」。`);
      } catch (e) {
        toast("作業指導書輸出失敗：" + e.message, true);
      } finally {
        viewer.setOutputScale(null);
        busyState(false);
        restoreView(state);
      }
    },
  );
}
let recording = null;
function exportVideo() {
  if (typeof MediaRecorder === "undefined") {
    toast("此瀏覽器不支援錄影（MediaRecorder）。", true);
    return;
  }
  rangeDialog(
    "錄製組裝影片",
    {
      limit: 60,
      note: "依目前視角與鏡頭跟隨即時播放並錄成 WebM，下方加上步驟字卡。錄影期間請勿切換分頁。",
      fields:
        '<label class="field">播放速度<select id="video-speed"><option value="1">1×（每步約 3.2 秒）</option><option value="1.5">1.5×</option><option value="2">2×</option></select></label>',
      read: () => ({ speed: Number($("#video-speed").value) || 1 }),
    },
    (from, to, { speed }) => record(from, to, speed),
  );
}
async function record(from, to, speed) {
  const state = saveView();
  viewer.setOutputScale(outputScale());
  const gl = viewer.renderer.domElement;
  const scale = Math.max(1, gl.height / 720);
  const bar = Math.round(118 * scale);
  const canvas = document.createElement("canvas");
  canvas.width = gl.width - (gl.width % 2);
  canvas.height = gl.height + bar - ((gl.height + bar) % 2);
  const ctx = canvas.getContext("2d");
  const type = ["video/webm;codecs=vp9", "video/webm;codecs=vp8", "video/webm"].find((t) =>
    MediaRecorder.isTypeSupported(t),
  );
  const recorder = new MediaRecorder(canvas.captureStream(30), {
    mimeType: type,
    videoBitsPerSecond: 8_000_000,
  });
  const chunks = [];
  recorder.ondataavailable = (e) => e.data.size && chunks.push(e.data);
  const stopped = new Promise((r) => (recorder.onstop = r));
  busy = true;
  playing = false;
  mode = "assemble";
  $("#future").value = state.future === "show" ? "ghost" : state.future;
  progress = from;
  lastFocus = null;
  sync();
  $("#recording").hidden = false;
  recording = { cancel: false };
  recorder.start(1000);
  const end = to + 1,
    started = performance.now();
  let hold = null;
  while (!recording.cancel) {
    await nextFrame();
    const elapsed = (performance.now() - started) / 1000;
    progress = Math.min(end, from + (elapsed * speed) / STEP_SECONDS);
    sync();
    viewer.renderNow();
    ctx.fillStyle = "#000";
    ctx.fillRect(0, 0, canvas.width, canvas.height);
    ctx.drawImage(gl, 0, 0);
    const k = Math.min(Math.floor(progress), to);
    const s = station.plan[k];
    drawCaption(ctx, {
      x: 0,
      y: gl.height,
      width: canvas.width,
      height: canvas.height - gl.height,
      index: `${station.name} · 步驟 ${String(k + 1).padStart(2, "0")} / ${String(station.plan.length).padStart(2, "0")}`,
      name: s.name,
      text: s.instruction,
      ratio: (progress - from) / (end - from),
      scale,
    });
    $("#recording-text").textContent = `錄影中 ${k + 1} / ${to + 1}`;
    // 最後一步完成後多停 1 秒
    if (progress >= end) {
      hold ??= performance.now();
      if (performance.now() - hold > 1000) break;
    }
  }
  recorder.stop();
  await stopped;
  viewer.setOutputScale(null);
  $("#recording").hidden = true;
  const cancelled = recording.cancel;
  recording = null;
  busy = false;
  restoreView(state);
  if (cancelled) {
    toast("已取消錄影。");
    return;
  }
  const range = from === 0 && to === station.plan.length - 1 ? "" : `-步驟${from + 1}-${to + 1}`;
  download(`${station.name}-組裝動畫${range}.webm`, new Blob(chunks, { type: "video/webm" }), "video/webm");
  toast("已輸出組裝影片（WebM）。");
}
async function changeUp(up) {
  if (!station || busy) return;
  const keep = !isUntouchedDraft(station) && station.planSource !== "geometry";
  station.up = up;
  // 已編輯的流程保留（方向需重新確認）；未編輯的依新朝上軸重新推論
  if (!keep) flatAssembly(station);
  changed();
  progress = 0;
  lastFocus = null;
  await selectStation(station.id);
  toast(
    keep
      ? `已改為${UP_LABELS[up]}；流程含手動編輯，未重新推論，請確認各步驟方向。`
      : `已改為${UP_LABELS[up]}，並依新的朝上方向重新推論組裝順序。`,
  );
}
function libraryDialog() {
  catalogUI.library();
}
$("#station-search").oninput = renderStations;
$("#part-search").oninput = renderParts;
$("#import").onclick = $("#empty-import").onclick = importDialog;
$("#library").onclick = libraryDialog;
$("#edit-plan").onclick = editPlan;
$("#auto-plan").onclick = () => autoPlan();
$("#export-sop").onclick = () => exportSop();
$("#export-video").onclick = () => exportVideo();
$("#recording-cancel").onclick = () => recording && (recording.cancel = true);
$("#future").onchange = () => sync();
$("#follow").onchange = () => {
  lastFocus = null;
  sync();
};
$("#save").onclick = save;
$("#new-project").onclick = newProject;
$("#add-station").onclick = () => {
  modal(
    '<h2>新增設備站別</h2><label class="field">站別名稱<input id="new-station-name" maxlength="100" placeholder="例如：上料站"></label><button id="add-station-apply" class="button primary">新增</button>',
  );
  $("#add-station-apply").onclick = async () => {
    const name = $("#new-station-name").value.trim();
    if (!name) return;
    const s = { id: uid(), name, parts: [], plan: [], nodes: [] };
    project.stations.push(s);
    $("#modal").close();
    changed();
    await selectStation(s.id);
  };
};
$("#projects").onchange = (e) => {
  const id = e.target.value;
  $("#projects").value = project.id;
  confirmDiscard(async () => {
    const p = migrateProject(
      (await getProject(id)) ||
        (id === "sat-source-project-v2"
          ? sourceProject(catalog, inventory.name)
          : null),
    );
    if (!p) return;
    project = p;
    dirty = false;
    await refreshProjects();
    await selectStation(project.stations[0].id);
  });
};
$("#explode").oninput = (e) => {
  playing = false;
  mode = "explode";
  explode = Number(e.target.value) / 100;
  sync();
  viewer.fit();
};
$("#mode-solid").onclick = () => {
  playing = false;
  mode = "solid";
  sync();
  viewer.fit();
};
$("#mode-explode").onclick = () => {
  playing = false;
  mode = "explode";
  sync();
  viewer.fit();
};
// 進入組裝模式時由 sync() 的鏡頭跟隨取景；關閉跟隨則顯示全景
function frameAssembly() {
  mode = "assemble";
  lastFocus = null;
  sync();
  if (!$("#follow").checked) viewer.fit();
}
$("#mode-assemble").onclick = () => frameAssembly();
$("#play").onclick = () => {
  if (!station.plan.length) return;
  const entering = mode !== "assemble";
  if (progress >= station.plan.length) progress = 0;
  playing = !playing;
  if (entering) frameAssembly();
  else sync();
};
$("#previous").onclick = () => {
  playing = false;
  progress = Math.max(0, Math.ceil(progress) - 1);
  frameAssembly();
};
$("#next").onclick = () => {
  playing = false;
  progress = Math.min(station.plan.length, Math.floor(progress) + 1);
  frameAssembly();
};
$("#restart").onclick = () => {
  progress = 0;
  playing = false;
  frameAssembly();
};
$("#scrub").oninput = (e) => {
  playing = false;
  progress = Number(e.target.value);
  mode = "assemble";
  sync();
};
$("#wire").onclick = () => {
  viewer.setWire(!viewer.wire);
  $("#wire").classList.toggle("active", viewer.wire);
};
$("#labels").onclick = () => {
  viewer.labelsOn = !viewer.labelsOn;
  $("#labels").classList.toggle("active", viewer.labelsOn);
  if (viewer.labelsOn && station.parts.length > 100)
    toast("大型模型僅顯示選取零件的標籤，以保持流暢。");
  sync();
};
$("#fit").onclick = () => viewer.fit();
$("#capture").onclick = () =>
  download(station.name + ".png", viewer.screenshot());
document.querySelectorAll("[data-view]").forEach(
  (b) =>
    (b.onclick = () => {
      viewer.view(b.dataset.view);
      document
        .querySelectorAll("[data-view]")
        .forEach((x) => x.classList.toggle("active", x === b));
    }),
);
window.addEventListener("beforeunload", (e) => {
  if (dirty) {
    e.preventDefault();
    e.returnValue = "";
  }
});
document.addEventListener("keydown", (e) => {
  if (
    e.target.matches("input,textarea,select") ||
    $("#modal").open ||
    $("#equipment-overview")?.open
  )
    return;
  if (e.code === "Space") {
    e.preventDefault();
    $("#play").click();
  }
  if (e.key === "ArrowRight") $("#next").click();
  if (e.key === "ArrowLeft") $("#previous").click();
});
let last = performance.now();
function animate(now) {
  const delta = Math.min((now - last) / 1000, 0.1);
  last = now;
  if (playing && !busy && station) {
    const total = station.plan.length,
      before = progress;
    progress = Math.min(
      total,
      progress + (delta * Number($("#speed").value)) / STEP_SECONDS,
    );
    // 每步暫停：停在下一步的起點，讓作業員看清楚再繼續
    if (
      $("#pause-steps").checked &&
      Math.floor(progress) > Math.floor(before) &&
      progress < total
    ) {
      progress = Math.floor(progress);
      playing = false;
    }
    if (progress >= total) playing = false;
    sync();
  }
  requestAnimationFrame(animate);
}
requestAnimationFrame(animate);
async function init() {
  try {
    viewer = new AssemblyViewer($("#viewport"), selectPart);
    viewer.attachAxisGizmo($(".axis-gizmo"));
    $(".toolbar-right").insertAdjacentHTML(
      "afterbegin",
      `<select id="up-axis" aria-label="朝上軸" title="模型哪一個軸朝上；底面朝下才正確">${Object.entries(UP_LABELS).map(([v, n]) => `<option value="${v}">${n}</option>`).join("")}</select><select id="render-quality" aria-label="渲染品質" title="精緻渲染包含接觸陰影；流暢操作降低陰影負擔"><option value="detailed">精緻渲染</option><option value="smooth">流暢操作</option></select>`,
    );
    $("#render-quality").onchange = (event) =>
      viewer.setQuality(event.target.value);
    $("#up-axis").onchange = (event) => changeUp(event.target.value);
    initializeTheme((theme) => viewer.setTheme(theme));
    [inventory, manifest, catalog] = await Promise.all([
      fetch("/data/source-inventory.json").then((r) => r.json()),
      fetch("/data/model-manifest.json").then((r) => r.json()),
      fetch("/data/cad-catalog.json").then((r) => {
        if (!r.ok) throw new Error("CAD 資料庫尚未建立");
        return r.json();
      }),
    ]);
    Object.assign(
      manifest,
      Object.fromEntries(catalogAssets(catalog).map((a) => [a.id, a])),
    );
    // 逐一檢查後確認的朝上軸（CAD 以 Z 軸朝上建模者）
    const orientation = await fetch("/data/orientation.json")
      .then((r) => (r.ok ? r.json() : { assets: {} }))
      .catch(() => ({ assets: {} }));
    for (const [id, up] of Object.entries(orientation.assets || {}))
      if (manifest[id]) manifest[id].upAxis = up;
    $(".search-box").insertAdjacentHTML(
      "beforebegin",
      '<button id="equipment-overview-open" class="button primary equipment-entry">▦ 全部設備 · 組合圖／成品圖</button>',
    );
    const equipmentOverview = createEquipmentOverview({
      getProject: () => project,
      manifest,
      async getModel(s) {
        const cached = roots.get(`${project.id}:${s.id}`);
        if (cached) return { root: orientRoot(cached, upFor(s)), owned: false };
        if (s.model)
          return {
            root: orientRoot(
              await new THREE.ObjectLoader().parseAsync(s.model),
              upFor(s),
            ),
            owned: true,
          };
        const asset = manifest[s.sample];
        return {
          root: asset?.url
            ? await loadSample("/" + asset.url, upFor(s))
            : null,
          owned: true,
        };
      },
      onOpen() {
        playing = false;
        sync();
        viewer.setActive(false);
      },
      onClose() {
        viewer.setActive(true);
      },
    });
    $("#equipment-overview-open").onclick = () => equipmentOverview.open();
    catalogUI = createCatalogUI(catalog, {
      modal,
      openAsset: openCatalogAsset,
      getStation: () => station,
    });
    $("#source-count").textContent =
      `${catalog.summary.cadFiles.toLocaleString()} 個 CAD／圖面`;
    const saved = migrateProject(await getProject("sat-source-project-v2"));
    project = saved || sourceProject(catalog, inventory.name);
    if (saved)
      for (const s of sourceProject(catalog, inventory.name).stations) {
        if (!project.stations.some((x) => x.id === s.id))
          project.stations.push(s);
      }
    await refreshProjects();
    await selectStation(
      project.stations.find((s) => s.id === "202401-BA00")?.id ||
        project.stations[0].id,
    );
  } catch (e) {
    toast("初始化失敗：" + e.message, true);
    $("#empty-state").hidden = false;
  }
}
init();
