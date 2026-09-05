/**
 * build 後預壓縮 dist/assets 的文字檔（.js .css .svg .json .txt）成 .gz 與 .br：whitenoise 看到同名壓縮檔會直接送，
 * 客戶端電腦第一次載入從 2.7 MB 降到約 0.8 MB，伺服端不必在請求時壓。用 Node 內建 zlib，不加套件。
 *   node scripts/compress.mjs [dist 路徑]
 */
import { readdirSync, readFileSync, statSync, writeFileSync } from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import zlib from 'node:zlib'

const here = path.dirname(fileURLToPath(import.meta.url))
const dist = path.resolve(process.argv[2] ?? path.join(here, '..', 'dist'))
const TEXT = new Set(['.js', '.css', '.svg', '.json', '.txt', '.html'])
const MIN_BYTES = 1024

function walk(dir) {
  const out = []
  for (const name of readdirSync(dir)) {
    const full = path.join(dir, name)
    if (statSync(full).isDirectory()) out.push(...walk(full))
    else out.push(full)
  }
  return out
}

let files = 0
let before = 0
let after = 0
for (const file of walk(dist)) {
  const ext = path.extname(file)
  if (!TEXT.has(ext) || file.endsWith('.map')) continue
  const data = readFileSync(file)
  if (data.length < MIN_BYTES) continue
  const gz = zlib.gzipSync(data, { level: 9 })
  const br = zlib.brotliCompressSync(data, { params: { [zlib.constants.BROTLI_PARAM_MODE]: zlib.constants.BROTLI_MODE_TEXT, [zlib.constants.BROTLI_PARAM_QUALITY]: 11, [zlib.constants.BROTLI_PARAM_SIZE_HINT]: data.length } })
  writeFileSync(file + '.gz', gz)
  writeFileSync(file + '.br', br)
  files += 1
  before += data.length
  after += br.length
}
console.log(`compressed ${files} files: ${(before / 1048576).toFixed(2)} MB -> ${(after / 1048576).toFixed(2)} MB (brotli)`)
