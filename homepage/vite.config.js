import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      "/api/auth": {
        target: process.env.VITE_AUTH_PROXY_TARGET || "http://127.0.0.1:9010",
        changeOrigin: false,
      },
    },
  },
  build: {
    sourcemap: true,
  },
});
