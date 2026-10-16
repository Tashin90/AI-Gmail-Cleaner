const test = require("node:test");
const assert = require("node:assert/strict");
const { DragSelectionModel } = require("../../drag_select_component/selection_model.js");

const ids = Array.from({ length: 10 }, (_, index) => `message-${index + 1}`);

test("dragging downward selects every crossed stable ID", () => {
  const model = new DragSelectionModel();
  model.setVisibleIds(ids);
  model.paintBetween("message-1", "message-10", true);
  assert.deepEqual(model.toArray(ids), ids);
});

test("dragging upward selects the same continuous range", () => {
  const model = new DragSelectionModel();
  model.setVisibleIds(ids);
  model.paintBetween("message-10", "message-1", true);
  assert.deepEqual(model.toArray(ids), ids);
});

test("individual toggle does not change other selected IDs", () => {
  const model = new DragSelectionModel(["message-2", "message-4"]);
  model.setVisibleIds(ids);
  model.toggle("message-4");
  model.toggle("message-7");
  assert.deepEqual(model.toArray(ids), ["message-2", "message-7"]);
});

test("shift range follows current filtered and sorted IDs", () => {
  const visible = ["message-9", "message-5", "message-2"];
  const model = new DragSelectionModel();
  model.setVisibleIds(visible);
  model.selectRange("message-9", "message-2");
  assert.deepEqual(model.toArray(ids), ["message-2", "message-5", "message-9"]);
});

test("reordering rows never changes which IDs are selected", () => {
  const model = new DragSelectionModel(["message-3", "message-8"]);
  model.setVisibleIds([...ids].reverse());
  assert.deepEqual(model.toArray(ids), ["message-3", "message-8"]);
});
