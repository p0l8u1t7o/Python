import { escapeHTML as h } from "../project/core.js";
export const catalogAssets = (catalog) => [
  ...catalog.items,
  ...(catalog.assemblies || []),
];
export function sourceProject(catalog, name) {
  return {
    schemaVersion: 2,
    id: "sat-source-project-v2",
    name: name + " · 完整資料庫",
    catalogRevision: catalog.revision,
    stations: catalog.stations.map((s) => {
      const asset = catalogAssets(catalog).find((a) => a.id === s.defaultAsset);
      return {
        id: s.id,
        name: s.name,
        parts: [],
        plan: [],
        sample: asset?.id,
        source: asset?.source,
        scope: asset?.scope,
        variants: {},
      };
    }),
  };
}
export function assetStateLabel(asset) {
  if (asset.url)
    return asset.geometrySource === "saved-display"
      ? asset.counts?.missing ||
        asset.counts?.unsupported ||
        asset.counts?.rejectedFaces
        ? "部分顯示快取"
        : "顯示快取"
      : "精細模型";
  if (asset.counts?.suppressed && !asset.parts) return "配置抑制";
  return "待轉換";
}
export function createCatalogUI(catalog, { modal, openAsset, getStation }) {
  catalog = { ...catalog, items: catalogAssets(catalog) };
  const $ = (s) => document.querySelector(s),
    byId = new Map(catalog.items.map((a) => [a.id, a]));
  $(".main-heading").insertAdjacentHTML(
    "afterend",
    `<div class="asset-bar"><label for="station-asset">本站 CAD</label><select id="station-asset" aria-label="本站 CAD 模型"></select><button id="asset-details" class="text-button">來源狀態 ↗</button></div>`,
  );
  $("#station-asset").onchange = (e) => openAsset(byId.get(e.target.value));
  const details = (asset) => {
    if (!asset) return;
    const c = asset.counts || {};
    modal(
      `<span class="eyebrow">SOURCE & GEOMETRY</span><h2>${h(asset.name || asset.source.split("/").pop())}</h2><p class="source-path">${h(asset.source)}</p><div class="source-metrics"><span>${asset.parts || 0}<small>已顯示零件</small></span><span>${c.missing || 0}<small>缺少引用</small></span><span>${c.unsupported || 0}<small>未解析引用</small></span><span>${c.suppressed || 0}<small>已抑制引用</small></span></div><p>${asset.geometrySource === "saved-display" ? "此模型由來源檔保存的三角網格與組合件變換還原；精度由原檔顯示設定決定，並非重新計算的 B-rep。" : !asset.url ? "此來源尚未轉為可顯示的 3D 幾何。請查看下方診斷。" : "STEP／IGES 使用 0.08 mm 弦差與 0.22 rad 角度設定細分，保留來源面色。此設定不是尺寸檢驗保證。"}</p>${c.rejectedFaces ? `<p class="source-warning">${c.rejectedFaces} 筆面記錄不符合解析規則，未納入顯示。</p>` : ""}${c.hidden ? `<p>另有 ${c.hidden} 個來源隱藏引用未顯示。</p>` : ""}${asset.preview ? `<figure class="source-preview"><img src="/${h(asset.preview)}" alt="原始 CAD 檔案內嵌預覽"><figcaption>原始檔案內嵌預覽（可能與目前配置不同）</figcaption></figure>` : ""}<details ${asset.diagnostics?.length ? "open" : ""}><summary>來源診斷（${asset.diagnostics?.length || 0}）</summary><ul class="diagnostic-list">${(asset.diagnostics || []).map((d) => `<li>${h(d)}</li>`).join("") || "<li>未記錄缺件；這不代表已驗證裝配工法或完整 B-rep。</li>"}</ul></details>`,
    );
  };
  $("#asset-details").onclick = () => details(byId.get(getStation()?.sample));
  function refresh(station) {
    const assets = catalog.items
      .filter((a) => a.stationId === station.id)
      .sort(
        (a, b) =>
          (a.url ? 0 : 1) - (b.url ? 0 : 1) || a.name.localeCompare(b.name),
      );
    $("#station-asset").innerHTML =
      (!assets.some((a) => a.id === station.sample)
        ? '<option value="">使用者匯入模型</option>'
        : "") +
      assets
        .map(
          (a) =>
            `<option value="${h(a.id)}">${h(a.name)} · ${assetStateLabel(a)}${a.parts ? " / " + a.parts + " 件" : ""}</option>`,
        )
        .join("");
    $("#station-asset").value = station.sample || "";
    $("#station-asset").disabled = !assets.length;
    $("#asset-details").disabled = !byId.has(station.sample);
  }
  function empty(station) {
    const a = byId.get(station.sample);
    const el = $("#empty-state");
    el.classList.toggle("with-preview", !!a?.preview);
    let reason = "此來源尚未有可顯示的 3D 網格。";
    if (a?.counts?.suppressed && !a.parts)
      reason = `目前來源配置的 ${a.counts.suppressed} 個引用全部被抑制，無可啟用的機構幾何。`;
    el.innerHTML = `${a?.preview ? `<img src="/${h(a.preview)}" alt="${h(station.name)} 原始檔案預覽">` : "<span>◇</span>"}<h3>${h(station.name)} · ${a ? assetStateLabel(a) : "尚未匯入"}</h3><p>${h(reason)}${a?.preview ? "<br>上方為檔案內嵌圖片，不是可操作的 3D 模型。" : ""}</p><button id="empty-details" class="button ghost">檢查來源資料</button>`;
    $("#empty-details").onclick = () => (a ? details(a) : library());
  }
  function library() {
    let page = 0;
    modal(
      `<span class="eyebrow">COMPLETE SOURCE LIBRARY</span><h2>完整 CAD 資料庫</h2><p>${catalog.summary.cadFiles.toLocaleString()} 個 CAD／圖面 · ${catalog.summary.ready.toLocaleString()} 個原檔可顯示模型 ＋ ${catalog.assemblies?.length || 0} 個設備分站模型 · ${catalog.stations.length} 個站別與分類</p><div class="catalog-filters"><input id="library-search" placeholder="搜尋檔名、路徑或站別" aria-label="搜尋 CAD 檔案"><select id="library-station" aria-label="篩選 CAD 站別"><option value="">全部站別</option>${catalog.stations.map((s) => `<option value="${h(s.id)}">${h(s.name)}</option>`).join("")}</select><select id="library-status" aria-label="篩選 CAD 狀態"><option value="">全部狀態</option><option value="ready">可顯示模型</option><option value="pending">待轉換／抑制</option></select></div><div id="library-list" class="library-list"></div><div class="catalog-pagination"><button id="catalog-prev" class="button ghost">← 上一頁</button><span id="catalog-page"></span><button id="catalog-next" class="button ghost">下一頁 →</button></div>`,
    );
    function draw() {
      const q = $("#library-search").value.toLowerCase(),
        sid = $("#library-station").value,
        status = $("#library-status").value;
      const matches = catalog.items.filter(
        (a) =>
          (!q ||
            (
              a.source +
              a.name +
              catalog.stations.find((s) => s.id === a.stationId)?.name
            )
              .toLowerCase()
              .includes(q)) &&
          (!sid || sid === a.stationId) &&
          (!status || (status === "ready" ? !!a.url : !a.url)),
      );
      const pages = Math.max(1, Math.ceil(matches.length / 40));
      page = Math.min(page, pages - 1);
      $("#library-list").innerHTML =
        matches
          .slice(page * 40, (page + 1) * 40)
          .map(
            (a) =>
              `<div class="catalog-row"><span class="file-type">${h(a.format.toUpperCase())}</span><div><strong>${h(a.name)}</strong><small>${h(a.source)}</small><small>${assetStateLabel(a)}${a.parts ? " · " + a.parts + " 件" : ""}${a.counts?.missing ? " · 有缺少引用" : ""}</small></div><button data-open="${h(a.id)}" class="button ${a.url ? "primary" : "ghost"}">${a.url ? "開啟" : "查看狀態"}</button></div>`,
          )
          .join("") || '<p class="catalog-no-results">沒有符合條件的檔案。</p>';
      $("#catalog-page").textContent =
        `${page + 1} / ${pages} 頁 · ${matches.length} 個結果`;
      $("#catalog-prev").disabled = page === 0;
      $("#catalog-next").disabled = page === pages - 1;
      document.querySelectorAll("[data-open]").forEach(
        (b) =>
          (b.onclick = () => {
            const a = byId.get(b.dataset.open);
            if (!a.url) {
              details(a);
              return;
            }
            $("#modal").close();
            openAsset(a);
          }),
      );
    }
    for (const id of ["library-search", "library-station", "library-status"])
      $("#" + id).oninput = () => {
        page = 0;
        draw();
      };
    $("#catalog-prev").onclick = () => {
      page--;
      draw();
    };
    $("#catalog-next").onclick = () => {
      page++;
      draw();
    };
    draw();
  }
  return { refresh, empty, library, details, byId };
}
