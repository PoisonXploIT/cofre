// COFRE - popup: lista nombres y rellena solo cuando lo pides.
//
// Cambios del 2026-11-14 (H16 y H17):
//   - ya no hay content_script inyectado en todas las webs: el script solo se
//     ejecuta en la pestana activa cuando pulsas "Rellenar";
//   - no se escribe en "el campo enfocado" de cualquier pagina: se busca un
//     campo de contrasena, o uno cuyo nombre/etiqueta hable de clave o token;
//   - R1 (2026-11-16): el dominio NO se decide aqui. El puente rechaza el
//     relleno si el host de la pestana no esta asignado a ESE secreto. No hay
//     segundo click de confirmacion: eso es lo que hace la victima de un phishing.
//
// 2026-11-18 (4.6):
//   - "Para este sitio" arriba: los secretos cuyos dominios encajan con la
//     pestana (los dice el cofre con `match`, no la extension);
//   - boton "Asignar" en los que no valen para este sitio: pide confirmacion en
//     la GUI y, si aceptas, el host actual se anade a ese secreto;
//   - Ctrl+Shift+L abre este aviso (definido en manifest.json).

const $ = (id) => document.getElementById(id);
let items = [];
let sugeridos = new Map();
let tab = null;

function send(msg) {
  return new Promise((resolve) =>
    chrome.runtime.sendMessage(msg, (r) => resolve(r || { ok: false, error: "sin respuesta" })));
}

function hostOf(url) {
  try {
    return new URL(url).hostname.toLowerCase();
  } catch (e) {
    return "";
  }
}

async function currentTab() {
  const [t] = await chrome.tabs.query({ active: true, currentWindow: true });
  return t || null;
}

async function refresh() {
  tab = await currentTab();
  const host = hostOf(tab?.url || "");
  $("host").textContent = host || "sin pestana";
  $("allownote").textContent = host
    ? "el cofre decide si este sitio vale para el secreto"
    : "abre una pagina primero";

  const st = await send({ type: "status" });
  const open = st.ok && st.open;
  $("dot").classList.toggle("on", !!open);
  $("state").textContent = open ? `abierto · ${st.count} secretos` : "cerrado";
  if (!open) {
    $("list").innerHTML = `<div class="empty">Conecta el pendrive y abre el cofre.</div>`;
    return;
  }
  const res = await send({ type: "list" });
  if (!res.ok) {
    $("list").innerHTML = `<div class="empty">${res.error || "error"}</div>`;
    return;
  }
  items = res.items || [];
  sugeridos = new Map();
  if (host) {
    const m = await send({ type: "match", domain: host });
    if (m.ok) {
      for (const it of m.items || []) sugeridos.set(it.name, it);
    }
  }
  render();
}

function fila(item, esSugerido) {
  const row = document.createElement("div");
  row.className = "row" + (esSugerido ? " sug" : "");

  const name = document.createElement("span");
  name.className = "name";
  name.textContent = item.name;

  const kind = document.createElement("span");
  kind.className = "kind";
  kind.textContent = esSugerido
    ? (sugeridos.get(item.name)?.exact ? "exacto" : "sitio")
    : ((item.tags && item.tags[0]) || "");

  const btn = document.createElement("button");
  btn.className = "fill";
  btn.textContent = "Rellenar";
  btn.addEventListener("click", (e) => {
    e.stopPropagation();
    fill(item.name);
  });

  row.append(name, kind);
  if (!esSugerido) {
    const asig = document.createElement("button");
    asig.className = "fill assign";
    asig.textContent = "Asignar";
    asig.title = "pedir a COFRE que este sitio valga para este secreto";
    asig.addEventListener("click", (e) => {
      e.stopPropagation();
      assignSite(item.name);
    });
    row.append(asig);
  }
  row.append(btn);
  row.addEventListener("click", () => fill(item.name));
  return row;
}

