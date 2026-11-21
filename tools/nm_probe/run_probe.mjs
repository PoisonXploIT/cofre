// Sonda H23 (2026-11-14): que puede lanzar Chrome como host de mensajeria nativa.
//
//   node tools/nm_probe/run_probe.mjs
//
// Carga una extension de prueba en un Chrome aislado (perfil temporal, puerto 9224)
// y tenta hablar con cuatro host: host.bat, host.cmd, python.exe y host.py.
// Comprueba en la maquina la afirmacion "Chrome no puede lanzar un .bat/.cmd".

import fs from "node:fs";
import path from "node:path";
import crypto from "node:crypto";
import { spawn } from "node:child_process";
import { fileURLToPath } from "node:url";
// puppeteer-core del proyecto, o la ruta de COFRE_PUPPETEER
import { createRequire } from "node:module";
const puppeteer = createRequire(import.meta.url)(
  process.env.COFRE_PUPPETEER || "puppeteer-core");

const HERE = path.dirname(fileURLToPath(import.meta.url));
const LOCALAPPDATA = process.env.LOCAPPDATA || path.join(process.env.USERPROFILE || "", "AppData", "Local");
const APP = path.join(LOCALAPPDATA, "cofre-nm-probe");
const HOSTS = path.join(APP, "nativeMessaging");
const PY = process.env.COMSPEC ? "C:\\Users\\Sammi\\AppData\\Local\\Programs\\Python\\Python312\\python.exe" : "python";
const CHROME = "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe";
const PORT = 9224;

function extId(der) {
  const digest = crypto.createHash("sha256").update(der).digest("hex").slice(0, 32);
  return [...digest].map((h) => "abcdefghijklmnop"[parseInt(h, 16)]).join("");
}

const keyfile = path.join(HERE, ".probe-key.pem");
let der;
if (fs.existsSync(keyfile)) {
  // Reutilizar la clave publica derivada del PEM no es trivial sin librerias:
  // si existe, regeneramos y sobrescribimos (el probe no necesita estabilidad).
  fs.unlinkSync(keyfile);
}
const pair = crypto.generateKeyPairSync("rsa", { modulusLength: 2048 });
der = pair.publicKey.export({ type: "spki", format: "der" });
fs.writeFileSync(keyfile, pair.privateKey.export({ type: "pkcs8", format: "pem" }));
const key = der.toString("base64");
const id = extId(der);
const origin = `chrome-extension://${id}`;

fs.writeFileSync(path.join(HERE, "manifest.json"), JSON.stringify({
  manifest_version: 3,
  name: "COFRE NM probe",
  version: "1.0.0",
  permissions: ["nativeMessaging"],
  background: { service_worker: "background.js" },
  action: { default_popup: "popup.html" },
  key,
}, null, 2));

fs.mkdirSync(HOSTS, { recursive: true });
const hosts = {
  bat: path.join(HERE, "host.bat"),
  cmd: path.join(HERE, "host.cmd"),
  python: PY,
  py: path.join(HERE, "host.py"),
};
for (const [name, p] of Object.entries(hosts)) {
  fs.writeFileSync(path.join(HOSTS, `com.cofre.${name}.json`), JSON.stringify({
    name: `com.cofre.${name}`,
    path: p,
    type: "stdio",
    allowed_origins: [origin],
  }, null, 2));
}

const profile = path.join(process.env.TEMP || "/tmp", `nm-probe-profile-${Date.now()}`);
fs.mkdirSync(profile, { recursive: true });
const chrome = spawn(CHROME, [
  `--remote-debugging-port=${PORT}`,
  `--user-data-dir=${profile}`,
  `--load-extension=${HERE}`,
  "--no-first-run",
  "--no-default-browser-check",
  "about:blank",
]);

let browser = null;
for (let i = 0; i < 40 && !browser; i++) {
  try {
    browser = await puppeteer.connect({ browserURL: `http://127.0.0.1:${PORT}`, defaultViewport: null });
  } catch (e) {
    await new Promise((r) => setTimeout(r, 500));
  }
}

const results = [];
if (!browser) {
  console.log("Chrome no exponio CDP en " + PORT);
} else {
  let page = null;
  for (let i = 0; i < 20 && !page; i++) {
    const pages = await browser.pages();
    page = pages.find((p) => p.url().startsWith(`chrome-extension://${id}/popup.html`)) || null;
    if (!page) await new Promise((r) => setTimeout(r, 500));
  }
  if (!page) { console.log("no se abrio la pagina de la extension de prueba"); }
  else {
    await new Promise((r) => setTimeout(r, 1500));
    const res = await page.evaluate(() => window.runProbe());
    results.push(...res);
    await page.close();
  }
  browser.disconnect();
}

chrome.kill();
import fs2 from "node:fs";
fs2.rmSync(profile, { recursive: true, force: true });

console.log("extension de prueba id:", id);
let ok = 0;
for (const r of results) {
  const line = r.ok
    ? `OK    ${r.name.padEnd(7)} Chrome LANZA el host: ${JSON.stringify(r.reply).slice(0, 140)}`
    : `FALLO ${r.name.padEnd(7)} ${r.error.slice(0, 140)}`;
  if (r.ok) ok++;
  console.log(line);
}
console.log(`\n${ok}/${results.length} host lanzados`);
process.exit(0);
