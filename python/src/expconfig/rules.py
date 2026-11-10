"""Derivation and validation rules (the #182 model).

The UI and any remote caller go through the same functions, so a rule is
enforced once: a V row cannot carry a shunt whether it was set from a table
cell or from JSON.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass

from .model import (
    CHANNEL_TYPES, DEFAULT_SHUNT, KH_CHANNELS_PER_CHASSIS, KH_COUPLINGS, KH_FILTERS, KH_GAINS,
    KH_SHUNTS, MINUS_AO, MODES, SHUNTS_BY_MODE, Channel, Config, normalize_minus, parse_kh_label,
)

# Error codes shared with the LabVIEW #182 spec.
E_AI_MISSING = 5000
E_AI_UNKNOWN = 5001
E_TYPE = 5002
E_SHUNT = 5003
E_GAIN = 5004
E_MINUS_SELF = 5005
E_KH = 5008
E_KH_DUPLICATE = 5009
E_COUPLE = 5010
E_FILTER = 5011
E_AO = 5012
E_VALUE = 5013
W_NO_ELECTRODE = 6001
W_U_SHUNT = 6002
W_NOT_A_PAD = 6003
W_DV_NO_PAD = 6004


@dataclass(frozen=True)
class Issue:
    code: int
    ai: int | None
    field: str
    message: str

    @property
    def is_error(self) -> bool:
        return self.code < 6000


def derive(ch: Channel) -> Channel:
    """Fill the derived fields (mode if unset, input, label) and force the shunt where it does not apply."""
    if ch.type == "Drive":   # older files: an AO driving the pad directly is a U row with no KH
        ch.type, ch.kh, ch.mode = "U", None, ch.mode or "gate"
    if ch.type == "U":
        if ch.mode not in MODES["U"]:
            ch.mode = "gate" if ch.shunt == "10M" or ch.kh is None else "I"
        ch.input = "DIFF"
        if ch.kh is None:   # the AO drives the pad directly: no shunt, nothing in front of the AI
            ch.minus = MINUS_AO
            ch.ext_gain = 1.0
            ch.shunt = "Open"
        ch.name = f"U{ch.electrode}" if ch.electrode else "U"   # the mode (I or gate) is kept apart
    elif ch.type == "V":
        if ch.minus_is_electrode:
            ch.mode = "dV"
        elif ch.mode not in MODES["V"]:
            ch.mode = "V"
        ch.input = "DIFF" if ch.mode == "dV" else "SE+"
        if ch.mode == "dV":
            ch.name = f"V{ch.electrode}-{ch.minus if ch.minus_is_electrode else '?'}"
        else:
            ch.name = f"V{ch.electrode}" if ch.electrode else "V"
        ch.shunt = "Open"
    else:
        ch.mode = ""
        ch.input = "OFF"
        ch.name = ""
        ch.shunt = "Open"
    if ch.kh is None:
        ch.input = "OFF"
    return ch


def _fit_shunt(ch: Channel, default_shunt: str) -> None:
    """A U row's shunt within its mode's range: the default for the mode if it is not."""
    if ch.type == "U" and ch.kh is not None and ch.shunt not in SHUNTS_BY_MODE[ch.mode]:
        ch.shunt = default_shunt if ch.mode == "I" and default_shunt in SHUNTS_BY_MODE["I"] \
            else DEFAULT_SHUNT[ch.mode]


def derive_all(cfg: Config) -> Config:
    for ch in cfg.channels:
        derive(ch)
    return cfg


def set_type(ch: Channel, new_type: str, default_shunt: str) -> None:
    """Change a row's type the way the UI does: a U row gets a shunt for its mode."""
    if new_type == "Drive":   # older callers: a U row whose AO drives the pad directly
        new_type, ch.kh, ch.mode = "U", None, "gate"
    elif ch.direct and new_type != "U":
        ch.kh = ch.ai - 1  # no longer driven directly: back to the standard KH channel
    if new_type == "U" and ch.ao is None:
        ch.ao = ch.ai
    if new_type != ch.type:
        ch.mode = MODES[new_type][0] if new_type in MODES and ch.mode not in MODES[new_type] else ch.mode
    ch.type = new_type
    derive(ch)
    _fit_shunt(ch, default_shunt)


