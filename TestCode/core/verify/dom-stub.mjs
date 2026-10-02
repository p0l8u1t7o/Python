// Node 端的最小 DOM：讓建立 CanvasTexture（文字貼圖、標籤）的模組能在檢查程式中載入。
// 2D context 的任何方法都是空操作；取值得到可再呼叫、可轉成 0 的物件，避免各專案寫法不同而報錯。
// 網頁上的幾何因此與瀏覽器相同（貼圖內容是空的，不影響幾何檢查）。
const anything = () => new Proxy(function () { }, {
  get: (_, k) => k === Symbol.toPrimitive ? () => 0 : k === 'length' ? 0 : k === Symbol.iterator ? function* () { } : anything(),
  apply: () => anything(),
  set: () => true,
});

function canvas() {
  const ctx = new Proxy({}, {
    get: (o, k) => k in o ? o[k] : (k === 'canvas' ? c : anything()),
    set: (o, k, v) => { o[k] = v; return true; },
  });
  const c = { width: 300, height: 150, style: {}, getContext: () => ctx, toDataURL: () => 'data:,', addEventListener() { }, removeEventListener() { } };
  return c;
}

if (typeof globalThis.document === 'undefined') {
  globalThis.document = {
    createElement: tag => tag === 'canvas' ? canvas() : { style: {}, appendChild() { }, setAttribute() { }, addEventListener() { }, classList: { add() { }, remove() { }, toggle() { } } },
    createElementNS: (_, tag) => canvas(),
    getElementById: () => null, querySelector: () => null, querySelectorAll: () => [],
    head: { append() { }, appendChild() { } }, body: { append() { }, appendChild() { } },
  };
}
