// Builds the standalone viewer of an exported Course into one HTML file (dist-export/export.html):
// every script, stylesheet, font and image inline, so the file opens offline from disk. The server fills <!--CF_COURSE-->.
import fs from "node:fs";
import path from "node:path";
import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig, type Plugin } from "vite";

const out = path.resolve(__dirname, "dist-export");
// After the write, when Vite has finished rewriting its chunks: inline each script and stylesheet, then drop the files.
const inline: Plugin = {
  name: "inline-everything",
  closeBundle() {
    const file = path.join(out, "export.html");
    const html = fs.readFileSync(file, "utf8")
      .replace(/<script[^>]*src="\/([^"]+)"[^>]*><\/script>/g, (_, f) =>
        `<script type="module">${fs.readFileSync(path.join(out, f), "utf8").replace(/<\/script/gi, "<\\/script")}</script>`)
      .replace(/<link rel="stylesheet"[^>]*href="\/([^"]+)"[^>]*>/g, (_, f) => `<style>${fs.readFileSync(path.join(out, f), "utf8")}</style>`);
    fs.writeFileSync(file, html);
    fs.rmSync(path.join(out, "assets"), { recursive: true, force: true });
  },
};

export default defineConfig({
  plugins: [react(), tailwindcss(), inline],
  resolve: { alias: { "@": path.resolve(__dirname, "src") } },
  publicDir: false,
  build: {
    outDir: out, emptyOutDir: true, cssCodeSplit: false, assetsInlineLimit: () => true, chunkSizeWarningLimit: 100_000,
    rollupOptions: { input: "export.html", output: { inlineDynamicImports: true } },
  },
});
