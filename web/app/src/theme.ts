/** Radius is the one visual channel the simulation needs in numbers.
 *
 * Everything else -- fill, stroke, dimming -- is a CSS class, so the light and
 * dark palettes live once in style.css and a theme change needs no JavaScript.
 */
export function radiusScale(nodes: { cited?: number; works?: number | null; kind: string }[]) {
  const magnitude = (n: { cited?: number; works?: number | null }) =>
    Math.max(n.cited ?? n.works ?? 1, 0);
  const max = Math.max(1, ...nodes.map(magnitude));
  return (n: { cited?: number; works?: number | null; kind: string }) => {
    if (n.kind === "focus") return 13;
    // Square root, because area should carry magnitude rather than radius --
    // a linear radius overstates a big node by its square.
    return 5 + 12 * Math.sqrt(magnitude(n) / max);
  };
}

export const prefersReducedMotion = () =>
  typeof window !== "undefined" &&
  window.matchMedia?.("(prefers-reduced-motion: reduce)").matches === true;
