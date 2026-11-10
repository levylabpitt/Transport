import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  ReactFlow, ReactFlowProvider, Controls, ConnectionLineType, ConnectionMode, useReactFlow, useNodesState,
  type Connection, type Node,
} from "@xyflow/react";
import { makeBridge } from "./bridge";
import { build, X } from "./layout";
import { ActionsContext, nodeTypes, type Actions } from "./nodes";
import { edgeTypes } from "./edges";
import { FILL, electrodeColor } from "./colors";
import { TraceContext, carries } from "./trace";
import type { Choices, Model, Port } from "./types";

const bridge = makeBridge();

const toPort = (handle: string | null | undefined): Port | null => {
  if (!handle || !handle.includes("|")) return null;
  const [kind, id] = handle.split("|");
  if (kind === "pad") return ["pad", id];
  if (kind === "gnd") return ["gnd", null];
  return [kind, Number(id)];
};

interface Editor {
  ai: number;
  key: string;
  x: number;
  y: number;
  choices: Choices | null;
}

function Diagram() {
  const [model, setModel] = useState<Model | null>(null);
  const [selected, setSelected] = useState<[number, string | null] | null>(null);
  const [dragging, setDragging] = useState(false);
  const [editor, setEditor] = useState<Editor | null>(null);
  const [toast, setToast] = useState<{ text: string; bad: boolean } | null>(null);
  const [trace, setTrace] = useState<Set<string> | null>(null);   // the pads being traced (hover)
  const traceCtx = useMemo(() => ({ pads: trace, set: (p: string[] | null) => setTrace(p ? new Set(p) : null) }), [trace]);
  const [nodes, setNodes, onNodesChange] = useNodesState<Node>([]);
  const flow = useReactFlow();
  const fitted = useRef(false);

  useEffect(() => {
    bridge.model().then(setModel);
    bridge.onModel(setModel);
    bridge.onSelect((ai, key) => setSelected([ai, key]));
  }, []);

  // One timer for the message, kept across renders, so a new message is not cut short by an old timer.
  const toastTimer = useRef(0);
  const say = (text: string, bad = false) => {
    setToast({ text, bad });
    window.clearTimeout(toastTimer.current);
    toastTimer.current = window.setTimeout(() => setToast(null), bad ? 6000 : 2500);
  };
  const done = (err: string) => { if (err) say(err, true); };

  const layout = useMemo(() => (model ? build(model, dragging, selected) : null), [model, dragging, selected]);
  useEffect(() => {
    if (!layout || !model) return;
    // The legend sits under the last row, on the canvas, so it never covers the diagram.
    setNodes([...layout.nodes, { id: "legend", type: "legend", position: { x: X.pad - 14, y: layout.height + 6 },
                                 draggable: false, selectable: false, data: { children: legend(model) } }]);
    if (!fitted.current) {
      fitted.current = true;
      requestAnimationFrame(() => flow.fitView({ padding: 0.04, maxZoom: 1.2 }));
    }
  }, [layout]);

  const actions: Actions = useMemo(() => ({
    edit: (ai, key, ev) => {
      setSelected([ai, key]);
      bridge.select(ai, key);
      const row = model?.rows.find((r) => r.ai === ai);
      if (!row?.cells[key]?.edit) return;
      const ed: Editor = { ai, key, x: ev.clientX, y: ev.clientY, choices: null };
      setEditor(ed);
      bridge.choices(ai, key).then((choices) => setEditor((e) => (e && e.ai === ai && e.key === key ? { ...e, choices } : e)));
    },
    unplug: (p, ev) => {
      ev.preventDefault();
      if (window.confirm(`Disconnect the KH ${p[0] === "kh+" ? "+" : "−"} input of AI ${p[1]}?`))
        bridge.unplug(p).then(done);
    },
  }), [model]);

  const onConnect = useCallback((c: Connection) => {
    const a = toPort(c.sourceHandle), b = toPort(c.targetHandle);
    if (a && b) bridge.cable(a, b).then(done);
  }, []);

  // Carrying a pad from the Pads column: drop it on a row's pad slot.
  const onNodeDragStart = useCallback((_: unknown, n: Node) => { if (n.type === "palpad") setDragging(true); }, []);
  const onNodeDragStop = useCallback((ev: MouseEvent | TouchEvent | React.MouseEvent, n: Node) => {
    if (n.type !== "palpad") return;
    // The slot under the mouse, not just any slot the carried pad overlaps.
    const pt = "clientX" in ev ? ev : ev.changedTouches[0];
    const p = flow.screenToFlowPosition({ x: pt.clientX, y: pt.clientY });
    const target = flow.getNodes().find((t) => (t.type === "pad" || t.type === "slot") && t.measured?.width &&
      p.x >= t.position.x && p.x <= t.position.x + t.measured.width &&
      p.y >= t.position.y && p.y <= t.position.y + (t.measured.height ?? 0));
    setDragging(false);   // re-lays out the nodes: the pad goes back to its column
    if (target) bridge.cable(n.data.port as Port, target.data.slot as Port).then(done);
  }, [flow, layout, model, selected]);

  // While tracing, the cables carrying the traced pads are drawn a little bolder.
  const edges = useMemo(() => (layout?.edges ?? []).map((e) =>
    carries(e.data!.pads, trace) ? { ...e, className: "traced" } : e), [layout, trace]);

  if (!model || !layout) return <div className="loading">Loading the wiring…</div>;
  // Output settings belong to the AO, not to the row's AI.
  const edRow = editor ? model.rows.find((r) => r.ai === editor.ai) : undefined;
  const onAo = editor && ["ao", "out_gain", "out_offset"].includes(editor.key) && edRow?.ao != null;
  const title = editor ? `${onAo ? `AO ${edRow!.ao}` : `AI ${editor.ai}`}: ${model.titles[editor.key] ?? editor.key}` : "";

  return (
    <ActionsContext.Provider value={actions}>
     <TraceContext.Provider value={traceCtx}>
      <ReactFlow
        nodes={nodes}
        edges={edges}
        onEdgeMouseEnter={(_, e) => traceCtx.set(e.data?.pads.length ? e.data.pads : null)}
        onEdgeMouseLeave={() => traceCtx.set(null)}
        nodeTypes={nodeTypes}
        edgeTypes={edgeTypes}
        onNodesChange={onNodesChange}
        onConnect={onConnect}
        onNodeDragStart={onNodeDragStart}
        onNodeDragStop={onNodeDragStop}
        connectionMode={ConnectionMode.Loose}
        connectOnClick={false}   // a click on a terminal chooses what it connects to; a drag cables it
        connectionLineType={ConnectionLineType.SmoothStep}
        nodesConnectable
        elementsSelectable={false}
        onPaneClick={() => setEditor(null)}
        onNodeClick={() => {}}   // React Flow turns off pointer events on nodes with no click handler
        minZoom={0.3}
        maxZoom={2.5}
        proOptions={{ hideAttribution: true }}
        translateExtent={[[-60, -40], [X.end + 200, layout.height + 300]]}
      >
        <Controls showInteractive={false} position="top-right" />
      </ReactFlow>
      {editor && (
        <Popup title={title} editor={editor} current={currentValue(model, editor)}
               onPick={(v) => { setEditor(null); bridge.setCell(editor.ai, editor.key, v).then(done); }}
               onClose={() => setEditor(null)} />
      )}
      {toast && <div className={`toast${toast.bad ? " bad" : ""}`}>{toast.text}</div>}
     </TraceContext.Provider>
    </ActionsContext.Provider>
  );
}

