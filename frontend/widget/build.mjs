import * as esbuild from "esbuild";
import { readFileSync } from "fs";

const result = await esbuild.build({
  entryPoints: ["frontend/widget/widget.src.js"],
  bundle: true,
  minify: true,
  sourcemap: true,
  outfile: "frontend/widget/dist/widget.js",
  target: ["es2017"],
  platform: "browser",
  format: "iife",
  metafile: true,
});

const { outputs } = result.metafile;
const [outFile] = Object.keys(outputs);
const sizeKb = Math.round(outputs[outFile].bytes / 1024 * 10) / 10;

console.log(`\n✅ Widget build tamamlandı!`);
console.log(`   dist/widget.js  ${sizeKb}kb`);
console.log(`\n📋 Entegrasyon kodu:`);
console.log(`   <script src="/widget/widget.js" data-key="ngssai_YOUR_KEY"></script>\n`);
