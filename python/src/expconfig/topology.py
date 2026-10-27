"""Wiring topology as a graph a machine can read.

Nodes are physical terminals: electrodes, KH channel inputs/outputs, lock-in
AIs and AOs, ground, and gain stages outside the instruments. Edges are
cables (or the shunt inside a KH channel). The graph is written into the
configuration file next to the tables, so a data file carries both the
human view (rows) and the connectivity (graph).
"""

from __future__ import annotations

from .model import MINUS_AO, MINUS_GND, MINUS_NC, Config, kh_label

SCHEMA = "levylab.topology/1"


def build(cfg: Config) -> dict:
    nodes: dict[str, dict] = {}
    edges: list[dict] = []

    def node(nid: str, kind: str, **attrs) -> str:
        nodes.setdefault(nid, {"id": nid, "kind": kind, **attrs})
        return nid

    def edge(a: str, b: str, kind: str = "cable", **attrs) -> None:
        edges.append({"from": a, "to": b, "kind": kind, **attrs})

    # An AO with gain != 1 has an amplifier between it and the device. When a
    # U row sources through a KH channel from that AO, the amplifier sits after
    # the KH (AO -> KH - / shunt / + -> amp -> electrode); otherwise it is
    # AO -> amp -> electrode directly.
    via_kh = {c.ao for c in cfg.channels
              if c.kh is not None and c.type == "U" and c.minus == MINUS_AO and c.ao is not None}
    driven: dict[int, list[str]] = {}  # Drive rows: AO -> pads it drives directly
    for c in cfg.channels:
        if c.type == "Drive" and c.ao is not None and c.electrode:
            driven.setdefault(c.ao, []).append(c.electrode)
    amps: dict[int, str] = {}
    for o in cfg.outputs:
        ao = node(f"ao:{o.ao}", "ao", channel=o.ao, name=o.name)
        if o.gain != 1:
            amps[o.ao] = node(f"amp:ao{o.ao}", "gain", gain=o.gain, note="between AO and device")
        if o.ao in via_kh:
            continue
        stage = ao
        if o.ao in amps:
            edge(ao, amps[o.ao])
            stage = amps[o.ao]
        for e in dict.fromkeys(([o.electrode] if o.electrode else []) + driven.get(o.ao, [])):
            edge(stage, node(f"electrode:{e}", "electrode", name=e))

    for ch in cfg.channels:
        if ch.type == "Drive" or (ch.type == "n.c." and not ch.electrode):
            continue
        ai = node(f"ai:{ch.ai}", "ai", channel=ch.ai, role=ch.role, name=ch.name,
                  ext_gain=ch.ext_gain, lockin_gain=ch.lockin_gain)
        sink = ai
        if ch.ext_gain != 1:
            stage = node(f"ext:ai{ch.ai}", "gain", gain=ch.ext_gain, note="between source and AI")
            edge(stage, ai)
            sink = stage
        plus = node(f"electrode:{ch.electrode}", "electrode", name=ch.electrode) if ch.electrode else None
        if ch.type == "Ground" and plus:
            edge(plus, node("gnd", "ground"), kind="ground")
        if ch.kh is None:
            if plus:
                edge(plus, sink)
            continue
        k = kh_label(ch.kh)
        p = node(f"kh:{k}:+", "kh_input", kh=k, terminal="+")
        m = node(f"kh:{k}:-", "kh_input", kh=k, terminal="-")
        out = node(f"kh:{k}:out", "kh_output", kh=k, input=ch.input, gain=ch.kh_gain,
                   shunt=ch.shunt, couple=ch.couple, filter=ch.filter)
        amp = amps.get(ch.ao) if ch.type == "U" and ch.minus == MINUS_AO else None
        if plus and amp:
            edge(plus, amp)
            edge(amp, p)
        elif plus:
            edge(plus, p)
        if ch.minus == MINUS_AO:
            if ch.ao is not None:
                edge(node(f"ao:{ch.ao}", "ao", channel=ch.ao), m)
        elif ch.minus == MINUS_GND:
            edge(node("gnd", "ground"), m)
        elif ch.minus != MINUS_NC:
            edge(node(f"electrode:{ch.minus}", "electrode", name=ch.minus), m)
        if ch.shunt != "Open":
            edge(m, p, kind="shunt", value=ch.shunt)
        edge(out, sink)

    return {"schema": SCHEMA, "nodes": list(nodes.values()), "edges": edges}


def path_to_ai(graph: dict, ai: int) -> list[str]:
    """Walk back from an AI to the electrodes feeding it: the 'what am I measuring' query."""
    into: dict[str, list[str]] = {}
    for e in graph["edges"]:
        into.setdefault(e["to"], []).append(e["from"])
    seen, stack, found = set(), [f"ai:{ai}"], []
    while stack:
        n = stack.pop()
        if n in seen:
            continue
        seen.add(n)
        if n.startswith("electrode:"):
            found.append(n)
        stack.extend(into.get(n, []))
        if n.endswith(":out"):
            k = n.rsplit(":", 1)[0]
            stack += [f"{k}:+", f"{k}:-"]
    return sorted(found)
