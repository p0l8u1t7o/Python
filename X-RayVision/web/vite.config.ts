import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// 開發時 /api 轉送到本機服務；正式版由後端直接提供 dist 靜態檔
export default defineConfig({
  plugins: [react()],
  base: "./",
  server: { port: 5173, proxy: { "/api": "http://127.0.0.1:8600" } },
  build: { outDir: "dist", emptyOutDir: true, chunkSizeWarningLimit: 1024 },
});
