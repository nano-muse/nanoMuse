import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

// The relay serves the console at /app/admin/ (api.py mounts nanomuse_cloud/console at
// /app). The build is written straight into the Python package, under fixed names, so the
// relay's URLs stay /app/admin/admin.js and /app/admin/admin.css across deploys; the mount
// answers them with Cache-Control: no-cache, so a deploy reaches the next reload.
// The dev server proxies the API to a running relay (NANOMUSE_RELAY, default 127.0.0.1:8787,
// the relay's own default port).
const relay = (process.env.NANOMUSE_RELAY ?? "127.0.0.1:8787").replace(/^https?:\/\//, "");

export default defineConfig({
  base: "/app/admin/",
  plugins: [react(), tailwindcss()],
  build: {
    outDir: "../nanomuse_cloud/console/admin",
    emptyOutDir: true,
    sourcemap: false,
    rollupOptions: {
      output: {
        entryFileNames: "admin.js",
        chunkFileNames: "admin-[name].js",
        assetFileNames: (info) => (info.names?.some((n) => n.endsWith(".css")) ? "admin.css" : "admin-[name][extname]"),
      },
    },
  },
  server: {
    port: 5174,
    proxy: {
      "/v1": `http://${relay}`,
      "/app/icon.svg": `http://${relay}`,
      "/app/mark.svg": `http://${relay}`,
    },
  },
  test: {
    environment: "node",
    include: ["src/**/*.test.{ts,tsx}"],
  },
});
