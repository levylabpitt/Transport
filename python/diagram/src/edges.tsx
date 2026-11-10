// Cables, drawn like real ones: a dark sheath with the color of the pad (or pads) whose
// signal it carries inside it, so a signal can be followed from the device to the lock-in.
// A difference (dV) carries both pads' colors. The geometry is in route.ts.

import { BaseEdge, type Edge, type EdgeProps } from "@xyflow/react";
import { offset, points, svgPath, type CableData } from "./route";

export type CableEdgeType = Edge<CableData, "cable">;

const warned = new Set<string>();

export function CableEdge({ id, sourceX, sourceY, targetX, targetY, data }: EdgeProps<CableEdgeType>) {
  const d = data!;
  // The layout works out where every terminal is; say so if the page puts one elsewhere,
  // because the layout tests check the layout's numbers.
  for (const [want, got, end] of [[d.from, [sourceX, sourceY], "start"], [d.to, [targetX, targetY], "end"]] as const) {
    if (want && (Math.abs(want[0] - got[0]) > 1 || Math.abs(want[1] - got[1]) > 1) && !warned.has(id + end)) {
      warned.add(id + end);
      console.warn(`cable ${id} ${end}: layout expects ${want}, the page has ${got}`);
    }
  }
  const pts = points(sourceX, sourceY, targetX, targetY, d);
  const colors = d.colors.filter(Boolean);
  return (
    <>
      <BaseEdge id={id} path={svgPath(pts)} className="cable-sheath" />
      {colors.length === 1 && <path d={svgPath(pts)} className="cable-core one" stroke={colors[0]} strokeWidth={2} />}
      {colors.length === 2 && <>
        <path d={svgPath(offset(pts, -0.5))} className="cable-core" stroke={colors[0]} strokeWidth={1} />
        <path d={svgPath(offset(pts, 0.5))} className="cable-core" stroke={colors[1]} strokeWidth={1} />
      </>}
    </>
  );
}

export const edgeTypes = { cable: CableEdge };
