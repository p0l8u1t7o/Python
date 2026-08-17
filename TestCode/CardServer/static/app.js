"use strict";

// ---------------------------------------------------- 拍照預覽 + 自動辨識
const photoInput = document.getElementById("photo-input");
const photoPreview = document.getElementById("photo-preview");
const photoPlaceholder = document.getElementById("photo-placeholder");
const photoIcon = document.getElementById("photo-icon");
const ocrStatus = document.getElementById("ocr-status");
const uploadForm = document.getElementById("upload-form");

const AUTOFILL_FIELDS = ["name", "company", "title", "phone", "email", "address"];

photoInput.addEventListener("change", async () => {
  const file = photoInput.files[0];
  if (!file) return;

  photoPreview.src = URL.createObjectURL(file);
  photoPreview.classList.remove("hidden");
  photoPlaceholder.classList.add("hidden");
  photoIcon.classList.add("hidden");

  await runAutoRecognition(file);
});

async function runAutoRecognition(file) {
  ocrStatus.textContent = "辨識中，請稍候...";
  ocrStatus.className = "status info";

  try {
    const res = await fetch("/api/ocr", { method: "POST", body: toFormData(file) });
    const data = await res.json();

    if (!res.ok || !data.available) {
      // 辨識引擎未安裝或辨識失敗：不當成錯誤處理，讓使用者照常手動輸入即可。
      // 但把伺服器回傳的原因一併顯示，管理者才知道是「引擎沒裝好」而不是照片問題。
      ocrStatus.textContent = data.error
        ? `自動辨識未啟用（${data.error}），請手動輸入名片資訊`
        : "未能自動辨識，請手動輸入名片資訊";
      ocrStatus.className = "status info";
      return;
    }

    let filledAny = false;
    for (const key of AUTOFILL_FIELDS) {
      const value = (data.fields && data.fields[key]) || "";
      const input = uploadForm.elements[key];
      if (value && input && !input.value.trim()) {
        input.value = value;
        input.classList.add("auto-filled");
        filledAny = true;
      }
    }

    if (filledAny) {
      ocrStatus.textContent = "已自動帶入辨識結果（淡藍色欄位），請核對後再儲存";
      ocrStatus.className = "status ok";
    } else {
      ocrStatus.textContent = "未辨識到可用欄位，請確認名片完整入鏡且畫面清晰，或直接手動輸入";
      ocrStatus.className = "status info";
    }
  } catch (err) {
    ocrStatus.textContent = "未能自動辨識，請手動輸入名片資訊";
    ocrStatus.className = "status info";
  }
}

function toFormData(file) {
  const fd = new FormData();
  fd.append("image", file);
  return fd;
}

// 使用者手動修改過的欄位，不再視為「辨識帶入待確認」。
for (const key of AUTOFILL_FIELDS) {
  const input = uploadForm.elements[key];
  input.addEventListener("input", () => input.classList.remove("auto-filled"));
}

// ---------------------------------------------------- 上傳名片
const uploadStatus = document.getElementById("upload-status");
const uploadSubmit = document.getElementById("upload-submit");

uploadForm.addEventListener("submit", async (ev) => {
  ev.preventDefault();
  uploadSubmit.disabled = true;
  uploadStatus.textContent = "儲存中...";
  uploadStatus.className = "status";

  try {
    const res = await fetch("/api/cards", { method: "POST", body: new FormData(uploadForm) });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || "儲存失敗");

    // 伺服器回傳這筆的建立時間，直接顯示出來讓使用者確認存檔時間點。
    uploadStatus.textContent = data.created_at
      ? `已儲存！建立時間 ${formatTime(data.created_at)}`
      : "已儲存！";
    uploadStatus.className = "status ok";
    resetUploadForm();
    loadCards();
  } catch (err) {
    uploadStatus.textContent = err.message;
    uploadStatus.className = "status err";
  } finally {
    uploadSubmit.disabled = false;
  }
});

