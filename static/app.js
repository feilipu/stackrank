(function () {
  function availableList() {
    return document.getElementById("available-list");
  }
  function poolList() {
    return document.getElementById("pool-list");
  }

  function setDisabled(disabled) {
    [availableList(), poolList()].forEach(function (el) {
      if (el && el._sortable) el._sortable.option("disabled", disabled);
    });
  }

  function bindSortable() {
    if (window.Sortable === undefined) return;
    var avail = availableList();
    var pool = poolList();
    if (!avail || !pool) return;
    if (avail._sortable) avail._sortable.destroy();
    if (pool._sortable) pool._sortable.destroy();

    avail._sortable = Sortable.create(avail, {
      group: "stackrank-pool",
      animation: 150,
      filter: "button",
      preventOnFilter: false,
      onAdd: function (evt) {
        var id = evt.item.getAttribute("data-id");
        setDisabled(true);
        htmx.ajax("POST", "/pool/remove/" + id, { target: "#pool-board", swap: "outerHTML" });
      },
    });
    pool._sortable = Sortable.create(pool, {
      group: "stackrank-pool",
      animation: 150,
      filter: "button",
      preventOnFilter: false,
      onAdd: function (evt) {
        var id = evt.item.getAttribute("data-id");
        setDisabled(true);
        htmx.ajax("POST", "/pool/add/" + id, { target: "#pool-board", swap: "outerHTML" });
      },
      onUpdate: function () {
        var values = Array.from(pool.children)
          .map(function (el) { return el.getAttribute("data-id"); })
          .filter(Boolean);
        setDisabled(true);
        htmx.ajax("POST", "/pool/reorder", {
          target: "#pool-board",
          swap: "outerHTML",
          values: { ids: values },
        });
      },
    });
  }

  document.body.addEventListener("htmx:beforeRequest", function () {
    setDisabled(true);
  });
  document.body.addEventListener("htmx:afterSwap", function () {
    bindSortable();
    setDisabled(false);
  });
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", bindSortable);
  } else {
    bindSortable();
  }
})();
