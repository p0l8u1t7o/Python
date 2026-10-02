import { AssemblyViewer } from "./scene-viewer.js";
import { describeParts } from "./importer.js";
import { escapeHTML as h } from "./core.js";
import "./equipment-overview.css";
import { overviewEntries } from "./overview-data.js";

function releaseRoot(root) {
  const resources = new Set();
  root?.traverse((o) => {
    if (!o.isMesh) return;
    resources.add(o.geometry);
    for (const m of Array.isArray(o.material) ? o.material : [o.material]) {
      resources.add(m);
      for (const value of Object.values(m))
        if (value?.isTexture) resources.add(value);
    }
  });
  resources.forEach((r) => r.dispose());
}

export function createEquipmentOverview({
  getProject,
  manifest,
  getModel,
  onOpen,
  onClose,
}) {
  const dialog = document.createElement("dialog");
  dialog.id = "equipment-overview";
  dialog.setAttribute("aria-label", "全部設備組合圖與成品圖");
  dialog.innerHTML = `
    <header class="overview-heading"><div><span class="eyebrow">COMPLETE EQUIPMENT</span><h2>全部設備</h2><p class="overview-project"></p></div><button class="button ghost overview-close" aria-label="關閉全部設備">返回工作台 ×</button></header>
    <div class="overview-toolbar"><div class="segmented"><button data-presentation="assembly" class="active">組合圖</button><button data-presentation="product">成品圖</button><button data-presentation="atlas">所有站總覽圖</button></div><label>設備／站別 <select aria-label="總覽設備或站別"></select></label><button class="button primary overview-download">下載圖片 PNG</button></div>
    <div class="overview-status" role="status"></div><div class="overview-export"></div>
    <section class="overview-scene"><div class="overview-viewport"></div><div class="overview-caption"><strong></strong><span></span></div><div class="overview-views"><button class="button ghost" data-axis="iso">等角</button><button class="button ghost" data-axis="front">正面</button><button class="button ghost" data-axis="top">俯視</button><button class="button ghost" data-axis="side">側面</button><button class="button ghost" data-axis="reset">重設視角</button></div><div class="overview-empty" hidden></div></section>
    <section class="overview-atlas" hidden><div class="overview-atlas-heading"><h3>所有站組合與成品總覽</h3><p>各站依自身尺寸取景；獨立展示，非實際廠區配置。整機與子站可能包含相同零件。</p></div><div class="overview-cards"></div></section>
    <footer class="overview-note"></footer>`;
  document.body.append(dialog);
  const $ = (s) => dialog.querySelector(s);
  let viewer,
    entries = [],
    selected,
    presentation = "assembly",
    version = 0;
  let ownedRoot,
    loading = false,
    captures = [],
    atlasReady = false;

  function busy(value, message = "") {
    loading = value;
    $(".overview-status").textContent = message;
    $(".overview-status").classList.toggle("working", value);
    dialog
      .querySelectorAll(
        ".overview-toolbar button, .overview-toolbar select, [data-axis]",
      )
      .forEach((el) => (el.disabled = value));
    $(".overview-download").disabled =
      value ||
      (presentation === "atlas" ? !atlasReady : !viewer?.meshes.length);
  }
  function cleanupSource() {
    viewer?.clear();
    releaseRoot(ownedRoot);
    ownedRoot = null;
  }
  function applyPresentation() {
    const product = presentation === "product" || presentation === "atlas";
    viewer.grid.visible = !product;
    viewer.setTheme(
      product ? "light" : document.documentElement.dataset.theme || "light",
    );
    $(".overview-views").hidden = presentation === "atlas";
    dialog
      .querySelectorAll("[data-presentation]")
      .forEach((b) =>
        b.classList.toggle("active", b.dataset.presentation === presentation),
      );
  }
  async function renderEntry(entry, token) {
    cleanupSource();
    const result = await getModel(entry.station);
    if (token !== version || !dialog.open) {
      if (result.owned) releaseRoot(result.root);
      return false;
    }
    ownedRoot = result.owned ? result.root : null;
    if (!result.root) return false;
    // Only this clone receives IDs. Saved project/source nodes stay untouched.
    const copy = result.root.clone(true);
    const described = describeParts(copy, entry.station.id);
    const parts = entry.station.parts.length ? entry.station.parts : described;
    viewer.load(copy, parts, { cadSource: !!entry.asset?.geometrySource });
    viewer.update(0, { mode: "solid" });
    applyPresentation();
    viewer.fit();
    viewer.controls.update();
    viewer.pipeline.render();
    return true;
  }
  function describe(entry) {
    $(".overview-caption strong").textContent =
      entry.station.name +
      (presentation === "product" ? " · 成品視圖" : " · 組合圖");
    $(".overview-caption span").textContent =
      `${viewer.meshes.length.toLocaleString()} 件零件 · ${entry.status}`;
    $(".overview-empty").hidden = viewer.meshes.length > 0;
    $(".overview-empty").textContent =
      `${entry.station.name}：${entry.status}。請由工作台查看來源診斷。`;
    const c = entry.asset?.counts || {};
    $(".overview-note").textContent =
      `${entry.station.id === "LINE" ? "依原始整線 CAD 的相對位置呈現，不重複疊加子站。" : "依本站 CAD 的組合位置呈現。"} ${entry.status === "部分還原" ? `目前來源部分還原：缺少 ${c.missing || 0} 個引用、未解析 ${c.unsupported || 0} 個引用。` : ""} 成品圖為現有 CAD 的完成組合外觀；未補造缺失零件。`;
  }
  async function showEntry(id) {
    const token = ++version;
    viewer.setActive(true);
    $(".overview-export").replaceChildren();
    selected = entries.find((e) => e.station.id === id) || entries[0];
    if (!selected) return;
    $("select").value = selected.station.id;
    $(".overview-scene").hidden = false;
    $(".overview-atlas").hidden = true;
    applyPresentation();
    busy(true, `載入 ${selected.station.name}…`);
    try {
      await renderEntry(selected, token);
      if (token !== version) return;
      describe(selected);
      busy(false);
    } catch (error) {
      if (token !== version) return;
      cleanupSource();
      describe(selected);
      busy(false, `載入失敗：${error.message}`);
    }
  }
  function drawCards() {
    $(".overview-cards").innerHTML = captures
      .map(
        (c, index) =>
          `<button class="overview-card" data-entry="${h(c.entry.station.id)}">${c.image ? `<img src="${c.image}" alt="${h(c.entry.station.name)} 組合外觀">` : `<div class="overview-missing">◇<span>${h(c.error || c.entry.status)}</span></div>`}<strong>${String(index + 1).padStart(2, "0")} ${h(c.entry.station.name)}</strong><small>${h(c.entry.station.id)} · ${h(c.error ? "載入失敗" : c.entry.status)}</small></button>`,
      )
      .join("");
    dialog.querySelectorAll("[data-entry]").forEach(
      (button) =>
        (button.onclick = () => {
          presentation = "product";
          showEntry(button.dataset.entry);
        }),
    );
  }
  async function showAtlas() {
    const token = ++version;
    presentation = "atlas";
    $(".overview-export").replaceChildren();
    viewer.setActive(false);
    applyPresentation();
    if (!atlasReady) {
      captures = [];
      $(".overview-atlas").hidden = true;
      $(".overview-scene").hidden = false;
      for (let i = 0; i < entries.length; i++) {
        const entry = entries[i];
        busy(
          true,
          `製作所有站總覽圖 ${i + 1} / ${entries.length}：${entry.station.name}`,
        );
        try {
          const ready = await renderEntry(entry, token);
          if (token !== version) return;
          captures.push({ entry, image: ready ? viewer.screenshot() : null });
        } catch (error) {
          if (token !== version) return;
          captures.push({ entry, image: null, error: error.message });
        }
        describe(entry);
        // Yield so progress and the close button remain responsive between models.
        await new Promise((resolve) => requestAnimationFrame(resolve));
        if (token !== version) return;
      }
      atlasReady = true;
      cleanupSource();
    }
    $(".overview-scene").hidden = true;
    $(".overview-atlas").hidden = false;
    drawCards();
    $(".overview-note").textContent =
      `涵蓋 ${entries.length} 個站別／分類，${captures.filter((c) => c.image).length} 個可顯示模型。點選圖卡可查看該站成品；無幾何與載入失敗項目仍保留在總覽中。`;
    busy(false);
  }
  async function exportImage() {
    if (loading) return;
    const atlas = presentation === "atlas";
    const canvas = document.createElement("canvas");
    const cols = 4,
      cellW = 480,
      cellH = 330;
    canvas.width = atlas
      ? cols * cellW
      : Math.max(1600, viewer.renderer.domElement.width);
    canvas.height = atlas
      ? 120 + Math.ceil(captures.length / cols) * cellH
      : Math.round(
          (canvas.width * viewer.renderer.domElement.height) /
            viewer.renderer.domElement.width,
        ) + 100;
    const context = canvas.getContext("2d");
    context.fillStyle = "#eef2f5";
    context.fillRect(0, 0, canvas.width, canvas.height);
    context.fillStyle = "#253b47";
    context.font = "bold 25px sans-serif";
    context.fillText(
      atlas
        ? "全部設備 · 所有站總覽圖"
        : `${selected.station.name} · ${presentation === "product" ? "成品圖" : "組合圖"}`,
      24,
      38,
    );
    context.font = "15px sans-serif";
    context.fillText(
      atlas
        ? "各站獨立尺度展示，非廠區配置；整機與子站可能重複。"
        : `${selected.status} · 依來源 CAD 相對位置；未補造缺失零件。`,
      24,
      68,
    );
    const drawImage = async (url, x, y, w, height) => {
      const img = new Image();
      img.src = url;
      await img.decode();
      const scale = Math.min(w / img.width, height / img.height);
      context.drawImage(
        img,
        x + (w - img.width * scale) / 2,
        y + (height - img.height * scale) / 2,
        img.width * scale,
        img.height * scale,
      );
    };
    if (atlas) {
      for (let i = 0; i < captures.length; i++) {
        const c = captures[i],
          x = (i % cols) * cellW,
          y = 110 + Math.floor(i / cols) * cellH;
        if (c.image) await drawImage(c.image, x + 12, y, cellW - 24, 250);
        context.fillStyle = "#253b47";
        context.font = "bold 18px sans-serif";
        context.fillText(
          `${i + 1}. ${c.entry.station.name}`,
          x + 20,
          y + 276,
          cellW - 40,
        );
        context.font = "14px sans-serif";
        context.fillText(
          `${c.entry.station.id} · ${c.error ? "載入失敗" : c.entry.status}`,
          x + 20,
          y + 303,
        );
      }
    } else
      await drawImage(
        viewer.screenshot(),
        0,
        100,
        canvas.width,
        canvas.height - 100,
      );
    const link = document.createElement("a");
    link.download = atlas
      ? "全部設備-所有站總覽圖.png"
      : `${selected.station.name}-${presentation === "product" ? "成品圖" : "組合圖"}.png`;
    link.href = canvas.toDataURL("image/png");
    link.textContent = `圖片已產生 · 下載 ${link.download}`;
    $(".overview-export").replaceChildren(link);
    link.click();
  }
  $(".overview-close").onclick = () => dialog.close();
  dialog.addEventListener("close", () => {
    ++version;
    cleanupSource();
    viewer?.dispose();
    viewer = null;
    captures = [];
    $(".overview-cards").replaceChildren();
    $(".overview-export").replaceChildren();
    onClose();
  });
  $("select").onchange = (event) => {
    if (presentation === "atlas") presentation = "product";
    showEntry(event.target.value);
  };
  dialog.querySelectorAll("[data-presentation]").forEach(
    (button) =>
      (button.onclick = () => {
        if (button.dataset.presentation === "atlas") return showAtlas();
        presentation = button.dataset.presentation;
        showEntry(selected.station.id);
      }),
  );
  dialog
    .querySelectorAll("[data-axis]")
    .forEach(
      (button) =>
        (button.onclick = () =>
          viewer.view(
            button.dataset.axis === "reset" ? "iso" : button.dataset.axis,
          )),
    );
  $(".overview-download").onclick = () =>
    exportImage().catch((error) =>
      busy(false, `圖片匯出失敗：${error.message}`),
    );
  return {
    async open() {
      if (dialog.open) return;
      const project = getProject();
      entries = overviewEntries(project, manifest);
      if (!entries.length) return;
      presentation = "assembly";
      atlasReady = false;
      $(".overview-project").textContent = project.name;
      $("select").innerHTML = entries
        .map(
          (e) =>
            `<option value="${h(e.station.id)}">${h(e.station.name)} · ${e.status}</option>`,
        )
        .join("");
      onOpen();
      dialog.showModal();
      $(".overview-scene").hidden = false;
      viewer = new AssemblyViewer($(".overview-viewport"), () => {});
      await showEntry(
        entries.find((e) => e.station.id === "LINE")?.station.id ||
          entries[0].station.id,
      );
    },
  };
}
