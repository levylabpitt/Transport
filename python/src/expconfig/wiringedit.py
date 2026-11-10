"""Turn a cable drawn in the wiring diagram into channel-table edits.

A port is (kind, id):
  ("pad", "7")   a device pad (electrode name)
  ("gnd", None)  ground
  ("kh+", ai)    the + input of the KH channel on row `ai`
  ("kh-", ai)    its - input
  ("khout", ai)  its output
  ("ai", ai)     lock-in AI
  ("ao", n)      lock-in AO n

The table stays the one source of truth: connect() edits the rows and returns
what it did, or raises WiringError with the reason a cable is not possible.
"""

from __future__ import annotations

from . import rules
from .model import MINUS_AO, MINUS_GND, MINUS_NC, Config, kh_label

Port = tuple[str, object]


class WiringError(ValueError):
    pass


def _row(cfg: Config, ai) -> object:
    ch = cfg.channel(ai)
    if ch is None:
        raise WiringError(f"there is no row for AI {ai}")
    return ch


def connect(cfg: Config, a: Port, b: Port) -> str:
    """Apply the cable a-b to cfg. Order does not matter."""
    if a == b:
        raise WiringError("a cable needs two different ends")
    order = ("pad", "gnd", "ao", "kh+", "kh-", "khout", "ai")
    a, b = sorted((a, b), key=lambda p: order.index(p[0]))
    kinds = (a[0], b[0])

    if kinds == ("pad", "kh+"):
        ch = _row(cfg, b[1])
        ch.electrode = str(a[1])
        if ch.type in ("n.c.", "Ground"):
            rules.set_type(ch, "V", cfg.default_shunt)
        rules.derive(ch)
        return f"AI {ch.ai}: pad {a[1]} on {kh_label(ch.kh)} +"
    if kinds == ("pad", "kh-"):
        ch = _row(cfg, b[1])
        if str(a[1]) == ch.electrode:
            raise WiringError(f"pad {a[1]} is already on the + input of {kh_label(ch.kh)}")
        ch.minus = str(a[1])
        rules.derive(ch)
        return f"AI {ch.ai}: pad {a[1]} on {kh_label(ch.kh)} − (differential)"
    if kinds == ("gnd", "kh-"):
        ch = _row(cfg, b[1])
        ch.minus = MINUS_GND
        rules.derive(ch)
        return f"AI {ch.ai}: {kh_label(ch.kh)} − to ground"
    if kinds == ("ao", "kh-"):
        ch = _row(cfg, b[1])
        if cfg.output(a[1]) is None:
            raise WiringError(f"the lock-in has no AO {a[1]}")
        ch.minus, ch.ao = MINUS_AO, int(a[1])
        if ch.type in ("n.c.", "Ground", "V"):
            rules.set_type(ch, "U", cfg.default_shunt)  # sourced through the shunt
        rules.derive(ch)
        return f"AI {ch.ai}: AO {a[1]} on {kh_label(ch.kh)} − (U, {ch.mode}, shunt {ch.shunt})"
    if kinds == ("khout", "ai"):
        src, dst = _row(cfg, a[1]), _row(cfg, b[1])
        if src is dst:
            return f"AI {dst.ai}: already fed by {kh_label(dst.kh)}"
        # The KH channels trade places; each row keeps its own pad, type and settings.
        src.kh, dst.kh = dst.kh, src.kh
        rules.derive(src)
        rules.derive(dst)
        return f"AI {dst.ai} now reads {kh_label(dst.kh)}; AI {src.ai} reads {kh_label(src.kh)}"
    if kinds == ("pad", "ai"):
        ch = _row(cfg, b[1])
        ch.electrode = str(a[1])
        if ch.type != "V":
            rules.set_type(ch, "V", cfg.default_shunt)
        ch.kh = None
        rules.derive(ch)
        return f"AI {ch.ai}: pad {a[1]} straight to the AI, no Krohn-Hite"
    if kinds == ("pad", "ao"):
        ch = _row(cfg, b[1])  # row n becomes a U row with no KH: AO n drives the pad, AI n is unused
        ch.electrode, ch.ao = str(a[1]), int(b[1])
        rules.set_type(ch, "U", cfg.default_shunt)
        ch.kh, ch.mode = None, "gate"
        rules.derive(ch)
        return f"AI {ch.ai}: AO {b[1]} drives pad {a[1]} directly (U, gate, no KH; AI {ch.ai} unused)"
    if kinds == ("gnd", "kh+") or kinds == ("pad", "gnd"):
        raise WiringError("ground goes on a KH − input; to ground a channel, set its type to Ground")
    if "ai" in kinds and "ao" in kinds:
        raise WiringError("an AO is not wired straight into an AI here")
    raise WiringError(f"a {a[0]} cannot be cabled to a {b[0]}")


def disconnect(cfg: Config, port: Port) -> str:
    """Remove the cable on a KH input."""
    kind, ai = port
    ch = _row(cfg, ai)
    if kind == "kh+":
        ch.electrode = ""
        rules.set_type(ch, "n.c.", cfg.default_shunt)
        return f"AI {ai}: + input disconnected"
    if kind == "kh-":
        ch.minus = MINUS_NC
        if ch.type == "V":
            ch.mode = "V"   # no second pad: single-ended again
        if ch.type == "U":
            rules.set_type(ch, "V", cfg.default_shunt)
        rules.derive(ch)
        return f"AI {ai}: − input disconnected"
    raise WiringError("only KH inputs can be disconnected here; edit the table for the rest")
