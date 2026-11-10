import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { viteSingleFile } from "vite-plugin-singlefile";

// One self-contained index.html (scripts and styles inlined), so the Qt app can load it
// from disk with no server, and the web trial can serve it as one file.
export default defineConfig({
  plugins: [react(), viteSingleFile()],
  base: "./",
  build: {
    outDir: "../src/expconfig/diagram_dist",
    emptyOutDir: true,
  },
  server: {
    // `npm run dev` against the web trial server (uv run --extra web expconfig-web --demo)
    proxy: { "/api": "http://127.0.0.1:8780" },
  },
});
