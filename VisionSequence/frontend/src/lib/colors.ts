/**
 * DL 教導的類別色（單一來源；DlPage 與 ShapeWorkspace 共用）。
 * 固定色相表（參考 VisionStereo 標註工具的做法）：前 10 類對比足夠，超過 10 類自動偏移色相，
 * 不需使用者挑色；同一顏色同時用在畫布輪廓、縮圖、類別按鈕、曲線。
 */
const HUES = [230, 12, 152, 38, 280, 190, 330, 96, 20, 258]

export function classColorAt(index: number, alpha = 1): string {
  if (index < 0) return alpha === 1 ? '#94a3b8' : `rgb(148 163 184 / ${alpha})`
  const h = HUES[index % HUES.length] + Math.floor(index / HUES.length) * 17
  // 注意：hsl() 字串不能再用 '99'/'cc' 這種 hex 後綴拼 alpha，要用斜線語法
  return alpha === 1 ? `hsl(${h} 72% 48%)` : `hsl(${h} 72% 48% / ${alpha})`
}

export function classColor(classes: string[], label: string, alpha = 1): string {
  return classColorAt(classes.indexOf(label), alpha)
}

/** 訓練曲線用色（取前幾個類別色相，飽和度略降）。 */
export const CURVE_COLORS = [0, 2, 3, 1, 4, 5].map((i) => `hsl(${HUES[i]} 60% 45%)`)
