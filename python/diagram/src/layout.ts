// Model -> React Flow nodes and edges, drawn as the hardware is: one strip per lock-in
// AI (its label, pad, Krohn-Hite channel), and the lock-in as its physical cards on the
// right, each spanning the rows of its AIs. An AO stays on its card; its cable runs to
// whichever row uses it, across rows if need be. The Pads column on the left is the
// chip carrier's pins, to drag from.
//
// Everything sits on one grid, so wires run straight: in a full row the boxes start at
// BOX_TOP, every terminal is on line L1 (+ input, KH out, AI) or L2 (- input, AO), and an
// AO cable runs back to the left in the LANE under the boxes of the row it serves.

import type { Edge, Node } from "@xyflow/react";
import { electrodeColor } from "./colors";
import type { CableData, Pt } from "./route";
import { rowPads } from "./trace";
import type { Card, Model, Row } from "./types";

export const ROW_H = 80;
export const BOX_TOP = 8;
export const BOX_H = 60;
export const L1 = BOX_TOP + 15;
export const L2 = BOX_TOP + 45;
export const LANE = BOX_TOP + BOX_H + 5;
const PAD_H = 26;
const AMP_WIRE = 29;   // where the amplifier's wires attach, from its top
// A row with only its AI (no KH channel, no AO on it, nothing connected) is one thin line.
export const IDLE_H = 38;
export const IDLE_L = 19;

export const CARD_W = 236;
export const X = {
  palette: 0,
  label: 70,
  pad: 132,
  amp: 214,
  kh: 282,
  ext: 530,
  li: 640,
  end: 640 + CARD_W,
};
const LABEL_W = 56;
// Between the KH outputs and the cards, cables change line at two places a third of the way
// apart: cables into the AIs first, then cables from the AOs, so they cross but never share a line.
export const KH_OUT = X.kh + 244;    // where the KH output terminal's cable starts
export const CARD_IN = X.li - 14;    // where a card terminal's cable ends
const THIRD = (CARD_IN - KH_OUT) / 3;
export const AI_STEP = KH_OUT + THIRD;
export const AO_STEP = CARD_IN - THIRD;

// Where each terminal's cable attaches, from its box's position. These follow the boxes'
// CSS (styles.css, nodes.tsx); the page warns if React Flow puts a terminal elsewhere. Every
// terminal sits 1px below its grid line (L1, L2): the boxes' 1px border.
export function anchor(n: Node, handle: string): Pt {
  const { x, y } = n.position;
  const kind = handle.split("|")[0];
  switch (n.type) {
    case "pad": return [x + 81, y + 14];
    case "kh": return kind === "khout" ? [KH_OUT, y + 16] : [x - 14, y + (kind === "kh-" ? 46 : 16)];
    case "card": {
      const id = Number(handle.split("|")[1]);
      const line = (n as CardNodeT).data.lines.find((l) => l.kind === kind && l.n === id)!;
      return [CARD_IN, y + line.top + 1];
    }
    case "amp": return [handle === "in" ? x + 46.5 : x - 0.5, y + AMP_WIRE + 1];
    case "ext": return [handle === "in" ? x - 0.5 : x + 48.5, y + 14];
    case "gnd": return [x + 18.5, y + 4];
  }
  throw new Error(`no terminal ${handle} on a ${n.type}`);
}
const PAD_W = 64;
const TOP = 10;

export const portId = (kind: string, id: string | number | null) => `${kind}|${id ?? ""}`;

const amplified = (r: Row) => r.ao != null && (r.outGain !== 1 || r.outOffset !== 0);

/** What a card box is given to draw. */
export type CardData = {
  card: Card;
  lines: CardLine[];
  height: number;
  sel: number | null;      // the selected row's AI
  selKey: string | null;   // and field
};
export type CardNodeT = Node<CardData, "card">;
export type CableEdgeT = Edge<CableData, "cable">;

