import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// base: './' is required — the built page is loaded from
// chrome-extension://<id>/popup/dist/index.html, not from the origin root,
// so asset paths must be relative or they 404.
export default defineConfig({
  plugins: [react()],
  base: "./",
  build: {
    outDir: "dist",
  },
});
