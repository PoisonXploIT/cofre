// COFRE - service worker.
// Habla con el host de mensajeria nativa, que reenvia a la tuberia donde escucha
// la GUI. Nunca guarda valores: los pasa y los olvida.
//
// Si la via TCP esta activa (COFRE_BRIDGE=tcp en la GUI), basta con cambiar
// USE_NATIVE a false: se conserva el codigo de fetch como respaldo.

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
  return USE_NATIVE ? sendNative(message) : callTcp("/" + message.type, {
    method: message.type === "get" ? "POST" : "GET",
    body: message.type === "get" ? JSON.stringify(message) : undefined,
  });
}

chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
  if (!msg?.type) return false;
  if (!["status", "list", "get"].includes(msg.type)) return false;
  call(msg).then(sendResponse).catch((e) =>
    sendResponse({ ok: false, error: String(e) }));
  return true;
});