function legend(model: Model) {
  return (
    <>
      {model.idle.length > 0 && <div className="idle">AI {spans(model.idle)}: not connected</div>}
      <Swatch color={FILL.kh} text="Krohn-Hite" />
      <Swatch color={FILL.lockin} text="Lock-in card (DAQ device)" />
      <Swatch color={FILL.measurement} text="Channel label (U or V, and pad), with its mode under it" />
      <Swatch color={FILL.other} text="Gain stage" />
      <span className="sw">
        <i style={{ background: electrodeColor("1") }} /><i style={{ background: electrodeColor("3") }} />
        Pad (one color per electrode; muted in the Pads column once used)
      </span>
      <span className="hint">Click a value to change it · click a KH + or − terminal to choose its pin, AO or GND ·
        drag between terminals (an AO onto a KH − input, for one) or a pin onto a slot to connect them ·
        right-click a KH input to disconnect it</span>
    </>
  );
}

function currentValue(m: Model, e: Editor): string {
  const r = m.rows.find((r) => r.ai === e.ai);
  if (!r) return "";
  const v: Record<string, unknown> = {
    electrode: r.electrode, type: r.type, mode: r.mode, kh: r.kh, kh_gain: r.khGain, couple: r.couple,
    filter: r.filter, shunt: r.shunt, minus: r.minus, ext_gain: r.extGain, ao: r.ao, out_gain: r.outGain,
    out_offset: r.outOffset, input: r.khInput,
  };
  return String(v[e.key] ?? "");
}

function spans(ais: number[]): string {
  const out: string[] = [];
  let start = ais[0];
  ais.forEach((a, i) => {
    if (ais[i + 1] !== a + 1) {
      out.push(start === a ? `${a}` : `${start}-${a}`);
      start = ais[i + 1];
    }
  });
  return out.join(", ");
}

function Swatch({ color, text }: { color: string; text: string }) {
  return <span className="sw"><i style={{ background: color }} />{text}</span>;
}

function Popup({ title, editor, current, onPick, onClose }:
               { title: string; editor: Editor; current: string; onPick: (v: string) => void; onClose: () => void }) {
  const [text, setText] = useState(current);
  const ref = useRef<HTMLDivElement>(null);
  const c = editor.choices;
  useEffect(() => {
    const out = (ev: PointerEvent) => { if (ref.current && !ref.current.contains(ev.target as globalThis.Node)) onClose(); };
    const esc = (ev: KeyboardEvent) => { if (ev.key === "Escape") onClose(); };
    document.addEventListener("pointerdown", out, true);
    document.addEventListener("keydown", esc);
    return () => { document.removeEventListener("pointerdown", out, true); document.removeEventListener("keydown", esc); };
  }, []);
  const left = Math.min(editor.x, window.innerWidth - 190);
  const top = Math.min(editor.y + 6, window.innerHeight - 260);
  return (
    <div className="popup" ref={ref} style={{ left, top }}>
      <div className="popup-title">{title}</div>
      {!c && <div className="popup-wait">…</div>}
      {c && (c.free || c.options.length === 0) && (
        <input autoFocus value={text} placeholder="type a value, Enter to apply"
               onChange={(e) => setText(e.target.value)}
               onKeyDown={(e) => { if (e.key === "Enter") onPick(text); }} />
      )}
      {c && c.options.slice(0, 60).map((o) => (
        <div key={o} className={`opt${o === current ? " on" : ""}`} onClick={() => onPick(o)}>{o || "(none)"}</div>
      ))}
    </div>
  );
}

export default function App() {
  return (
    <ReactFlowProvider>
      <Diagram />
    </ReactFlowProvider>
  );
}