function resetUploadForm() {
  // 送出成功後把整張表單（含照片預覽、辨識狀態）清空，方便馬上填下一張名片。
  uploadForm.reset();
  photoPreview.classList.add("hidden");
  photoPreview.src = "";
  photoPlaceholder.classList.remove("hidden");
  photoIcon.classList.remove("hidden");
  ocrStatus.textContent = "";
  for (const key of AUTOFILL_FIELDS) {
    uploadForm.elements[key].classList.remove("auto-filled");
  }
}

// ---------------------------------------------------- 名片列表 / 搜尋 / 匯出
const cardList = document.getElementById("card-list");
const searchInput = document.getElementById("search-input");
const searchBtn = document.getElementById("search-btn");
const exportBtn = document.getElementById("export-btn");
const totalCount = document.getElementById("total-count");
const matchedBadge = document.getElementById("matched-badge");
const matchedCount = document.getElementById("matched-count");
const listFooter = document.getElementById("list-footer");
const listProgress = document.getElementById("list-progress");
const loadMoreBtn = document.getElementById("load-more-btn");

// 分頁狀態：只保留「已載入幾筆」與「當前查詢條件」，其餘交給伺服器算。
const PAGE_SIZE = 20;
let loadedCount = 0;
let activeQuery = "";

/**
 * 載入名片清單。
 * append=false 代表重新查詢（清空列表、從最新的一頁開始）；
 * append=true 代表按下「載入更多」，把下一頁接在現有清單後面。
 * 一次只取一頁，資料累積到上千筆時也不會整批塞進畫面造成卡頓。
 */
async function loadCards(append = false) {
  if (!append) {
    activeQuery = searchInput.value.trim();
    loadedCount = 0;
  }

  const params = new URLSearchParams({ limit: PAGE_SIZE, offset: loadedCount });
  if (activeQuery) params.set("q", activeQuery);

  loadMoreBtn.disabled = true;
  let data;
  try {
    const res = await fetch(`/api/cards?${params}`);
    data = await res.json();
  } catch (err) {
    listProgress.textContent = "載入失敗，請稍後再試";
    return;
  } finally {
    loadMoreBtn.disabled = false;
  }

  const cards = data.cards || [];

  // 「目前已儲存 N 筆」永遠是資料庫總筆數，不受搜尋條件影響；
  // 有搜尋條件時才另外顯示符合筆數，避免兩個數字混淆。
  totalCount.textContent = data.total;
  if (activeQuery) {
    matchedCount.textContent = data.matched;
    matchedBadge.classList.remove("hidden");
  } else {
    matchedBadge.classList.add("hidden");
  }

  if (!append) cardList.innerHTML = "";
  loadedCount += cards.length;

  if (loadedCount === 0) {
    cardList.innerHTML = activeQuery
      ? '<li class="empty-hint">找不到符合條件的名片</li>'
      : '<li class="empty-hint">尚無資料，請於上方拍照建檔</li>';
    listFooter.classList.add("hidden");
    return;
  }

  for (const card of cards) {
    cardList.appendChild(buildCardItem(card));
  }

  // 只有還有下一頁時才顯示按鈕；筆數提示則一律顯示，讓使用者知道看到哪了。
  listFooter.classList.remove("hidden");
  listProgress.textContent = `顯示 ${loadedCount} / ${data.matched} 筆`;
  loadMoreBtn.classList.toggle("hidden", !data.has_more);
}

function buildCardItem(card) {
  const li = document.createElement("li");
  li.className = "card-item";
  li.innerHTML = `
    <img src="${card.thumb_url || card.image_url}" alt="名片縮圖" loading="lazy">
    <div class="meta">
      <div class="name">${escapeHtml(card.name || "（未填姓名）")}</div>
      <div class="sub">${escapeHtml([card.company, card.title].filter(Boolean).join(" · "))}</div>
      <div class="sub">${escapeHtml(card.phone || "")}</div>
      <div class="created">建立於 ${escapeHtml(formatTime(card.created_at))}</div>
    </div>`;
  li.addEventListener("click", () => openDetail(card.id));
  return li;
}

loadMoreBtn.addEventListener("click", () => loadCards(true));
searchBtn.addEventListener("click", () => loadCards());
searchInput.addEventListener("keydown", (ev) => {
  if (ev.key === "Enter") loadCards();
});
// 清空搜尋框（含輸入框內建的 x 按鈕）時自動回到完整清單
searchInput.addEventListener("search", () => loadCards());

