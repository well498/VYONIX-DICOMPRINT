// Empacota a interface web (React + TypeScript) em web/dist com esbuild.
// Sem CDN nem recursos externos: tudo é servido pelo próprio VYONIX Core (CSP 'self').
import { build } from "esbuild";
import { createHash } from "node:crypto";
import { mkdirSync, readFileSync, rmSync, writeFileSync, copyFileSync } from "node:fs";

const out = "dist";
rmSync(out, { recursive: true, force: true });
mkdirSync(`${out}/assets`, { recursive: true });
const r = await build({
  entryPoints: ["src/main.tsx"], bundle: true, minify: true, sourcemap: false, format: "esm",
  target: ["es2022"], jsx: "automatic", write: false, outdir: `${out}/assets`,
  define: { "process.env.NODE_ENV": '"production"' }, logLevel: "warning",
});
const names = {};
for (const f of r.outputFiles) {
  const ext = f.path.endsWith(".css") ? "css" : "js";
  const h = createHash("sha256").update(f.contents).digest("hex").slice(0, 10);
  const name = `app-${h}.${ext}`;
  writeFileSync(`${out}/assets/${name}`, f.contents);
  names[ext] = name;
}
const html = readFileSync("src/index.html", "utf8")
  .replace("%CSS%", names.css ? `<link rel="stylesheet" href="/assets/${names.css}">` : "")
  .replace("%JS%", `<script type="module" src="/assets/${names.js}"></script>`);
writeFileSync(`${out}/index.html`, html);
copyFileSync("src/favicon.svg", `${out}/favicon.svg`);
console.log("web/dist:", names);
