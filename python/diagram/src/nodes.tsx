// The boxes of the diagram. Values shown on a box are clickable when the table lets
// that cell be changed on this row; clicking opens the same choices as the table.

import { createContext, useContext, type ReactNode } from "react";
import { Handle, Position, type NodeProps } from "@xyflow/react";
import { electrodeColor } from "./colors";
import { portId, type CardNodeT } from "./layout";
import { rowPads, useTrace } from "./trace";
import type { Card, Port, Row } from "./types";

export interface Actions {
  edit: (ai: number, key: string, ev: React.MouseEvent) => void;
  unplug: (p: Port, ev: React.MouseEvent) => void;
}
export const ActionsContext = createContext<Actions>({ edit: () => {}, unplug: () => {} });

type D<T> = NodeProps & { data: T };
interface RowData {
  row: Row;
  sel: string | null;   // the selected field on this row, "" for the row only; null: not selected
}

function Field({ row, k, sel, children, className = "" }:
               { row: Row; k: string; sel: string | null; children: ReactNode; className?: string }) {
  const { edit } = useContext(ActionsContext);
  const cell = row.cells[k];
  const cls = ["field", className];
  if (cell?.edit) cls.push("editable");
  if (cell?.why) cls.push("why");
  if (cell?.issue) cls.push(cell.issue.error ? "error" : "warn");
  if (sel === k) cls.push("current");
  const tip = [cell?.why, cell?.issue && `[${cell.issue.code}] ${cell.issue.message}`,
               cell?.edit ? "click to change" : ""].filter(Boolean).join("\n");
  return (
    <span className={cls.join(" ")} title={tip || undefined}
          onClick={(ev) => { ev.stopPropagation(); edit(row.ai, k, ev); }}>
      {children}
    </span>
  );
}

/** A cable end: a small circle; drag from it to another to cable them. */
function Terminal({ id, pos, label, used = true, unplug, choose, style }:
                  { id: string; pos: Position; label?: string; used?: boolean; unplug?: Port;
                    choose?: { ai: number; key: string }; style?: React.CSSProperties }) {
  const { unplug: doUnplug, edit } = useContext(ActionsContext);
  return (
    <Handle type="source" id={id} position={pos} style={style}
            className={`terminal${used ? "" : " unused"}`}
            title={(label ? `${label}: ` : "") +
                   (choose ? "click to choose what it is connected to (pad, AO, GND, ...); " : "") +
                   "drag to another terminal to cable it" + (unplug ? "\nright-click to disconnect" : "")}
            onClick={choose ? (ev) => { ev.stopPropagation(); edit(choose.ai, choose.key, ev); } : undefined}
            onContextMenu={unplug ? (ev) => { ev.preventDefault(); doUnplug(unplug, ev); } : undefined}>
      {label && <span className="sign">{label}</span>}
    </Handle>
  );
}

export function BandNode({ data }: D<{ even: boolean; selected: boolean; width: number; height: number }>) {
  return <div className={`band${data.even ? " even" : ""}${data.selected ? " selected" : ""}`}
              style={{ width: data.width, height: data.height }} />;
}

export function PadNode({ data }: D<RowData & { field: string; name: string; dragging: boolean }>) {
  const { row, field, name, sel, dragging } = data;
  const t = useTrace(name ? [name] : []);
  return (
    <div className={`pad${name ? "" : " empty"}${dragging ? " droppable" : ""}${t.cls}`} {...t.hover}
         style={name ? { background: electrodeColor(name) } : undefined}>
      <Field row={row} k={field} sel={sel}>{name || "(no pad)"}</Field>
      {name && <Terminal id={portId("pad", name)} pos={Position.Right} />}
    </div>
  );
}

export function SlotNode({ data }: D<{ label: string }>) {
  return <div className="pad empty droppable">{data.label}</div>;
}

export function PalettePadNode({ data }: D<{ name: string; port: Port; used: boolean; gnd?: boolean }>) {
  const t = useTrace([data.name]);
  return (
    <div className={`palpad${data.used ? " used" : ""}${data.gnd ? " gnd" : ""}${t.cls}`} {...t.hover}
         style={data.used ? { background: electrodeColor(data.name, true) } : undefined}
         title={`Pin ${data.name}${data.used ? " (in use)" : ""}: drag onto a row's pad slot`}>
      {data.name}
      <Terminal id={portId(data.port[0], data.port[1])} pos={Position.Right} />
    </div>
  );
}

function Shunt({ value }: { value: string }) {
  // The resistor wired across the + and - inputs: from the + terminal (line 1), down
  // through the resistor, to the - terminal (line 2).
  return (
    <svg className="shunt" width="40" height="60" viewBox="0 0 40 60">
      <path d="M7 15 H26 V21 L31 23.5 L21 27 L31 30.5 L21 34 L31 37.5 L26 39 V45 H7" fill="none"
            stroke="#2f4a3a" strokeWidth="1.4" strokeLinejoin="round" />
      <title>{`shunt ${value} between the + and \u2212 inputs`}</title>
    </svg>
  );
}