exportBtn.addEventListener("click", () => {
  const q = searchInput.value.trim();
  const url = q ? `/api/export?q=${encodeURIComponent(q)}` : "/api/export";
  window.location.href = url;
});

function escapeHtml(str) {
  const div = document.createElement("div");
  div.textContent = str;
  return div.innerHTML;
}

// ---------------------------------------------------- 名片詳情 / 編輯彈窗
const overlay = document.getElementById("detail-overlay");
const detailImage = document.getElementById("detail-image");
const detailCreated = document.getElementById("detail-created");
const editForm = document.getElementById("edit-form");
const editStatus = document.getElementById("edit-status");
const detailRequirements = document.getElementById("detail-requirements");
const addRequirementForm = document.getElementById("add-requirement-form");
const detailStatus = document.getElementById("detail-status");
const reocrBtn = document.getElementById("reocr-btn");
const deleteBtn = document.getElementById("delete-btn");
const EDIT_FIELDS = ["name", "company", "title", "phone", "email", "address", "note"];
let currentCardId = null;

// ---------------------------------------------------- 名片影像縮放 / 平移
const viewport = document.getElementById("image-viewport");
const zoomLevelLabel = document.getElementById("zoom-level");
const MIN_ZOOM = 1;
const MAX_ZOOM = 6;
let zoom = 1;
let panX = 0;
let panY = 0;

function applyTransform() {
  detailImage.style.transform = `translate(${panX}px, ${panY}px) scale(${zoom})`;
  zoomLevelLabel.textContent = `${Math.round(zoom * 100)}%`;
}

function resetZoom() {
  zoom = 1;
  panX = panY = 0;
  applyTransform();
}

/**
 * 以 viewport 內的某一點為中心縮放。
 * 先把該點換算成「影像座標」，縮放後再把它移回原本的螢幕位置，
 * 使用者才會覺得是朝著游標/手指的位置放大，而不是永遠從正中央放大。
 */
function zoomAt(factor, originX, originY) {
  const next = Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, zoom * factor));
  if (next === zoom) return;

  const rect = viewport.getBoundingClientRect();
  const cx = originX - rect.left - rect.width / 2;
  const cy = originY - rect.top - rect.height / 2;
  panX = cx - ((cx - panX) * next) / zoom;
  panY = cy - ((cy - panY) * next) / zoom;
  zoom = next;
  clampPan();
  applyTransform();
}

/** 限制平移範圍，避免把影像拖到整個離開畫面。 */
function clampPan() {
  if (zoom <= 1) {
    panX = panY = 0;
    return;
  }
  const rect = viewport.getBoundingClientRect();
  const maxX = (rect.width * (zoom - 1)) / 2;
  const maxY = (rect.height * (zoom - 1)) / 2;
  panX = Math.min(maxX, Math.max(-maxX, panX));
  panY = Math.min(maxY, Math.max(-maxY, panY));
}

document.getElementById("zoom-in").addEventListener("click", () => centerZoom(1.4));
document.getElementById("zoom-out").addEventListener("click", () => centerZoom(1 / 1.4));
document.getElementById("zoom-reset").addEventListener("click", resetZoom);

function centerZoom(factor) {
  const rect = viewport.getBoundingClientRect();
  zoomAt(factor, rect.left + rect.width / 2, rect.top + rect.height / 2);
}

viewport.addEventListener("wheel", (ev) => {
  ev.preventDefault();
  zoomAt(ev.deltaY < 0 ? 1.15 : 1 / 1.15, ev.clientX, ev.clientY);
}, { passive: false });

// 用 Pointer Events 同時支援滑鼠拖曳與手機雙指縮放，不必分別寫 mouse/touch 兩套。
const activePointers = new Map();
let pinchStartDistance = 0;
let pinchStartZoom = 1;

viewport.addEventListener("pointerdown", (ev) => {
  viewport.setPointerCapture(ev.pointerId);
  activePointers.set(ev.pointerId, { x: ev.clientX, y: ev.clientY });
  if (activePointers.size === 2) {
    pinchStartDistance = pointerDistance();
    pinchStartZoom = zoom;
  }
  viewport.classList.add("dragging");
});

