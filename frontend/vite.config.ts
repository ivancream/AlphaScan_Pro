import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import path from "path";

export default defineConfig({
  plugins: [tailwindcss(), react()],
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
  // Tauri 開發伺服器預設埠 1420；/api、/ws 轉到 FastAPI :8000，前端可用同源網址
  server: {
    port: 1420,
    strictPort: true,
    host: "localhost",
    proxy: {
      "/api": { target: "http://127.0.0.1:8000", changeOrigin: true },
      "/ws": { target: "ws://127.0.0.1:8000", ws: true },
    },
  },
  // Tauri 要求使用相對路徑
  base: "./",
  build: {
    // Tauri 使用 Chromium，不需要舊瀏覽器 polyfill
    target: ["es2021", "chrome100", "safari13"],
    outDir: "dist",
    minify: !process.env.TAURI_DEBUG ? "esbuild" : false,
    sourcemap: !!process.env.TAURI_DEBUG,
  },
});
