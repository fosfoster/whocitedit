/* Search only local, renderer-copied indexes. The static HTML remains complete. */
(function () {
  var MAX_RESULTS = 60;
  var globalRoutes = { work: "w", author: "a", institution: "i", topic: "t" };
  var globalTypes = { work: "Paper", author: "Author", institution: "Institution", topic: "Topic" };
  var globalBadges = {
    author: function (state) { return state ? { className: state, text: state + " confidence" } : null; },
    work: function (state) { return state ? { className: state, text: state + " record quality" } : null; }
  };
  var collectionRoutes = { works: "w", authors: "a", institutions: "i", topics: "t" };
  var globalRows = null;
  var globalLoad = null;

  function clear(node) {
    while (node.firstChild) node.removeChild(node.firstChild);
  }

  function paragraph(region, value, className) {
    var message = document.createElement("p");
    message.className = className || "faint";
    message.textContent = value;
    region.appendChild(message);
  }

  function link(region, href, label, detail, badge) {
    var item = document.createElement("a");
    item.href = href;
    item.appendChild(document.createTextNode(label));
    if (detail) {
      var meta = document.createElement("small");
      meta.textContent = detail;
      item.appendChild(document.createTextNode(" "));
      item.appendChild(meta);
    }
    if (badge) {
      var chip = document.createElement("span");
      chip.className = "badge " + badge.className;
      chip.textContent = badge.text;
      item.appendChild(document.createTextNode(" "));
      item.appendChild(chip);
    }
    region.appendChild(item);
  }

  function normalized(value) {
    return String(value || "").toLowerCase();
  }

  function loadGlobal(index) {
    if (globalRows) return Promise.resolve(globalRows);
    if (globalLoad) return globalLoad;
    globalLoad = fetch(index).then(function (response) {
      if (!response.ok) throw new Error("Global search index request failed");
      return response.json();
    }).then(function (rows) {
      globalRows = rows;
      return rows;
    }).catch(function (error) {
      globalLoad = null;
      throw error;
    });
    return globalLoad;
  }

  function rankGlobalMatches(rows, query) {
    var exact = [];
    var substring = [];
    rows.forEach(function (row) {
      if (normalized(row.label) === query || normalized(row.id) === query) {
        exact.push(row);
        return;
      }
      var isSubstring = normalized(row.label).indexOf(query) >= 0 ||
        normalized(row.id).indexOf(query) >= 0 ||
        (row.aliases || []).some(function (alias) {
          return normalized(alias).indexOf(query) >= 0;
        });
      if (isSubstring) substring.push(row);
    });
    return exact.concat(substring);
  }

  function initGlobalSearch(form) {
    var box = form.querySelector("[data-search-input]");
    var results = form.querySelector(".search-results");
    if (!box || !results) return;
    form.addEventListener("submit", function (event) { event.preventDefault(); });

    function render(matches) {
      clear(results);
      if (!matches.length) {
        paragraph(results, "No results match your search.");
        return;
      }
      var shown = matches.slice(0, MAX_RESULTS);
      paragraph(results, shown.length === matches.length ?
        shown.length + " result" + (shown.length === 1 ? "" : "s") + "." :
        "Showing " + shown.length + " of " + matches.length + " results.", "search-summary");
      shown.forEach(function (row) {
        var route = globalRoutes[row.kind];
        if (!route) return;
        var badgeFor = globalBadges[row.kind];
        link(results, form.dataset.root + route + "/" + encodeURIComponent(row.id) + "/",
             row.label || row.id, globalTypes[row.kind], badgeFor && badgeFor(row.state));
      });
    }

    box.addEventListener("input", function () {
      var query = normalized(box.value.trim());
      clear(results);
      if (!query) return;
      loadGlobal(form.dataset.index).then(function (rows) {
        if (query !== normalized(box.value.trim())) return;
        render(rankGlobalMatches(rows, query));
      }).catch(function () {
        if (query === normalized(box.value.trim())) {
          paragraph(results, "Search is unavailable. Please try again.");
        }
      });
    });
  }

  function initCollectionSearch(box) {
    var results = document.getElementById(box.getAttribute("aria-controls"));
    var table = document.getElementById("collection-table");
    var route = collectionRoutes[box.dataset.kind];
    var rows = null;
    if (!results || !table || !route) return;

    function load() {
      if (rows) return Promise.resolve(rows);
      return fetch(box.dataset.index).then(function (response) {
        if (!response.ok) throw new Error("Collection search index request failed");
        return response.json();
      }).then(function (data) { rows = data; return rows; });
    }

    function detail(row) {
      if (box.dataset.kind === "works") return (row.year || "") + " · " +
        (row.cited || 0).toLocaleString() + " cited";
      if (box.dataset.kind === "authors") return (row.band || "") + " confidence · " +
        (row.works || 0) + " work(s)";
      if (box.dataset.kind === "institutions") return (row.authors || 0) + " author(s) · " +
        (row.works || 0) + " work(s)";
      return (row.works || 0) + " work(s) · " + (row.authors || 0) + " author(s)";
    }

    function render(matches, query) {
      clear(results);
      if (!query) {
        table.hidden = false;
        return;
      }
      table.hidden = true;
      if (!matches.length) {
        paragraph(results, "Nothing matches.");
        return;
      }
      matches.slice(0, MAX_RESULTS).forEach(function (row) {
        link(results, "../" + route + "/" + encodeURIComponent(row.id) + "/",
             row.name || row.title || row.id, detail(row));
      });
    }

    var timer;
    box.addEventListener("input", function () {
      clearTimeout(timer);
      timer = setTimeout(function () {
        var query = normalized(box.value.trim());
        if (!query) return render([], "");
        load().then(function (all) {
          if (query !== normalized(box.value.trim())) return;
          render(all.filter(function (row) {
            return normalized(row.title || row.name || row.id).indexOf(query) >= 0;
          }), query);
        }).catch(function () {
          if (query !== normalized(box.value.trim())) return;
          table.hidden = true;
          clear(results);
          paragraph(results, "Search is unavailable. Please try again.");
        });
      }, 120);
    });
  }

  var global = document.querySelector("[data-global-search]");
  if (global) initGlobalSearch(global);
  var collection = document.querySelector("[data-collection-search]");
  if (collection) initCollectionSearch(collection);
})();
