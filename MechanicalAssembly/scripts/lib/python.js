// 解析專案虛擬環境（.venv）的 Python；沒有 .venv 時退回系統 python。
// 直接執行時把其餘參數轉交給該 Python：node scripts/lib/python.js <script.py> [args]
import fs from "node:fs";
import path from "node:path";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import { projectRoot } from "./paths.js";

const venvPython = path.join(
  projectRoot,
  ".venv",
  process.platform === "win32" ? "Scripts/python.exe" : "bin/python",
);
export const python = fs.existsSync(venvPython) ? venvPython : "python";

if (
  process.argv[1] &&
  path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)
) {
  const result = spawnSync(python, process.argv.slice(2), { stdio: "inherit" });
  if (result.error) throw result.error;
  process.exit(result.status ?? 1);
}
