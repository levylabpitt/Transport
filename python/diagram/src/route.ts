// Cable geometry, kept apart from React so the layout tests can check it.
//
// Routes:
//   direct  straight across, or across-down-across with the step half way
//   step    across-down-across with the step at midX (beside the lock-in cards)
//   lane    from a lock-in AO: out to outX, along the bottom lane of the row it serves
//           (laneY), and up into the target at turnX, so it never crosses the boxes of
//           the strips in between

export type Pt = [number, number];

export type CableData = {
  route: "direct" | "step" | "lane";
  pads: string[];     // the pads whose signal it carries, 0 to 2 (traced on hover)
  colors: string[];   // their colors
  midX?: number;
  laneY?: number;
  turnX?: number;
  outX?: number;
  from?: Pt;          // where the layout expects the cable to start and end (tests, and a check
  to?: Pt;            // against where React Flow actually puts the terminals)
};

export function points(sx: number, sy: number, tx: number, ty: number, d: CableData): Pt[] {
  if (d.route === "lane")
    return [[sx, sy], [d.outX!, sy], [d.outX!, d.laneY!], [d.turnX!, d.laneY!], [d.turnX!, ty], [tx, ty]];
  if (Math.abs(sy - ty) < 0.5) return [[sx, sy], [tx, ty]];
  const mx = d.route === "step" && d.midX != null ? Math.max(d.midX, sx + 10) : (sx + tx) / 2;
  return [[sx, sy], [mx, sy], [mx, ty], [tx, ty]];
}

/** The polyline moved sideways by off; right angles stay square. */
export function offset(pts: Pt[], off: number): Pt[] {
  const norm = (a: Pt, b: Pt): Pt => {
    const dx = b[0] - a[0], dy = b[1] - a[1], l = Math.hypot(dx, dy) || 1;
    return [(dy / l) * off, (-dx / l) * off];
  };
  return pts.map((p, i) => {
    const n1 = i > 0 ? norm(pts[i - 1], p) : null;
    const n2 = i < pts.length - 1 ? norm(p, pts[i + 1]) : null;
    if (!n1) return [p[0] + n2![0], p[1] + n2![1]];
    if (!n2) return [p[0] + n1[0], p[1] + n1[1]];
    const same = Math.abs(n1[0] - n2[0]) < 1e-6 && Math.abs(n1[1] - n2[1]) < 1e-6;
    return same ? [p[0] + n1[0], p[1] + n1[1]] : [p[0] + n1[0] + n2[0], p[1] + n1[1] + n2[1]];
  });
}

export const svgPath = (pts: Pt[]) => pts.map((p, i) => `${i ? "L" : "M"} ${p[0]} ${p[1]}`).join(" ");
