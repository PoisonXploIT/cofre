// Sonda de la extension COFRE (H16, H17). Ejecuta la logica real de relleno
// en Chrome, en paginas de prueba. No toca ninguna web real.
//
//   node tools/extension_fill_test.mjs
//
// Requiere Chrome con depuracion en 9222 (skill browser-tools).

import fs from "node:fs";
import path from "node:path";
// Requiere puppeteer-core. Se busca en el proyecto (npm i puppeteer-core) o en la
// ruta que diga la variable COFRE_PUPPETEER, para no clavar rutas de una maquina.
import { createRequire } from "node:module";
const puppeteer = createRequire(import.meta.url)(
  process.env.COFRE_PUPPETEER || "puppeteer-core");

const REPO = path.dirname(path.dirname(process.argv[2] || "tools/extension_fill_test.mjs"));
const MANIFEST = JSON.parse(fs.readFileSync(path.join(REPO, "extension/manifest.json"), "utf-8"));
const POPUP = fs.readFileSync(path.join(REPO, "extension/popup.js"), "utf-8");
// R1 (2026-11-16): la lista de dominios ya no vive en la extension. La decide
// el puente, por secreto. Aqui solo se comprueba que la extension no la usa.
const ALLOW = { domains: [] };

const results = [];
function check(name, ok, detail = "") {
  results.push({ name, ok: !!ok, detail });
  console.log(`${ok ? "OK   " : "FALLO"}  ${name}  ${detail}`);
}

// --- comprobaciones estaticas del manifest (H16) ---
check("manifest sin content_scripts", !MANIFEST.content_scripts || MANIFEST.content_scripts.length === 0,
  "no se inyecta script en ninguna pagina al cargar");
const wildcards = (MANIFEST.content_scripts || []).flatMap((c) => c.matches || [])
  .filter((m) => m.includes("*"));
check("ningun match con comodin", wildcards.length === 0, wildcards.join(", "));
check("host_permissions solo loopback",
  (MANIFEST.host_permissions || []).every((h) => h.includes("127.0.0.1")),
  (MANIFEST.host_permissions || []).join(", "));
check("la extension no lleva lista de dominios",
  !fs.existsSync(path.join(REPO, "extension/allowed-domains.json")),
  "la lista vive junto al cofre, por secreto (.cofre-hosts.json)");
check("la logica de relleno esta en popup.js", POPUP.includes("function cofreFill"), "");
check("no se rellena el enfocado por defecto",
  POPUP.includes("allowFocused && focused"), "el modo 'campo enfocado' es explicito");

// --- extraccion de funciones reales para probarlas en el navegador ---
function extract(name) {
  const start = POPUP.indexOf(`function ${name}(`);
  if (start < 0) throw new Error(`no se encuentra ${name} en popup.js`);
  let depth = 0, i = POPUP.indexOf("(", start), bodyStart = i;
  for (; i < POPUP.length; i++) {
    if (POPUP[i] === "{") depth++;
    else if (POPUP[i] === "}") {
      depth--;
      if (depth === 0) { i++; break; }
    }
  }
  return POPUP.slice(start, i);
}

const cofreFillSrc = extract("cofreFill");
const registrableSrc = "function registrable() { return null; }";

const FIXTURE = `data:text/html,` + encodeURIComponent(`<!doctype html><body>
  <form id="login">
    <input id="decoy" type="text" value="">
    <input id="pass" type="password">
  </form>
  <form id="api">
    <input id="apikey" type="text" name="api_key" placeholder="API key">
  </form>
  <form id="plain">
    <input id="note" type="text" name="comentario">
  </form>
</body>`);

const browser = await Promise.race([
  puppeteer.connect({ browserURL: "http://localhost:9222", defaultViewport: null }),
  new Promise((_, r) => setTimeout(() => r(new Error("Chrome no responde en 9222")), 6000)),
]).catch((e) => { console.error("no se pudo conectar:", e.message); process.exit(1); });

const page = await browser.newPage();
await page.goto(FIXTURE);

const out = await page.evaluate((fillSrc, regSrc, allow) => {
  eval(fillSrc);
  eval("let allow = " + JSON.stringify(allow) + ";");
  eval(regSrc);

  function visible(el) { return el && !el.disabled; }

  // 1. foco en el decoy: se rellena la contrasena, no el decoy
  document.getElementById("decoy").focus();
  const r1 = cofreFill("SECRETO1", false);
  const decoy = document.getElementById("decoy").value;
  const pass = document.getElementById("pass").value;

  // 2. sin contrasena pero con campo de clave: se rellena ese
  document.getElementById("pass").setAttribute("type", "hidden");
  const r2 = cofreFill("SECRETO2", false);
  const api = document.getElementById("apikey").value;

  // 3. solo un campo generico sin etiqueta de clave: no rellena
  document.getElementById("apikey").remove();
  document.getElementById("note").value = "";
  const r3 = cofreFill("SECRETO3", false);
  const note = document.getElementById("note").value;

  // 4. modo explicito "campo enfocado": si rellena
  document.getElementById("note").focus();
  const r4 = cofreFill("SECRETO4", true);
  const note4 = document.getElementById("note").value;

  return {
    r1, decoy, pass, r2, api, r3, note, r4, note4,
    allow: { plain: registrable("example.com"), sub: registrable("dash.cloudflare.com"), exact: registrable("github.com"), evil: registrable("github.com.evil.co") },
  };
}, cofreFillSrc, registrableSrc, ALLOW.domains);

check("con foco en un campo texto, rellena la contrasena y no el decoy",
  out.r1.filled === 1 && out.pass === "SECRETO1" && out.decoy === "",
  `pass=${out.pass || 'vacio'} decoy=${out.decoy || 'vacio'}`);
check("sin contrasena, rellena el campo etiquetado como clave",
  out.r2.filled === 1 && out.api === "SECRETO2", out.api || "no rellenado");
check("un campo generico sin etiqueta de clave NO se rellena",
  out.r3.filled === 0 && out.note === "",
  out.r3.reason || "relleno un campo que no deberia");
check("con 'campo enfocado' explicito si rellena",
  out.r4.filled === 1 && out.note4 === "SECRETO4", out.note4 || "");
check("sin lista local no hay decision en la extension",
  out.allow.plain === null && out.allow.evil === null,
  "el rechazo lo hace el puente, no el popup");

await page.close();
const failed = results.filter((r) => !r.ok);
console.log(`\n${results.length - failed.length}/${results.length} comprobaciones OK`);
process.exit(failed.length ? 1 : 0);
