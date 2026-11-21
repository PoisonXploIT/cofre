// Lee los resultados de la sonda H23 desde un Chrome/Brave con CDP abierto.
//   node tools/nm_probe/read_probe.mjs 9226
// Requiere puppeteer-core. Se busca en el proyecto (npm i puppeteer-core) o en la
// ruta que diga la variable COFRE_PUPPETEER, para no clavar rutas de una maquina.
import { createRequire } from "node:module";
const puppeteer = createRequire(import.meta.url)(
  process.env.COFRE_PUPPETEER || "puppeteer-core");

const port = process.argv[2] || "9226";
const browser = await puppeteer.connect({ browserURL: `http://127.0.0.1:${port}`, defaultViewport: null });
const pages = await browser.pages();
const page = pages.find((p) => p.url().includes("probe.html"));
if (!page) { console.log("no se encontro la pagina de la sonda"); process.exit(1); }

for (let i = 0; i < 12; i++) {
  const lines = await page.evaluate(() => [...document.querySelectorAll(".line pre")].map((e) => e.textContent));
  if (lines.length >= 4) { lines.forEach((l) => console.log(l)); process.exit(0); }
  await new Promise((r) => setTimeout(r, 1500));
}
console.log("sin resultados tras 18 s");
process.exit(1);
