(function (root, factory) {
  const exports = factory();
  if (typeof module === "object" && module.exports) {
    module.exports = exports;
  }
  root.DragSelectionModel = exports.DragSelectionModel;
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  "use strict";

  class DragSelectionModel {
    constructor(selectedIds = []) {
      this.selected = new Set(selectedIds);
      this.visibleIds = [];
    }

    replace(selectedIds) {
      this.selected = new Set(selectedIds);
    }

    retain(validIds) {
      const valid = new Set(validIds);
      this.selected = new Set([...this.selected].filter((id) => valid.has(id)));
    }

    setVisibleIds(ids) {
      this.visibleIds = [...ids];
    }

    has(id) {
      return this.selected.has(id);
    }

    set(id, desired) {
      if (desired) {
        this.selected.add(id);
      } else {
        this.selected.delete(id);
      }
    }

    toggle(id) {
      const desired = !this.has(id);
      this.set(id, desired);
      return desired;
    }

    paintBetween(fromId, toId, desired = true) {
      const from = this.visibleIds.indexOf(fromId);
      const to = this.visibleIds.indexOf(toId);
      if (from < 0 || to < 0) {
        this.set(toId, desired);
        return;
      }
      const start = Math.min(from, to);
      const end = Math.max(from, to);
      for (let index = start; index <= end; index += 1) {
        this.set(this.visibleIds[index], desired);
      }
    }

    selectRange(anchorId, targetId) {
      if (!anchorId || !this.visibleIds.includes(anchorId)) {
        this.set(targetId, true);
        return;
      }
      this.paintBetween(anchorId, targetId, true);
    }

    toArray(order = []) {
      if (!order.length) {
        return [...this.selected];
      }
      return order.filter((id) => this.selected.has(id));
    }
  }

  return { DragSelectionModel };
});
