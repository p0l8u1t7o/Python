(() => {
  const $ = (id) => document.getElementById(id);
  const state = { running: false, depthMap: null, mapTimer: null, statusTimer: null, cams: [] };
  const setStatus = (msg, kind = "") => { const el = $("status"); el.textContent = msg; el.className = "status " + kind; };

  // ------------------------------------------------------------ 選項
  async function loadOptions() {
    const r = await fetch("/api/options");
    const o = await r.json();
    const dev = $("device"); dev.innerHTML = "";
    let note = "";
    for (const d of o.devices) {
      const opt = document.createElement("option");
      opt.value = d.id; opt.textContent = d.name; opt.disabled = !d.available;
      dev.appendChild(opt);
      if (!d.available) note = d.name;
    }
    $("device-note").textContent = note ? "GPU 不可用：" + note.replace(/^GPU \(|\)$/g, "") : "";
    const gpu = o.devices.find((d) => d.available && d.id !== "cpu");
    if (gpu) { dev.value = gpu.id; $("device-note").textContent = "已偵測到 GPU，預設用 GPU 推論"; }
    const res = $("resolution"); res.innerHTML = "";
    for (const [w, h] of o.resolutions) {
      const opt = document.createElement("option"); opt.value = `${w}x${h}`; opt.textContent = `${w} × ${h}`; res.appendChild(opt);
    }
    const custom = document.createElement("option"); custom.value = "custom"; custom.textContent = "自訂…"; res.appendChild(custom);
    const model = $("model"); model.innerHTML = "";
    for (const m of o.models) { const opt = document.createElement("option"); opt.value = m; opt.textContent = m.replace("-depth.pt", "").replace("yolo26", "YOLO26-") + (m.startsWith("yolo26n") ? "（最快）" : m.startsWith("yolo26x") ? "（最準、最慢）" : ""); model.appendChild(opt); }
    const cmap = $("cmap"); cmap.innerHTML = "";
    for (const c of o.cmaps) { const opt = document.createElement("option"); opt.value = c; opt.textContent = c; cmap.appendChild(opt); }
  }

  async function loadCameras(refresh) {
    $("cam-info").textContent = "掃描相機中…";
    const r = await fetch("/api/cameras" + (refresh ? "?refresh=1" : ""));
    const o = await r.json();
    state.cams = o.cameras || [];
    const sel = $("camera"); sel.innerHTML = "";
    for (const c of state.cams) {
      const opt = document.createElement("option");
      opt.value = c.index; opt.disabled = !c.ok;
      opt.textContent = `#${c.index} ${c.name}` + (c.ok ? `（${c.width}×${c.height}）` : "（打不開）");
      sel.appendChild(opt);
    }
    const first = state.cams.find((c) => c.ok);
    if (first) sel.value = first.index;
    $("cam-info").textContent = state.cams.length ? `找到 ${state.cams.length} 台（名稱來源 ${o.source}）` : "沒有找到相機";
    if (refresh && state.running) { state.running = false; updateButtons(); }
    // 相機預設解析度帶入解析度清單
    if (first) {
      const v = `${first.width}x${first.height}`;
      if ([...$("resolution").options].some((op) => op.value === v)) $("resolution").value = v;
    }
  }

  // ------------------------------------------------------------ 啟動 / 停止
  function currentSettings() {
    let width = null, height = null;
    const rv = $("resolution").value;
    if (rv === "custom") { width = +$("res-w").value || null; height = +$("res-h").value || null; }
    else if (rv) { [width, height] = rv.split("x").map(Number); }
    const fixed = $("range-mode").value === "fixed";
    return {
      camera: +$("camera").value, width, height, device: $("device").value, model: $("model").value, imgsz: +$("imgsz").value,
      alpha: +$("alpha").value, cmap: $("cmap").value, view: $("view").value, flip: $("flip").checked, half: $("half").checked,
      dmin: fixed ? $("dmin").value : null, dmax: fixed ? $("dmax").value : null,
    };
  }
  async function start() {
    if (!state.cams.some((c) => c.ok)) { setStatus("沒有可用的相機", "error"); return; }
    setStatus("啟動中…載入模型（第一次會下載權重）", "busy");
    $("start").disabled = true;
    const r = await fetch("/api/start", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(currentSettings()) });
    const o = await r.json();
    if (!r.ok) { setStatus("啟動失敗：" + o.error, "error"); $("start").disabled = false; return; }
    state.running = true;
    $("stream").src = "/stream?t=" + Date.now();
    $("placeholder").classList.add("hidden");
    updateButtons();
    startPolling();
  }
  async function stop() {
    await fetch("/api/stop", { method: "POST" });
    state.running = false;
    $("stream").removeAttribute("src");
    $("placeholder").classList.remove("hidden");
    $("hover").classList.add("hidden");
    updateButtons();
    setStatus("已停止");
  }
  function updateButtons() {
    $("start").disabled = state.running;
    $("stop").disabled = !state.running;
    $("snapshot").disabled = !state.running;
  }
  async function pushSettings() {
    if (!state.running) return;
    const fixed = $("range-mode").value === "fixed";
    await fetch("/api/settings", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ alpha: +$("alpha").value, cmap: $("cmap").value, view: $("view").value, flip: $("flip").checked,
        dmin: fixed ? $("dmin").value : null, dmax: fixed ? $("dmax").value : null }) });
  }

  // ------------------------------------------------------------ 狀態 / 深度圖輪詢
  function startPolling() {
    clearInterval(state.statusTimer); clearInterval(state.mapTimer);
    state.statusTimer = setInterval(pollStatus, 500);
    state.mapTimer = setInterval(pollDepthMap, 300);
  }
  async function pollStatus() {
    const r = await fetch("/api/status");
    const s = await r.json();
    if (s.error) { setStatus("錯誤：" + s.error, "error"); state.running = false; updateButtons(); clearInterval(state.statusTimer); clearInterval(state.mapTimer); return; }
    if (!s.running && state.running) { setStatus("已停止"); state.running = false; updateButtons(); return; }
    if (s.loading) { setStatus("載入模型中…", "busy"); return; }
    setStatus(`${s.camera_name}  ${s.width}×${s.height}  ${s.fps.toFixed(1)} fps  推論 ${s.infer_ms.toFixed(0)} ms  ${s.device}`, "ok");
    $("stats").textContent = [
      `相機：${s.camera_name}（實際 ${s.width}×${s.height}）`,
      `模型：${s.model}  裝置：${s.device}  推論尺寸 ${s.settings.imgsz}`,
      `速度：${s.fps.toFixed(1)} fps，推論 ${s.infer_ms.toFixed(0)} ms/幀`,
      `深度範圍：顯示 ${s.lo.toFixed(2)}～${s.hi.toFixed(2)} m（${s.settings.dmin != null ? "固定" : "自動"}）`,
      `畫面最近 ${s.dmin.toFixed(2)} m，最遠 ${s.dmax.toFixed(2)} m`,
      `畫面中心距離：${s.center.toFixed(2)} m`,
    ].join("\n");
  }
  async function pollDepthMap() {
    const r = await fetch("/api/depth_map?w=160");
    const d = await r.json();
    if (d && d.data) state.depthMap = d;
  }

  // ------------------------------------------------------------ 滑鼠距離
  const img = $("stream");
  img.addEventListener("mousemove", (ev) => {
    const d = state.depthMap;
    if (!state.running || !d || !img.naturalWidth) { $("hover").classList.add("hidden"); return; }
    const rect = img.getBoundingClientRect();
    const fx = (ev.clientX - rect.left) / rect.width, fy = (ev.clientY - rect.top) / rect.height;   // 0~1
    const sx = Math.min(d.sw - 1, Math.max(0, Math.floor(fx * d.sw))), sy = Math.min(d.sh - 1, Math.max(0, Math.floor(fy * d.sh)));
    const val = d.data[sy * d.sw + sx];
    const px = Math.round(fx * d.w), py = Math.round(fy * d.h);
    $("hover-text").textContent = `${val.toFixed(2)} m  (${px}, ${py})`;
    const h = $("hover"); h.style.left = (ev.clientX - rect.left) + "px"; h.style.top = (ev.clientY - rect.top) + "px"; h.classList.remove("hidden");
  });
  img.addEventListener("mouseleave", () => $("hover").classList.add("hidden"));
  img.addEventListener("click", async (ev) => {
    // 點一下用伺服器的全解析度深度圖精確查一次
    if (!state.running || !img.naturalWidth) return;
    const rect = img.getBoundingClientRect();
    const px = Math.round((ev.clientX - rect.left) / rect.width * img.naturalWidth), py = Math.round((ev.clientY - rect.top) / rect.height * img.naturalHeight);
    const r = await fetch(`/api/depth?x=${px}&y=${py}`); const o = await r.json();
    if (o.depth != null) $("hover-text").textContent = `${o.depth.toFixed(3)} m  (${px}, ${py}) 精確`;
  });

  // ------------------------------------------------------------ UI 綁定
  $("refresh-cams").onclick = () => loadCameras(true);
  $("resolution").addEventListener("change", () => $("custom-res").classList.toggle("hidden", $("resolution").value !== "custom"));
  $("range-mode").addEventListener("change", () => { $("fixed-range").classList.toggle("hidden", $("range-mode").value !== "fixed"); pushSettings(); });
  $("alpha").addEventListener("input", () => { $("alpha-val").textContent = (+$("alpha").value).toFixed(2); pushSettings(); });
  ["cmap", "view", "flip", "dmin", "dmax"].forEach((id) => $(id).addEventListener("change", pushSettings));
  $("start").onclick = start;
  $("stop").onclick = stop;
  $("snapshot").onclick = async () => {
    const r = await fetch("/api/snapshot", { method: "POST" }); const o = await r.json();
    $("snap-info").textContent = r.ok ? `已存 ${o.overlay}` : ("失敗：" + o.error);
  };
  window.addEventListener("beforeunload", () => { if (state.running) navigator.sendBeacon("/api/stop"); });

  // 開頁時若後端已在跑 (例如另一個分頁啟動的)，直接接上串流
  async function attachIfRunning() {
    const r = await fetch("/api/status"); const s = await r.json();
    if (s.running) {
      state.running = true;
      $("stream").src = "/stream?t=" + Date.now();
      $("placeholder").classList.add("hidden");
      updateButtons(); startPolling();
    }
  }
  loadOptions().then(() => loadCameras(false)).then(attachIfRunning);
})();