function render() {
  const q = $("search").value.trim().toLowerCase();
  const coincide = (i) => !q || i.name.toLowerCase().includes(q);
  const aqui = items.filter((i) => sugeridos.has(i.name) && coincide(i));
  const resto = items.filter((i) => !sugeridos.has(i.name) && coincide(i));

  if (!aqui.length && !resto.length) {
    $("list").innerHTML = `<div class="empty">Ningun secreto coincide.</div>`;
    return;
  }
  $("list").innerHTML = "";
  if (aqui.length) {
    const t = document.createElement("div");
    t.className = "section";
    t.textContent = "Para este sitio";
    $("list").appendChild(t);
    for (const item of aqui) $("list").appendChild(fila(item, true));
  }
  if (resto.length) {
    const t = document.createElement("div");
    t.className = "section";
    t.textContent = aqui.length ? "Todos los secretos" : "Secretos";
    $("list").appendChild(t);
    for (const item of resto) $("list").appendChild(fila(item, false));
  }
}

// 4.8: leer el usuario que hay escrito en la pagina (solo se envia a COFRE
// como pista; el valor del secreto se teclea en la GUI).
function cofreUsuario() {
  const campos = [...document.querySelectorAll("input[type=email], input[type=text]")]
    .filter((el) => el.offsetParent !== null && !el.disabled && !el.readOnly);
  const elegido = campos.find((el) =>
    /(usuario|user|login|correo|email|mail|cuenta)/i.test(
      (el.name || "") + " " + (el.id || "") + " " + (el.placeholder || "")));
  if (!elegido || elegido.type === "password") return "";
  const v = String(elegido.value || "").trim();
  return v.length > 0 && v.length <= 80 ? v : "";
}

// 4.7: generar una contrasena nueva y guardarla para este sitio. La confirmacion
// la pide COFRE en su ventana; aqui solo se rellena el formulario con el valor.
function cofreFillAll(value) {
  function visible(el) {
    if (!el || el.disabled || el.readOnly) return false;
    const r = el.getBoundingClientRect();
    return r.width >= 8 && r.height >= 8 && el.type === "password";
  }
  const campos = [...document.querySelectorAll("input[type=password]")].filter(visible);
  for (const el of campos) {
    el.focus();
    el.value = value;
    el.dispatchEvent(new Event("input", { bubbles: true }));
    el.dispatchEvent(new Event("change", { bubbles: true }));
  }
  return { filled: campos.length };
}

async function generarYGuardar() {
  const host = hostOf(tab?.url || "");
  const nombre = ($("gen_name").value || "").trim().toUpperCase();
  if (!host) {
    $("foot").textContent = "no hay pestana activa";
    return;
  }
  $("foot").textContent = "esperando la confirmación en COFRE...";
  const res = await send({ type: "generate", domain: host, name: nombre });
  if (!res.ok) {
    $("foot").textContent = res.error || "no se pudo generar";
    return;
  }
  try {
    const r = await chrome.scripting.executeScript({
      target: { tabId: tab.id }, func: cofreFillAll, args: [res.value],
    });
    const n = r?.[0]?.result?.filled || 0;
    $("foot").textContent = n
      ? `guardado como ${res.name} y rellenado en ${n} campo(s). Apunta el nombre; el valor está en COFRE.`
      : `guardado como ${res.name}, pero no encontré campos de contraseña en la página.`;
    if (n) setTimeout(() => window.close(), 1600);
  } catch (e) {
    $("foot").textContent = "guardado, pero no se pudo rellenar: " + e.message;
  }
  await refresh();
}

async function saveSite() {
  const host = hostOf(tab?.url || "");
  if (!host) {
    $("foot").textContent = "no hay pestana activa";
    return;
  }
  let usuario = "";
  try {
    const r = await chrome.scripting.executeScript({
      target: { tabId: tab.id }, func: cofreUsuario,
    });
    usuario = String(r?.[0]?.result || "");
  } catch (e) {
    usuario = "";
  }
  $("foot").textContent = "abriendo la hoja de COFRE...";
  const res = await send({ type: "save", domain: host, username: usuario });
  $("foot").textContent = res.ok
    ? `${host} anotado. Termina de guardar en la ventana de COFRE.`
    : (res.error || "no se pudo abrir la hoja");
  if (res.ok) setTimeout(() => window.close(), 1200);
}

async function assignSite(name) {
  const host = hostOf(tab?.url || "");
  if (!host) {
    $("foot").textContent = "no hay pestana activa";
    return;
  }
  $("foot").textContent = `esperando la confirmación en COFRE para ${host}...`;
  const res = await send({ type: "assign", name, domain: host });
  if (!res.ok) {
    $("foot").textContent = res.error || "no se pudo asignar";
    return;
  }
  $("foot").textContent = res.changed
    ? `${host} añadido a ${name}. Ya se puede rellenar aquí.`
    : `${host} ya valía para ${name}.`;
  await refresh();
}

