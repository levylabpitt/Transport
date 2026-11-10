// Tracing: hover a pad, a cable or a box, and every cable and box carrying that pad's
// signal lights up while the rest fades. What carries what is worked out by the layout
// (each cable's and card connector's `pads`); this is the bit that decides.

import { createContext, useContext } from "react";
import type { Row } from "./types";

/** The pads whose signal a row carries: its pad, and the second pad of a difference. */
export const rowPads = (r: Row): string[] =>
  r.idle ? [] : [r.electrode, r.minusKind === "pad" ? r.minus : ""].filter(Boolean);

/** Does something carrying `pads` belong to the trace? */
export const carries = (pads: string[], trace: Set<string> | null) => !!trace && pads.some((p) => trace.has(p));

export interface Trace {
  pads: Set<string> | null;              // what is being traced, or null: nothing
  set: (pads: string[] | null) => void;
}
export const TraceContext = createContext<Trace>({ pads: null, set: () => {} });

/** Props for a box that traces its pads when hovered, and its class while a trace is on. */
export function useTrace(pads: string[]) {
  const t = useContext(TraceContext);
  return {
    cls: ` trace-item${carries(pads, t.pads) ? " traced" : ""}`,
    hover: {
      onMouseEnter: () => t.set(pads.length ? pads : null),
      onMouseLeave: () => t.set(null),
    },
  };
}
