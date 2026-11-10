"""The data the wiring diagram draws, described once, here.

diagrammodel.build() returns a Model. The TypeScript diagram (python/diagram) reads the
same shapes from src/model.gen.ts, which is generated from this file:

    uv run python -m expconfig.diagramtypes          # rewrite diagram/src/model.gen.ts
    uv run python -m expconfig.diagramtypes --check  # fail if it is out of date

Fixtures of real models (the demo rig, and variants) for the diagram's own tests are
written the same way, to diagram/test/fixtures/. tests/test_diagram_types.py checks both
the generated types and the fixtures are current, and that build() returns exactly these
fields.
"""

from __future__ import annotations

import json
import sys
import types
import typing
from pathlib import Path
from typing import Annotated, Literal, TypedDict, Union, get_args, get_origin, get_type_hints

DIAGRAM = Path(__file__).resolve().parents[2] / "diagram"
GENERATED = DIAGRAM / "src" / "model.gen.ts"
FIXTURES = DIAGRAM / "test" / "fixtures"

MinusKind = Literal["ao", "gnd", "nc", "pad", "unused", "none"]


class Issue(TypedDict):
    code: int
    message: str
    error: bool


class Cell(TypedDict):
    edit: Annotated[bool, "can be changed on this row"]
    why: Annotated[str, "differs from the standard channel, and why"]
    issue: Issue | None


class Row(TypedDict):
    ai: int
    type: Annotated[str, "U (sourced), V (measured), n.c., Ground"]
    mode: Annotated[str, "I or gate (U), V or dV (V)"]
    direct: Annotated[bool, "a U row with no Krohn-Hite: the AO drives the pad, the AI is unused"]
    name: Annotated[str, "the automatic label: U1, V2, V26-27"]
    electrode: str
    minus: str
    minusKind: MinusKind
    kh: Annotated[str | None, '"A1", or null: no Krohn-Hite']
    khInput: Annotated[str, "the KH input: DIFF, SE+, OFF"]
    khGain: str
    couple: str
    filter: str
    shunt: Annotated[str | None, "only on U rows with a KH"]
    extGain: float
    lockinGain: float
    ao: Annotated[int | None, "the AO this row's cable uses"]
    aoSlot: Annotated[int | None, "the AO standard for this row, used or not"]
    aoName: str
    outGain: float
    outOffset: float
    aiUsed: bool
    aiChannel: Annotated[str, 'physical channel from the lock-in once read, "PXI1Slot2/ai0"']
    aoChannel: str
    cells: dict[str, Cell]
    mismatch: str
    idle: Annotated[bool, "not connected: drawn thin, still a place to drop a pad"]


class CardAo(TypedDict):
    ao: int
    channel: str
    name: str
    gain: float
    offset: float
    usedBy: Annotated[int | None, "the AI row whose cable uses this AO"]


class Card(TypedDict):
    """A physical lock-in card (a DAQ device): its AIs and AOs, in front-panel order."""
    device: Annotated[str, '"PXI1Slot2"; "lock-in AI n" (one per AI) until the channels are read']
    read: bool
    type: Annotated[str, '"PXI-4461", from getDevices or the DAQ Type; "" when the lock-in does not say']
    serial: Annotated[str, 'DAQ serial number from getDevices (lock-in 3.11+); "" if unknown']
    simulated: Annotated[bool, "an NI-DAQmx simulated device"]
    slot: Annotated[str, '"chassis 1, slot 2" for a PXI card; "" otherwise']
    ais: list[int]
    aos: list[CardAo]


class Pad(TypedDict):
    name: str
    used: bool


class Model(TypedDict):
    pads: Annotated[list[Pad], "the chip carrier's pins"]
    rows: Annotated[list[Row], "one per lock-in AI"]
    cards: list[Card]
    idle: list[int]
    titles: Annotated[dict[str, str], "the table's column titles, by key"]
    selected: tuple[int, str | None] | None


EXPORTS = (Issue, Cell, Row, CardAo, Card, Pad, Model)


# ---- TypeScript ------------------------------------------------------------

