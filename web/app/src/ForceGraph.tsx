import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  forceCenter,
  forceCollide,
  forceLink,
  forceManyBody,
  forceSimulation,
  forceX,
  forceY,
  type Simulation,
} from "d3-force";
import { drag as d3drag } from "d3-drag";
import { select } from "d3-selection";
import { zoom as d3zoom, zoomIdentity, type ZoomTransform } from "d3-zoom";
import type { GraphEdge, GraphNode, SimNode } from "./types";
import { nodeTooltip } from "./format";
import { prefersReducedMotion, radiusScale } from "./theme";

interface Props {
  nodes: GraphNode[];
  edges: GraphEdge[];
  width: number;
  height: number;
  focus: string;
  hrefFor: (id: string) => string;
  /** When set, x is pinned to this value and only y relaxes. */
  pinX?: (n: GraphNode) => number | null;
  /** Drawn under the graph in the pinned mode: an axis. */
  axis?: React.ReactNode;
  /** Ids to draw; anything else is filtered out entirely. */
  visible?: Set<string>;
  directed?: boolean;
}

const LABEL_ZOOM_ALL = 1.55;
const TOP_LABELS = 8;

export function ForceGraph({
  nodes,
  edges,
  width,
  height,
  focus,
  hrefFor,
  pinX,
  axis,
  visible,
  directed = false,
}: Props) {
  const svgRef = useRef<SVGSVGElement | null>(null);
  const simRef = useRef<Simulation<SimNode, undefined> | null>(null);
  const [tick, setTick] = useState(0);
  const [transform, setTransform] = useState<ZoomTransform>(zoomIdentity);
  const [hover, setHover] = useState<string | null>(null);

  const shown = useMemo(
    () => (visible ? nodes.filter((n) => visible.has(n.id)) : nodes),
    [nodes, visible],
  );
  const shownIds = useMemo(() => new Set(shown.map((n) => n.id)), [shown]);
  const shownEdges = useMemo(
    () => edges.filter((e) => shownIds.has(e.s) && shownIds.has(e.t)),
    [edges, shownIds],
  );

  const radius = useMemo(() => radiusScale(nodes), [nodes]);

  // The simulation owns one mutable node object per id for its whole life, so a
  // filter change moves the survivors rather than teleporting the whole graph.
  const simNodes = useRef<Map<string, SimNode>>(new Map());
  for (const n of nodes) {
    if (!simNodes.current.has(n.id)) simNodes.current.set(n.id, { ...n });
  }

  const neighbours = useMemo(() => {
    const map = new Map<string, Set<string>>();
    for (const e of shownEdges) {
      if (!map.has(e.s)) map.set(e.s, new Set());
      if (!map.has(e.t)) map.set(e.t, new Set());
      map.get(e.s)!.add(e.t);
      map.get(e.t)!.add(e.s);
    }
    return map;
  }, [shownEdges]);

  useEffect(() => {
    const active = shown.map((n) => simNodes.current.get(n.id)!);
    const links = shownEdges.map((e) => ({ source: e.s, target: e.t, w: e.w ?? 1 }));

    simRef.current?.stop();
    // Scale the forces to the space and the node count rather than hardcoding
    // them. Fixed constants tuned on one graph leave every other one wrong: 36
    // nodes at a fixed 70px link distance collapsed into a tight rosette in the
    // middle of the canvas with two thirds of it empty. `k` is the classic
    // ideal edge length, sqrt(area / n).
    const k = Math.sqrt((width * height) / Math.max(active.length, 1));
    const sim = forceSimulation<SimNode>(active)
      .force(
        "link",
        forceLink<SimNode, { source: string; target: string; w: number }>(links)
          .id((d) => d.id)
          .distance((l) => k * 0.95 + 40 / (1 + l.w))
          .strength((l) => Math.min(0.9, 0.18 + l.w * 0.12)),
      )
      .force("charge", forceManyBody().strength(-k * 4).distanceMax(width * 0.75))
      .force("collide", forceCollide<SimNode>().radius((d) => radius(d) + 7))
      .alphaDecay(0.045);

    if (pinX) {
      // Pinned mode: x carries time, so only y is free. A center force here
      // would fight the axis and slide everything off its own year.
      for (const n of active) {
        const x = pinX(n);
        n.fx = x == null ? undefined : x;
      }
      sim.force("y", forceY(height / 2).strength(0.06));
    } else {
      for (const n of active) n.fx = undefined;
      sim.force("center", forceCenter(width / 2, height / 2));
      sim.force("x", forceX(width / 2).strength(0.03));
      sim.force("y", forceY(height / 2).strength(0.05));
    }

    // The focus node is the subject of the page; anchoring it keeps the reader
    // oriented while everything else rearranges around it.
    const centre = simNodes.current.get(focus);
    if (centre && !pinX) {
      centre.fx = width / 2;
      centre.fy = height / 2;
    } else if (centre) {
      centre.fy = height / 2;
    }

    simRef.current = sim;

    if (prefersReducedMotion()) {
      sim.stop();
      sim.tick(260);
      setTick((t) => t + 1);
      return () => void sim.stop();
    }
    sim.on("tick", () => setTick((t) => t + 1));
    return () => {
      sim.on("tick", null);
      sim.stop();
    };
  }, [shown, shownEdges, width, height, focus, pinX, radius]);

  const zoomRef = useRef<ReturnType<typeof d3zoom<SVGSVGElement, unknown>> | null>(null);

  useEffect(() => {
    const svg = svgRef.current;
    if (!svg) return;
    const behaviour = d3zoom<SVGSVGElement, unknown>()
      .scaleExtent([0.45, 5])
      .on("zoom", (event) => setTransform(event.transform));
    zoomRef.current = behaviour;
    select(svg).call(behaviour);
    return () => void select(svg).on(".zoom", null);
  }, []);

  const attachDrag = useCallback(
    (el: SVGGElement | null, id: string) => {
      if (!el) return;
      const behaviour = d3drag<SVGGElement, unknown>()
        .on("start", (event) => {
          if (!event.active) simRef.current?.alphaTarget(0.25).restart();
          const n = simNodes.current.get(id)!;
          n.fx = n.x;
          n.fy = n.y;
        })
        .on("drag", (event) => {
          const n = simNodes.current.get(id)!;
          // The pointer arrives in screen space; the graph lives in zoomed
          // space, so without this a node lags the cursor at any zoom but 1.
          const [x, y] = transform.invert([event.x, event.y]);
          n.fx = x;
          n.fy = y;
        })
        .on("end", (event) => {
          if (!event.active) simRef.current?.alphaTarget(0);
          const n = simNodes.current.get(id)!;
          if (id !== focus || pinX) n.fx = pinX ? n.fx : undefined;
          if (id !== focus) n.fy = undefined;
        });
      select(el).call(behaviour);
    },
    [transform, focus, pinX],
  );

  const resetView = () => {
    // Reset THROUGH the live behaviour, not by setting state. d3-zoom keeps its
    // own transform on the node; assigning React state alone leaves the two out
    // of step and the next scroll jumps back to where the user had been.
    if (svgRef.current && zoomRef.current) {
      select(svgRef.current).call(zoomRef.current.transform, zoomIdentity);
    }
    setTransform(zoomIdentity);
  };

  const near = hover ? neighbours.get(hover) ?? new Set<string>() : null;
  const dimmed = (id: string) => hover != null && id !== hover && !near!.has(id);

  const ranked = useMemo(
    () =>
      [...shown]
        .sort((a, b) => (b.cited ?? b.works ?? 0) - (a.cited ?? a.works ?? 0))
        .slice(0, TOP_LABELS)
        .map((n) => n.id),
    [shown],
  );
  const labelled = new Set(ranked);

  const showLabel = (n: SimNode) =>
    n.id === focus ||
    n.id === hover ||
    (near?.has(n.id) ?? false) ||
    transform.k >= LABEL_ZOOM_ALL ||
    labelled.has(n.id);

  const positioned = shown.map((n) => simNodes.current.get(n.id)!);
  const byId = new Map(positioned.map((n) => [n.id, n]));
  const hovered = hover ? byId.get(hover) : null;
  const tip = hovered ? nodeTooltip(hovered) : null;
  void tick;

  return (
    <div className="fg">
      <svg
        ref={svgRef}
        viewBox={`0 0 ${width} ${height}`}
        role="img"
        aria-label="Interactive graph. Drag to pan, scroll to zoom, hover a node for detail."
        onMouseLeave={() => setHover(null)}
      >
        {directed && (
          <defs>
            <marker
              id="fg-arrow"
              viewBox="0 0 10 10"
              refX="9"
              refY="5"
              markerWidth="5"
              markerHeight="5"
              orient="auto-start-reverse"
            >
              <path d="M0,1 L9,5 L0,9 z" className="fg-arrowhead" />
            </marker>
          </defs>
        )}
        <g transform={transform.toString()}>
          {axis}
          <g className="fg-edges">
            {shownEdges.map((e, i) => {
              const a = byId.get(e.s);
              const b = byId.get(e.t);
              if (!a || !b) return null;
              const lit = hover != null && (e.s === hover || e.t === hover);
              return (
                <line
                  key={`${e.s}-${e.t}-${i}`}
                  x1={a.x}
                  y1={a.y}
                  x2={b.x}
                  y2={b.y}
                  className={
                    "fg-edge" +
                    (e.inner ? " inner" : "") +
                    (lit ? " lit" : "") +
                    (hover != null && !lit ? " dim" : "")
                  }
                  strokeWidth={e.w ? Math.min(0.8 + e.w * 0.9, 4.5) : 1.2}
                  markerEnd={directed && lit ? "url(#fg-arrow)" : undefined}
                />
              );
            })}
          </g>
          <g className="fg-nodes">
            {positioned.map((n) => {
              const r = radius(n);
              return (
                <a
                  key={n.id}
                  href={n.id === focus ? undefined : hrefFor(n.id)}
                  className={`fg-node ${n.kind}${dimmed(n.id) ? " dim" : ""}${
                    n.id === hover ? " lit" : ""
                  }`}
                >
                  <g
                    ref={(el) => attachDrag(el, n.id)}
                    onMouseEnter={() => setHover(n.id)}
                    onFocus={() => setHover(n.id)}
                    tabIndex={0}
                  >
                    {/* A generous invisible target: an 8px circle is a hard
                        thing to hit, and harder on a touch screen. */}
                    <circle cx={n.x} cy={n.y} r={Math.max(r + 8, 16)} className="fg-hit" />
                    <circle cx={n.x} cy={n.y} r={r} className="fg-dot" />
                    {showLabel(n) && (
                      <text
                        className="fg-label"
                        x={n.x}
                        y={(n.y ?? 0) - r - 6}
                        textAnchor="middle"
                      >
                        {n.label.length > 34 ? n.label.slice(0, 33) + "…" : n.label}
                      </text>
                    )}
                  </g>
                </a>
              );
            })}
          </g>
        </g>
      </svg>

      {tip && (
        <div
          className="fg-tip"
          style={{
            left: `${(((hovered!.x ?? 0) * transform.k + transform.x) / width) * 100}%`,
            top: `${(((hovered!.y ?? 0) * transform.k + transform.y) / height) * 100}%`,
          }}
          role="status"
        >
          <b>{tip.title}</b>
          {tip.lines.map((l) => (
            <span key={l}>{l}</span>
          ))}
        </div>
      )}

      <button type="button" className="fg-reset" onClick={resetView}>
        Reset view
      </button>
    </div>
  );
}
