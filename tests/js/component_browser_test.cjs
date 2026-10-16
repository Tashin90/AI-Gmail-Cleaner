const assert = require("node:assert/strict");

const cdpBase = process.env.CDP_URL || "http://127.0.0.1:9223";
let selectionEpoch = Date.now();
let lastRows = [];

function delay(milliseconds) {
  return new Promise((resolve) => setTimeout(resolve, milliseconds));
}

class CdpClient {
  constructor(socketUrl) {
    this.socket = new WebSocket(socketUrl);
    this.nextId = 1;
    this.pending = new Map();
  }

  async connect() {
    await new Promise((resolve, reject) => {
      this.socket.addEventListener("open", resolve, { once: true });
      this.socket.addEventListener("error", reject, { once: true });
    });
    this.socket.addEventListener("message", (event) => {
      const message = JSON.parse(event.data);
      if (!message.id || !this.pending.has(message.id)) return;
      const { resolve, reject } = this.pending.get(message.id);
      this.pending.delete(message.id);
      if (message.error) reject(new Error(message.error.message));
      else resolve(message.result);
    });
  }

  send(method, params = {}) {
    const id = this.nextId;
    this.nextId += 1;
    return new Promise((resolve, reject) => {
      this.pending.set(id, { resolve, reject });
      this.socket.send(JSON.stringify({ id, method, params }));
    });
  }

  close() {
    this.socket.close();
  }
}

async function evaluate(client, expression) {
  const result = await client.send("Runtime.evaluate", {
    expression,
    returnByValue: true,
    awaitPromise: true,
  });
  if (result.exceptionDetails) {
    throw new Error(result.exceptionDetails.text || "Browser evaluation failed");
  }
  return result.result.value;
}

async function renderRows(client, selectedIds = []) {
  selectionEpoch += 1;
  const rows = Array.from({ length: 40 }, (_, index) => ({
    id: `message-${index + 1}`,
    sender: `Sender ${index + 1} <sender${index + 1}@example.test>`,
    subject: `Synthetic subject ${index + 1}`,
    category: index % 7 === 0 ? "Protected" : "Promotion",
    reason: "Synthetic browser interaction test",
    date: `2026-10-${String((index % 28) + 1).padStart(2, "0")}`,
    protected: index % 7 === 0,
  }));
  lastRows = rows;
  const payload = JSON.stringify({
    type: "streamlit:render",
    args: { rows, selected_ids: selectedIds, selection_epoch: selectionEpoch },
  });
  await evaluate(client, `window.postMessage(${payload}, "*")`);
  await delay(75);
  await evaluate(client, "document.getElementById('viewport').scrollTop = 0");
}

async function repeatRender(client, selectedIds) {
  const payload = JSON.stringify({
    type: "streamlit:render",
    args: { rows: lastRows, selected_ids: selectedIds, selection_epoch: selectionEpoch },
  });
  await evaluate(client, `window.postMessage(${payload}, "*")`);
  await delay(75);
}

async function checkboxCenter(client, rowNumber) {
  return evaluate(client, `(() => {
    const box = document.querySelectorAll('.drag-checkbox')[${rowNumber - 1}];
    const rect = box.getBoundingClientRect();
    return { x: rect.left + rect.width / 2, y: rect.top + rect.height / 2 };
  })()`);
}

async function mouse(client, type, point, modifiers = 0, buttons = 0) {
  await client.send("Input.dispatchMouseEvent", {
    type,
    x: point.x,
    y: point.y,
    button: "left",
    buttons,
    modifiers,
    clickCount: 1,
  });
}

async function drag(client, fromRow, toRow) {
  const start = await checkboxCenter(client, fromRow);
  const end = await checkboxCenter(client, toRow);
  await mouse(client, "mousePressed", start, 0, 1);
  await delay(30);
  await mouse(client, "mouseMoved", end, 0, 1);
  await delay(30);
  await mouse(client, "mouseReleased", end, 0, 0);
  await delay(50);
}

async function click(client, rowNumber, modifiers = 0) {
  const point = await checkboxCenter(client, rowNumber);
  await mouse(client, "mousePressed", point, modifiers, 1);
  await mouse(client, "mouseReleased", point, modifiers, 0);
  await delay(40);
}

async function selectedIds(client) {
  return evaluate(client, `[...document.querySelectorAll('tr.selected')]
    .map((row) => row.dataset.messageId)`);
}

