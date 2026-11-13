// COFRE - popup: lista nombres y rellena el campo de la pagina activa.
// El valor se pide solo al pulsar. No se guarda en ningun sitio.

const $ = (id) => document.getElementById(id);
let items = [];

function send(msg) {
  return new Promise((resolve) =>
    chrome.runtime.sendMessage(msg, (r) => resolve(r || { ok: false, error: "sin respuesta" })));
}

async function refresh() {
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
    btn.textContent = "Rellenar";
    btn.addEventListener("click", (e) => {
      e.stopPropagation();
      fill(item.name);
    });
    row.addEventListener("click", () => fill(item.name));
    row.append(name, kind, btn);
    $("list").appendChild(row);
  }
}

async function fill(name) {
  $("foot").textContent = "pidiendo el valor...";
  const res = await send({ type: "get", name });
  if (!res.ok) {
    $("foot").textContent = res.error || "no se pudo leer";
    return;
  }
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  if (!tab?.id) {
    $("foot").textContent = "no hay pestana activa";
    return;
  }
  chrome.tabs.sendMessage(tab.id, { type: "cofre-fill", value: res.value, name },
    (r) => {
      if (chrome.runtime.lastError || !r || !r.filled) {
        $("foot").textContent = "no encontre un campo donde escribir en esta pagina";
      } else {
        $("foot").textContent = `rellenado en ${r.filled} campo(s)`;
        setTimeout(() => window.close(), 600);
      }
    });
}

$("search").addEventListener("input", render);
$("search").addEventListener("keydown", (e) => {
  if (e.key === "Enter") {
    const first = document.querySelector(".row");
    if (first) first.click();
  }
});
refresh();
$("search").focus();
