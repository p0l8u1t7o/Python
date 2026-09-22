/* Flip-Chip X 光標註工具 前端
 * 物件模型：{oid, alg ('die'|'pad'|'bump'|null), shape ('rect'|'circle'), 幾何, meta, user (人工類別|null), deleted, added}
 * oid：D# 晶片矩形、P# 焊點圓、B# 凸塊圓、U# 人工新增
 */
(() => {
  const $ = (id) => document.getElementById(id);
  const canvas = $("view");
  const ctx = canvas.getContext("2d");
  const wrap = $("canvas-wrap");
  const COLORS = { die: "#38d0e6", pad: "#4ade80", bump: "#ff5d5d", ignore: "#9aa4b1", sel: "#ffd84d", offset: "#ff9f1a" };
  const CLASS_ZH = { die: "晶片", pad: "基板焊點", bump: "金屬凸塊", ignore: "忽略" };

  const state = {
    image: null, data: null, objects: [], byId: new Map(), sites: [],
    selected: new Set(), tool: "select", cls: "bump",
    view: { scale: 1, tx: 0, ty: 0 },
    img: null, imgRaw: null,
    undo: [], drag: null, lasso: [], spaceDown: false,
    addCounter: 1, saveTimer: null, dirty: false, exportPkg: null,
    roi: null,                 // 使用者畫的 ROI (world 座標 {x,y,w,h})
  };

  // ------------------------------------------------------------------ 工具
  const setStatus = (msg, kind = "") => { const el = $("status"); el.textContent = msg; el.className = "status " + kind; };
  const dist = (a, b) => Math.hypot(a.x - b.x, a.y - b.y);
  const finalClass = (o) => (o.deleted ? "deleted" : (o.user || o.alg));
  const center = (o) => (o.shape === "circle" ? { x: o.cx, y: o.cy } : { x: o.x + o.w / 2, y: o.y + o.h / 2 });
  const pointInPoly = (p, poly) => {
    let inside = false;
    for (let i = 0, j = poly.length - 1; i < poly.length; j = i++) {
      const a = poly[i], b = poly[j];
      if ((a.y > p.y) !== (b.y > p.y) && p.x < ((b.x - a.x) * (p.y - a.y)) / (b.y - a.y) + a.x) inside = !inside;
    }
    return inside;
  };
  const toWorld = (sx, sy) => ({ x: (sx - state.view.tx) / state.view.scale, y: (sy - state.view.ty) / state.view.scale });
  const canvasPos = (ev) => { const r = canvas.getBoundingClientRect(); return { x: ev.clientX - r.left, y: ev.clientY - r.top }; };

  // ------------------------------------------------------------------ 物件建立
  function buildObjects(data) {
    const objs = [];
    for (const rg of data.regions) {
      objs.push({ oid: `D${rg.id}`, alg: "die", shape: "rect", x: rg.x, y: rg.y, w: rg.w, h: rg.h,
        meta: rg, user: null, deleted: false, added: false });
    }
    for (const s of data.sites) {
      const meta = { site: s.id, type: s.type, region: s.region, cluster: s.cluster, dx: s.dx, dy: s.dy, d: s.d, sep: s.sep, depth: s.depth, note: s.note,
        used: s.used, reject: s.reject, shift_inlier: s.shift_inlier, mode: s.mode, lobe_span: s.lobe_span, lobe_depth: s.lobe_depth };
      objs.push({ oid: `P${s.id}`, alg: "pad", shape: "circle", cx: s.pad.x, cy: s.pad.y, r: s.pad.r,
        meta: { ...meta, rms: s.pad.rms, cov: s.pad.cov }, user: null, deleted: false, added: false });
      if (s.bump) {
        objs.push({ oid: `B${s.id}`, alg: "bump", shape: "circle", cx: s.bump.x, cy: s.bump.y, r: s.bump.r,
          meta: { ...meta, rms: s.bump.rms, cov: s.bump.cov }, user: null, deleted: false, added: false });
      }
    }
    return objs;
  }

  function applyLabels(labels) {
    if (!labels || !labels.objects) return;
    let maxU = 0;
    for (const u of labels.objects) {
      if (u.added) {
        const o = { oid: u.oid, alg: null, shape: u.shape, meta: {}, user: u.user_class, deleted: !!u.deleted, added: true };
        if (u.shape === "circle") { o.cx = u.cx; o.cy = u.cy; o.r = u.r; } else { o.x = u.x; o.y = u.y; o.w = u.w; o.h = u.h; }
        state.objects.push(o);
        const n = parseInt(String(u.oid).slice(1), 10); if (n > maxU) maxU = n;
      } else {
        const o = state.byId.get(u.oid);
        if (o) { o.user = u.user_class || null; o.deleted = !!u.deleted; }
      }
    }
    state.addCounter = maxU + 1;
    $("notes").value = labels.notes || "";
    rebuildIndex();
  }

  function rebuildIndex() {
    state.byId = new Map(state.objects.map((o) => [o.oid, o]));
  }

  function labelsPayload() {
    const objects = [];
    for (const o of state.objects) {
      if (o.added) {
        const u = { oid: o.oid, added: true, user_class: o.user, deleted: o.deleted, shape: o.shape };
        if (o.shape === "circle") { u.cx = o.cx; u.cy = o.cy; u.r = o.r; } else { u.x = o.x; u.y = o.y; u.w = o.w; u.h = o.h; }
        objects.push(u);
      } else if (o.user || o.deleted) {
        objects.push({ oid: o.oid, user_class: o.user, deleted: o.deleted });
      }
    }
    return { objects, notes: $("notes").value };
  }

  // ------------------------------------------------------------------ 載入影像與結果
  function loadImages(image) {
    return new Promise((resolve) => {
      let n = 0;
      const done = () => { if (++n === 2) resolve(); };
      state.img = new Image(); state.img.onload = done; state.img.onerror = done; state.img.src = image.display;
      state.imgRaw = new Image(); state.imgRaw.onload = done; state.imgRaw.onerror = done; state.imgRaw.src = image.raw;
    });
  }

  async function loadResult(data, labels) {
    state.data = data; state.image = data.image; state.sites = data.sites;
    state.objects = buildObjects(data); rebuildIndex();
    state.selected.clear(); state.undo = []; state.lasso = []; state.exportPkg = null;
    const roi = data.summary.roi;
    state.roi = roi ? { x: roi[0], y: roi[1], w: roi[2], h: roi[3] } : null;
    updateRoiUi();
    applyLabels(labels);
    await loadImages(data.image);
    $("drop-hint").classList.add("hidden");
    fitView();
    renderSummary(); renderDieShift(); renderRegions(); renderSizes(); renderLabelStats(); renderSelection();
    $("download-circles-btn").disabled = false;
    ["download-md-btn", "download-json-btn", "copy-md-btn"].forEach((id) => { $(id).disabled = true; });
    $("export-text").value = "";
    setStatus(`${data.image.name}：位點 ${data.summary.sites}、晶片矩形 ${data.summary.regions}` + (state.roi ? `（ROI ${roiText(state.roi)}）` : ""));
    draw();
  }
  const roiText = (r) => `${Math.round(r.x)},${Math.round(r.y)} ${Math.round(r.w)}x${Math.round(r.h)}`;
  function updateRoiUi() {
    const has = !!state.roi && !!state.image;
    $("roi-run-btn").disabled = !has;
    $("roi-clear-btn").disabled = !has;
    $("roi-full-btn").disabled = !state.image || !(state.data && state.data.summary.roi);
    $("roi-info").textContent = has ? `ROI ${roiText(state.roi)} px` : "尚未畫 ROI";
  }
  async function reanalyze(roi) {
    if (!state.image) return;
    setStatus(roi ? `分析 ROI 中… ${roiText(roi)}` : "重新分析整張…", "busy");
    $("roi-run-btn").disabled = true; $("roi-full-btn").disabled = true;
    try {
      const body = { roi: roi ? [roi.x, roi.y, roi.w, roi.h] : null, scale: $("scale-input").value || "1",
        limit: $("limit-input").value || "5", px_um: $("pxum-input").value || "" };
      const r = await fetch(`/api/reanalyze/${state.image.id}`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
      const data = await r.json();
      if (!r.ok) throw new Error(data.error || r.statusText);
      const keepView = { ...state.view };
      await loadResult(data, null);
      state.view = keepView; draw();
      loadHistory();
    } catch (e) {
      setStatus("分析失敗：" + e.message, "error");
    } finally {
      updateRoiUi();
    }
  }

  async function analyzeFile(file) {
    const fd = new FormData();
    fd.append("image", file);
    fd.append("scale", $("scale-input").value || "1");
    fd.append("limit", $("limit-input").value || "5");
    fd.append("px_um", $("pxum-input").value || "");
    setStatus(`分析中… ${file.name}`, "busy");
    $("analyze-btn").disabled = true;
    try {
      const r = await fetch("/api/analyze", { method: "POST", body: fd });
      const data = await r.json();
      if (!r.ok) throw new Error(data.error || r.statusText);
      await loadResult(data, null);
      loadHistory();
    } catch (e) {
      setStatus("分析失敗：" + e.message, "error");
    } finally {
      $("analyze-btn").disabled = false;
    }
  }

  async function openResult(id) {
    setStatus("載入中…", "busy");
    const r = await fetch(`/api/results/${id}`);
    if (!r.ok) { setStatus("載入失敗", "error"); return; }
    const data = await r.json();
    await loadResult(data, data.labels);
  }

  async function loadHistory() {
    const r = await fetch("/api/results");
    if (!r.ok) return;
    const items = await r.json();
    const ul = $("history"); ul.innerHTML = "";
    for (const it of items) {
      const li = document.createElement("li");
      li.innerHTML = `${it.name}<span class="muted">${it.analyzed_at} · 位點 ${it.sites} · 矩形 ${it.regions} · 已標 ${it.labeled}</span>`;
      li.onclick = () => openResult(it.id);
      ul.appendChild(li);
    }
  }

  // ------------------------------------------------------------------ 視圖
  function resizeCanvas() {
    const dpr = window.devicePixelRatio || 1;
    const w = wrap.clientWidth, h = wrap.clientHeight;
    canvas.width = Math.round(w * dpr); canvas.height = Math.round(h * dpr);
    draw();
  }
  function fitView() {
    if (!state.image) return;
    const w = wrap.clientWidth, h = wrap.clientHeight;
    const s = Math.min(w / state.image.width, h / state.image.height) * 0.98;
    state.view = { scale: s, tx: (w - state.image.width * s) / 2, ty: (h - state.image.height * s) / 2 };
  }
  function zoomAt(sx, sy, factor) {
    const v = state.view;
    const ns = Math.min(Math.max(v.scale * factor, 0.05), 40);
    v.tx = sx - (sx - v.tx) * (ns / v.scale);
    v.ty = sy - (sy - v.ty) * (ns / v.scale);
    v.scale = ns;
    draw();
  }
  function centerOn(wx, wy, scale) {
    const v = state.view;
    if (scale) v.scale = scale;
    v.tx = wrap.clientWidth / 2 - wx * v.scale;
    v.ty = wrap.clientHeight / 2 - wy * v.scale;
    draw();
  }

  // ------------------------------------------------------------------ 繪圖
  function draw() {
    const dpr = window.devicePixelRatio || 1;
    ctx.setTransform(1, 0, 0, 1, 0, 0);
    ctx.fillStyle = "#05070a"; ctx.fillRect(0, 0, canvas.width, canvas.height);
    if (!state.image) return;
    const v = state.view;
    ctx.setTransform(dpr * v.scale, 0, 0, dpr * v.scale, dpr * v.tx, dpr * v.ty);
    const img = $("show-raw").checked && state.imgRaw && state.imgRaw.complete && state.imgRaw.naturalWidth ? state.imgRaw : state.img;
    if (img && img.complete && img.naturalWidth) ctx.drawImage(img, 0, 0);
    const lw = parseFloat($("line-width").value) / v.scale;
    const showDie = $("show-die").checked, showPad = $("show-pad").checked, showBump = $("show-bump").checked;
    const showOff = $("show-offset").checked, showIds = $("show-ids").checked;
    const fontPx = Math.max(10 / v.scale, 0.5);
    ctx.font = `${fontPx}px sans-serif`;
    ctx.lineJoin = "round";

    const showRej = $("show-rejected").checked;
    // 偏移向量 (兩圓都在時；篩除的位點不畫)
    if (showOff) {
      ctx.strokeStyle = COLORS.offset; ctx.fillStyle = COLORS.offset; ctx.lineWidth = lw * 0.8;
      for (const s of state.sites) {
        if (!s.bump || !s.used) continue;
        const p = state.byId.get(`P${s.id}`), b = state.byId.get(`B${s.id}`);
        if (!p || !b || p.deleted || b.deleted) continue;
        ctx.beginPath(); ctx.moveTo(p.cx, p.cy); ctx.lineTo(b.cx, b.cy); ctx.stroke();
        if (s.d != null) {
          const txt = s.type === "two-level" ? s.d.toFixed(1) : `(${s.d.toFixed(1)})`;
          ctx.fillStyle = s.type === "two-level" ? COLORS.offset : "rgba(255,159,26,.6)";
          ctx.fillText(txt, p.cx + p.r * 0.7, p.cy - p.r * 0.7);
        }
      }
    }
    // 物件
    const drawOrder = state.objects.filter((o) => !o.deleted);
    for (const o of drawOrder) {
      const fc = finalClass(o);
      if (o.shape === "rect" && !showDie) continue;
      if (o.shape === "circle" && ((o.alg === "pad" && !showPad) || (o.alg === "bump" && !showBump))) continue;
      const rejected = o.shape === "circle" && o.meta && o.meta.used === false;
      if (rejected && !showRej) continue;
      const sel = state.selected.has(o.oid);
      const col = rejected && !o.user ? "rgba(160,160,170,.55)" : (COLORS[fc] || "#fff");
      ctx.setLineDash(fc === "ignore" ? [4 / v.scale, 4 / v.scale] : []);
      if (o.shape === "rect") {
        if (sel) { ctx.strokeStyle = COLORS.sel; ctx.lineWidth = lw * 4; ctx.strokeRect(o.x, o.y, o.w, o.h); }
        ctx.strokeStyle = col; ctx.lineWidth = lw * 1.8; ctx.strokeRect(o.x, o.y, o.w, o.h);
        ctx.fillStyle = col; ctx.font = `bold ${fontPx * 1.6}px sans-serif`;
        const m = o.meta || {};
        let label = o.oid + (m.parent ? `<D${m.parent}` : "") + (m.n_sites != null ? ` n=${m.n_sites}` : "");
        if (m.primary && m.shift) label += ` ★ 需位移 (${fmt(m.shift.corr_dx)}, ${fmt(m.shift.corr_dy)}) px  ${m.shift.n_in}/${m.shift.n_used} ${m.shift.grade}`;
        if (o.user) label += ` → ${CLASS_ZH[o.user]}`;
        // 巢狀矩形的標籤依灰階層往下錯開，避免外層與內層的標籤疊在同一個角落
        ctx.fillText(label, o.x + 6 / v.scale, o.y + fontPx * 1.8 * (1 + (m.level || 0)));
        ctx.font = `${fontPx}px sans-serif`;
      } else {
        if (sel) { ctx.strokeStyle = COLORS.sel; ctx.lineWidth = lw * 3; ctx.beginPath(); ctx.arc(o.cx, o.cy, o.r + lw, 0, Math.PI * 2); ctx.stroke(); }
        ctx.strokeStyle = col; ctx.lineWidth = lw; ctx.beginPath(); ctx.arc(o.cx, o.cy, o.r, 0, Math.PI * 2); ctx.stroke();
        if (o.user && o.user !== o.alg) { ctx.fillStyle = col; ctx.fillText(CLASS_ZH[o.user], o.cx - o.r, o.cy + o.r + fontPx); }
        if (showIds || o.added) { ctx.fillStyle = col; ctx.fillText(o.oid, o.cx - o.r, o.cy - o.r - 2 / v.scale); }
      }
    }
    ctx.setLineDash([]);
    // 主要晶片的「需位移」箭頭 (放大 45 倍)
    if ($("show-arrow").checked) {
      for (const o of drawOrder) {
        const m = o.meta || {};
        if (o.shape !== "rect" || !m.primary || !m.shift || o.deleted) continue;
        const cx = o.x + o.w / 2, cy = o.y + o.h / 2, k = 45;
        const ex = cx + m.shift.corr_dx * k, ey = cy + m.shift.corr_dy * k;
        ctx.lineWidth = lw * 3; ctx.strokeStyle = "#000"; drawArrow(cx, cy, ex, ey, 14 / v.scale);
        ctx.lineWidth = lw * 1.5; ctx.strokeStyle = COLORS.sel; drawArrow(cx, cy, ex, ey, 14 / v.scale);
        ctx.fillStyle = COLORS.sel; ctx.font = `bold ${fontPx * 1.6}px sans-serif`;
        ctx.fillText(`move (${fmt(m.shift.corr_dx)}, ${fmt(m.shift.corr_dy)}) px`, ex + 6 / v.scale, ey);
        ctx.font = `${fontPx}px sans-serif`;
      }
    }
    // ROI 矩形 (橘色虛線)
    if (state.roi) {
      const R = state.roi;
      ctx.setLineDash([10 / v.scale, 6 / v.scale]); ctx.lineWidth = lw * 2; ctx.strokeStyle = "#ff9f1a";
      ctx.strokeRect(R.x, R.y, R.w, R.h); ctx.setLineDash([]);
      ctx.fillStyle = "#ff9f1a"; ctx.font = `bold ${fontPx * 1.6}px sans-serif`;
      ctx.fillText(`ROI ${roiText(R)}`, R.x + 6 / v.scale, Math.max(R.y - 6 / v.scale, fontPx * 1.6));
      ctx.font = `${fontPx}px sans-serif`;
    }
    // 進行中的框選 / 套索 / 新增預覽
    const d = state.drag;
    if (d && d.kind === "rect") {
      ctx.strokeStyle = COLORS.sel; ctx.lineWidth = lw; ctx.setLineDash([6 / v.scale, 4 / v.scale]);
      ctx.strokeRect(Math.min(d.a.x, d.b.x), Math.min(d.a.y, d.b.y), Math.abs(d.b.x - d.a.x), Math.abs(d.b.y - d.a.y));
      ctx.setLineDash([]);
    }
    if (d && d.kind === "roi") {
      ctx.strokeStyle = "#ff9f1a"; ctx.lineWidth = lw * 2; ctx.setLineDash([10 / v.scale, 6 / v.scale]);
      ctx.strokeRect(Math.min(d.a.x, d.b.x), Math.min(d.a.y, d.b.y), Math.abs(d.b.x - d.a.x), Math.abs(d.b.y - d.a.y));
      ctx.setLineDash([]);
    }
    if (d && d.kind === "add") {
      ctx.strokeStyle = COLORS[state.cls]; ctx.lineWidth = lw * 1.5;
      if (state.cls === "die") ctx.strokeRect(Math.min(d.a.x, d.b.x), Math.min(d.a.y, d.b.y), Math.abs(d.b.x - d.a.x), Math.abs(d.b.y - d.a.y));
      else { ctx.beginPath(); ctx.arc(d.a.x, d.a.y, Math.max(dist(d.a, d.b), 1), 0, Math.PI * 2); ctx.stroke(); }
    }
    if (state.lasso.length) {
      ctx.strokeStyle = COLORS.sel; ctx.lineWidth = lw; ctx.setLineDash([6 / v.scale, 4 / v.scale]);
      ctx.beginPath(); ctx.moveTo(state.lasso[0].x, state.lasso[0].y);
      for (const p of state.lasso.slice(1)) ctx.lineTo(p.x, p.y);
      if (state.hoverPt) ctx.lineTo(state.hoverPt.x, state.hoverPt.y);
      ctx.stroke(); ctx.setLineDash([]);
    }
  }

  const fmt = (v, n = 2) => (v == null ? "-" : (v > 0 ? "+" : "") + Number(v).toFixed(n));
  function drawArrow(x0, y0, x1, y1, head) {
    const a = Math.atan2(y1 - y0, x1 - x0);
    ctx.beginPath(); ctx.moveTo(x0, y0); ctx.lineTo(x1, y1);
    ctx.moveTo(x1, y1); ctx.lineTo(x1 - head * Math.cos(a - 0.5), y1 - head * Math.sin(a - 0.5));
    ctx.moveTo(x1, y1); ctx.lineTo(x1 - head * Math.cos(a + 0.5), y1 - head * Math.sin(a + 0.5));
    ctx.stroke();
  }

  // ------------------------------------------------------------------ 選取
  function visible(o) {
    if (o.deleted) return false;
    if (o.shape === "rect") return $("show-die").checked;
    if (o.alg === "pad") return $("show-pad").checked;
    if (o.alg === "bump") return $("show-bump").checked;
    return true;
  }
  function hitTest(p) {
    // 小的優先：圓 (半徑小者先)，再矩形 (面積小者先)
    const circles = state.objects.filter((o) => o.shape === "circle" && visible(o) && dist(p, { x: o.cx, y: o.cy }) <= o.r + 2 / state.view.scale);
    if (circles.length) return circles.sort((a, b) => a.r - b.r)[0];
    const rects = state.objects.filter((o) => o.shape === "rect" && visible(o) && p.x >= o.x && p.x <= o.x + o.w && p.y >= o.y && p.y <= o.y + o.h);
    if (rects.length) return rects.sort((a, b) => a.w * a.h - b.w * b.h)[0];
    return null;
  }
  function selectIn(predicate, additive) {
    if (!additive) state.selected.clear();
    for (const o of state.objects) if (visible(o) && predicate(o)) state.selected.add(o.oid);
    renderSelection(); draw();
  }
  function renderSelection() {
    if (state.data) renderSizes();
    const n = state.selected.size;
    const el = $("selection-info");
    if (!n) { el.textContent = "未選取"; return; }
    const counts = {};
    for (const oid of state.selected) { const o = state.byId.get(oid); if (o) counts[finalClass(o)] = (counts[finalClass(o)] || 0) + 1; }
    let txt = `已選 ${n} 個：` + Object.entries(counts).map(([k, v]) => `${CLASS_ZH[k] || k} ${v}`).join("、");
    if (n === 1) {
      const o = state.byId.get([...state.selected][0]);
      const m = o.meta || {};
      if (o.shape === "circle") txt += `\n${o.oid} 圓心 (${o.cx.toFixed(1)}, ${o.cy.toFixed(1)}) r=${o.r.toFixed(1)}`;
      else txt += `\n${o.oid} (${o.x}, ${o.y}) ${o.w}x${o.h}`;
      if (m.type) txt += `\n${m.type}${m.mode ? " / " + m.mode + (m.mode === "lobe" ? ` 弧${m.lobe_span}°` : "") : ""}  偏移 ${m.d ?? "-"} px (dx ${m.dx ?? "-"}, dy ${m.dy ?? "-"})  半徑差 ${m.sep ?? "-"}  深度 ${m.depth ?? "-"}`;
      if (m.note) txt += `\n${m.note}`;
      if (m.used === true) txt += `\n品質篩選：採用${m.shift_inlier === false ? "（但整體位移估計視為離群）" : ""}`;
      else if (m.used === false) txt += `\n品質篩選：排除（${m.reject || "-"}）`;
      if (m.verdict) txt += `\n${m.verdict}`;
      if (o.user) txt += `\n人工：${CLASS_ZH[o.user]}（演算法：${o.alg ? CLASS_ZH[o.alg] : "無"}）`;
    }
    el.textContent = txt;
  }

  // ------------------------------------------------------------------ 編輯 (含復原)
  function snapshot(oids) {
    return oids.map((oid) => { const o = state.byId.get(oid); return o ? JSON.parse(JSON.stringify(o)) : null; }).filter(Boolean);
  }
  function pushUndo(entry) { state.undo.push(entry); if (state.undo.length > 100) state.undo.shift(); }
  function markDirty() {
    state.dirty = true; renderLabelStats();
    clearTimeout(state.saveTimer); state.saveTimer = setTimeout(saveLabels, 1500);
  }
  function assignClass(cls) {
    if (!state.selected.size) return;
    pushUndo({ type: "modify", before: snapshot([...state.selected]) });
    for (const oid of state.selected) { const o = state.byId.get(oid); if (o) o.user = cls; }
    markDirty(); renderSelection(); draw();
  }
  function deleteSelected() {
    if (!state.selected.size) return;
    const removed = [];
    pushUndo({ type: "modify", before: snapshot([...state.selected]), removed });
    for (const oid of state.selected) {
      const o = state.byId.get(oid);
      if (!o) continue;
      if (o.added) { removed.push(o); state.objects = state.objects.filter((x) => x !== o); } else o.deleted = true;
    }
    rebuildIndex(); state.selected.clear(); markDirty(); renderSelection(); draw();
  }
  function addObject(a, b) {
    const oid = `U${state.addCounter++}`;
    let o;
    if (state.cls === "die") {
      const x = Math.min(a.x, b.x), y = Math.min(a.y, b.y), w = Math.abs(b.x - a.x), h = Math.abs(b.y - a.y);
      if (w < 4 || h < 4) return;
      o = { oid, alg: null, shape: "rect", x: Math.round(x), y: Math.round(y), w: Math.round(w), h: Math.round(h), meta: {}, user: "die", deleted: false, added: true };
    } else {
      const r = Math.max(dist(a, b), 3);
      o = { oid, alg: null, shape: "circle", cx: +a.x.toFixed(1), cy: +a.y.toFixed(1), r: +r.toFixed(1), meta: {}, user: state.cls, deleted: false, added: true };
    }
    state.objects.push(o); rebuildIndex();
    pushUndo({ type: "add", oid });
    state.selected.clear(); state.selected.add(oid);
    markDirty(); renderSelection(); draw();
  }
  function undo() {
    const e = state.undo.pop();
    if (!e) return;
    if (e.type === "add") {
      state.objects = state.objects.filter((o) => o.oid !== e.oid);
    } else {
      for (const snap of e.before) {
        const o = state.byId.get(snap.oid);
        if (o) Object.assign(o, snap);
      }
      if (e.removed) for (const o of e.removed) if (!state.byId.has(o.oid)) state.objects.push(o);
    }
    rebuildIndex(); state.selected.clear(); markDirty(); renderSelection(); draw();
  }

  // ------------------------------------------------------------------ 儲存 / 匯出
  async function saveLabels() {
    if (!state.image) return;
    clearTimeout(state.saveTimer);
    const r = await fetch(`/api/labels/${state.image.id}`, { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(labelsPayload()) });
    const d = await r.json();
    $("save-status").textContent = r.ok ? `已儲存 ${d.saved_at}（${d.count} 筆）` : "儲存失敗：" + (d.error || r.status);
    if (r.ok) state.dirty = false;
  }
  async function exportPackage() {
    if (!state.image) return;
    await saveLabels();
    const r = await fetch(`/api/export/${state.image.id}`, { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(labelsPayload()) });
    if (!r.ok) { setStatus("匯出失敗", "error"); return; }
    state.exportPkg = await r.json();
    $("export-text").value = state.exportPkg.markdown;
    ["download-md-btn", "download-json-btn", "copy-md-btn"].forEach((id) => { $(id).disabled = false; });
    setStatus("匯出內容已產生，可下載或複製");
  }
  function download(name, text, type) {
    const a = document.createElement("a");
    a.href = URL.createObjectURL(new Blob([text], { type }));
    a.download = name; document.body.appendChild(a); a.click();
    setTimeout(() => { URL.revokeObjectURL(a.href); a.remove(); }, 500);
  }
  const baseName = () => (state.image ? state.image.name.replace(/\.[^.]+$/, "") : "export");

  // ------------------------------------------------------------------ 右側面板
  function renderSummary() {
    const s = state.data.summary;
    const g = s.global_transform;
    const lines = [
      `候選 ${s.candidates}  位點 ${s.sites}  (two-level ${s.two_level} / single ${s.single})`,
      `晶片矩形 ${s.regions}  群 ${s.clusters}`,
      s.offset_median != null ? `偏移 px: 中位 ${s.offset_median}  P95 ${s.offset_p95}  最大 ${s.offset_max}  超過門檻 ${s.over_limit}` : "無 two-level 位點",
      g ? `全域: 平移 (${g.tx}, ${g.ty})  旋轉 ${g.rot_deg}°  縮放 ${g.scale}` : "全域變換: 樣本不足",
      `品質篩選後可用位點 ${s.n_used ?? "-"} / ${s.sites}`,
      s.modes ? `量測模式: ${Object.entries(s.modes).map(([k, v]) => `${k} ${v}`).join("、")}` : "",
      s.roi ? `ROI: ${s.roi.join(", ")}` : "",
      `參數: scale ${s.params.scale}, pad_r ${s.params.pad_r.map((v) => v.toFixed(0)).join("~")}, min_sep ${s.params.min_sep}`,
    ];
    $("summary").textContent = lines.join("\n");
  }
  function shiftHtml(sh, label, rn, vs) {
    if (!sh) return `<div class="die">${label}：可用位點不足</div>`;
    const g = sh.grade === "高" ? "grade-high" : sh.grade === "中" ? "grade-mid" : "grade-low";
    const um = sh.corr_um ? ` = (${fmt(sh.corr_um[0], 1)}, ${fmt(sh.corr_um[1], 1)}) µm` : "";
    const rot = sh.rot_deg != null ? `，旋轉 ${fmt(sh.rot_deg, 3)}°，縮放 ${fmt(sh.scale_ppm, 0)} ppm（邊角差 ${(sh.edge_var ?? 0).toFixed(1)} px）` : "";
    return `<div class="die">${label}<br>凸塊−焊點 (${fmt(sh.dx)}, ${fmt(sh.dy)}) px → <b>晶片需位移 (${fmt(sh.corr_dx)}, ${fmt(sh.corr_dy)}) px</b>${um}<br>` +
      `<span class="${g}">信心 ${sh.grade}</span>，內點 ${sh.n_in}/${sh.n_used} (${Math.round(sh.ratio * 100)}%)，統計 ±${sh.se.toFixed(2)} px${rot}` +
      rangeHtml(rn, vs) + `</div>`;
  }
  function rangeHtml(rn, vs) {
    if (!rn) return "";
    const parts = Object.entries(vs || {}).map(([k, v]) => v ? `${k} (${fmt(v.corr_dx)}, ${fmt(v.corr_dy)}) n=${v.n_in}` : `${k} -`).join("；");
    return `<div class="range">前處理敏感度 (${rn.n_variants} 種去噪)：dx ${fmt(rn.dx_min)}~${fmt(rn.dx_max)}、dy ${fmt(rn.dy_min)}~${fmt(rn.dy_max)} → ` +
      `系統 ±(${rn.sys_dx.toFixed(2)}, ${rn.sys_dy.toFixed(2)})，<b>合併不確定度 ±${rn.total.toFixed(2)} px</b><br>${parts}</div>`;
  }
  function renderDieShift() {
    const s = state.data.summary;
    let html = "";
    for (const d of s.die_shifts || []) {
      html += shiftHtml(d.shift, `晶片 D${d.region} (${d.bbox.join(",")})`, d.shift_range, d.shift_variants);
      if (d.shift_two) html += `<div class="muted">　只用 two-level：需位移 (${fmt(d.shift_two.corr_dx)}, ${fmt(d.shift_two.corr_dy)}) px，內點 ${d.shift_two.n_in}/${d.shift_two.n_used}，信心 ${d.shift_two.grade}</div>`;
    }
    if (!(s.die_shifts || []).length) html += `<div class="muted">沒有主要晶片矩形達到最少可用位點數</div>`;
    html += shiftHtml(s.shift_all, "全圖所有可用位點", s.shift_all_range, s.shift_all_variants);
    $("die-shift").innerHTML = html;
  }
  // ------------------------------------------------------------------ 圓尺寸表
  function circleRows() {
    const rows = [];
    for (const s of state.sites) {
      for (const [tag, c] of [["P", s.pad], ["B", s.bump]]) {
        if (!c) continue;
        const o = state.byId.get(`${tag}${s.id}`);
        rows.push({ oid: `${tag}${s.id}`, site: s.id, kind: tag === "P" ? "pad" : "bump", region: s.region, x: c.x, y: c.y, r: c.r,
          d: 2 * c.r, area: Math.PI * c.r * c.r, used: s.used, reject: s.reject || "", deleted: !!(o && o.deleted), user: o ? o.user : null });
      }
    }
    return rows;
  }
  function renderSizes() {
    const g = (v) => (v == null ? "-" : Number(v).toFixed(1));
    const sum = (state.data.summary.sizes || []).map((r) =>
      `<tr><td>${r.region ? "D" + r.region : "外"}</td><td>${r.n}/${r.n_bump}/${r.n_used}</td>` +
      `<td>${g(r.pad_d_med)} (${g(r.pad_d_min)}~${g(r.pad_d_max)})</td><td>${g(r.bump_d_med)} (${g(r.bump_d_min)}~${g(r.bump_d_max)})</td>` +
      `<td>${g(r.bump_d_used_med)} (${g(r.bump_d_used_min)}~${g(r.bump_d_used_max)})</td></tr>`).join("");
    $("size-summary").innerHTML = `<table><tr><th>矩形</th><th>位點/凸塊/可用</th><th>焊點直徑 中位(最小~最大)</th><th>凸塊直徑 中位(最小~最大)</th><th>可用凸塊直徑</th></tr>${sum}</table>`;
    const f = $("size-filter").value, q = $("size-search").value.trim().toUpperCase();
    let rows = circleRows();
    if (f === "pad" || f === "bump") rows = rows.filter((r) => r.kind === f);
    else if (f === "used") rows = rows.filter((r) => r.used);
    else if (f === "rejected") rows = rows.filter((r) => !r.used);
    if (q) rows = rows.filter((r) => r.oid.toUpperCase() === q || ("D" + r.region) === q || r.oid.toUpperCase().startsWith(q));
    const px = state.data.summary.params.px_um;
    const body = rows.slice(0, 1500).map((r) =>
      `<tr class="clickable${state.selected.has(r.oid) ? " hl" : ""}" data-oid="${r.oid}"><td>${r.oid}</td><td>${r.kind === "pad" ? "焊點" : "凸塊"}</td>` +
      `<td>${r.region ? "D" + r.region : "外"}</td><td>${r.x.toFixed(1)}, ${r.y.toFixed(1)}</td><td>${r.r.toFixed(2)}</td><td>${r.d.toFixed(2)}${px ? ` (${(r.d * px).toFixed(1)}µm)` : ""}</td>` +
      `<td>${r.area.toFixed(0)}</td><td>${r.deleted ? "刪" : r.used ? "✓" : ""}</td><td title="${r.reject}">${r.reject ? r.reject.slice(0, 18) : ""}</td></tr>`).join("");
    $("circles").innerHTML = `<table><tr><th>圓</th><th>類別</th><th>矩形</th><th>圓心</th><th>r px</th><th>直徑 px</th><th>面積 px</th><th>採用</th><th>排除原因</th></tr>${body}</table>` +
      (rows.length > 1500 ? `<p class="muted">只列前 1500 筆，共 ${rows.length} 筆；完整表請下載 CSV</p>` : `<p class="muted">共 ${rows.length} 筆</p>`);
    $("circles").querySelectorAll("tr[data-oid]").forEach((tr) => {
      tr.onclick = (ev) => {
        const o = state.byId.get(tr.dataset.oid);
        if (!o) return;
        if (!ev.shiftKey) state.selected.clear();
        state.selected.add(o.oid);
        centerOn(o.cx, o.cy, Math.max(state.view.scale, 4));
        renderSelection();
      };
    });
  }
  function circlesCsv() {
    const px = state.data.summary.params.px_um;
    const head = ["oid", "site", "kind", "region", "x", "y", "r_px", "d_px", "area_px"].concat(px ? ["d_um", "area_um2"] : []).concat(["used", "reject", "user_class", "deleted"]);
    const lines = [head.join(",")];
    for (const r of circleRows()) {
      const row = [r.oid, r.site, r.kind, r.region, r.x.toFixed(2), r.y.toFixed(2), r.r.toFixed(2), r.d.toFixed(2), r.area.toFixed(1)]
        .concat(px ? [(r.d * px).toFixed(2), (Math.PI * (r.r * px) ** 2).toFixed(1)] : [])
        .concat([r.used ? 1 : 0, `"${r.reject.replace(/"/g, "'")}"`, r.user || "", r.deleted ? 1 : 0]);
      lines.push(row.join(","));
    }
    return "\ufeff" + lines.join("\n");
  }
  function verdictTag(rg) {
    const lv = rg.level_verdict;
    const cls = lv === "高" ? "high" : (lv === "中" || lv === "高(低可信)") ? "mid" : "na";
    return `<span class="tag ${cls}">${rg.verdict || ""}</span>`;
  }
  function renderRegions() {
    const rows = state.data.regions.map((rg) => {
      const sh = rg.shift;
      return `<tr class="clickable${rg.primary ? " hl" : ""}" data-oid="D${rg.id}"><td>${rg.primary ? "★" : ""}D${rg.id}</td><td>${rg.parent ? "D" + rg.parent : "-"}</td>` +
        `<td>${rg.contrast ?? "-"}</td><td>${rg.n_sites}/${rg.n_used}</td>` +
        `<td>${sh ? `(${fmt(sh.corr_dx)}, ${fmt(sh.corr_dy)})` : "-"}</td><td>${sh ? `${sh.n_in}/${sh.n_used}` : "-"}</td><td>${sh ? sh.grade : "-"}</td></tr>`;
    }).join("");
    $("regions").innerHTML = `<table><tr><th>矩形</th><th>父</th><th>對比</th><th>位點/可用</th><th>需位移 (dx,dy)</th><th>內點</th><th>信心</th></tr>${rows}</table>`;
    $("regions").querySelectorAll("tr[data-oid]").forEach((tr) => {
      tr.onclick = () => {
        const o = state.byId.get(tr.dataset.oid);
        if (!o) return;
        state.selected.clear(); state.selected.add(o.oid);
        const s = Math.min(wrap.clientWidth / o.w, wrap.clientHeight / o.h) * 0.85;
        centerOn(o.x + o.w / 2, o.y + o.h / 2, s);
        renderSelection();
      };
    });
  }
  function renderLabelStats() {
    const classes = ["die", "pad", "bump", "ignore", "deleted"];
    const conf = {};
    let changed = 0, added = 0;
    for (const o of state.objects) {
      if (o.added) { if (!o.deleted) added++; continue; }
      const fc = finalClass(o);
      conf[o.alg] = conf[o.alg] || {}; conf[o.alg][fc] = (conf[o.alg][fc] || 0) + 1;
      if (fc !== o.alg) changed++;
    }
    const head = `<tr><th>演算法＼人工</th>${classes.map((c) => `<th>${CLASS_ZH[c] || "刪除"}</th>`).join("")}<th>同意</th></tr>`;
    const rows = ["die", "pad", "bump"].map((a) => {
      const r = conf[a] || {}; const tot = Object.values(r).reduce((x, y) => x + y, 0); const ok = r[a] || 0;
      return `<tr><td>${CLASS_ZH[a]}</td>${classes.map((c) => `<td>${r[c] || 0}</td>`).join("")}<td>${tot ? Math.round((100 * ok) / tot) : 0}%</td></tr>`;
    }).join("");
    $("label-stats").innerHTML = `<table>${head}${rows}</table><p class="muted">與演算法不同 ${changed} 個，人工新增 ${added} 個${state.dirty ? "（未儲存）" : ""}</p>`;
  }

  // ------------------------------------------------------------------ 滑鼠 / 鍵盤
  function setTool(t) {
    state.tool = t; state.lasso = [];
    document.querySelectorAll(".tool").forEach((b) => b.classList.toggle("active", b.dataset.tool === t));
    canvas.classList.toggle("pan", t === "pan");
    draw();
  }
  function setClass(c) {
    state.cls = c;
    document.querySelectorAll(".cls").forEach((b) => b.classList.toggle("active", b.dataset.class === c));
  }

  canvas.addEventListener("pointerdown", (ev) => {
    if (!state.image) return;
    const sp = canvasPos(ev), wp = toWorld(sp.x, sp.y);
    const panning = state.tool === "pan" || state.spaceDown || ev.button === 1;
    canvas.setPointerCapture(ev.pointerId);
    if (panning) { state.drag = { kind: "pan", sx: sp.x, sy: sp.y, tx: state.view.tx, ty: state.view.ty }; return; }
    if (ev.button !== 0) return;
    if (state.tool === "lasso") { state.lasso.push(wp); draw(); return; }
    if (state.tool === "add") { state.drag = { kind: "add", a: wp, b: wp }; return; }
    if (state.tool === "roi") { state.drag = { kind: "roi", a: wp, b: wp }; return; }
    state.drag = { kind: "rect", a: wp, b: wp, sx: sp.x, sy: sp.y, shift: ev.shiftKey };
  });
  canvas.addEventListener("pointermove", (ev) => {
    const sp = canvasPos(ev), wp = toWorld(sp.x, sp.y);
    state.hoverPt = wp;
    const d = state.drag;
    if (!d) { if (state.lasso.length) draw(); return; }
    if (d.kind === "pan") { state.view.tx = d.tx + (sp.x - d.sx); state.view.ty = d.ty + (sp.y - d.sy); draw(); return; }
    d.b = wp; draw();
  });
  canvas.addEventListener("pointerup", (ev) => {
    const d = state.drag; state.drag = null;
    if (!d) return;
    const sp = canvasPos(ev), wp = toWorld(sp.x, sp.y);
    if (d.kind === "pan") return;
    if (d.kind === "add") { addObject(d.a, wp); return; }
    if (d.kind === "roi") {
      const x = Math.max(0, Math.min(d.a.x, wp.x)), y = Math.max(0, Math.min(d.a.y, wp.y));
      const w = Math.min(state.image.width, Math.max(d.a.x, wp.x)) - x, h = Math.min(state.image.height, Math.max(d.a.y, wp.y)) - y;
      if (w >= 40 && h >= 40) state.roi = { x: Math.round(x), y: Math.round(y), w: Math.round(w), h: Math.round(h) };
      updateRoiUi(); draw(); return;
    }
    if (Math.hypot(sp.x - d.sx, sp.y - d.sy) < 4) {
      const hit = hitTest(wp);
      if (!d.shift) state.selected.clear();
      if (hit) { if (d.shift && state.selected.has(hit.oid)) state.selected.delete(hit.oid); else state.selected.add(hit.oid); }
      renderSelection(); draw();
    } else {
      const x0 = Math.min(d.a.x, wp.x), x1 = Math.max(d.a.x, wp.x), y0 = Math.min(d.a.y, wp.y), y1 = Math.max(d.a.y, wp.y);
      selectIn((o) => { const c = center(o); return c.x >= x0 && c.x <= x1 && c.y >= y0 && c.y <= y1; }, d.shift);
    }
  });
  canvas.addEventListener("dblclick", (ev) => {
    if (!state.image) return;
    const sp = canvasPos(ev), wp = toWorld(sp.x, sp.y);
    if (state.tool === "lasso" && state.lasso.length >= 3) { finishLasso(ev.shiftKey); return; }
    centerOn(wp.x, wp.y);
  });
  canvas.addEventListener("wheel", (ev) => {
    if (!state.image) return;
    ev.preventDefault();
    const sp = canvasPos(ev);
    zoomAt(sp.x, sp.y, ev.deltaY < 0 ? 1.15 : 1 / 1.15);
  }, { passive: false });
  canvas.addEventListener("contextmenu", (ev) => ev.preventDefault());
  function finishLasso(additive) {
    const poly = state.lasso.slice(); state.lasso = [];
    if (poly.length >= 3) selectIn((o) => pointInPoly(center(o), poly), additive);
    else draw();
  }

  window.addEventListener("keydown", (ev) => {
    if (ev.target.matches("input, textarea")) return;
    if (ev.code === "Space") { state.spaceDown = true; canvas.classList.add("pan"); ev.preventDefault(); return; }
    if (ev.ctrlKey && ev.key.toLowerCase() === "z") { undo(); ev.preventDefault(); return; }
    if (ev.ctrlKey && ev.key.toLowerCase() === "s") { saveLabels(); ev.preventDefault(); return; }
    switch (ev.key) {
      case "v": case "V": setTool("select"); break;
      case "l": case "L": setTool("lasso"); break;
      case "a": case "A": setTool("add"); break;
      case "h": case "H": setTool("pan"); break;
      case "r": case "R": setTool("roi"); break;
      case "1": setClass("die"); assignClass("die"); break;
      case "2": setClass("bump"); assignClass("bump"); break;
      case "3": setClass("pad"); assignClass("pad"); break;
      case "0": setClass("ignore"); assignClass("ignore"); break;
      case "Delete": case "Backspace": deleteSelected(); break;
      case "Enter": if (state.tool === "lasso") finishLasso(ev.shiftKey); break;
      case "Escape": state.selected.clear(); state.lasso = []; renderSelection(); draw(); break;
      case "f": case "F": fitView(); draw(); break;
      default: return;
    }
    ev.preventDefault();
  });
  window.addEventListener("keyup", (ev) => {
    if (ev.code === "Space") { state.spaceDown = false; if (state.tool !== "pan") canvas.classList.remove("pan"); }
  });

  // ------------------------------------------------------------------ UI 綁定
  $("upload-form").addEventListener("submit", (ev) => {
    ev.preventDefault();
    const f = $("file-input").files[0];
    if (!f) { setStatus("請先選擇影像", "error"); return; }
    analyzeFile(f);
  });
  ["dragenter", "dragover"].forEach((t) => wrap.addEventListener(t, (ev) => { ev.preventDefault(); wrap.classList.add("dragover"); }));
  ["dragleave", "drop"].forEach((t) => wrap.addEventListener(t, (ev) => { ev.preventDefault(); wrap.classList.remove("dragover"); }));
  wrap.addEventListener("drop", (ev) => { const f = ev.dataTransfer.files[0]; if (f) analyzeFile(f); });
  document.querySelectorAll(".tool").forEach((b) => b.addEventListener("click", () => setTool(b.dataset.tool)));
  document.querySelectorAll(".cls").forEach((b) => b.addEventListener("click", () => { setClass(b.dataset.class); assignClass(b.dataset.class); }));
  $("delete-btn").onclick = deleteSelected;
  $("roi-run-btn").onclick = () => reanalyze(state.roi);
  $("roi-full-btn").onclick = () => reanalyze(null);
  $("roi-clear-btn").onclick = () => { state.roi = null; updateRoiUi(); draw(); };
  $("undo-btn").onclick = undo;
  $("clear-sel-btn").onclick = () => { state.selected.clear(); state.lasso = []; renderSelection(); draw(); };
  ["show-die", "show-pad", "show-bump", "show-offset", "show-ids", "show-raw", "show-rejected", "show-arrow"].forEach((id) => $(id).addEventListener("change", draw));
  $("line-width").addEventListener("input", draw);
  $("save-btn").onclick = saveLabels;
  $("notes").addEventListener("input", markDirty);
  $("export-btn").onclick = exportPackage;
  $("size-filter").addEventListener("change", renderSizes);
  $("size-search").addEventListener("input", renderSizes);
  $("download-circles-btn").onclick = () => download(`${baseName()}_circles.csv`, circlesCsv(), "text/csv");
  $("download-md-btn").onclick = () => download(`${baseName()}_flipchip_review.md`, state.exportPkg.markdown, "text/markdown");
  $("download-json-btn").onclick = () => download(`${baseName()}_flipchip_review.json`, JSON.stringify(state.exportPkg.json, null, 1), "application/json");
  $("copy-md-btn").onclick = async () => {
    try { await navigator.clipboard.writeText(state.exportPkg.markdown); setStatus("Markdown 已複製到剪貼簿"); }
    catch (e) { $("export-text").select(); document.execCommand("copy"); setStatus("已複製 (fallback)"); }
  };
  window.addEventListener("beforeunload", (ev) => { if (state.dirty) { ev.preventDefault(); ev.returnValue = ""; } });

  new ResizeObserver(resizeCanvas).observe(wrap);
  setClass("bump"); setTool("select"); resizeCanvas(); loadHistory();
  // 網址帶 ?open=<id> 直接開啟之前分析過的結果 (可當成分享連結)
  const openId = new URLSearchParams(location.search).get("open");
  if (openId) openResult(openId);
})();