def set_mode(ch: Channel, mode: str, default_shunt: str) -> None:
    """Change a U row between I and gate (the shunt follows), or a V row between V and dV."""
    if mode not in MODES.get(ch.type, ()):
        raise ValueError(f"mode {mode!r} is not one of {MODES.get(ch.type, ())} for a {ch.type} row")
    ch.mode = mode
    if ch.type == "V" and mode == "V" and ch.minus_is_electrode:
        ch.minus = MINUS_AO   # single-ended: the - input is no longer on a second pad
    derive(ch)
    _fit_shunt(ch, default_shunt)


def validate(cfg: Config) -> list[Issue]:
    issues: list[Issue] = []
    limit = KH_CHANNELS_PER_CHASSIS * cfg.kh_chassis
    seen_kh: dict[int, int] = {}
    ao_numbers = {o.ao for o in cfg.outputs}
    for ch in cfg.channels:
        if ch.type not in CHANNEL_TYPES:
            issues.append(Issue(E_TYPE, ch.ai, "type", f"type {ch.type!r} is not one of {CHANNEL_TYPES}"))
        for fld, allowed, code in (("shunt", KH_SHUNTS, E_SHUNT), ("kh_gain", KH_GAINS, E_GAIN),
                                   ("couple", KH_COUPLINGS, E_COUPLE), ("filter", KH_FILTERS, E_FILTER)):
            if getattr(ch, fld) not in allowed:
                issues.append(Issue(code, ch.ai, fld, f"{fld} {getattr(ch, fld)!r} is not one of {allowed}"))
        if ch.minus_is_electrode and ch.minus == ch.electrode:
            issues.append(Issue(E_MINUS_SELF, ch.ai, "minus", "minus input is the same electrode as plus"))
        if ch.kh is not None:
            if ch.kh >= limit:
                issues.append(Issue(E_KH, ch.ai, "kh", f"KH channel beyond the {cfg.kh_chassis} chassis configured"))
            elif ch.kh in seen_kh:
                issues.append(Issue(E_KH_DUPLICATE, ch.ai, "kh",
                                    f"KH channel also used by AI {seen_kh[ch.kh]}"))
            else:
                seen_kh[ch.kh] = ch.ai
        if ch.type in ("U", "V") and not ch.electrode:
            issues.append(Issue(W_NO_ELECTRODE, ch.ai, "electrode", "no electrode entered"))
        for fld, e in (("electrode", ch.electrode), ("minus", ch.minus if ch.minus_is_electrode else "")):
            if e and not (e.isdigit() and 1 <= int(e) <= cfg.experiment.pads):
                issues.append(Issue(W_NOT_A_PAD, ch.ai, fld,
                                    f"{e} is not a pin of the {cfg.experiment.pads}-pin chip carrier"))
        if ch.type == "U" and ch.kh is not None and ch.shunt not in SHUNTS_BY_MODE.get(ch.mode, ()):
            issues.append(Issue(W_U_SHUNT, ch.ai, "shunt",
                                f"a U row in {ch.mode} mode takes a shunt of {' / '.join(SHUNTS_BY_MODE[ch.mode])}"))
        if ch.type == "V" and ch.mode == "dV" and not ch.minus_is_electrode:
            issues.append(Issue(W_DV_NO_PAD, ch.ai, "minus", "dV needs a second pad on the \u2212 input"))
        if ch.type == "U" and ch.minus == MINUS_AO and ch.ao not in ao_numbers:
            issues.append(Issue(E_AO, ch.ai, "ao", f"AO {ch.ao} is not an output of the lock-in"))
        if ch.ext_gain <= 0:
            issues.append(Issue(E_VALUE, ch.ai, "ext_gain", "external gain must be positive"))
    for o in cfg.outputs:
        if o.gain == 0:
            issues.append(Issue(E_VALUE, None, f"output {o.ao}", "output gain must not be 0"))
    return issues


