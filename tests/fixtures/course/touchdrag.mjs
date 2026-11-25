// Real touch drag through CDP (Input.dispatchTouchEvent) — used to verify that order tasks work with a finger.
// usage: node touchdrag.mjs <browser-ws-url> <pageUrlSubstring> x y x2 y2
const [ws, sub, x1, y1, x2, y2] = process.argv.slice(2);
const http = ws.replace("ws://", "http://").replace(/\/devtools\/browser\/.*/, "");
const targets = await (await fetch(http + "/json")).json();
const t = targets.find((t) => t.type === "page" && t.url.includes(sub));
if (!t) { console.error("no page", sub); process.exit(1); }
const sock = new WebSocket(t.webSocketDebuggerUrl);
let id = 0;
const pending = new Map();
sock.onmessage = (m) => { const d = JSON.parse(m.data); if (d.id && pending.has(d.id)) { pending.get(d.id)(d); pending.delete(d.id); } };
await new Promise((r) => (sock.onopen = r));
const send = (method, params = {}) => new Promise((r) => { const i = ++id; pending.set(i, r); sock.send(JSON.stringify({ id: i, method, params })); });
await send("Emulation.setTouchEmulationEnabled", { enabled: true, maxTouchPoints: 1 });
const pt = (x, y) => [{ x: +x, y: +y, radiusX: 4, radiusY: 4, force: 1, id: 1 }];
await send("Input.dispatchTouchEvent", { type: "touchStart", touchPoints: pt(x1, y1) });
const steps = 12;
for (let k = 1; k <= steps; k++) {
  const x = +x1 + ((+x2 - +x1) * k) / steps, y = +y1 + ((+y2 - +y1) * k) / steps;
  await send("Input.dispatchTouchEvent", { type: "touchMove", touchPoints: pt(x, y) });
  await new Promise((r) => setTimeout(r, 30));
}
await send("Input.dispatchTouchEvent", { type: "touchEnd", touchPoints: [] });
const r = await send("Runtime.evaluate", { expression: 'JSON.stringify([...document.querySelectorAll(".task[data-type=order] .order-item")].map(li=>li.dataset.pos))', returnByValue: true });
console.log(r.result.result.value);
sock.close();
