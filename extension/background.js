// COFRE - service worker.
// Habla con el host de mensajeria nativa, que reenvia a la tuberia donde escucha
// la GUI. Nunca guarda valores: los pasa y los olvida.
//
// Si la via TCP esta activa (COFRE_BRIDGE=tcp en la GUI), basta con cambiar
// USE_NATIVE a false: se conserva el codigo de fetch como respaldo.
//
// 2026-11-18 (4.6): el aviso pinta una insignia "off" cuando el cofre esta
// cerrado, y admite `match` (sugeridos para el sitio) y `assign` (asignar este
// sitio, que confirma la GUI).

const USE_NATIVE = true;
const HOST_NAME = "com.cofre.host";
const PORT = 47653;
const BASE = `http://127.0.0.1:${PORT}`;

function sendNative(message) {
  return new Promise((resolve) => {
    try {
      chrome.runtime.sendNativeMessage(HOST_NAME, message, (reply) => {
        if (chrome.runtime.lastError) {
          resolve({ ok: false, error: chrome.runtime.lastError.message });
          return;
        }
        resolve(reply || { ok: false, error: "respuesta vacia del host" });
      });
    } catch (e) {
      resolve({ ok: false, error: String(e) });
    }
  });
}

async function callTcp(path, options = {}) {
  const res = await fetch(BASE + path, {
    ...options,
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
  });
  const data = await res.json().catch(() => ({ ok: false, error: "respuesta ilegible" }));
  if (!res.ok && data.ok !== false) {
    return { ok: false, error: `HTTP ${res.status}` };
  }
  return data;
}

function call(message) {
  if (USE_NATIVE) return sendNative(message);
  if (message.type === "match") {
    return callTcp("/match?domain=" + encodeURIComponent(message.domain || ""), {});
  }
  return callTcp("/" + message.type, {
    method: message.type === "get" ? "POST" : "GET",
    body: message.type === "get" ? JSON.stringify(message) : undefined,
  });
}

// Insignia: "off" cuando el cofre esta cerrado, vacia cuando esta abierto.
async function updateBadge() {
  const st = await call({ type: "status" });
  const abierto = !!(st.ok && st.open);
  try {
    await chrome.action.setBadgeText({ text: abierto ? "" : "off" });
    await chrome.action.setBadgeBackgroundColor({ color: abierto ? "#3E9C7A" : "#6B7787" });
  } catch (e) {
    // en algunos navegadores action no esta disponible en el worker: no es grave
  }
}

chrome.runtime.onInstalled.addListener(updateBadge);
chrome.runtime.onStartup.addListener(updateBadge);
updateBadge();

chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
  if (!msg?.type) return false;
  if (!["status", "list", "get", "match", "assign", "save"].includes(msg.type)) return false;
  call(msg).then((r) => {
    if (msg.type === "status" || msg.type === "assign") updateBadge();
    sendResponse(r);
  }).catch((e) => sendResponse({ ok: false, error: String(e) }));
  return true;
});