/** One line on a card: an AI or an AO, at its height on the card. */
export interface CardLine {
  kind: "ai" | "ao";
  n: number;        // AI or AO number
  top: number;      // from the card's top
  row?: Row;        // AI: its row; AO: the row that uses it, if any
  channel: string;  // the DAQ channel, "PXI1Slot2/ai0"
  hw: string;       // its name on the card's front panel, "ai0"
  pads: string[];   // the pads whose signal goes through it
  name?: string;
  gain?: number;
  offset?: number;
}

export function build(m: Model, dragging: boolean, selected: [number, string | null] | null) {
  const nodes: Node[] = [];
  const edges: CableEdgeT[] = [];
  const wire = (id: string, source: string, sourceHandle: string, target: string, targetHandle: string,
                carried: string[], route: Partial<CableData> = {}) =>
    edges.push({ id, source, sourceHandle, target, targetHandle, type: "cable", selectable: false, focusable: false,
                 data: { route: "direct", pads: carried.filter(Boolean),
                         colors: carried.filter(Boolean).map((p) => electrodeColor(p)), ...route } });
  const at = (x: number, y: number) => ({ x, y });

  // The Pads column: the chip carrier's pins.
  m.pads.forEach((p, i) => nodes.push({
    id: `pal-${p.name}`, type: "palpad", position: at(X.palette, TOP + i * 26), draggable: true,
    data: { name: p.name, port: ["pad", p.name], used: p.used },
  }));

  // A card's terminals are in front-panel order, top to bottom: ai0, ai1, ..., ao0, ao1, ...
  // They take the grid lines of the card's rows in turn (L1 and L2 of a full row, the one
  // line of a thin row); a card with more terminals than lines grows its last row.
  const compact = new Map<number, boolean>();
  for (const r of m.rows) compact.set(r.ai, r.idle && !r.kh);
  const grow = new Map<number, number>();       // AI row -> extra lines below it
  const cardOf = new Map<number, Card>();       // AO -> card
  for (const c of m.cards) {
    c.aos.forEach((o) => cardOf.set(o.ao, c));
    const lines = c.ais.reduce((n, ai) => n + (compact.get(ai) ? 1 : 2), 0);
    const need = c.ais.length + c.aos.length;
    if (need > lines && c.ais.length) grow.set(c.ais[c.ais.length - 1], need - lines);
  }
  const rowY = new Map<number, number>();
  let next = TOP;
  for (const r of m.rows) {
    rowY.set(r.ai, next);
    next += (compact.get(r.ai) ? IDLE_H : ROW_H) + (grow.get(r.ai) ?? 0) * 26;
  }
  const line1 = (ai: number) => rowY.get(ai)! + (compact.get(ai) ? IDLE_L : L1);
  const rowBottom = (ai: number) =>
    rowY.get(ai)! + (compact.get(ai) ? IDLE_H - 6 : BOX_TOP + BOX_H) + (grow.get(ai) ?? 0) * 26;
  const aiY = new Map<number, number>(), aoY = new Map<number, number>();
  for (const c of m.cards) {
    const slots: number[] = [];
    for (const ai of c.ais) {
      slots.push(line1(ai));
      if (!compact.get(ai)) slots.push(rowY.get(ai)! + L2);
    }
    const last = c.ais[c.ais.length - 1];
    if (last != null) for (let k = 0; k < (grow.get(last) ?? 0); k++) slots.push(slots[slots.length - 1] + 26);
    let s = 0;
    for (const ai of c.ais) aiY.set(ai, slots[s++]);
    for (const o of c.aos) aoY.set(o.ao, slots[s++]);
  }
  const short = (chan: string) => chan.split("/").pop() ?? "";

  // The lock-in cards.
  const rowOf = new Map(m.rows.map((r) => [r.ai, r]));
  for (const c of m.cards) {
    const first = c.ais[0] ?? null;
    if (first == null || !rowY.has(first)) continue;
    const top = rowY.get(first)! + (compact.get(first) ? 6 : BOX_TOP);
    const bottom = Math.max(...c.ais.map(rowBottom));
    const lines: CardLine[] = [];
    for (const ai of c.ais) {
      const r = rowOf.get(ai)!;
      lines.push({ kind: "ai", n: ai, top: aiY.get(ai)! - top, row: r, channel: r.aiChannel, hw: short(r.aiChannel),
                   pads: r.aiUsed ? rowPads(r) : [] });
    }
    for (const o of c.aos) {
      lines.push({ kind: "ao", n: o.ao, top: aoY.get(o.ao)! - top, row: o.usedBy != null ? rowOf.get(o.usedBy) : undefined,
                   channel: o.channel, hw: short(o.channel), name: o.name, gain: o.gain, offset: o.offset,
                   // every row this AO drives (one AO can be teed to several)
                   pads: [...new Set(m.rows.filter((r) => r.ao === o.ao).flatMap(rowPads))] });
    }
    const sel = selected ? selected[0] : null;
    nodes.push({ id: `card-${c.device}-${first}`, type: "card", position: at(X.li, top), draggable: false,
                 data: { card: c, lines, height: bottom - top, sel, selKey: selected?.[1] ?? null } } satisfies CardNodeT);
  }
  const cardNode = (ai: number) => {
    const c = m.cards.find((c) => c.ais.includes(ai));
    return c ? `card-${c.device}-${c.ais[0]}` : "";
  };
  const aoNode = (ao: number) => {
    const c = cardOf.get(ao);
    return c && c.ais.length ? `card-${c.device}-${c.ais[0]}` : "";
  };

  m.rows.forEach((r, i) => {
    const ai = r.ai;
    const y = rowY.get(ai)!;
    const thin = compact.get(ai)!;
    const h = rowBottom(ai) - y + (thin ? 6 : ROW_H - BOX_TOP - BOX_H);
    const sel = selected && selected[0] === ai ? selected[1] ?? "" : null;   // null: row not selected
    const faded = r.idle ? "idle" : undefined;
    nodes.push({ id: `band-${ai}`, type: "band", position: at(X.label - 10, y), draggable: false,
                 selectable: false, zIndex: -1, data: { even: i % 2 === 1, selected: sel !== null,
                                                         width: X.end - X.label + 20, height: h - 4 } });
    nodes.push({ id: `label-${ai}`, type: "label", position: at(X.label, thin ? y + 6 : y + L1 - PAD_H / 2),
                 draggable: false, data: { row: r, sel, thin, width: LABEL_W } });
    const card = cardNode(ai);

    if (thin) {
      nodes.push({ id: `pad-${ai}`, type: "pad", position: at(X.pad, y + 6), draggable: false,
                   data: { row: r, field: "electrode", name: "", slot: ["ai", ai], sel, dragging } });
      return;
    }

    // Where a carried pad can land: the + side (or the AI/AO for rows without a KH), and the - side.
    const plusPort = r.direct ? ["ao", r.ao] : r.kh ? ["kh+", ai] : ["ai", ai];
    nodes.push({ id: `pad-${ai}`, type: "pad", position: at(X.pad, y + L1 - PAD_H / 2), draggable: false,
                 data: { row: r, field: "electrode", name: r.electrode, slot: plusPort, sel, dragging } });
    if (r.kh && r.minusKind === "pad")
      nodes.push({ id: `padm-${ai}`, type: "pad", position: at(X.pad, y + L2 - PAD_H / 2), draggable: false,
                   data: { row: r, field: "minus", name: r.minus, slot: ["kh-", ai], sel, dragging } });
    else if (r.kh && dragging)
      nodes.push({ id: `slotm-${ai}`, type: "slot", position: at(X.pad, y + L2 - PAD_H / 2), draggable: false,
                   data: { slot: ["kh-", ai], label: "− input" } });

    // The pads whose signal a cable carries (its colors, and what hovering traces).
    const plusC = r.electrode;
    const minusC = r.minusKind === "pad" ? r.minus : "";
    // An AO cable: out of the AO on its card, beside the cards to this row's lane, in from the left.
    // It carries the signal to this row's pad.
    const lane = (id: string, target: string, targetHandle: string, turnX: number) => {
      if (r.ao == null || !aoNode(r.ao)) return;
      wire(id, aoNode(r.ao), portId("ao", r.ao), target, targetHandle, [plusC],
           { route: "lane", laneY: y + LANE, turnX, outX: AO_STEP - 6 * ((r.ao - 1) % 2) });
    };

    if (r.direct) {
      if (r.ao != null && r.electrode) {
        if (amplified(r)) {
          nodes.push({ id: `amp-${ai}`, type: "amp", position: at(X.ext - 20, y + LANE - AMP_WIRE),
                       draggable: false, data: { row: r, sel } });
          lane(`e-ao-amp-${ai}`, `amp-${ai}`, "in", X.ext + 30);
          wire(`e-amp-pad-${ai}`, `amp-${ai}`, "out", `pad-${ai}`, portId("pad", r.electrode), [plusC]);
        } else {
          lane(`e-ao-pad-${ai}`, `pad-${ai}`, portId("pad", r.electrode), X.pad + PAD_W + 22);
        }
      }
      return;
    }

    let src: [string, string] | null = null;   // what feeds the AI (or the ext stage)
    const signal = r.mode === "dV" ? [plusC, minusC] : [plusC];   // what the KH output carries
    if (r.kh) {
      const kh = `kh-${ai}`;
      nodes.push({ id: kh, type: "kh", position: at(X.kh, y + BOX_TOP), draggable: false, className: faded,
                   data: { row: r, sel } });
      if (r.electrode) {
        if (r.type === "U" && r.minusKind === "ao" && amplified(r)) {
          // The amplifier sits between the KH + input and the pad.
          nodes.push({ id: `amp-${ai}`, type: "amp", position: at(X.amp, y + L1 - AMP_WIRE), draggable: false,
                       data: { row: r, sel } });
          wire(`e-amp-kh-${ai}`, `amp-${ai}`, "in", kh, portId("kh+", ai), [plusC]);
          wire(`e-pad-amp-${ai}`, `pad-${ai}`, portId("pad", r.electrode), `amp-${ai}`, "out", [plusC]);
        } else {
          wire(`e-pad-kh-${ai}`, `pad-${ai}`, portId("pad", r.electrode), kh, portId("kh+", ai), [plusC]);
        }
      }
      if (r.minusKind === "pad")
        wire(`e-padm-kh-${ai}`, `padm-${ai}`, portId("pad", r.minus), kh, portId("kh-", ai), [minusC]);
      else if (r.minusKind === "gnd") {
        nodes.push({ id: `gnd-${ai}`, type: "gnd", position: at(X.kh - 34, y + L2 - 3), draggable: false,
                     data: {} });
        wire(`e-gnd-kh-${ai}`, `gnd-${ai}`, "g", kh, portId("kh-", ai), []);
      } else if (r.minusKind === "ao" && r.ao != null)
        lane(`e-ao-kh-${ai}`, kh, portId("kh-", ai), X.kh - 44);
      if (r.khInput !== "OFF") src = [kh, portId("khout", ai)];
    } else {
      if (r.electrode) src = [`pad-${ai}`, portId("pad", r.electrode)];
    }
    if (r.extGain !== 1) {
      nodes.push({ id: `ext-${ai}`, type: "ext", position: at(X.ext, y + L1 - PAD_H / 2), draggable: false,
                   data: { row: r, sel } });
      if (src) wire(`e-src-ext-${ai}`, src[0], src[1], `ext-${ai}`, "in", signal);
      src = [`ext-${ai}`, "out"];
    }
    // Into the AI at its place on the card; it climbs or drops beside the cards if that is another line.
    const k = m.cards.find((c) => c.ais.includes(ai))?.ais.indexOf(ai) ?? 0;
    // It changes line close to the KH output, and the AO cables close to the cards, so the two
    // never share a stretch of the same line (a KH output can sit level with an AO on the card).
    if (src && card) wire(`e-ai-${ai}`, src[0], src[1], card, portId("ai", ai), signal,
                          { route: "step", midX: AI_STEP + 7 * Math.max(0, k - 1) });
  });
  const byId = new Map(nodes.map((n) => [n.id, n]));
  for (const e of edges) {
    e.data!.from = anchor(byId.get(e.source)!, e.sourceHandle!);
    e.data!.to = anchor(byId.get(e.target)!, e.targetHandle!);
  }
  return { nodes, edges, height: next };
}
