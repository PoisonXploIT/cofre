// COFRE - popup: lista nombres y rellena solo cuando lo pides.
//
// Cambios del 2026-11-14 (H16 y H17):
//   - ya no hay content_script inyectado en todas las webs: el script solo se
//     ejecuta en la pestana activa cuando pulsas "Rellenar";
//   - no se escribe en "el campo enfocado" de cualquier pagina: se busca un
//     campo de contrasena, o uno cuyo nombre/etiqueta hable de clave o token;
//   - el dominio tiene que estar en allowed-domains.json. Si no esta, hace
//     falta un segundo click de confirmacion (defensa contra phishing).

const $ = (id) => document.getElementById(id);
let items = [];
let allow = [];
let armed = null;      // nombre del secreto awaits second click
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

function registrable(host) {
  // "dash.cloudflare.com" -> "cloudflare.com" para la comprobacion
  const parts = host.split(".");
  for (let i = 0; i < parts.length - 1; i++) {
    const candidate = parts.slice(i).join(".");
    if (allow.includes(candidate)) return candidate;
  }
  return null;
}

async function loadAllow() {
  try {
    const res = await fetch(chrome.runtime.getURL("allowed-domains.json"));
    const data = await res.json();
    allow = (data.domains || []).map((d) => String(d).toLowerCase());
  } catch (e) {
    allow = [];
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
  const allowed = registrable(host);
  $("host").classList.toggle("ok", !!allowed);
  $("allownote").textContent = allowed
    ? `dominio autorizado (${allowed})`
    : host ? "dominio no autorizado: hara falta confirmacion" : "abre una pagina primero";

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
  render();
}

function render() {
  const q = $("search").value.trim().toLowerCase();
  const shown = items.filter((i) => !q || i.name.toLowerCase().includes(q));
  if (!shown.length) {
    $("list").innerHTML = `<div class="empty">Ningun secreto coincide.</div>`;
    return;
  }
  $("list").innerHTML = "";
  for (const item of shown) {
    const row = document.createElement("div");
    row.className = "row";
    const name = document.createElement("span");
    name.className = "name";
    name.textContent = item.name;
    const kind = document.createElement("span");
    kind.className = "kind";
    kind.textContent = (item.tags && item.tags[0]) || "";
    const btn = document.createElement("button");
    btn.className = "fill";
    btn.textContent = armed === item.name ? "Confirmar" : "Rellenar";
    btn.addEventListener("click", (e) => {
      e.stopPropagation();
      fill(item.name);
    });
    row.addEventListener("click", () => fill(item.name));
    row.append(name, kind, btn);
    $("list").appendChild(row);
  }
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
  const allowed = registrable(host);
  if (!allowed) {
    if (armed !== name) {
      armed = name;
      render();
      $("foot").textContent = `Cuidado: ${host} no esta en la lista de dominios autorizados. ` +
        "Pulsa Confirmar solo si confias en esta pagina (el riesgo es un sitio de phishing).";
      return;
    }
    armed = null;
  }

  $("foot").textContent = "pidiendo el valor...";
  const res = await send({ type: "get", name, domain: host });
  if (!res.ok) {
    $("foot").textContent = res.error || "no se pudo leer";
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

$("search").addEventListener("input", render);
$("search").addEventListener("keydown", (e) => {
  if (e.key === "Enter") {
    const first = document.querySelector(".row");
    if (first) first.click();
  }
});
loadAllow().then(refresh);
$("search").focus();
