/**
 * 自動優化（輪廓貼邊）：純前端 JS，對齊 Temp/WebTraining.md §8 的做法——
 * 在降到最長邊 1280 的灰階梯度圖上，沿各頂點法線 ±R 搜尋梯度最大處（帶位移懲罰），
 * 迭代 3 次、每次平滑，最後 Douglas–Peucker 簡化到 ≤120 點。不自動儲存，呼叫端自己進歷史堆疊。
 */

export interface GradientMap {
  data: Float32Array
  width: number
  height: number
  /** 梯度圖尺寸相對原圖的縮放（gradient = original * scale） */
  scale: number
}

/** 從 <img>（已載入完成）建立灰階梯度圖。 */
export function buildGradientMap(image: HTMLImageElement, imageWidth: number, imageHeight: number): GradientMap {
  const scale = Math.min(1, 1280 / Math.max(imageWidth, imageHeight))
  const w = Math.max(2, Math.round(imageWidth * scale))
  const h = Math.max(2, Math.round(imageHeight * scale))
  const canvas = document.createElement('canvas')
  canvas.width = w
  canvas.height = h
  const ctx = canvas.getContext('2d', { willReadFrequently: true })!
  ctx.drawImage(image, 0, 0, w, h)
  const rgba = ctx.getImageData(0, 0, w, h).data
  const gray = new Float32Array(w * h)
  for (let i = 0; i < w * h; i++) gray[i] = 0.299 * rgba[i * 4] + 0.587 * rgba[i * 4 + 1] + 0.114 * rgba[i * 4 + 2]
  const mag = new Float32Array(w * h)
  for (let y = 1; y < h - 1; y++) {
    for (let x = 1; x < w - 1; x++) {
      const gx = gray[y * w + x + 1] - gray[y * w + x - 1]
      const gy = gray[(y + 1) * w + x] - gray[(y - 1) * w + x]
      mag[y * w + x] = Math.hypot(gx, gy)
    }
  }
  return { data: mag, width: w, height: h, scale }
}

function sample(map: GradientMap, x: number, y: number): number {
  const xi = Math.round(x)
  const yi = Math.round(y)
  if (xi < 0 || yi < 0 || xi >= map.width || yi >= map.height) return 0
  return map.data[yi * map.width + xi]
}

/** Douglas–Peucker（點數上限另外截斷）。 */
function simplify(points: [number, number][], epsilon: number): [number, number][] {
  if (points.length <= 3) return points
  const keep = new Array(points.length).fill(false)
  keep[0] = keep[points.length - 1] = true
  const stack: [number, number][] = [[0, points.length - 1]]
  while (stack.length) {
    const [a, b] = stack.pop()!
    const [ax, ay] = points[a]
    const [bx, by] = points[b]
    const len = Math.hypot(bx - ax, by - ay) || 1
    let best = -1
    let bestDist = 0
    for (let i = a + 1; i < b; i++) {
      const d = Math.abs((points[i][0] - ax) * (by - ay) - (points[i][1] - ay) * (bx - ax)) / len
      if (d > bestDist) {
        bestDist = d
        best = i
      }
    }
    if (best >= 0 && bestDist > epsilon) {
      keep[best] = true
      stack.push([a, best], [best, b])
    }
  }
  return points.filter((_, i) => keep[i])
}

/**
 * 貼邊優化：輸入／輸出皆為原圖像素座標的封閉 polygon。
 * radius = 法線搜尋半徑（原圖像素）；penalty = 每像素位移懲罰。
 */
export function optimizePolygon(points: [number, number][], map: GradientMap, radius = 24, penalty = 0.6): [number, number][] {
  if (points.length < 3) return points
  let pts = points.map(([x, y]) => [x * map.scale, y * map.scale] as [number, number])
  const r = Math.max(3, radius * map.scale)
  for (let iter = 0; iter < 3; iter++) {
    const n = pts.length
    const moved: [number, number][] = pts.map(([x, y], i) => {
      const [px, py] = pts[(i - 1 + n) % n]
      const [nx, ny] = pts[(i + 1) % n]
      // 法線 = 前後點連線的垂直方向
      let tx = nx - px
      let ty = ny - py
      const tl = Math.hypot(tx, ty) || 1
      tx /= tl
      ty /= tl
      const normalX = -ty
      const normalY = tx
      let bestScore = -Infinity
      let bestT = 0
      for (let t = -r; t <= r; t += 1) {
        const score = sample(map, x + normalX * t, y + normalY * t) - penalty * Math.abs(t)
        if (score > bestScore) {
          bestScore = score
          bestT = t
        }
      }
      return [x + normalX * bestT, y + normalY * bestT]
    })
    // 平滑（保形的 3 點移動平均，權重 1:2:1）
    pts = moved.map(([x, y], i) => {
      const [px, py] = moved[(i - 1 + n) % n]
      const [nx, ny] = moved[(i + 1) % n]
      return [(px + 2 * x + nx) / 4, (py + 2 * y + ny) / 4] as [number, number]
    })
  }
  let out = simplify(pts, 1.2)
  if (out.length > 120) out = out.filter((_, i) => i % Math.ceil(out.length / 120) === 0)
  return out.map(([x, y]) => [x / map.scale, y / map.scale] as [number, number])
}
