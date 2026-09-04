import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// ONE self-contained IIFE bundle written into web/assets/ and COMMITTED.
//
// Committing the build output is deliberate. `render.py` stays pure Python and
// `tools/check.sh` stays hermetic, so the site can be rendered and published on
// a host with no Node at all -- which is what keeps the two failure modes that
// have cost this fleet board-days (a broken `npm ci`, a wrong Node major) out
// of the path that produces the site. `tools/check.sh` verifies that the
// committed bundle matches its source hash rather than rebuilding it.
export default defineConfig({
  plugins: [react()],
  // LIB MODE DOES NOT SUBSTITUTE THIS AND REACT CHECKS IT AT RUNTIME. Without
  // it the "production" build ships React's development build -- 657 kB raw
  // against 205 kB, with every warning path, the dev-only prop validation and
  // the profiler hooks included, on every page of the site.
  define: { "process.env.NODE_ENV": JSON.stringify("production") },
  build: {
    lib: {
      entry: "src/main.tsx",
      formats: ["iife"],
      name: "WhoCitedIt",
      fileName: () => "islands.js",
    },
    outDir: "../assets",
    emptyOutDir: false,
    cssCodeSplit: false,
    minify: "esbuild",
    target: "es2020",
  },
});