viewport.addEventListener("pointermove", (ev) => {
  const prev = activePointers.get(ev.pointerId);
  if (!prev) return;
  const dx = ev.clientX - prev.x;
  const dy = ev.clientY - prev.y;
  activePointers.set(ev.pointerId, { x: ev.clientX, y: ev.clientY });

  if (activePointers.size === 2 && pinchStartDistance > 0) {
    // 雙指：依兩指間距的變化比例縮放
    const scale = pointerDistance() / pinchStartDistance;
    const mid = pointerMidpoint();
    const target = Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, pinchStartZoom * scale));
    zoomAt(target / zoom, mid.x, mid.y);
  } else if (activePointers.size === 1 && zoom > 1) {
    // 單指/滑鼠：放大後才需要平移
    panX += dx;
    panY += dy;
    clampPan();
    applyTransform();
  }
});

function endPointer(ev) {
  activePointers.delete(ev.pointerId);
  if (activePointers.size < 2) pinchStartDistance = 0;
  if (activePointers.size === 0) viewport.classList.remove("dragging");
}

viewport.addEventListener("pointerup", endPointer);
viewport.addEventListener("pointercancel", endPointer);

// 連點兩下在「原始大小」與「放大 2.5 倍」之間切換
viewport.addEventListener("dblclick", (ev) => {
  if (zoom > 1) resetZoom();
  else zoomAt(2.5, ev.clientX, ev.clientY);
});

function pointerDistance() {
  const [a, b] = [...activePointers.values()];
  return Math.hypot(a.x - b.x, a.y - b.y);
}

function pointerMidpoint() {
  const [a, b] = [...activePointers.values()];
  return { x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 };
}

async function openDetail(cardId) {
  const res = await fetch(`/api/cards/${cardId}`);
  if (!res.ok) return;
  const card = await res.json();
  currentCardId = cardId;

  detailImage.src = card.image_url;
  resetZoom();
  detailCreated.textContent = formatTime(card.created_at);
  for (const key of EDIT_FIELDS) {
    editForm.elements[key].value = card[key] || "";
    editForm.elements[key].classList.remove("auto-filled");
  }
  editStatus.textContent = "";
  detailStatus.textContent = "";

  renderRequirements(card.requirements);
  overlay.classList.remove("hidden");
}