async function main() {
  const targets = await (await fetch(`${cdpBase}/json/list`)).json();
  const target = targets.find((item) => item.type === "page" && item.url.includes("index.html"));
  assert.ok(target, "The drag-select component page was not found in Edge");

  const client = new CdpClient(target.webSocketDebuggerUrl);
  await client.connect();
  await client.send("Runtime.enable");
  await client.send("Emulation.setDeviceMetricsOverride", {
    width: 1280,
    height: 800,
    deviceScaleFactor: 1,
    mobile: false,
  });

  await renderRows(client);
  await drag(client, 1, 10);
  assert.deepEqual(await selectedIds(client),
    Array.from({ length: 10 }, (_, index) => `message-${index + 1}`),
    "downward drag should select rows 1 through 10");
  await repeatRender(client, []); // Simulate Streamlit echoing stale args during rerun.
  assert.deepEqual(await selectedIds(client),
    Array.from({ length: 10 }, (_, index) => `message-${index + 1}`),
    "a same-epoch rerun must not overwrite browser-local selection");

  await renderRows(client);
  const upwardStart = await checkboxCenter(client, 10);
  const upwardEnd = await checkboxCenter(client, 1);
  const upwardHit = await evaluate(client, `(() => {
    const point = { x: ${upwardStart.x}, y: ${upwardStart.y} };
    const hit = document.elementFromPoint(point.x, point.y);
    const viewportRect = document.getElementById('viewport').getBoundingClientRect();
    return { point, tag: hit && hit.tagName, className: hit && hit.className,
      viewportTop: viewportRect.top, viewportBottom: viewportRect.bottom };
  })()`);
  assert.equal(upwardHit.className, "drag-checkbox",
    `row 10 checkbox must be hit-testable: ${JSON.stringify(upwardHit)}`);
  await mouse(client, "mousePressed", upwardStart, 0, 1);
  assert.deepEqual(await selectedIds(client), ["message-10"],
    "the upward drag start should toggle row 10 on");
  await mouse(client, "mouseMoved", upwardEnd, 0, 1);
  await delay(30);
  assert.deepEqual(await selectedIds(client),
    Array.from({ length: 10 }, (_, index) => `message-${index + 1}`),
    "the upward pointer move should paint rows 1 through 10");
  await mouse(client, "mouseReleased", upwardEnd, 0, 0);
  await delay(50);
  assert.deepEqual(await selectedIds(client),
    Array.from({ length: 10 }, (_, index) => `message-${index + 1}`),
    "upward drag should select rows 1 through 10");

  await renderRows(client);
  await click(client, 2);
  await click(client, 6, 8); // CDP modifier bit 8 is Shift.
  assert.deepEqual(await selectedIds(client),
    ["message-2", "message-3", "message-4", "message-5", "message-6"]);
  await click(client, 4, 2); // CDP modifier bit 2 is Ctrl.
  assert.deepEqual(await selectedIds(client),
    ["message-2", "message-3", "message-5", "message-6"]);

  await evaluate(client, `(() => {
    const filter = document.getElementById('filter');
    filter.value = 'subject 3';
    filter.dispatchEvent(new Event('input', { bubbles: true }));
  })()`);
  assert.deepEqual(await selectedIds(client), ["message-3"]);
  await evaluate(client, `(() => {
    const filter = document.getElementById('filter');
    filter.value = '';
    filter.dispatchEvent(new Event('input', { bubbles: true }));
  })()`);
  assert.deepEqual(await selectedIds(client),
    ["message-2", "message-3", "message-5", "message-6"]);

  await renderRows(client);
  await evaluate(client, "document.getElementById('viewport').scrollTop = 0");
  const start = await checkboxCenter(client, 1);
  const edge = await evaluate(client, `(() => {
    const rect = document.getElementById('viewport').getBoundingClientRect();
    return { x: ${start.x}, y: rect.bottom - 4 };
  })()`);
  await mouse(client, "mousePressed", start, 0, 1);
  await mouse(client, "mouseMoved", edge, 0, 1);
  await delay(800);
  await mouse(client, "mouseReleased", edge, 0, 0);
  const scrollResult = await evaluate(client, `({
    top: document.getElementById('viewport').scrollTop,
    selected: document.querySelectorAll('tr.selected').length
  })`);
  assert.ok(scrollResult.top > 0, "Dragging at the bottom edge should auto-scroll");
  assert.ok(scrollResult.selected > 10, "Auto-scroll should continue painting rows");

  client.close();
  console.log("Browser pointer tests passed: down/up drag, Ctrl, Shift, filter stability, and auto-scroll.");
}

main().catch((error) => {
  console.error(error.stack || error.message);
  process.exit(1);
});
