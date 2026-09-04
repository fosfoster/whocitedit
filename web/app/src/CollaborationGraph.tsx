import { useMemo, useState } from "react";
import { ForceGraph } from "./ForceGraph";
import type { GraphPayload } from "./types";

/** A collaboration network is not one network; it is a different one each year.
 *
 * The static page can only show the career total, which reads as though every
 * one of these people were a current collaborator. Brushing a year range is the
 * part a list of co-author names cannot do at all: drag the window and the
 * groups someone actually worked in appear and dissolve.
 */
export function CollaborationGraph({ data }: { data: GraphPayload }) {
  const bounds = useMemo(() => {
    const ys = data.nodes
      .flatMap((n) => [n.first_year, n.last_year])
      .filter((y): y is number => !!y);
    return ys.length ? { min: Math.min(...ys), max: Math.max(...ys) } : null;
  }, [data.nodes]);

  const [from, setFrom] = useState(bounds?.min ?? 0);

  const visible = useMemo(() => {
    if (!bounds) return undefined;
    const keep = new Set<string>([data.focus]);
    for (const n of data.nodes) {
      if (n.id === data.focus) continue;
      // Kept when the collaboration was still live at or after the cut. A pair
      // whose last shared paper predates the window is not a current tie.
      if ((n.last_year ?? bounds.max) >= from) keep.add(n.id);
    }
    return keep;
  }, [data.nodes, data.focus, from, bounds]);

  const kept = (visible?.size ?? data.nodes.length) - 1;

  return (
    <div className="island">
      <div className="island-bar">
        {bounds && bounds.min < bounds.max && (
          <label className="brush">
            <span>Active since</span>
            <input
              type="range"
              min={bounds.min}
              max={bounds.max}
              value={from}
              onChange={(ev) => setFrom(Number(ev.target.value))}
            />
            <b>{from}</b>
          </label>
        )}
        <p className="island-hint">
          {kept} of {data.nodes.length - 1} collaborators
          {bounds && from > bounds.min ? ` still active in ${from} or later` : ""}.
          Line weight is collaboration weight, not shared-paper count.
        </p>
      </div>
      <ForceGraph
        nodes={data.nodes}
        edges={data.edges}
        width={data.width}
        height={data.height}
        focus={data.focus}
        hrefFor={(id) => `${data.href_prefix}${id}/`}
        visible={visible}
      />
    </div>
  );
}
