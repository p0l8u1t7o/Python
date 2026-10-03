// 專案共用路徑：CAD 來源資料夾可用環境變數 CAD_SOURCE_DIR 覆寫
import path from "node:path";
import { fileURLToPath } from "node:url";

export const projectRoot = path.resolve(
  path.dirname(fileURLToPath(import.meta.url)),
  "../..",
);
export const cadSource = path.resolve(
  projectRoot,
  process.env.CAD_SOURCE_DIR || "cad-source",
);
