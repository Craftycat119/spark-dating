// Сборка демо COFI в один HTML-файл: node build.mjs <out.html>
// Нужен esbuild (npm i esbuild) и Python для выгрузки данных ботов из app/demo.py.
import { build } from "esbuild";
import { execFileSync } from "node:child_process";
import { readFileSync, writeFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const root = resolve(here, "../..");
const out = process.argv[2] || resolve(here, "cofi-demo.html");

// 1. Данные ботов и опроса берём из бэкенда, чтобы демо не расходилось с приложением
const data = execFileSync("python3", ["-c", `
import json, sys
sys.path.insert(0, ".")
from app import demo, interests
print(json.dumps({
  "bots": [{k: b[k] for k in ("key","name","age","gender","km","likes_you","scenes","goals","interests","bio","replies","fit")} for b in demo.BOTS],
  "guest": {k: v for k, v in demo.GUEST.items() if k != "photo"},
  "fallback_reply": demo.FALLBACK_REPLY,
  "center": demo.CENTER,
  "survey": interests.SURVEY, "genders": interests.GENDERS, "looking_for": interests.LOOKING_FOR,
  "min_interests": interests.MIN_INTERESTS,
}, ensure_ascii=False))
`], { cwd: root, env: { ...process.env, DATA_DIR: resolve(here, ".tmp-data") } }).toString();
writeFileSync(resolve(here, "data.json"), data);

// 2. Бандл: api.js подменяем имитатором, three.js берём из static/vendor
const swap = {
  name: "swap",
  setup(b) {
    b.onResolve({ filter: /^\.\/api\.js$/ }, () => ({ path: resolve(here, "mock-api.js") }));
    b.onResolve({ filter: /^\/static\/vendor\// }, (a) => ({ path: resolve(root, a.path.slice(1)) }));
  },
};
const res = await build({
  entryPoints: [resolve(here, "entry.js")], bundle: true, format: "iife", minify: true,
  write: false, plugins: [swap], target: "es2020", charset: "utf8", logLevel: "warning",
});
const js = res.outputFiles[0].text.replaceAll("</script", "<\\/script");

// 3. Стили: app.css + иконки Phosphor с встроенными шрифтами
const font = (f) => `url(data:font/woff2;base64,${readFileSync(resolve(root, "static/vendor/phosphor", f)).toString("base64")}) format("woff2")`;
const phosphor = ["regular.css", "fill.css"].map((f) =>
  readFileSync(resolve(root, "static/vendor/phosphor", f), "utf8")
    .replace(/url\("\.\/(Phosphor[^"]*\.woff2)"\) format\("woff2"\)/, (_, file) => font(file))).join("\n");
const css = readFileSync(resolve(root, "static/css/app.css"), "utf8");

// 4. Разметка из index.html: фильтры «надутого» материала и контейнеры
const index = readFileSync(resolve(root, "static/index.html"), "utf8");
const svgDefs = index.match(/<svg width="0"[\s\S]*?<\/svg>/)[0];
const themeScript = index.match(/<script>\/\* тема[\s\S]*?<\/script>/)[0];

const html = `<title>COFI демо</title>
<meta name="theme-color" content="#120c09">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Onest:wght@400;500;600;800&family=Pixelify+Sans:wght@500;700&family=Unbounded:wght@600;700&display=swap" rel="stylesheet">
${themeScript.replace('localStorage.getItem("theme")||"dark"', 'localStorage.getItem("theme")||"system"')}
<style>
${phosphor}
${css}
html, body { min-height: 100%; }
</style>
${svgDefs}
<div id="app"></div>
<div class="toast-host" id="toasts" aria-live="polite"></div>
<script>${js}</script>
`;
writeFileSync(out, html);
console.log(`${out}: ${(html.length / 1024).toFixed(0)} КБ`);
