"""The wiring diagram as data, for the TypeScript diagram (python/diagram).

The diagram draws only what is here; every edit goes back to Python (the table
logic, wiringedit), which sends a new model. Shared by the Qt window
(wiringweb.py) and the web trial server.
"""

from __future__ import annotations

from .hardware import daq_type
from .model import MINUS_AO, MINUS_GND, MINUS_NC, Config, kh_label
from .tablemodels import CHANNEL_COLUMNS, ChannelModel, exception

# Fields the diagram shows as clickable; the table column they edit.
EDITABLE = ("electrode", "type", "mode", "input", "kh", "kh_gain", "couple", "filter", "shunt", "minus", "ext_gain", "ao",
            "out_gain", "out_offset")


def _natural(s: str):
    return (0, int(s), "") if s.isdigit() else (1, 0, s)


def _minus_kind(ch) -> str:
    if ch.kh is None:
        return "none"
    if ch.minus_is_electrode:
        return "pad"
    if ch.minus == MINUS_GND:
        return "gnd"   # cabled to ground: drawn even when a single-ended input does not use it
    if ch.input in ("SE+", "OFF"):
        return "unused"
    return {MINUS_AO: "ao", MINUS_GND: "gnd", MINUS_NC: "nc"}[ch.minus]


def _device(daq: list[dict], n: int) -> str | None:
    """The DAQ device of AI or AO n ("PXI1Slot2" from "PXI1Slot2/ai0"); None until read."""
    if 1 <= n <= len(daq):
        chan = str(daq[n - 1].get("Channels", ""))
        if "/" in chan:
            return chan.split("/")[0]
    return None


def cards(cfg: Config, model: ChannelModel, ai_daq: list[dict], ao_daq: list[dict],
          devices: list[dict] | None = None) -> list[dict]:
    """The lock-in as its physical cards: each with its AIs and AOs, in channel order.

    Cards come from the DAQ channel names. Until they are read, each AI is drawn as a
    card of its own with AO n beside AI n (the usual pairing), not as made-up hardware.
    """
    out: list[dict] = []
    by_dev: dict[str, dict] = {}
    for ch in cfg.channels:
        dev = _device(ai_daq, ch.ai) or f"lock-in AI {ch.ai}"
        if dev not in by_dev:
            by_dev[dev] = {"device": dev, "ais": [], "aos": []}
            out.append(by_dev[dev])
        by_dev[dev]["ais"].append(ch.ai)
    users = {}
    for ch in cfg.channels:
        if ch.ao is not None and model._drives_ao(ch) and (ch.direct or ch.input == "DIFF"):
            users.setdefault(ch.ao, ch.ai)
    for o in cfg.outputs:
        dev = _device(ao_daq, o.ao)
        card = by_dev.get(dev) if dev else None
        if card is None and dev is None:
            card = next((c for c in out if o.ao in c["ais"]), None)
        if card is None:
            if dev and out:
                # A card with outputs but no inputs: drawn as its own card after the last.
                card = by_dev[dev] = {"device": dev, "ais": [], "aos": []}
                out.append(card)
            elif out:
                card = out[-1]
            else:
                continue
        chan = str(ao_daq[o.ao - 1].get("Channels", "")) if 1 <= o.ao <= len(ao_daq) else ""
        card["aos"].append({"ao": o.ao, "channel": chan, "name": o.name, "gain": o.gain, "offset": o.offset,
                            "usedBy": users.get(o.ao)})
    # What each card is: getDevices (lock-in 3.11+), else the Type in getInputDAQ/getOutputDAQ.
    inventory = {str(d.get("DeviceName")): d for d in devices or []}
    types: dict[str, str] = {}
    for e in [*ai_daq, *ao_daq]:
        dev = str(e.get("Channels", "")).split("/")[0]
        types.setdefault(dev, daq_type(e))
    for c in out:
        c["read"] = not c["device"].startswith("lock-in")
        d = inventory.get(c["device"], {})
        c["type"] = str(d.get("ProductType") or types.get(c["device"], ""))
        c["serial"] = str(d.get("DeviceSerialNumber") or "")
        c["simulated"] = bool(d.get("DevIsSimulated", False))
        c["slot"] = (f"chassis {d['ChassisNumber']}, slot {d['SlotNumber']}"
                     if d.get("ChassisNumber") and d.get("SlotNumber") is not None else "")
    return out


def build(cfg: Config, model: ChannelModel, ai_daq: list[dict] | None = None,
          ao_daq: list[dict] | None = None, selected: tuple | None = None,
          devices: list[dict] | None = None) -> dict:
    ai_daq, ao_daq = ai_daq or [], ao_daq or []
    used = {c.electrode for c in cfg.channels} | {c.minus for c in cfg.channels if c.minus_is_electrode}
    # The Pads column is the chip carrier's pins, nothing else (ground is a choice on the KH - input).
    names = [str(i) for i in range(1, cfg.experiment.pads + 1)]

    def card(daq: list[dict], n) -> str:
        return str(daq[n - 1].get("Channels", "")) if n and 1 <= n <= len(daq) else ""

    rows = []
    for ch in cfg.channels:
        # Every channel stays in the diagram, idle ones too, so a pad can still be dropped onto them.
        out = cfg.output(ch.ao) if ch.ao is not None else None
        uses_ao = model._drives_ao(ch) and (ch.direct or ch.input == "DIFF")
        kh_input = ch.input if cfg.kh_override == "No Selection" else (
            "OFF" if cfg.kh_override == "All Ground" else "DIFF")
        cells = {}
        for key in EDITABLE:
            issue = model.issues.get((ch.ai, key))
            cells[key] = {"edit": model._cell_editable(ch, key), "why": exception(ch, key),
                          "issue": {"code": issue.code, "message": issue.message, "error": issue.is_error}
                          if issue else None}
        mism = model.mismatch.get(ch.ai, "") or (model.ao_mismatch.get(ch.ao, "") if uses_ao else "")
        rows.append({
            "ai": ch.ai, "type": ch.type, "mode": ch.mode, "direct": ch.direct, "name": ch.name or ch.type,
            "electrode": ch.electrode, "minus": ch.minus, "minusKind": _minus_kind(ch),
            "kh": kh_label(ch.kh) if ch.kh is not None else None,
            "khInput": kh_input, "khGain": ch.kh_gain, "couple": ch.couple, "filter": ch.filter,
            "shunt": ch.shunt if ch.type == "U" and ch.kh is not None else None,
            "extGain": ch.ext_gain, "lockinGain": ch.lockin_gain,
            "ao": ch.ao if uses_ao else None, "aoSlot": ch.ao if uses_ao else (ch.ai if cfg.output(ch.ai) else None),
            "aoName": out.name if out and uses_ao else "",
            "outGain": out.gain if out and uses_ao else 1.0, "outOffset": out.offset if out and uses_ao else 0.0,
            "aiUsed": not ch.direct,
            "aiChannel": card(ai_daq, ch.ai), "aoChannel": card(ao_daq, ch.ao if uses_ao else None),
            "cells": cells, "mismatch": mism, "idle": ch.type == "n.c." and not ch.electrode,
        })
    return {
        "pads": [{"name": n, "used": n in used} for n in names],
        "rows": rows,
        "cards": cards(cfg, model, ai_daq, ao_daq, devices),
        "idle": [],   # no longer listed apart: idle rows are drawn, faded
        "titles": {c.key: c.title for c in CHANNEL_COLUMNS},
        "selected": list(selected) if selected else None,
    }
