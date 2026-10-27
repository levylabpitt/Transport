"""Derivation and validation rules (the #182 model).

The UI and any remote caller go through the same functions, so a rule is
enforced once: a V row cannot carry a shunt whether it was set from a table
cell or from JSON.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass

from .model import (
    CHANNEL_TYPES, KH_CHANNELS_PER_CHASSIS, KH_COUPLINGS, KH_FILTERS, KH_GAINS,
    KH_SHUNTS, MINUS_AO, Channel, Config, normalize_minus, parse_kh_label,
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
W_U_OPEN_SHUNT = 6002
W_NOT_A_PAD = 6003


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
    """Fill the derived fields (input, name) and force the shunt where it does not apply."""
    if ch.type == "U":
        ch.input = "DIFF"
        ch.name = f"U{ch.electrode}" if ch.electrode else "U"
    elif ch.type == "Drive":
        ch.kh = None
        ch.minus = MINUS_AO
        ch.ext_gain = 1.0
        ch.shunt = "Open"
        ch.name = ""
    elif ch.type == "V":
        if ch.minus_is_electrode:
            ch.input = "DIFF"
            ch.name = f"dV{ch.electrode}-{ch.minus}"
        else:
            ch.input = "SE+"
            ch.name = f"V{ch.electrode}" if ch.electrode else "V"
        ch.shunt = "Open"
    else:
        ch.input = "OFF"
        ch.name = ""
        ch.shunt = "Open"
    if ch.kh is None:
        ch.input = "OFF"
    return ch


def derive_all(cfg: Config) -> Config:
    for ch in cfg.channels:
        derive(ch)
    return cfg


def set_type(ch: Channel, new_type: str, default_shunt: str) -> None:
    """Change a row's type the way the UI does: a new U row gets the default shunt."""
    if ch.type == "Drive" and new_type != "Drive" and ch.kh is None:
        ch.kh = ch.ai - 1  # back to the standard channel
    if new_type == "Drive" and ch.ao is None:
        ch.ao = ch.ai
    ch.type = new_type
    if new_type == "U" and ch.shunt == "Open":
        ch.shunt = default_shunt
    derive(ch)


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
        if ch.type in ("U", "V", "Drive") and not ch.electrode:
            issues.append(Issue(W_NO_ELECTRODE, ch.ai, "electrode", "no electrode entered"))
        for fld, e in (("electrode", ch.electrode), ("minus", ch.minus if ch.minus_is_electrode else "")):
            if e.isdigit() and not 1 <= int(e) <= cfg.experiment.pads:
                issues.append(Issue(W_NOT_A_PAD, ch.ai, fld,
                                    f"electrode {e} is not a pad of a {cfg.experiment.pads}-pad device"))
        if ch.type == "U" and ch.shunt == "Open":
            issues.append(Issue(W_U_OPEN_SHUNT, ch.ai, "shunt", "U with an open shunt measures no current"))
        if ch.type in ("U", "Drive") and ch.minus == MINUS_AO and ch.ao not in ao_numbers:
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
    "Type": ("type", CHANNEL_TYPES, E_TYPE),
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
