import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  server: {
    // 綁 0.0.0.0，讓同區網的手機／平板可以連進來測試（API 與 media 仍由 Vite 代理到本機 Django）
    host: true,
    port: 5174,
    strictPort: true,
    proxy: {
      '/api': 'http://127.0.0.1:8001',
      '/media': 'http://127.0.0.1:8001',
    },
  },
});