export function KhNode({ data }: D<RowData>) {
  const { row: r, sel } = data;
  const minusUsed = r.minusKind !== "unused";
  const t = useTrace(rowPads(r));
  return (
    <div className={`kh${r.khInput === "OFF" ? " off" : ""}${t.cls}`} {...t.hover}>
      <Terminal id={portId("kh+", r.ai)} pos={Position.Left} label="+" unplug={["kh+", r.ai]}
                choose={{ ai: r.ai, key: "electrode" }} style={{ top: 15 }} />
      <Terminal id={portId("kh-", r.ai)} pos={Position.Left} label={"−"} used={minusUsed}
                unplug={["kh-", r.ai]} choose={{ ai: r.ai, key: "minus" }} style={{ top: 45 }} />
      {r.shunt && r.shunt !== "Open" && <Shunt value={r.shunt} />}
      {r.shunt && (
        <Field row={r} k="shunt" sel={sel} className="shunt-value">{r.shunt === "Open" ? "no shunt" : r.shunt}</Field>
      )}
      <div className="kh-body">
        <div className="line1">
          <Field row={r} k="kh" sel={sel} className="strong">{r.kh}</Field>
          <Field row={r} k="input" sel={sel} className="mode">{r.khInput}</Field>
          <Field row={r} k="kh_gain" sel={sel} className="strong">{`×${r.khGain}`}</Field>
        </div>
        <div className="line2">
          <Field row={r} k="couple" sel={sel}>{r.couple}</Field>
          <Field row={r} k="filter" sel={sel}>{`filter ${r.filter}`}</Field>
        </div>
      </div>
      <span className="out-label">out</span>
      <Terminal id={portId("khout", r.ai)} pos={Position.Right} used={r.khInput !== "OFF"} style={{ top: 15 }} />
    </div>
  );
}

export function NoKhNode({ data }: D<RowData & { text: string }>) {
  // Clicking it gives the row a Krohn-Hite channel.
  return (
    <div className="nokh">
      <Field row={data.row} k="kh" sel={data.sel}>{data.text}</Field>
    </div>
  );
}

export function GndNode() {
  return (
    <div className="gnd-symbol" title="ground">
      <svg width="18" height="16" viewBox="0 0 18 16">
        <path d="M9 0 V6 M2 6 H16 M5 10 H13 M7.5 14 H10.5" stroke="#333" strokeWidth="1.4" fill="none" />
      </svg>
      <Handle type="source" id="g" position={Position.Right} isConnectable={false} className="hidden-handle"
              style={{ top: 4 }} />
    </div>
  );
}

export function AmpNode({ data }: D<RowData & { flip: boolean }>) {
  const { row: r, sel } = data;
  // Signal runs right to left: from the KH + input (or the AO) out to the pad.
  const t = useTrace(rowPads(r));
  return (
    <div className={`amp${t.cls}`} {...t.hover}>
      <Field row={r} k="out_gain" sel={sel} className="amp-label">
        {`×${r.outGain}${r.outOffset ? `  ${r.outOffset > 0 ? "+" : ""}${r.outOffset}` : ""}`}
      </Field>
      <svg width="30" height="22" viewBox="0 0 30 22">
        <path d="M29 1 V21 L1 11 Z" fill="#fcdecc" stroke="#b5835f" strokeWidth="1.2" />
      </svg>
      {/* 30: level with the KH + terminal, which sits 1px below the line for the box's border */}
      <Handle type="source" id="in" position={Position.Right} isConnectable={false} className="hidden-handle"
              style={{ top: 30 }} />
      <Handle type="source" id="out" position={Position.Left} isConnectable={false} className="hidden-handle"
              style={{ top: 30 }} />
    </div>
  );
}

export function ExtNode({ data }: D<RowData>) {
  const { row: r, sel } = data;
  const t = useTrace(rowPads(r));
  return (
    <div className={`ext${t.cls}`} {...t.hover}>
      <Handle type="source" id="in" position={Position.Left} isConnectable={false} className="hidden-handle" />
      <Field row={r} k="ext_gain" sel={sel}>{`×${r.extGain}`}</Field>
      <Handle type="source" id="out" position={Position.Right} isConnectable={false} className="hidden-handle" />
    </div>
  );
}

