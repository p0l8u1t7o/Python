/** vitest 共用前置：jest-dom 斷言、i18n 初始化（繁中）、瀏覽器 API 補丁（jsdom 缺的）。 */
import '@testing-library/jest-dom/vitest'
import '@/i18n'

// jsdom 沒有 ResizeObserver / matchMedia / scrollIntoView：畫布與 viewer 元件會用到
class RO {
  observe() {}
  unobserve() {}
  disconnect() {}
}
;(globalThis as unknown as { ResizeObserver: typeof RO }).ResizeObserver = RO
if (!window.matchMedia) {
  window.matchMedia = (query: string) => ({
    matches: false, media: query, onchange: null,
    addListener: () => {}, removeListener: () => {}, addEventListener: () => {}, removeEventListener: () => {}, dispatchEvent: () => false,
  }) as unknown as MediaQueryList
}
Element.prototype.scrollIntoView = Element.prototype.scrollIntoView ?? (() => {})

// jsdom 沒有 DOMMatrixReadOnly：React Flow 重量把手位置（updateNodeInternals）時用它讀節點的 transform 縮放，給一個 m22=1 的最小替身即可
if (!('DOMMatrixReadOnly' in window)) {
  class DOMMatrixStub {
    m22 = 1
    constructor(_transform?: string) {}
  }
  ;(window as unknown as { DOMMatrixReadOnly: typeof DOMMatrixStub }).DOMMatrixReadOnly = DOMMatrixStub
}
