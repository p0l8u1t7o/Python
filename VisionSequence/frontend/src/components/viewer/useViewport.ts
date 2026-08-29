/**
 * 視角（平移／縮放）。
 *
 * 座標轉換公式（scale 為「螢幕 CSS px / 影像 px」）：
 *   screenX = imageX * scale + tx
 *   imageX  = (screenX - tx) / scale
 * 螢幕座標以 canvas 左上角為原點、單位 CSS px（devicePixelRatio 只在繪圖時乘上，不進入視角）。
 *
 * 視角放在 useRef 而不是 useState：拖曳／滾輪每秒可能觸發上百次，若走 React state
 * 每次都會 re-render 整個元件樹；改為直接改 ref 並用 requestAnimationFrame 合併重繪，
 * 4K 影像也能維持 60fps。需要顯示在 UI 的數值（比例 %）由呼叫端透過 DOM ref 直接更新。
 */
import { useRef } from 'react'

export interface Viewport {
  scale: number
  tx: number
  ty: number
}

export const MIN_SCALE = 0.05
export const MAX_SCALE = 64

export function clampScale(s: number): number {
  return Math.min(MAX_SCALE, Math.max(MIN_SCALE, s))
}

export function toImage(vp: Viewport, sx: number, sy: number): [number, number] {
  return [(sx - vp.tx) / vp.scale, (sy - vp.ty) / vp.scale]
}

export function toScreen(vp: Viewport, ix: number, iy: number): [number, number] {
  return [ix * vp.scale + vp.tx, iy * vp.scale + vp.ty]
}

/** 適合視窗：整張影像置中、四周留 padding */
export function fitViewport(
  viewW: number,
  viewH: number,
  imgW: number,
  imgH: number,
  padding = 16,
): Viewport {
  if (imgW <= 0 || imgH <= 0 || viewW <= 0 || viewH <= 0) return { scale: 1, tx: 0, ty: 0 }
  const scale = clampScale(
    Math.min((viewW - padding * 2) / imgW, (viewH - padding * 2) / imgH),
  )
  return {
    scale,
    tx: (viewW - imgW * scale) / 2,
    ty: (viewH - imgH * scale) / 2,
  }
}

/** 以螢幕點 (sx, sy) 為中心縮放：該點對應的影像座標在縮放前後不變 */
export function zoomAt(vp: Viewport, sx: number, sy: number, factor: number): Viewport {
  const scale = clampScale(vp.scale * factor)
  if (scale === vp.scale) return vp
  const k = scale / vp.scale
  return { scale, tx: sx - (sx - vp.tx) * k, ty: sy - (sy - vp.ty) * k }
}

/** 設定絕對比例，以視窗中心為基準 */
export function setScaleCentered(vp: Viewport, viewW: number, viewH: number, scale: number): Viewport {
  const target = clampScale(scale)
  return zoomAt(vp, viewW / 2, viewH / 2, target / vp.scale)
}

/** 用 ref 持有視角；回傳 ref 本身，讓事件處理直接讀寫。 */
export function useViewport(initial?: Partial<Viewport>) {
  return useRef<Viewport>({ scale: 1, tx: 0, ty: 0, ...initial })
}
