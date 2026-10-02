// 展示影片：以虛擬時鐘逐格算圖（不受即時效能影響、不掉格），GPU（NVENC）編碼成 MP4，
// 並逐格檢查亮度，確認沒有閃爍格與黑畫面。
// 需先以 `npm.cmd run dev` 啟動工作台。
// 用法：node scripts/media/render-showcase.mjs --station=202401-BA00 --out=<mp4> [--ffmpeg=<ffmpeg.exe>] [--theme=dark]
import fs from "node:fs";
import path from "node:path";
import { spawn } from "node:child_process";
import { chromium } from "playwright";

const arg = (name, fallback) =>
  process.argv.find((a) => a.startsWith(`--${name}=`))?.slice(name.length + 3) ?? fallback;
const station = arg("station", "202401-BA00");
const out = path.resolve(arg("out", `output/${station}_1080p30.mp4`));
const ffmpeg = arg("ffmpeg", path.resolve("../TestCode/MilitaryGradePC/tools/bin/ffmpeg.exe"));
const url = arg("url", "http://127.0.0.1:6001/");
const theme = arg("theme", "dark");
const stepSeconds = Number(arg("step", "1.6"));
const W = 1920,
  H = 1080,
  FPS = 30;

const ease = (t) => {
  const c = Math.max(0, Math.min(1, t));
  return c * c * (3 - 2 * c);
};
const lerp = (a, b, t) => a + (b - a) * t;
const lerp3 = (a, b, t) => a.map((v, i) => lerp(v, b[i], t));
const deg = (d) => (d * Math.PI) / 180;

fs.mkdirSync(path.dirname(out), { recursive: true });
const browser = await chromium.launch({
  channel: "chrome",
  headless: false,
  args: ["--use-angle=d3d11", "--window-position=-2400,0", "--force-device-scale-factor=1"],
});
const page = await browser.newPage({ viewport: { width: W, height: H }, deviceScaleFactor: 1 });
const errors = [];
page.on("pageerror", (e) => errors.push(e.message));
page.on("console", (m) => m.type() === "error" && errors.push(m.text()));
await page.goto(url);
await page.waitForFunction(() => window.studioAutomation && document.querySelector("#loading").hidden, null, {
  timeout: 300000,
});
const current = await page.evaluate(() => document.documentElement.dataset.theme || "light");
if (current !== theme) await page.click("#theme-toggle");
const info = await page.evaluate((id) => window.studioAutomation.open(id), station);
await page.waitForFunction(() => document.querySelector("#loading").hidden, null, { timeout: 600000 });
const view = await page.evaluate(([w, h]) => window.studioAutomation.begin(w, h), [W, H]);
await page.waitForTimeout(500);
if (view.canvas[0] !== W || view.canvas[1] !== H)
  throw new Error(`算圖畫布 ${view.canvas.join("×")} 不是 ${W}×${H}`);
const steps = await page.evaluate(() => window.studioAutomation.steps());
const bounds = (state, kind, k) =>
  page.evaluate(([s, kd, i]) => window.studioAutomation.bounds(s, kd, i), [state, kind, k]);
const solidBox = await bounds({ mode: "solid" }, "all");
const explodeBox = await bounds({ mode: "explode", explode: 1 }, "all");
const stepBoxes = [];
for (let k = 0; k < steps.length; k++)
  stepBoxes.push(await bounds({ mode: "assemble", progress: k, future: "ghost" }, "step", k));

// 鏡頭：等角方向繞 Z 軸（畫面上方）旋轉；距離依範圍半徑取景
const vfov = deg(view.fov);
const fitDistance = (radius) => (radius / Math.sin(vfov / 2)) * 1.08;
const camera = (target, radius, yaw) => {
  const dir = [Math.sin(deg(45 + yaw)), 0.62, Math.cos(deg(45 + yaw))];
  const n = Math.hypot(...dir);
  const d = fitDistance(radius);
  return { target, position: target.map((v, i) => v + (dir[i] / n) * d) };
};
const minRadius = solidBox.radius * 0.3;