// 查詢到的名片可以直接在這裡補上或修正公司、姓名等欄位。
editForm.addEventListener("submit", async (ev) => {
  ev.preventDefault();
  if (currentCardId === null) return;
  editStatus.textContent = "儲存中...";
  editStatus.className = "status span2";

  try {
    const res = await fetch(`/api/cards/${currentCardId}`, {
      method: "PUT",
      body: new URLSearchParams(new FormData(editForm)),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || "儲存失敗");

    editStatus.textContent = "已儲存";
    editStatus.className = "status ok span2";
    loadCards();
  } catch (err) {
    editStatus.textContent = err.message;
    editStatus.className = "status err span2";
  }
});

// ---------------------------------------------------- 旋轉名片照片 90 度
// 旋轉是直接把伺服器上的照片轉正後覆寫，不是只在畫面上轉；因此重新整理、列表縮圖、
// 匯出與「重新辨識」看到的都會是轉正後的方向。
const rotateCw = document.getElementById("rotate-cw");
const rotateCcw = document.getElementById("rotate-ccw");

async function rotateImage(direction) {
  if (currentCardId === null) return;
  rotateCw.disabled = rotateCcw.disabled = true;
  detailStatus.textContent = "旋轉中...";
  detailStatus.className = "status";

  try {
    const res = await fetch(`/api/cards/${currentCardId}/rotate`, {
      method: "POST",
      body: new URLSearchParams({ direction }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || "旋轉失敗");

    // 檔名沒變，靠伺服器回傳的版本化網址讓瀏覽器重新載入而不是用快取的舊圖
    detailImage.src = data.image_url;
    resetZoom();
    detailStatus.textContent = `已旋轉，目前角度 ${data.rotation}°（已存檔）`;
    detailStatus.className = "status ok";
    loadCards();   // 讓列表縮圖也跟著更新
  } catch (err) {
    detailStatus.textContent = err.message;
    detailStatus.className = "status err";
  } finally {
    rotateCw.disabled = rotateCcw.disabled = false;
  }
}

rotateCw.addEventListener("click", () => rotateImage("cw"));
rotateCcw.addEventListener("click", () => rotateImage("ccw"));

// ---------------------------------------------------- 重新辨識既有名片
reocrBtn.addEventListener("click", async () => {
  if (currentCardId === null) return;
  reocrBtn.disabled = true;
  detailStatus.textContent = "重新辨識中，請稍候...";
  detailStatus.className = "status info";

  try {
    const res = await fetch(`/api/cards/${currentCardId}/reocr`, { method: "POST" });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || "重新辨識失敗");

    if (!data.available) {
      detailStatus.textContent = data.error
        ? `自動辨識未啟用（${data.error}）`
        : "未能辨識，請手動輸入";
      detailStatus.className = "status info";
      return;
    }

    // 辨識結果只填進表單並標示顏色，尚未寫入資料庫；使用者確認後按「儲存修改」才生效，
    // 這樣既能重新辨識，也不會直接蓋掉先前人工修正好的內容。
    let changed = 0;
    for (const key of AUTOFILL_FIELDS) {
      const value = (data.fields && data.fields[key]) || "";
      const input = editForm.elements[key];
      if (value && input && input.value.trim() !== value) {
        input.value = value;
        input.classList.add("auto-filled");
        changed += 1;
      }
    }

    detailStatus.textContent = changed
      ? `已帶入 ${changed} 個辨識結果（淡藍色欄位），確認後請按「儲存修改」`
      : "辨識結果與目前內容相同，未做變更";
    detailStatus.className = changed ? "status ok" : "status info";
  } catch (err) {
    detailStatus.textContent = err.message;
    detailStatus.className = "status err";
  } finally {
    reocrBtn.disabled = false;
  }
});

// ---------------------------------------------------- 刪除名片
deleteBtn.addEventListener("click", async () => {
  if (currentCardId === null) return;
  const who = editForm.elements.name.value.trim() || "這張名片";
  // 刪除連同照片與需求紀錄都會消失且無法復原，先確認一次。
  if (!window.confirm(`確定要刪除「${who}」嗎？\n名片照片與需求紀錄都會一併刪除，且無法復原。`)) {
    return;
  }

  deleteBtn.disabled = true;
  detailStatus.textContent = "刪除中...";
  detailStatus.className = "status";

  try {
    const res = await fetch(`/api/cards/${currentCardId}`, { method: "DELETE" });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || "刪除失敗");

    closeDetail();
    loadCards();
  } catch (err) {
    detailStatus.textContent = err.message;
    detailStatus.className = "status err";
  } finally {
    deleteBtn.disabled = false;
  }
});

function renderRequirements(reqs) {
  detailRequirements.innerHTML = reqs.length
    ? reqs.map((r) => `<li>${escapeHtml(r.content)}<span class="req-time">${escapeHtml(formatTime(r.created_at))}</span></li>`).join("")
    : '<li class="empty-hint">尚無需求紀錄</li>';
}

function formatTime(iso) {
  // 伺服器存的是帶時區的 ISO 字串，交給 Date 轉成瀏覽器所在時區的當地時間顯示。
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString("zh-TW", {
    year: "numeric", month: "2-digit", day: "2-digit",
    hour: "2-digit", minute: "2-digit", hour12: false,
  });
}

function closeDetail() {
  overlay.classList.add("hidden");
  currentCardId = null;
  resetZoom();
}

document.getElementById("detail-close").addEventListener("click", closeDetail);

// 點彈窗外的暗色區域也能關閉，手機上比按右上角的小叉叉好按。
overlay.addEventListener("click", (ev) => {
  if (ev.target === overlay) closeDetail();
});

addRequirementForm.addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const textarea = addRequirementForm.elements.content;
  const content = textarea.value.trim();
  if (!content || currentCardId === null) return;

  const res = await fetch(`/api/cards/${currentCardId}/requirements`, {
    method: "POST",
    body: new URLSearchParams({ content }),
  });
  if (res.ok) {
    textarea.value = "";
    const detail = await (await fetch(`/api/cards/${currentCardId}`)).json();
    renderRequirements(detail.requirements);
    loadCards();
  }
});