def _ts(t) -> str:
    origin, args = get_origin(t), get_args(t)
    if origin is Annotated:
        return _ts(args[0])
    if t is str:
        return "string"
    if t in (int, float):
        return "number"
    if t is bool:
        return "boolean"
    if t is type(None):
        return "null"
    if t is MinusKind:
        return "MinusKind"
    if isinstance(t, type) and typing.is_typeddict(t):
        return t.__name__
    if origin is Literal:
        return " | ".join(json.dumps(a) for a in args)
    if origin in (Union, types.UnionType):
        return " | ".join(_ts(a) for a in args)
    if origin is list:
        inner = _ts(args[0])
        return f"({inner})[]" if "|" in inner else f"{inner}[]"
    if origin is tuple:
        return "[" + ", ".join(_ts(a) for a in args) + "]"
    if origin is dict:
        return f"Record<{_ts(args[0])}, {_ts(args[1])}>"
    raise TypeError(f"no TypeScript for {t!r}")


def typescript() -> str:
    out = ["// GENERATED from python/src/expconfig/diagramtypes.py: do not edit.",
           "// Regenerate: uv run python -m expconfig.diagramtypes", "",
           "export type MinusKind = " + " | ".join(json.dumps(a) for a in get_args(MinusKind)) + ";", ""]
    for td in EXPORTS:
        if td.__doc__:
            out.append(f"/** {td.__doc__.strip()} */")
        out.append(f"export interface {td.__name__} {{")
        for name, t in get_type_hints(td, include_extras=True).items():
            note = next((a for a in get_args(t)[1:] if isinstance(a, str)), "") if get_origin(t) is Annotated else ""
            out.append(f"  {name}: {_ts(t)};" + (f"   // {note}" if note else ""))
        out.append("}")
        out.append("")
    return "\n".join(out)


def check_model(m: dict) -> list[str]:
    """Fields build() sends that the types do not list, or the other way round."""
    problems = []

    def same(d: dict, td, where: str):
        want = set(get_type_hints(td))
        if set(d) != want:
            problems.append(f"{where}: extra {sorted(set(d) - want)}, missing {sorted(want - set(d))}")

    same(m, Model, "model")
    for r in m["rows"]:
        same(r, Row, f"row {r.get('ai')}")
        for k, c in r["cells"].items():
            same(c, Cell, f"row {r.get('ai')} cell {k}")
    for c in m["cards"]:
        same(c, Card, f"card {c.get('device')}")
        for o in c["aos"]:
            same(o, CardAo, f"card {c.get('device')} AO {o.get('ao')}")
    for p in m["pads"]:
        same(p, Pad, "pad")
    return problems


# ---- fixtures ----------------------------------------------------------------

def fixtures() -> dict[str, dict]:
    """Real models for the diagram's tests: the demo rig, read and not, and edited variants."""
    from . import diagrammodel, rules, wiringedit
    from .demo import demo_config, demo_daq, demo_devices
    from .tablemodels import ChannelModel

    def model(cfg, daq=True):
        rules.derive_all(cfg)
        cm = ChannelModel(cfg, lambda: None)
        cm.refresh()
        return diagrammodel.build(cfg, cm, *(demo_daq() if daq else ([], [])),
                                  devices=demo_devices() if daq else None)

    out = {"demo": model(demo_config()), "demo-unread": model(demo_config(), daq=False)}
    cfg = demo_config()
    wiringedit.connect(cfg, ("ao", 4), ("kh-", 3))      # one AO on two rows, across rows
    wiringedit.connect(cfg, ("pad", "20"), ("ai", 10))   # a pad straight onto a 4431 input
    out["shared-ao"] = model(cfg)
    return out


def write_fixtures() -> list[Path]:
    FIXTURES.mkdir(parents=True, exist_ok=True)
    paths = []
    for name, m in fixtures().items():
        p = FIXTURES / f"{name}.json"
        p.write_text(json.dumps(m, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
        paths.append(p)
    return paths


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if "--check" in argv:
        current = GENERATED.read_text(encoding="utf-8") if GENERATED.exists() else ""
        if current != typescript():
            print(f"{GENERATED} is out of date: run python -m expconfig.diagramtypes")
            return 1
        return 0
    GENERATED.write_text(typescript(), encoding="utf-8")
    print(f"wrote {GENERATED}")
    for p in write_fixtures():
        print(f"wrote {p}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
