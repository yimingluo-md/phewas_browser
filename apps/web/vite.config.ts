import { defineConfig } from "vite";

// `npm run dev` proxies /api to a running phewas-server (set PHEWAS_API to its origin).
export default defineConfig({
  server: {
    proxy: { "/api": process.env.PHEWAS_API ?? "http://127.0.0.1:8555" },
  },
  build: {
    outDir: "dist",
    sourcemap: false,
    chunkSizeWarningLimit: 4500,
  },
});
