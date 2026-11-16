// Lee los resultados de la sonda H23 via CDP crudo (sin puppeteer).
//   node tools/nm_probe/read_cdp.mjs 9226
const port = process.argv[2] || "9226";
const list = await (await fetch(`http://127.0.0.1:${port}/json/list`)).json();
const target = list.find((t) => t.url.includes("probe.html"));
if (!target) {
  console.log("no se encontro probe.html. targets:");
  list.forEach((t) => console.log(" ", t.type, t.url.slice(0, 80)));
  process.exit(1);
}
const ws = new WebSocket(target.webSocketDebuggerUrl);
let id = 0;
const pending = new Map();
ws.addEventListener("message", (ev) => {
  const msg = JSON.parse(ev.data);
  if (msg.id && pending.has(msg.id)) {
    pending.get(msg.id)(msg);
    pending.delete(msg.id);
  }
});
await new Promise((res, rej) => {
  ws.addEventListener("open", res);
  ws.addEventListener("error", rej);
});
function send(method, params = {}) {
  const myId = ++id;
  ws.send(JSON.stringify({ id: myId, method, params }));
  return new Promise((res) => pending.set(myId, res));
}
await send("Runtime.enable");
const r = await send("Runtime.evaluate", {
  expression: "document.getElementById('out').innerText",
  returnByValue: true,
});
console.log(r.result?.result?.value ?? JSON.stringify(r));
ws.close();