export function CardNode({ data }: NodeProps<CardNodeT>) {
  // One physical lock-in card: its AIs and AOs where they are, used or not.
  const { card, lines, height, sel, selKey } = data;
  const fieldSel = (r?: Row) => (r && sel === r.ai ? selKey ?? "" : null);
  const nAi = lines.filter((l) => l.kind === "ai").length, nAo = lines.length - nAi;
  return (
    <div className="card" style={{ height }}>
      {(() => {
        // The inputs and the outputs as two blocks, split half way between the last AI and the first AO.
        const ai = lines.filter((l) => l.kind === "ai").map((l) => l.top);
        const ao = lines.filter((l) => l.kind === "ao").map((l) => l.top);
        const split = ai.length && ao.length ? (Math.max(...ai) + Math.min(...ao)) / 2 : ai.length ? height : 0;
        return <>
          {ai.length > 0 && <div className="card-band ai" style={{ top: 0, height: split }} />}
          {ao.length > 0 && <div className="card-band ao" style={{ top: split, bottom: 0 }} />}
        </>;
      })()}
      {lines.map((l) => (
        <Terminal key={`t-${l.kind}${l.n}`} id={portId(l.kind, l.n)} pos={Position.Left}
                  used={l.kind === "ai" ? !!l.row?.aiUsed && !l.row?.idle : !!l.row} style={{ top: l.top }} />
      ))}
      {lines.map((l) => {
        // Our channel number (AI 1, AO 1) and the card's own name for the connector (ai0, ao0).
        const r = l.row;
        const used = l.kind === "ai" ? !!r && r.aiUsed && !r.idle : !!r;
        return (
          <CardLineDiv key={`${l.kind}${l.n}`} pads={l.pads} className={`card-line${used ? "" : " unused"}`}
               style={{ top: l.top - 11 }}
               title={`${l.kind.toUpperCase()} ${l.n}${l.channel ? ` (${l.channel})` : ""}${l.name ? `: ${l.name}` : ""}`}>
            <span className="strong num">{l.n}</span>
            <span className="hw">{l.hw}</span>
            {l.kind === "ai" && r && used && (
              // The lock-in input gain is KH gain x external gain; clicking it sets the external gain.
              <Field row={r} k="ext_gain" sel={fieldSel(r)} className="muted gain-hint">{`×${r.lockinGain}`}</Field>
            )}
            {l.kind === "ao" && r && (
              <Field row={r} k="out_gain" sel={fieldSel(r)} className="muted gain-hint">
                {`×${l.gain}${l.offset ? `  ${l.offset! > 0 ? "+" : ""}${l.offset}` : ""}`}
              </Field>
            )}
          </CardLineDiv>
        );
      })}
      {(["ai", "ao"] as const).map((kind) => {
        // The group's name beside its connectors, like the IN and OUT brackets on the front panel.
        const tops = lines.filter((l) => l.kind === kind).map((l) => l.top);
        if (!tops.length) return null;
        const top = Math.min(...tops) - 11, bottom = Math.max(...tops) + 11;
        return <div key={kind} className="card-group" style={{ top, height: bottom - top }}>{kind.toUpperCase()}</div>;
      })}
      <div className="card-id" title={cardTitle(card)}>
        <span className="strong">{card.read ? card.device : "Lock-in"}</span>
        <span className="card-type">{card.type || `${nAi} AI · ${nAo} AO`}</span>
        {card.simulated && <span className="card-sim">simulated</span>}
      </div>
    </div>
  );
}

/** The card's tooltip: what the lock-in says it is, and where. */
function cardTitle(c: Card): string {
  if (!c.read) return "Read the instruments to see its cards";
  return [`${c.device}${c.type ? `: ${c.type}` : ""}`,
          c.serial ? `serial ${c.serial}` : "",
          c.slot,
          c.simulated ? "simulated device (NI-DAQmx)" : "",
          `${c.ais.length} AI, ${c.aos.length} AO`].filter(Boolean).join("\n");
}

/** A connector's line on a card: traces the pads whose signal goes through it. */
function CardLineDiv({ pads, className, ...rest }: { pads: string[]; className: string } & React.HTMLAttributes<HTMLDivElement>) {
  const t = useTrace(pads);
  return <div className={className + t.cls} {...t.hover} {...rest} />;
}

export function LabelNode({ data }: D<RowData & { thin: boolean; width: number }>) {
  // What the channel is, next to its pad: the automatic label (its first letter is the type,
  // click to change it), and under it the mode.
  const { row: r, sel, thin, width } = data;
  const rest = r.name.startsWith(r.type) ? r.name.slice(r.type.length) : "";
  const t = useTrace(rowPads(r));
  return (
    <div className={`label-col${t.cls}`} style={{ width }} {...t.hover}>
      <div className={`label${r.mismatch ? " mismatch" : ""}${r.idle ? " idle" : ""}`}
           title={r.mismatch || "Automatic label, saved with the data"}>
        <Field row={r} k="type" sel={sel} className={thin ? "" : "strong"}>{r.type}</Field>
        {!thin && rest && <span className="strong">{rest}</span>}
      </div>
      {!thin && r.mode && <Field row={r} k="mode" sel={sel} className="label-mode">{r.mode}</Field>}
    </div>
  );
}

export function LegendNode({ data }: D<{ children: ReactNode }>) {
  return <div className="legend">{data.children}</div>;
}

export const nodeTypes = {
  legend: LegendNode, card: CardNode, label: LabelNode,
  band: BandNode, pad: PadNode, slot: SlotNode, palpad: PalettePadNode, kh: KhNode, nokh: NoKhNode,
  gnd: GndNode, amp: AmpNode, ext: ExtNode,
};
