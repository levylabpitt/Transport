// Layout tests: run the real layout on real models (fixtures written by Python from the
// demo rig, see expconfig/diagramtypes.py) and check the drawing the way you would by eye.
//
//   npm test

import { readdirSync, readFileSync } from "node:fs";
import type { Node } from "@xyflow/react";
import { describe, expect, test } from "vitest";
import { AI_STEP, AO_STEP, CARD_IN, KH_OUT, build, type CableEdgeT, type CardNodeT } from "../src/layout";
import { points, type Pt } from "../src/route";
import { carries } from "../src/trace";
import type { Model } from "../src/types";

const dir = new URL("./fixtures/", import.meta.url);
const fixtures: [string, Model][] = readdirSync(dir).filter((f) => f.endsWith(".json"))
  .map((f) => [f.replace(".json", ""), JSON.parse(readFileSync(new URL(f, dir), "utf-8"))]);

const SHEATH = 4;   // a cable's drawn width: closer than this and two cables touch

interface Seg { a: Pt; b: Pt; edge: CableEdgeT }

function cables(edges: CableEdgeT[]) {
  return edges.map((e) => {
    const d = e.data!;
    return { edge: e, pts: points(d.from![0], d.from![1], d.to![0], d.to![1], d) };
  });
}

function segments(edges: CableEdgeT[]): Seg[] {
  return cables(edges).flatMap(({ edge, pts }) => pts.slice(1).map((b, i) => ({ a: pts[i], b, edge })))
    .filter((s) => Math.hypot(s.b[0] - s.a[0], s.b[1] - s.a[1]) > 0.01);
}

const horizontal = (s: Seg) => Math.abs(s.a[1] - s.b[1]) < 0.01;
const span = (p: number, q: number): [number, number] => [Math.min(p, q), Math.max(p, q)];
const overlap = ([a, b]: [number, number], [c, d]: [number, number]) => Math.min(b, d) - Math.max(a, c);
const from = (e: CableEdgeT) => `${e.source}/${e.sourceHandle}`;

// Box sizes, from styles.css (a 1px border outside the width on pads and gain boxes).
function box(n: Node): [number, number, number, number] | null {
  const { x, y } = n.position;
  switch (n.type) {
    case "kh": return [x, y, 230, 60];
    case "card": return [x, y, 236, n.data.height as number];
    case "pad": return [x, y, 66, 28];
    case "label": return [x, y, 56, 26];
    case "ext": return [x, y, 48, 28];
  }
  return null;
}

