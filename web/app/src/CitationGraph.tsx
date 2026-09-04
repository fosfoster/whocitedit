import { useCallback, useMemo, useState } from "react";
import { ForceGraph } from "./ForceGraph";
import type { GraphPayload } from "./types";

/** Force shows the neighbourhood's shape; time shows which way it flows.
 *
 * A citation graph is a directed acyclic thing through time -- a paper can only
 * cite what already existed -- and a force layout throws that away completely.
 * Pinning x to the publication year puts every reference to the left of the
 * paper and every citer to the right, so the reader sees the influence run in
 * one direction instead of inferring it from two colours.
 */
/** `#time` in the URL selects the time layout, and choosing it writes the hash.
 *
 * So a link to a particular view is shareable, the back button works, and a
 * reader who wanted the timeline does not have to find the toggle again.
 */
function initialMode(): "force" | "time" {
  if (typeof window === "undefined") return "force";
  return window.location.hash === "#time" ? "time" : "force";
}

export function CitationGraph({ data }: { data: GraphPayload }) {
  const [mode, setModeState] = useState<"force" | "time">(initialMode);

  const setMode = (next: "force" | "time") => {
    setModeState(next);
    if (typeof window !== "undefined") {
      const url = new URL(window.location.href);
      url.hash = next === "time" ? "time" : "";
      window.history.replaceState(null, "", url.toString());
    }
  };

  const years = data.nodes.map((n) => n.year).filter((y): y is number => !!y);
  const min = Math.min(...years);
  const max = Math.max(...years);
  const pad = 70;
  const span = Math.max(max - min, 1);
  const xOf = useCallback(
    (year: number) => pad + ((year - min) / span) * (data.width - pad * 2),
    [min, span, data.width],
  );

  const pinX = useCallback(
    (n: { year?: number | null }) => (n.year ? xOf(n.year) : null),
    [xOf],
  );

  const ticks = useMemo(() => {
    if (!years.length) return [];
    const step = span <= 12 ? 2 : span <= 30 ? 5 : 10;
    const first = Math.ceil(min / step) * step;
    const out: number[] = [];
    for (let y = first; y <= max; y += step) out.push(y);
    return out;
  }, [min, max, span, years.length]);

  const axis = (
    <g className="fg-axis" aria-hidden="true">
      {ticks.map((y) => (
        <g key={y}>
          <line x1={xOf(y)} y1={22} x2={xOf(y)} y2={data.height - 22} />
          <text x={xOf(y)} y={16} textAnchor="middle">
            {y}
          </text>
        </g>
      ))}
    </g>
  );

  return (
    <div className="island">
      <div className="island-bar">
        <div className="seg" role="group" aria-label="Layout">
          <button
            type="button"
            className={mode === "force" ? "on" : ""}
            aria-pressed={mode === "force"}
            onClick={() => setMode("force")}
          >
            Neighbourhood
          </button>
          <button
            type="button"
            className={mode === "time" ? "on" : ""}
            aria-pressed={mode === "time"}
            onClick={() => setMode("time")}
            disabled={years.length < 2}
          >
            Over time
          </button>
        </div>
        <p className="island-hint">
          {mode === "time"
            ? `Position left to right is the publication year, ${min}–${max}. Everything left of this paper is a work it cites.`
            : "Drag a node, scroll to zoom, hover for the full title."}
        </p>
      </div>
      <ForceGraph
        nodes={data.nodes}
        edges={data.edges}
        width={data.width}
        height={data.height}
        focus={data.focus}
        directed
        hrefFor={(id) => `${data.href_prefix}${id}/`}
        pinX={mode === "time" ? pinX : undefined}
        axis={mode === "time" ? axis : undefined}
      />
    </div>
  );
}
