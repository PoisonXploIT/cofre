// Sonda H23: la logica va en un fichero aparte porque MV3 bloquea los
// <script> inline en las paginas de extension (CSP: script-src 'self').

const NAMES = ["bat", "cmd", "python", "py"];
const TIMEOUT = 5000;

function timeout(ms, name) {
  return new Promise((resolve) =>
    setTimeout(() => resolve({ name, ok: false, error: "sin respuesta en " + ms + " ms" }), ms));
}

async function probe(name) {
  try {
    return await Promise.race([
      chrome.runtime.sendNativeMessage("com.cofre." + name, { ping: 1 })
        .then((r) => ({ name, ok: true, reply: r })),
      timeout(TIMEOUT, name),
    ]);
  } catch (e) {
    return { name, ok: false, error: String(e) };
  }
}

async function run() {
  const out = document.getElementById("out");
  out.innerHTML = "";
  for (const n of NAMES) {
    const r = await probe(n);
    const div = document.createElement("div");
    div.className = "line " + (r.ok ? "ok" : "bad");
    const pre = document.createElement("pre");
    pre.textContent = r.ok
      ? "OK    " + n + "  el navegador LO LANZA y responde: " + JSON.stringify(r.reply)
      : "FALLO " + n + "  " + r.error;
    div.appendChild(pre);
    out.appendChild(div);
  }
}

document.getElementById("run").addEventListener("click", run);
run();
