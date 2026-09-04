/* Search over the local index file the page names. The only JavaScript on this site:
   every page, every graph and every number is already in the HTML. */
(function () {
  var box = document.getElementById("q");
  if (!box) return;
  var hits = document.getElementById("hits");
  var table = document.getElementById("table");
  var kind = box.dataset.kind;
  var route = { works: "w", authors: "a", institutions: "i", topics: "t" }[kind];
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
      var label = r.name || r.title || r.id;
      var details;
      if (kind === "works") details = (r.year || "") + " &middot; " + (r.cited || 0).toLocaleString() + " cited";
      else if (kind === "authors") details = (r.band || "") + " confidence &middot; " + (r.works || 0) + " work(s)";
      else if (kind === "institutions") details = (r.authors || 0) + " author(s) &middot; " + (r.works || 0) + " work(s)";
      else details = (r.works || 0) + " work(s) &middot; " + (r.authors || 0) + " author(s)";
      return '<a href="../' + route + '/' + encodeURIComponent(r.id) + '/">' + esc(label) +
        " <small>" + details + "</small></a>";
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
          return (r.title || r.name || r.id).toLowerCase().indexOf(q) >= 0;
        }), q);
      });
    }, 120);
  });
})();
