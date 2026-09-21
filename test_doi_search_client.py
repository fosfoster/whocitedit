#!/usr/bin/env python3
"""Browser-contract coverage for DOI aliases in deferred global search."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path


CLIENT = Path(__file__).parent / "web" / "assets" / "app.js"


HARNESS = r'''
function fail(message) { throw new Error(message); }

function Node(tag) {
  this.tagName = tag;
  this.children = [];
  this.className = "";
  this.href = "";
  this.hidden = false;
  this.listeners = {};
}
Object.defineProperty(Node.prototype, "firstChild", {
  get: function () { return this.children[0] || null; }
});
Object.defineProperty(Node.prototype, "textContent", {
  get: function () {
    return this.children.map(function (child) { return child.textContent; }).join("");
  },
  set: function (value) { this.children = [{ textContent: String(value) }]; }
});
Node.prototype.appendChild = function (child) { this.children.push(child); return child; };
Node.prototype.removeChild = function (child) {
  this.children.splice(this.children.indexOf(child), 1);
  return child;
};
Node.prototype.addEventListener = function (event, listener) { this.listeners[event] = listener; };

var form = new Node("form");
var box = new Node("input");
var results = new Node("div");
form.dataset = { root: "../", index: "../data/search-index.json" };
form.querySelector = function (selector) {
  return selector === "[data-search-input]" ? box :
    selector === ".search-results" ? results : null;
};

var fetches = [];
var records = [
  {
    kind: "work",
    id: "canonical-work",
    label: "Canonical Work",
    state: "complete",
    aliases: ["https://doi.org/10.5555/Resolver-Form"]
  },
  { kind: "author", id: "author-id", label: "Author Name", state: "high" }
];
var recordsBefore = JSON.stringify(records);
var document = {
  querySelector: function (selector) {
    return selector === "[data-global-search]" ? form : null;
  },
  createElement: function (tag) { return new Node(tag); },
  createTextNode: function (text) { return { textContent: String(text) }; }
};
function fetch(url) {
  fetches.push(url);
  if (url !== form.dataset.index) fail("global search fetched a non-local index: " + url);
  return Promise.resolve({ ok: true, json: function () { return Promise.resolve(records); } });
}

'''


ASSERTIONS = r'''
function input(value) {
  box.value = value;
  box.listeners.input();
  return new Promise(function (resolve) { setImmediate(resolve); });
}
function links() {
  return results.children.filter(function (node) { return node.tagName === "a"; });
}
function expectWorkResult(description) {
  var matches = links();
  if (matches.length !== 1) fail(description + " returned " + matches.length + " results");
  if (matches[0].href !== "../w/canonical-work/")
    fail(description + " did not retain the canonical work URL");
  if (matches[0].textContent !== "Canonical Work Paper complete record quality")
    fail(description + " changed the canonical work result presentation");
}

(async function () {
  await input("");
  if (fetches.length !== 0) fail("empty global query fetched an index");

  await input("10.5555/rEsOlVeR-fOrM");
  expectWorkResult("mixed-case bare DOI query");
  if (fetches.length !== 1 || fetches[0] !== "../data/search-index.json")
    fail("non-empty global query did not make exactly one local index request");

  await input("hTtPs://DoI.oRg/10.5555/ReSoLvEr-FoRm");
  expectWorkResult("mixed-case resolver DOI query");
  if (fetches.length !== 1) fail("cached global index was fetched more than once");

  await input("aUtHoR nAmE");
  var matches = links();
  if (matches.length !== 1 || matches[0].href !== "../a/author-id/" ||
      matches[0].textContent !== "Author Name Author high confidence")
    fail("DOI alias matching altered ordinary entity matching");
  if (JSON.stringify(records) !== recordsBefore)
    fail("DOI alias matching mutated search records");

  console.log("DOI global-search client contract ok");
})().catch(function (error) { console.error(error.message); process.exitCode = 1; });
'''


def main() -> int:
    client = CLIENT.read_text()
    completed = subprocess.run(
        ["node", "-e", HARNESS + client + ASSERTIONS], text=True, capture_output=True
    )
    if completed.stdout:
        print(completed.stdout, end="")
    if completed.stderr:
        print(completed.stderr, end="", file=sys.stderr)
    if completed.returncode:
        print("test_doi_search_client: FAILED")
        return 1
    print("test_doi_search_client: ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
