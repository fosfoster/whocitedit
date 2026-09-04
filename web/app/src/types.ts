export type NodeKind = "focus" | "reference" | "citer" | "coauthor";

export interface GraphNode {
  id: string;
  label: string;
  kind: NodeKind;
  x: number;
  y: number;
  /** Works only. */
  year?: number | null;
  cited?: number;
  /** Authors only. */
  works?: number | null;
  weight?: number | null;
  first_year?: number | null;
  last_year?: number | null;
  confidence?: string | null;
}

export interface GraphEdge {
  /** `s` cites `t` on a citation graph; an unordered pair on a collaboration graph. */
  s: string;
  t: string;
  w?: number;
  inner?: boolean;
}

export interface GraphPayload {
  width: number;
  height: number;
  nodes: GraphNode[];
  edges: GraphEdge[];
  shown: number;
  available: number;
  /** Set by render.py so the island knows which wrapper to build. */
  kind: "citation" | "collaboration";
  /** The entity the page is about, used for hrefs and for the focus ring. */
  focus: string;
  /** Relative prefix for a sibling entity page, e.g. "../". */
  href_prefix: string;
}

/** A node once the simulation owns it. */
export interface SimNode extends GraphNode {
  fx?: number | null;
  fy?: number | null;
  vx?: number;
  vy?: number;
  index?: number;
}