// 時間軸
const segments = [];
const add = (seconds, render) => segments.push({ frames: Math.round(seconds * FPS), render });
const label = `${info.name} · ${info.id}`;
add(4, (t) => ({
  state: { mode: "solid", camera: camera(solidBox.center, solidBox.radius, lerp(-30, -10, t)) },
  overlay: {
    fade: 1 - ease(t / 0.15),
    title: {
      alpha: t < 0.75 ? 1 : 1 - ease((t - 0.75) / 0.25),
      eyebrow: "ASSEMBLY STUDIO · 組裝流程展示",
      main: info.name,
      sub: `${info.id} · ${info.parts} 件零件 · ${info.steps} 個組裝步驟`,
    },
  },
}));
add(3, (t) => ({
  state: { mode: "solid", camera: camera(solidBox.center, solidBox.radius, lerp(-10, 0, t)) },
  overlay: { label: `${label} · 組合完成外觀` },
}));
add(3.5, (t) => {
  const e = ease(t);
  return {
    state: {
      mode: "explode",
      explode: e,
      camera: camera(lerp3(solidBox.center, explodeBox.center, e), lerp(solidBox.radius, explodeBox.radius, e), lerp(0, 15, t)),
    },
    overlay: { label: `${label} · 爆炸圖：依組裝階層分層展開` },
  };
});
add(5, (t) => ({
  state: { mode: "explode", explode: 1, camera: camera(explodeBox.center, explodeBox.radius, lerp(15, 60, ease(t))) },
  overlay: { label: `${label} · 爆炸圖` },
}));
add(2.5, (t) => {
  const e = 1 - ease(t);
  return {
    state: {
      mode: "explode",
      explode: e,
      camera: camera(lerp3(solidBox.center, explodeBox.center, e), lerp(solidBox.radius, explodeBox.radius, e), lerp(60, 35, ease(t))),
    },
    overlay: { label: `${label} · 依推論順序逐步組裝`, snapshot: t === 1 },
  };
});
// 組裝流程：每步前 0.6 秒把鏡頭移到本步範圍
let previous = { center: solidBox.center, radius: solidBox.radius };
steps.forEach((step, k) => {
  const from = previous;
  const box = stepBoxes[k] || solidBox;
  const to = { center: box.center, radius: Math.max(box.radius * 1.05, minRadius) };
  previous = to;
  add(stepSeconds, (t) => {
    const c = ease((t * stepSeconds) / 0.6);
    return {
      state: {
        mode: "assemble",
        future: "ghost",
        // 預組步驟只顯示該預組件，避免近拍時被其他零件的淡影擋住
        outside: "hide",
        progress: k + t * 0.999,
        camera: camera(lerp3(from.center, to.center, c), lerp(from.radius, to.radius, c), 35),
      },
      overlay: {
        label: `${label} · 組裝流程`,
        // 進入組裝或預組情境切換時，以上一步最後一格交叉淡化
        blend:
          k === 0 || steps[k - 1].context !== step.context
            ? 1 - ease((t * stepSeconds) / 0.5)
            : 0,
        snapshot: t === 1,
        caption: {
          index: `步驟 ${String(k + 1).padStart(2, "0")} / ${String(steps.length).padStart(2, "0")}`,
          name: step.name,
          text: step.instruction,
          ratio: (k + t) / steps.length,
        },
      },
    };
  });
});
const last = previous;
add(1.5, (t) => ({
  state: {
    mode: "assemble",
    progress: steps.length,
    camera: camera(lerp3(last.center, solidBox.center, ease(t)), lerp(last.radius, solidBox.radius, ease(t)), 35),
  },
  overlay: { label: `${label} · 組裝完成` },
}));
add(5, (t) => ({
  state: { mode: "solid", camera: camera(solidBox.center, solidBox.radius, lerp(35, 95, ease(t))) },
  overlay: {
    fade: t > 0.88 ? ease((t - 0.88) / 0.12) : 0,
    title: {
      alpha: t < 0.3 ? 0 : ease((t - 0.3) / 0.15),
      eyebrow: "組裝完成",
      main: info.name,
      sub: `${info.steps} 個步驟 · 順序由 CAD 階層與干涉檢查推論，實際工法以工程審核為準`,
    },
  },
}));

const totalFrames = segments.reduce((n, s) => n + s.frames, 0);
const encodeLog = fs.createWriteStream(out.replace(/\.mp4$/i, ".encode.log"));
const encoder = spawn(
  ffmpeg,
  [
    "-hide_banner", "-y",
    "-f", "image2pipe", "-framerate", String(FPS), "-c:v", "mjpeg", "-i", "-",
    "-vf", "scale=in_range=full:out_range=tv,format=yuv420p",
    "-c:v", "h264_nvenc", "-preset", "p7", "-tune", "hq", "-profile:v", "high",
    "-rc", "vbr", "-cq", "18", "-b:v", "0", "-maxrate", "40M", "-bufsize", "80M",
    // 不開 temporal AQ：避免平坦背景的量化在時間上起伏造成亮度跳動
    "-spatial-aq", "1", "-rc-lookahead", "32", "-bf", "3", "-g", String(FPS * 2),
    "-color_range", "tv", "-colorspace", "smpte170m",
    "-movflags", "+faststart",
    out,
  ],
  { stdio: ["pipe", "ignore", "pipe"] },
);
encoder.stderr.pipe(encodeLog);
const encoded = new Promise((resolve, reject) => {
  encoder.on("exit", (code) => (code === 0 ? resolve() : reject(new Error(`ffmpeg 結束碼 ${code}`))));
  encoder.on("error", reject);
});
const shots = [];
let frame = 0;
const started = Date.now();
for (const segment of segments) {
  for (let f = 0; f < segment.frames; f++) {
    const t = segment.frames > 1 ? f / (segment.frames - 1) : 1;
    const { state, overlay } = segment.render(t);
    const data = await page.evaluate(([s, o]) => window.studioAutomation.frame(s, o), [state, overlay]);
    const jpeg = Buffer.from(data.slice(data.indexOf(",") + 1), "base64");
    if (!encoder.stdin.write(jpeg)) await new Promise((r) => encoder.stdin.once("drain", r));
    if (frame % (FPS * 6) === 0) shots.push({ frame, seconds: +(frame / FPS).toFixed(2), label: overlay.label || overlay.title?.main || "" });
    frame++;
    if (frame % 150 === 0)
      console.log(`${frame}/${totalFrames} frames · ${((Date.now() - started) / 1000).toFixed(0)} s`);
  }
}
encoder.stdin.end();
await encoded;
await page.evaluate(() => window.studioAutomation.end());
await browser.close();
console.log(`encoded ${frame} frames → ${out}`);

