export const num = (n: number | null | undefined) =>
  n == null ? "" : n.toLocaleString();

export function nodeTooltip(n: {
  label: string;
  kind: string;
  year?: number | null;
  cited?: number;
  works?: number | null;
  first_year?: number | null;
  last_year?: number | null;
  confidence?: string | null;
}): { title: string; lines: string[] } {
  const lines: string[] = [];
  if (n.year) lines.push(String(n.year));
  if (n.cited != null) lines.push(`${num(n.cited)} citations`);
  if (n.works != null) lines.push(`${n.works} shared work${n.works === 1 ? "" : "s"}`);
  if (n.first_year && n.last_year) {
    lines.push(
      n.first_year === n.last_year ? `${n.first_year}` : `${n.first_year}–${n.last_year}`,
    );
  }
  if (n.confidence) lines.push(`${n.confidence} confidence`);
  const role =
    n.kind === "reference" ? "cited by this paper"
    : n.kind === "citer" ? "cites this paper"
    : n.kind === "coauthor" ? "collaborator"
    : "";
  if (role) lines.push(role);
  return { title: n.label, lines };
}
