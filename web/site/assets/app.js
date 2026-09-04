/* Search over the index file the page names. The only JavaScript on this site:
   every page, every graph and every number is already in the HTML. */
(function () {
  var box = document.getElementById("q");
  if (!box) return;
  var hits = document.getElementById("hits");
  var table = document.getElementById("table");
  var kind = box.dataset.kind;
  var rows = null;

  function load() {
    if (rows) return Promise.resolve(rows);
    return fetch(box.dataset.index)
      .then(function (r) { return r.json(); })
      .then(function (d) { rows = d; return rows; });
  }

  function render(matches, q) {
    if (!q) { hits.innerHTML = ""; table.hidden = false; return; }
    table.hidden = true;
    hits.innerHTML = matches.slice(0, 60).map(function (r) {
      return kind === "works"
        ? '<a href="../w/' + r.id + '/">' + esc(r.title) + " <small>" + (r.year || "") +
          " &middot; " + r.cited.toLocaleString() + " cited</small></a>"
        : '<a href="../a/' + r.id + '/">' + esc(r.name) + " <small>" + r.band +
          " confidence &middot; " + r.works + " work(s)</small></a>";
    }).join("") || '<p class="faint">Nothing matches.</p>';
  }

  function esc(s) {
    return String(s).replace(/[&<>"]/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c];
    });
  }

  var timer;
  box.addEventListener("input", function () {
    clearTimeout(timer);
    timer = setTimeout(function () {
      var q = box.value.trim().toLowerCase();
      if (!q) return render([], "");
      load().then(function (all) {
        render(all.filter(function (r) {
          return (kind === "works" ? r.title : r.name).toLowerCase().indexOf(q) >= 0;
        }), q);
      });
    }, 120);
  });
})();
