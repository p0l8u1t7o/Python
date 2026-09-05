/**
 * 畫面截圖：把目前的 DOM 畫成 JPEG（html-to-image 走 SVG foreignObject，瀏覽器看得懂的 CSS 都畫得出來，不需要安全內容也不跳系統選擇器），
 * 縮到最長邊 1600 px、品質 0.8，給支援影像的 LLM 看。只在使用者按下相機圖示時擷取；助手視窗與 toast 不入鏡。
 */
import { toJpeg } from 'html-to-image'

const MAX_SIDE = 1600
const QUALITY = 0.8
const EXCLUDE = ['assistant-dock', 'assistant-toggle', 'toast-stack']

function excluded(node: HTMLElement): boolean {
  const id = node.dataset?.testid
  return Boolean(id && EXCLUDE.includes(id))
}

/** 縮到最長邊 MAX_SIDE（已經夠小就原樣回）。 */
export async function downscale(dataUrl: string, maxSide = MAX_SIDE): Promise<string> {
  const img = new Image()
  img.src = dataUrl
  await new Promise<void>((resolve, reject) => { img.onload = () => resolve(); img.onerror = () => reject(new Error('decode')) })
  const scale = Math.min(1, maxSide / Math.max(img.naturalWidth, img.naturalHeight))
  if (scale >= 1) return dataUrl
  const canvas = document.createElement('canvas')
  canvas.width = Math.round(img.naturalWidth * scale)
  canvas.height = Math.round(img.naturalHeight * scale)
  const ctx = canvas.getContext('2d')
  if (!ctx) return dataUrl
  ctx.drawImage(img, 0, 0, canvas.width, canvas.height)
  return canvas.toDataURL('image/jpeg', QUALITY)
}

/** 擷取整個可見頁面；失敗回 null（不擋提問）。 */
export async function captureScreenshot(): Promise<string | null> {
  if (typeof document === 'undefined') return null
  try {
    const url = await toJpeg(document.body, {
      quality: QUALITY,
      pixelRatio: 1,
      backgroundColor: getComputedStyle(document.body).backgroundColor || '#ffffff',
      skipFonts: true,
      cacheBust: false,
      filter: (node) => !(node instanceof HTMLElement && excluded(node)),
    })
    return await downscale(url)
  } catch {
    return null
  }
}

/** data URL → 純 base64（後端要的形狀）。 */
export function base64Of(dataUrl: string): string {
  const i = dataUrl.indexOf(',')
  return i >= 0 ? dataUrl.slice(i + 1) : dataUrl
}