describe.each(fixtures)("%s", (_name, model) => {
  const { nodes, edges } = build(model, false, null);
  const segs = segments(edges);

  test("cables run at right angles", () => {
    for (const s of segs) {
      const dx = Math.abs(s.a[0] - s.b[0]), dy = Math.abs(s.a[1] - s.b[1]);
      expect(Math.min(dx, dy), `${s.edge.id} ${s.a} -> ${s.b}`).toBeLessThan(0.01);
    }
  });

  test("cables between boxes in the same row run straight", () => {
    for (const e of edges.filter((e) => /^e-(pad-kh|padm-kh|pad-amp|amp-kh|gnd-kh|src-ext)-/.test(e.id))) {
      const d = e.data!;
      expect(d.to![1], e.id).toBeCloseTo(d.from![1], 5);
    }
  });

  test("no two cables share a stretch of line", () => {
    const bad: string[] = [];
    for (let i = 0; i < segs.length; i++)
      for (let j = i + 1; j < segs.length; j++) {
        const s = segs[i], t = segs[j];
        if (s.edge === t.edge || from(s.edge) === from(t.edge)) continue;   // one AO teed to two rows
        if (horizontal(s) !== horizontal(t)) continue;
        const k = horizontal(s) ? 1 : 0;      // the coordinate across the cable
        if (Math.abs(s.a[k] - t.a[k]) >= SHEATH) continue;
        const along = overlap(span(s.a[1 - k], s.b[1 - k]), span(t.a[1 - k], t.b[1 - k]));
        if (along > 0.5) bad.push(`${s.edge.id} and ${t.edge.id} along ${horizontal(s) ? "y" : "x"}=${s.a[k]}`);
      }
    expect(bad).toEqual([]);
  });

  test("no cable runs through a box it does not connect to", () => {
    const bad: string[] = [];
    for (const n of nodes) {
      const r = box(n);
      if (!r) continue;
      const [x, y, w, h] = r;
      for (const s of segs) {
        if (s.edge.source === n.id || s.edge.target === n.id) continue;
        const [x0, x1] = span(s.a[0], s.b[0]), [y0, y1] = span(s.a[1], s.b[1]);
        if (x1 > x + 1 && x0 < x + w - 1 && y1 > y + 1 && y0 < y + h - 1) bad.push(`${s.edge.id} through ${n.id}`);
      }
    }
    expect(bad).toEqual([]);
  });

  test("the elbows between the KH outputs and the cards are evenly spaced", () => {
    expect(AI_STEP - KH_OUT).toBeCloseTo(AO_STEP - AI_STEP, 5);
    expect(CARD_IN - AO_STEP).toBeCloseTo(AO_STEP - AI_STEP, 5);
    for (const { edge, pts } of cables(edges)) {
      const d = edge.data!;
      if (d.route === "step" && pts.length === 4 && d.from![0] === KH_OUT)
        expect([AI_STEP, AI_STEP + 7, AI_STEP + 14], edge.id).toContain(pts[1][0]);
      if (d.route === "lane") expect([AO_STEP, AO_STEP - 6], edge.id).toContain(pts[1][0]);
    }
  });

  test("every card shows all its connectors, in front-panel order", () => {
    for (const c of model.cards) {
      const node = nodes.filter((n): n is CardNodeT => n.type === "card").find((n) => n.data.card.device === c.device);
      expect(node, c.device).toBeDefined();
      const lines = node!.data.lines;
      expect(lines.map((l) => `${l.kind}${l.n}`)).toEqual([...c.ais.map((a) => `ai${a}`), ...c.aos.map((o) => `ao${o.ao}`)]);
      const tops = lines.map((l) => l.top);
      tops.slice(1).forEach((t, i) => expect(t - tops[i], c.device).toBeGreaterThanOrEqual(20));
      for (const l of lines) expect(l.top + 11, `${c.device} ${l.kind}${l.n}`).toBeLessThanOrEqual(node!.data.height);
    }
  });

  test("every cable ends on a terminal that exists", () => {
    const ids = new Set(nodes.map((n) => n.id));
    for (const e of edges) {
      expect(ids.has(e.source), `${e.id} from ${e.source}`).toBe(true);
      expect(ids.has(e.target), `${e.id} to ${e.target}`).toBe(true);
    }
  });
});

describe("tracing (hover)", () => {
  const model = (name: string) => fixtures.find(([n]) => n === name)![1];
  const traced = (name: string, pad: string) => {
    const { edges } = build(model(name), false, null);
    return edges.filter((e) => carries(e.data!.pads, new Set([pad]))).map((e) => e.id).sort();
  };

  test("every cable carries the pads its colors show", () => {
    for (const [, m] of fixtures)
      for (const e of build(m, false, null).edges) expect(e.data!.colors.length, e.id).toBe(e.data!.pads.length);
  });

  test("a teed pad traces every row it feeds, a difference traces both its pads", () => {
    // Pad 26 is on AI 6 (V26) and on the + of AI 8 (V26-27); pad 27 on AI 7 and the - of AI 8.
    expect(traced("demo", "26")).toEqual(["e-ai-6", "e-ai-8", "e-pad-kh-6", "e-pad-kh-8"]);
    expect(traced("demo", "27")).toEqual(["e-ai-7", "e-ai-8", "e-pad-kh-7", "e-padm-kh-8"]);
  });

  test("a sourced pad traces its AO cable and amplifier, a measured one its gain stage", () => {
    expect(traced("demo", "28")).toEqual(["e-ai-4", "e-amp-kh-4", "e-ao-kh-4", "e-pad-amp-4"]);
    expect(traced("demo", "14")).toEqual(["e-ao-pad-9"]);
    expect(traced("demo", "5")).toEqual(["e-ai-5", "e-src-ext-5"]);
  });

  test("one AO teed to two rows traces from either pad, and its card connector carries both", () => {
    expect(traced("shared-ao", "3")).toContain("e-ao-kh-3");
    expect(traced("shared-ao", "28")).toContain("e-ao-kh-4");
    const card = build(model("shared-ao"), false, null).nodes
      .filter((n): n is CardNodeT => n.type === "card").find((n) => n.data.card.device === "PXI1Slot3")!;
    expect(card.data.lines.find((l) => l.kind === "ao" && l.n === 4)!.pads.sort()).toEqual(["28", "3"]);
  });
});
