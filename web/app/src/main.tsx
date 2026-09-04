import { createRoot } from "react-dom/client";
import { CitationGraph } from "./CitationGraph";
import { CollaborationGraph } from "./CollaborationGraph";
import type { GraphPayload } from "./types";

/** Islands, not an application.
 *
 * Every page on this site is complete static HTML with the graph already drawn
 * as SVG in the markup -- that is what makes it crawlable, instant, and
 * identical for every reader, and it is the thing the competing tools do not
 * do. This file finds those figures and upgrades them in place. The static SVG
 * is only hidden once React has actually mounted, so a failed bundle, a slow
 * network or JavaScript switched off leaves the page exactly as it was rather
 * than leaving a hole where the graph used to be.
 */
function boot() {
  const figures = document.querySelectorAll<HTMLElement>("[data-island]");
  figures.forEach((figure) => {
    const script = figure.querySelector<HTMLScriptElement>("script.graph-data");
    const mount = figure.querySelector<HTMLElement>(".island-mount");
    const fallback = figure.querySelector<HTMLElement>(".static-graph");
    if (!script?.textContent || !mount) return;

    let data: GraphPayload;
    try {
      data = JSON.parse(script.textContent) as GraphPayload;
    } catch {
      return;
    }
    if (!data.nodes || data.nodes.length < 2) return;

    try {
      createRoot(mount).render(
        data.kind === "collaboration" ? (
          <CollaborationGraph data={data} />
        ) : (
          <CitationGraph data={data} />
        ),
      );
      if (fallback) fallback.hidden = true;
      figure.classList.add("upgraded");
    } catch {
      // Leave the server-rendered SVG visible. A broken upgrade must never be
      // worse than no upgrade.
      if (fallback) fallback.hidden = false;
    }
  });
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", boot, { once: true });
} else {
  boot();
}