// ---------------------------------------------------- 內建相機（含對準輔助線）
// 為什麼要自己做相機：手機原生的 <input capture> 相機是系統 UI，網頁無法在上面畫
// 輔助線。改用 getUserMedia 把即時影像放進頁面，就能疊上名片外框讓使用者對準。
// 限制：getUserMedia 只在安全來源（HTTPS 或 localhost）可用，區網用 http:// 連進來
// 時瀏覽器會擋掉。因此按鈕預設隱藏，偵測到能用才顯示，否則沿用原生相機。
const cameraOverlay = document.getElementById("camera-overlay");
const cameraVideo = document.getElementById("camera-video");
const cameraStatus = document.getElementById("camera-status");
const openCameraBtn = document.getElementById("open-camera-btn");
let cameraStream = null;
let facingMode = "environment";

function cameraSupported() {
  return Boolean(navigator.mediaDevices && navigator.mediaDevices.getUserMedia);
}

if (cameraSupported()) {
  openCameraBtn.classList.remove("hidden");
}

openCameraBtn.addEventListener("click", () => startCamera());

async function startCamera() {
  cameraOverlay.classList.remove("hidden");
  cameraStatus.textContent = "啟動相機中...";
  cameraStatus.className = "status";

  try {
    stopCamera();
    cameraStream = await navigator.mediaDevices.getUserMedia({
      // 要求較高解析度，名片上的小字才辨識得出來
      video: { facingMode, width: { ideal: 1920 }, height: { ideal: 1080 } },
      audio: false,
    });
    cameraVideo.srcObject = cameraStream;
    await cameraVideo.play();
    cameraStatus.textContent = "";
  } catch (err) {
    // 最常見的是「非 HTTPS」或使用者拒絕授權，兩者都退回原生相機即可。
    cameraStatus.textContent =
      "無法開啟相機（需 HTTPS 或已授權），請改用上方的拍照欄位";
    cameraStatus.className = "status err";
  }
}

function stopCamera() {
  if (cameraStream) {
    cameraStream.getTracks().forEach((track) => track.stop());
    cameraStream = null;
  }
}

function closeCamera() {
  stopCamera();
  cameraOverlay.classList.add("hidden");
}

document.getElementById("camera-cancel").addEventListener("click", closeCamera);

document.getElementById("camera-switch").addEventListener("click", () => {
  facingMode = facingMode === "environment" ? "user" : "environment";
  startCamera();
});

document.getElementById("camera-shoot").addEventListener("click", () => {
  if (!cameraStream) return;

  // 以影片的原始解析度截圖，不受畫面上縮放顯示的影響，保留最多細節給 OCR。
  const canvas = document.createElement("canvas");
  canvas.width = cameraVideo.videoWidth;
  canvas.height = cameraVideo.videoHeight;
  canvas.getContext("2d").drawImage(cameraVideo, 0, 0, canvas.width, canvas.height);

  canvas.toBlob(async (blob) => {
    if (!blob) return;
    closeCamera();

    const file = new File([blob], "card.jpg", { type: "image/jpeg" });
    // 把拍到的檔案塞回原本的 file input，後續送出表單的流程完全共用。
    const transfer = new DataTransfer();
    transfer.items.add(file);
    photoInput.files = transfer.files;

    photoPreview.src = URL.createObjectURL(blob);
    photoPreview.classList.remove("hidden");
    photoPlaceholder.classList.add("hidden");
    photoIcon.classList.add("hidden");
    await runAutoRecognition(file);
  }, "image/jpeg", 0.92);
});

// 離開頁面時確實關掉鏡頭，避免相機指示燈一直亮著
window.addEventListener("pagehide", stopCamera);

// ---------------------------------------------------- 初始載入
loadCards();