// Funcion que se inyecta en la pestana activa. Solo escribe en campos de
// contrasena o en campos claramente de clave; nunca en el primero que encuentre.
function cofreFill(value, allowFocused) {
  function visible(el) {
    if (!el || el.disabled || el.readOnly) return false;
    const r = el.getBoundingClientRect();
    if (r.width < 8 || r.height < 8) return false;
    const style = window.getComputedStyle(el);
    return style.visibility !== "hidden" && style.display !== "none" &&
      el.type !== "hidden";
  }

  function labelOf(el) {
    const l = (el.name || "") + " " + (el.id || "") + " " + (el.placeholder || "") +
      " " + (el.getAttribute("aria-label") || "");
    const label = el.closest("label")?.textContent || "";
    return (l + " " + label).toLowerCase();
  }

  const isKeyField = (el) =>
    /(key|token|clave|api|secret|contras|passcode|pin)/.test(labelOf(el));

  function setValue(el, value) {
    el.focus();
    el.value = value;
    el.dispatchEvent(new Event("input", { bubbles: true }));
    el.dispatchEvent(new Event("change", { bubbles: true }));
  }

  const inputs = [...document.querySelectorAll(
    "input[type=password], input[type=text], input[type=email], input:not([type])")]
    .filter(visible);

  if (!inputs.length) return { filled: 0, reason: "no hay campos visibles en la pagina" };

  const password = inputs.find((el) => el.type === "password");
  const keyField = inputs.find((el) => el.type !== "password" && isKeyField(el));
  const focused = document.activeElement;

  let target = null;
  if (allowFocused && focused && inputs.includes(focused)) {
    target = focused;
  } else if (password) {
    target = password;
  } else if (keyField) {
    target = keyField;
  }

  if (!target) {
    return {
      filled: 0,
      reason: "no localizo un campo de contrasena ni de clave. Si quieres escribir " +
              "en el campo enfocado, activa 'campo enfocado'.",
    };
  }
  setValue(target, value);
  return { filled: 1, where: target.type === "password" ? "campo de contrasena" : (target.name || target.id || "campo") };
}

async function fill(name) {
  tab = await currentTab();
  if (!tab?.id) {
    $("foot").textContent = "no hay pestana activa";
    return;
  }
  const host = hostOf(tab.url || "");
  // R1: no hay confirmacion en la extension. El servidor rechaza el dominio que
  // no este asignado a ESE secreto. Autorizar es cosa de la GUI/CLI, no del aviso.

  $("foot").textContent = "pidiendo el valor...";
  const res = await send({ type: "get", name, domain: host });
  if (!res.ok) {
    const motivo = String(res.error || "no se pudo leer");
    $("foot").textContent = motivo.includes("no esta asignado") || motivo.includes("no tiene ningun sitio")
      ? motivo + ". Pulsa Asignar (lo confirma COFRE) o usa host-assign."
      : motivo;
    return;
  }
  try {
    const results = await chrome.scripting.executeScript({
      target: { tabId: tab.id },
      func: cofreFill,
      args: [res.value, $("focused").checked],
    });
    const r = results?.[0]?.result || { filled: 0, reason: "no se pudo ejecutar" };
    if (r.filled) {
      $("foot").textContent = `rellenado en ${host} (${r.where}). El valor no se guarda en la extension.`;
      setTimeout(() => window.close(), 900);
    } else {
      $("foot").textContent = r.reason || "no se pudo rellenar";
    }
  } catch (e) {
    $("foot").textContent = "no se pudo escribir en la pagina: " + e.message;
  }
}

$("guardar_sitio").addEventListener("click", saveSite);
$("gen_open").addEventListener("click", () => {
  const host = hostOf(tab?.url || "");
  const sugerido = host.split(".")[0].replace(/[^A-Za-z0-9]+/g, "_").toUpperCase();
  $("gen_name").value = sugerido || "SITIO";
  $("gen").classList.toggle("hidden");
  $("gen_name").focus();
});
$("gen_go").addEventListener("click", generarYGuardar);
$("search").addEventListener("input", render);
$("search").addEventListener("keydown", (e) => {
  if (e.key === "Enter") {
    const first = document.querySelector(".row");
    if (first) first.click();
  }
});
refresh();
$("search").focus();
