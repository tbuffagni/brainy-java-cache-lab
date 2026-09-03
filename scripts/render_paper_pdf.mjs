#!/usr/bin/env node
import fs from "node:fs/promises";
import path from "node:path";
import { pathToFileURL } from "node:url";
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
const { chromium } = require("playwright");
const { PDFDocument } = require("pdf-lib");
const markedPath = require.resolve("marked");
const { marked } = await import(pathToFileURL(markedPath).href);

const [sourceArg, outputArg, languageArg = "auto"] = process.argv.slice(2);
if (!sourceArg || !outputArg) {
  throw new Error("usage: render_paper_pdf.mjs <paper.md> <output.pdf>");
}

const source = path.resolve(sourceArg);
const output = path.resolve(outputArg);
const markdown = await fs.readFile(source, "utf8");
const footerFont = (await fs.readFile(path.join(path.dirname(source), "fonts", "LibertinusSans-Regular.woff2"))).toString("base64");
if (/\{\{V42_/.test(markdown)) throw new Error("paper contains unfilled placeholders");

marked.setOptions({ gfm: true, breaks: false });
const body = marked.parse(markdown);
const language = languageArg === "auto"
  ? (/^## Abstract$/m.test(markdown) ? "en" : "it")
  : languageArg;
if (!["en", "it"].includes(language)) throw new Error("language must be en, it, or auto");
const titleMatch = markdown.match(/^#\s+(.+)$/m);
const documentTitle = (titleMatch?.[1] || "Beyond Throughput").replace(/[&<>\"]/g, character => ({
  "&": "&amp;", "<": "&lt;", ">": "&gt;", "\"": "&quot;",
})[character]);
const base = pathToFileURL(path.dirname(source) + path.sep).href;
const document = `<!doctype html>
<html lang="${language}"><head><meta charset="utf-8"><base href="${base}">
<title>${documentTitle}</title>
<style>
@font-face { font-family: "Libertinus Serif"; src: url("fonts/LibertinusSerif-Regular.woff2") format("woff2"); font-style: normal; font-weight: 400; }
@font-face { font-family: "Libertinus Serif"; src: url("fonts/LibertinusSerif-Italic.woff2") format("woff2"); font-style: italic; font-weight: 400; }
@font-face { font-family: "Libertinus Serif"; src: url("fonts/LibertinusSerif-Semibold.woff2") format("woff2"); font-style: normal; font-weight: 600; }
@font-face { font-family: "Libertinus Serif"; src: url("fonts/LibertinusSerif-SemiboldItalic.woff2") format("woff2"); font-style: italic; font-weight: 600; }
@font-face { font-family: "Libertinus Serif"; src: url("fonts/LibertinusSerif-Bold.woff2") format("woff2"); font-style: normal; font-weight: 700; }
@font-face { font-family: "Libertinus Serif"; src: url("fonts/LibertinusSerif-BoldItalic.woff2") format("woff2"); font-style: italic; font-weight: 700; }
@font-face { font-family: "Libertinus Sans"; src: url("fonts/LibertinusSans-Regular.woff2") format("woff2"); font-style: normal; font-weight: 400; }
@font-face { font-family: "Libertinus Sans"; src: url("fonts/LibertinusSans-Italic.woff2") format("woff2"); font-style: italic; font-weight: 400; }
@font-face { font-family: "Libertinus Sans"; src: url("fonts/LibertinusSans-Bold.woff2") format("woff2"); font-style: normal; font-weight: 700; }
@font-face { font-family: "Libertinus Mono"; src: url("fonts/LibertinusMono-Regular.woff2") format("woff2"); font-style: normal; font-weight: 400; }
@page { size: A4; margin: 21mm 22mm 23mm; }
html { font-family: "Libertinus Serif", Georgia, serif; color: #202124; font-size: 10.5pt; line-height: 1.4; }
body { margin: 0; }
h1, h2, h3, h4, th { font-family: "Libertinus Sans", Arial, sans-serif; }
h1 { font-size: 21pt; line-height: 1.12; margin: 0 0 8mm; color: #17365d; }
h2 { font-size: 14pt; margin: 8mm 0 3mm; padding-bottom: 1.5mm; border-bottom: 0.5pt solid #b8c2cc; color: #17365d; break-after: avoid; }
h3 { font-size: 11.5pt; margin: 6mm 0 2mm; color: #244a73; break-after: avoid; }
h4 { font-size: 10.5pt; margin: 4mm 0 2mm; break-after: avoid; }
p { margin: 0 0 3mm; orphans: 3; widows: 3; }
ul, ol { margin: 1.5mm 0 3mm 5mm; padding-left: 5mm; }
ul:has(> li:first-child:nth-last-child(-n+6)), ol:has(> li:first-child:nth-last-child(-n+6)) { break-inside: avoid; }
li { margin-bottom: 1mm; }
table { width: 100%; border-collapse: collapse; margin: 2.5mm 0 5mm; font-family: "Libertinus Sans", Arial, sans-serif; font-size: 8.2pt; line-height: 1.25; break-inside: avoid; }
thead { display: table-header-group; }
tr { break-inside: avoid; }
th { background: #eaf0f6; color: #17365d; font-weight: 700; }
th, td { border: 0.45pt solid #aab4be; padding: 1.25mm 1.1mm; vertical-align: top; overflow-wrap: normal; word-break: normal; hyphens: manual; }
code { font-family: "Libertinus Mono", "Libertinus Serif", monospace; font-size: 0.9em; overflow-wrap: anywhere; }
pre { white-space: pre-wrap; border: 0.5pt solid #bbc4cd; background: #f5f7f9; padding: 3mm; break-inside: avoid; }
a { color: #174f85; text-decoration: none; overflow-wrap: anywhere; }
img { display: block; width: 100%; max-height: 175mm; object-fit: contain; margin: 4mm auto 2mm; break-inside: avoid; }
p:has(> img) { break-after: avoid; }
p:has(> strong:first-child) { break-inside: avoid; break-after: avoid; }
h2:last-of-type + ol { font-size: 9.5pt; line-height: 1.3; }
blockquote { margin: 3mm 7mm; border-left: 2pt solid #7b93aa; padding-left: 4mm; color: #394b59; }
</style></head><body>${body}</body></html>`;

await fs.mkdir(path.dirname(output), { recursive: true });
const htmlPath = output.replace(/\.pdf$/i, ".html");
await fs.writeFile(htmlPath, document, "utf8");
const executablePath = process.env.PAPER_BROWSER || "C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe";
const browser = await chromium.launch({ headless: true, executablePath });
try {
  const page = await browser.newPage({ viewport: { width: 1200, height: 900 } });
  await page.goto(pathToFileURL(htmlPath).href, { waitUntil: "load" });
  await page.evaluate(() => document.fonts.ready);
  await page.emulateMedia({ media: "print" });
  await page.pdf({
    path: output,
    format: "A4",
    printBackground: true,
    displayHeaderFooter: true,
    tagged: true,
    outline: true,
    headerTemplate: "<div></div>",
    footerTemplate: `<style>@font-face{font-family:"Libertinus Sans";src:url("data:font/woff2;base64,${footerFont}") format("woff2")}</style><div style="width:100%;font-family:'Libertinus Sans',sans-serif;font-size:8px;color:#666;text-align:center"><span class="pageNumber"></span> / <span class="totalPages"></span></div>`,
    margin: { top: "21mm", right: "22mm", bottom: "23mm", left: "22mm" },
  });
} finally {
  await browser.close();
}
const pdf = await PDFDocument.load(await fs.readFile(output));
pdf.setTitle(titleMatch?.[1] || "Beyond Throughput");
pdf.setAuthor("Thomas Buffagni");
pdf.setSubject(language === "en"
  ? "A reproducible benchmark of Java caches across a Tomcat application lifecycle"
  : "Benchmark riproducibile di cache Java nel lifecycle di un'applicazione Tomcat");
pdf.setKeywords(language === "en"
  ? ["Java", "caching", "Apache Tomcat", "reproducible benchmarking", "redeployment", "memory leak"]
  : ["Java", "cache", "Apache Tomcat", "benchmark riproducibile", "redeploy", "memory leak"]);
pdf.setCreator("Beyond Throughput reproducible release pipeline");
await fs.writeFile(output, await pdf.save());
await fs.rm(htmlPath);
console.log(`Rendered ${output}`);
