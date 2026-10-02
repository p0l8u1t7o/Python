import { defineConfig } from "vite";
import fs from "node:fs";
import path from "node:path";
import { spawn, execFileSync } from "node:child_process";
import { pipeline } from "node:stream/promises";
import { cadSource } from "./scripts/lib/paths.js";
const base = process.cwd();
const source = cadSource;
const cache = path.join(base, ".cache", "imports");
export function safePath(root, relative) {
  if (
    typeof relative !== "string" ||
    !relative ||
    relative.includes("\0") ||
    relative.includes(":") ||
    path.isAbsolute(relative)
  )
    throw new Error("無效檔案路徑");
  const resolved = path.resolve(root, relative);
  const rel = path.relative(root, resolved);
  if (rel.startsWith("..") || path.isAbsolute(rel))
    throw new Error("不可存取指定目錄以外的檔案");
  return resolved;
}
function available() {
  if (process.platform !== "win32") return false;
  try {
    execFileSync("reg.exe", ["query", "HKCR\\SldWorks.Application\\CLSID"], {
      stdio: "ignore",
      windowsHide: true,
    });
    return true;
  } catch {
    return false;
  }
}
async function readJSON(req) {
  let body = "";
  for await (const chunk of req) {
    body += chunk;
    if (body.length > 4096) throw new Error("請求過大");
  }
  return JSON.parse(body);
}
export function localCadPlugin() {
  return {
    name: "local-cad-service",
    configureServer(server) {
      server.middlewares.use(async (req, res, next) => {
        if (!req.url?.startsWith("/api/")) return next();
        const origin = req.headers.origin;
        if (origin && !/^http:\/\/(127\.0\.0\.1|localhost):\d+$/.test(origin)) {
          res.statusCode = 403;
          res.end("僅限本機工作台存取");
          return;
        }
        try {
          const url = new URL(req.url, "http://localhost");
          if (url.pathname === "/api/converter" && req.method === "GET") {
            res.setHeader("Content-Type", "application/json");
            res.end(
              JSON.stringify({
                available: available(),
                provider: "SolidWorks COM",
                note: "需已安裝並授權 SolidWorks，且引用零件完整",
              }),
            );
            return;
          }
          if (url.pathname === "/api/source" && req.method === "GET") {
            const file = safePath(source, url.searchParams.get("path"));
            if (!/\.(step|stp|igs|iges|brep|stl|obj|glb)$/i.test(file))
              throw new Error("檔案格式不支援");
            // Resolve symlinks as well as textual traversal.
            safePath(
              fs.realpathSync(source),
              path.relative(fs.realpathSync(source), fs.realpathSync(file)),
            );
            res.setHeader("Content-Type", "application/octet-stream");
            res.setHeader("Content-Length", fs.statSync(file).size);
            await pipeline(fs.createReadStream(file), res);
            return;
          }
          const upload = url.pathname.match(
            /^\/api\/uploads\/([a-f0-9-]{36})\/(.+)$/,
          );
          if (upload && req.method === "PUT") {
            const root = path.join(cache, upload[1]);
            const file = safePath(root, decodeURIComponent(upload[2]));
            if (!/\.(sldasm|sldprt|step|stp|igs|iges|x_t|dwg|pdf)$/i.test(file))
              throw new Error("不支援的上傳格式");
            if (Number(req.headers["content-length"]) > 200 * 1024 * 1024)
              throw new Error("單檔超過 200 MB");
            fs.mkdirSync(path.dirname(file), { recursive: true });
            let size = 0;
            req.on("data", (chunk) => {
              size += chunk.length;
              if (size > 200 * 1024 * 1024)
                req.destroy(new Error("單檔超過 200 MB"));
            });
            await pipeline(req, fs.createWriteStream(file, { flags: "wx" }));
            res.end("ok");
            return;
          }
          const convert = url.pathname.match(
            /^\/api\/convert\/([a-f0-9-]{36})$/,
          );
          if (convert && req.method === "POST") {
            if (!available()) {
              res.statusCode = 503;
              res.end("未安裝 SolidWorks，請先輸出 STEP。");
              return;
            }
            const body = await readJSON(req);
            const file = safePath(path.join(cache, convert[1]), body.path);
            if (!/\.(sldasm|sldprt)$/i.test(file))
              throw new Error("僅能轉換 SolidWorks 組合件或零件");
            const output = file + ".step";
            await new Promise((resolve, reject) => {
              const child = spawn(
                "powershell.exe",
                [
                  "-NoProfile",
                  "-NonInteractive",
                  "-ExecutionPolicy",
                  "Bypass",
                  "-File",
                  path.join(base, "scripts", "cad", "convert-solidworks.ps1"),
                  "-InputPath",
                  file,
                  "-OutputPath",
                  output,
                ],
                { windowsHide: true },
              );
              let log = "";
              child.stdout.on("data", (c) => (log += c));
              child.stderr.on("data", (c) => (log += c));
              const timer = setTimeout(() => {
                child.kill();
                reject(
                  new Error(
                    "SolidWorks 轉換超時（180 秒），請在 CAD 軟體檢查引用與模型狀態。",
                  ),
                );
              }, 180000);
              child.on("error", (e) => {
                clearTimeout(timer);
                reject(e);
              });
              child.on("exit", (code) => {
                clearTimeout(timer);
                code === 0
                  ? resolve()
                  : reject(
                      new Error("SolidWorks 轉換失敗：" + log.slice(-1500)),
                    );
              });
            });
            res.setHeader("Content-Type", "application/octet-stream");
            await pipeline(fs.createReadStream(output), res);
            return;
          }
          res.statusCode = 404;
          res.end("找不到 API");
        } catch (e) {
          if (!res.headersSent) {
            res.statusCode = 400;
            res.end(e.message);
          } else res.destroy();
        }
      });
    },
  };
}
export default defineConfig({
  plugins: [localCadPlugin()],
  server: {
    host: "127.0.0.1",
    port: 6001,
    strictPort: true,
    fs: { strict: true },
  },
  build: {
    rollupOptions: {
      output: {
        manualChunks: {
          three: [
            "three",
            "three/addons/controls/OrbitControls.js",
            "three/addons/loaders/GLTFLoader.js",
          ],
        },
      },
    },
  },
});