_STRING_FIELDS = {
    # entry key -> (channel attribute, allowed values or None, error code)
    "Electrode": ("electrode", None, None),
    "Role": ("role", None, None),
    "Type": ("type", CHANNEL_TYPES + ("Drive",), E_TYPE),   # Drive: still accepted from older callers
    "Shunt": ("shunt", KH_SHUNTS, E_SHUNT),
    "KH Gain": ("kh_gain", KH_GAINS, E_GAIN),
    "Couple": ("couple", KH_COUPLINGS, E_COUPLE),
    "Filter": ("filter", KH_FILTERS, E_FILTER),
}


class EntryError(ValueError):
    def __init__(self, issues: list[Issue]):
        super().__init__("; ".join(f"[{i.code}] AI {i.ai}: {i.message}" for i in issues))
        self.issues = issues


def apply_entries(cfg: Config, entries: list[dict]) -> Config:
    """Merge partial channel entries (the setChannelConfig payload) into a copy of cfg.

    Keys are those of the #182 request: AI (required), Electrode, Minus, Type,
    Role, KH, Shunt, KH Gain, Couple, Filter, External Gain, AO. Missing keys
    leave the field unchanged. Any error rejects the whole request.
    """
    new = copy.deepcopy(cfg)
    issues: list[Issue] = []
    for idx, e in enumerate(entries):
        ai = e.get("AI")
        if not isinstance(ai, int):
            issues.append(Issue(E_AI_MISSING, None, "AI", f"entry {idx}: AI missing or not an integer"))
            continue
        ch = new.channel(ai)
        if ch is None:
            issues.append(Issue(E_AI_UNKNOWN, ai, "AI", f"entry {idx}: AI {ai} not in the table"))
            continue
        for key, (attr, allowed, code) in _STRING_FIELDS.items():
            if key not in e:
                continue
            value = str(e[key])
            if allowed is not None and value not in allowed:
                issues.append(Issue(code, ai, attr, f"entry {idx}: {key} {value!r} not one of {allowed}"))
                continue
            if attr == "type":
                set_type(ch, value, new.default_shunt)
            else:
                setattr(ch, attr, value)
        if "Mode" in e:
            try:
                set_mode(ch, str(e["Mode"]), new.default_shunt)
            except ValueError as err:
                issues.append(Issue(E_TYPE, ai, "mode", f"entry {idx}: {err}"))
        elif "Shunt" in e and ch.type == "U" and ch.shunt not in SHUNTS_BY_MODE[ch.mode]:
            # A shunt given without a mode says which mode it is (10M: a gate).
            ch.mode = next((m for m, s in SHUNTS_BY_MODE.items() if ch.shunt in s), ch.mode)
        if "Minus" in e:
            ch.minus = normalize_minus(str(e["Minus"]))
        if "KH" in e:
            try:
                ch.kh = parse_kh_label(str(e["KH"]))
            except ValueError as err:
                issues.append(Issue(E_KH, ai, "kh", f"entry {idx}: {err}"))
        if "External Gain" in e:
            try:
                ch.ext_gain = float(e["External Gain"])
            except (TypeError, ValueError):
                issues.append(Issue(E_VALUE, ai, "ext_gain", f"entry {idx}: External Gain not a number"))
        if "AO" in e:
            ch.ao = e["AO"] if isinstance(e["AO"], int) else None
        derive(ch)
    issues += [i for i in validate(new) if i.is_error]
    if issues:
        raise EntryError(issues)
    return new


def set_all(cfg: Config, attr: str, value: str) -> None:
    """Set-all control: write one couple/filter value into every row."""
    for ch in cfg.channels:
        setattr(ch, attr, value)