// ---- 品質檢查：逐格亮度差，找出單格閃爍與黑畫面 ----
const probe = spawn(ffmpeg, ["-hide_banner", "-loglevel", "error", "-i", out, "-vf", "scale=192:108,format=gray", "-f", "rawvideo", "-"]);
const chunks = [];
probe.stdout.on("data", (c) => chunks.push(c));
await new Promise((r, j) => probe.on("exit", (code) => (code === 0 ? r() : j(new Error("解碼失敗")))));
const raw = Buffer.concat(chunks);
const size = 192 * 108;
const count = Math.floor(raw.length / size);
const mean = [],
  diff = [];
for (let i = 0; i < count; i++) {
  let s = 0;
  for (let p = 0; p < size; p++) s += raw[i * size + p];
  mean.push(s / size);
}
const mad = (a, b) => {
  let s = 0;
  for (let p = 0; p < size; p++) s += Math.abs(raw[a * size + p] - raw[b * size + p]);
  return s / size;
};
for (let i = 1; i < count; i++) diff.push(mad(i - 1, i));
const flicker = [];
for (let i = 1; i < count - 1; i++) {
  const d1 = diff[i - 1],
    d2 = diff[i],
    d0 = mad(i - 1, i + 1);
  // 單格閃爍：前後兩格幾乎相同，中間這格卻和兩邊都差很多
  if (d1 > 3 && d2 > 3 && d0 < 0.35 * Math.min(d1, d2)) flicker.push({ frame: i, d1: +d1.toFixed(2), d2: +d2.toFixed(2), d0: +d0.toFixed(2) });
}
const skip = FPS; // 開頭淡入與結尾淡出為刻意的黑畫面
const blackFrames = mean.map((m, i) => [i, m]).filter(([i, m]) => i > skip && i < count - skip && m < 12).map(([i]) => i);
const maxDiff = Math.max(...diff);
const report = {
  project: "MechanicalAssembly",
  station: info.id,
  name: info.name,
  file: out,
  bytes: fs.statSync(out).size,
  resolution: `${W}x${H}`,
  fps: FPS,
  framesRendered: frame,
  framesDecoded: count,
  seconds: +(count / FPS).toFixed(2),
  encoder: "h264_nvenc preset p7 hq, VBR CQ18, spatial AQ, no temporal AQ",
  steps: info.steps,
  stepSeconds,
  decodedWithoutErrors: count === frame,
  temporalAudit: {
    method: "192×108 灰階逐格平均絕對差；單格閃爍＝與前後格差 >3 且前後格彼此差 <35%",
    flickerFrames: flicker,
    blackFrames,
    maxFrameDiff: +maxDiff.toFixed(2),
    // 變化最大的幾格（多為段落切換或步驟開始），供人工複查
    largestChanges: diff
      .map((d, i) => ({ frame: i + 1, seconds: +((i + 1) / FPS).toFixed(2), diff: +d.toFixed(2) }))
      .sort((a, b) => b.diff - a.diff)
      .slice(0, 8),
    meanFrameDiff: +(diff.reduce((a, b) => a + b, 0) / diff.length).toFixed(3),
  },
  shots,
  pageErrors: errors,
  generated: new Date().toISOString(),
};
fs.writeFileSync(out.replace(/\.mp4$/i, "-verification.json"), JSON.stringify(report, null, 1));
// 縮圖總覽：每 6 秒一格
await new Promise((resolve) => {
  const sheet = spawn(ffmpeg, ["-hide_banner", "-loglevel", "error", "-y", "-i", out, "-vf", `fps=1/6,scale=480:-1,tile=4x${Math.ceil(count / FPS / 6 / 4)}`, "-frames:v", "1", "-q:v", "3", out.replace(/_1080p30\.mp4$|\.mp4$/i, "-contact.jpg")]);
  sheet.on("exit", resolve);
});
console.log(JSON.stringify({ frames: count, seconds: report.seconds, flicker: flicker.length, black: blackFrames.length, maxDiff: report.temporalAudit.maxFrameDiff, errors: errors.length }));
