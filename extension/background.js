// COFRE - service worker.
// Habla con el puente local (127.0.0.1). Nunca guarda valores: los pasa y los
// olvida. El servidor solo contesta mientras el cofre esta abierto.

const PORT = 47653;
const BASE = `http://127.0.0.1:${PORT}`;

async function call(path, options = {}) {
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

chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
  if (msg?.type === "status") {
    call("/status").then(sendResponse).catch((e) =>
      sendResponse({ ok: false, error: String(e) }));
    return true;
  }
  if (msg?.type === "list") {
    call("/list").then(sendResponse).catch((e) =>
      sendResponse({ ok: false, error: String(e) }));
    return true;
  }
  if (msg?.type === "get") {
    // El dominio se manda solo para el registro de accesos: sirve para saber
    // donde se relleno, no para nada mas.
    call("/get", { method: "POST", body: JSON.stringify({ name: msg.name, domain: msg.domain || "" }) })
      .then(sendResponse)
      .catch((e) => sendResponse({ ok: false, error: String(e) }));
    return true;
  }
  return false;
});
