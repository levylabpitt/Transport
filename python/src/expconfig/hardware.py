"""Turn the configuration into instrument settings, apply them, read them back."""

from __future__ import annotations

from dataclasses import dataclass, field

from .instruments import KH7008, Lockin
from .model import KH_CHANNELS_PER_CHASSIS, KH_SHUNTS, Config, kh_label


def kh_settings(cfg: Config, current: dict[int, list[dict]]) -> dict[int, list[dict]]:
    """New allChannelProperties per chassis. Channels no row uses keep their current settings."""
    new = {c: [dict(p) for p in props] for c, props in current.items()}
    for ch in cfg.channels:
        if ch.kh is None:
            continue
        chassis, idx = divmod(ch.kh, KH_CHANNELS_PER_CHASSIS)
        props = new.get(chassis)
        if props is None:
            continue
        entry = next((p for p in props if p.get("channel") == idx + 1), None)
        if entry is None:
            entry = {"channel": idx + 1}
            props.append(entry)
        entry.update(gain=ch.kh_gain, input=ch.input, shunt=ch.shunt, couple=ch.couple, filter=ch.filter)
        if cfg.kh_override == "All Ground":
            entry["input"] = "OFF"
        elif cfg.kh_override == "All Differential":
            entry["input"] = "DIFF"
    return new


def input_gains(cfg: Config, n: int) -> list[float]:
    gains = [1.0] * n
    for ch in cfg.channels:
        if 1 <= ch.ai <= n:
            gains[ch.ai - 1] = ch.lockin_gain
    return gains


def output_gains(cfg: Config, n: int) -> list[float]:
    gains = [1.0] * n
    for o in cfg.outputs:
        if 1 <= o.ao <= n:
            gains[o.ao - 1] = o.gain
    return gains


def available_shunts(reply) -> list[str] | None:
    """getShuntResistor returns the optional resistor fitted in the chassis as one
    string: "500" means the 10M position is not usable, anything else non-empty means
    the 500 position is not (Configure Experiment, UI: Disable KH SR). "" = unknown."""
    if isinstance(reply, list):
        return [str(x) for x in reply] or None
    fitted = str(reply or "").strip()
    if not fitted:
        return None
    missing = "10M" if fitted == "500" else "500"
    return [s for s in KH_SHUNTS if s != missing]


@dataclass
class Readback:
    kh: dict[int, list[dict]] = field(default_factory=dict)
    input_gain: list[float] = field(default_factory=list)
    shunts: dict[int, list[str]] = field(default_factory=dict)
    output_gain: list[float] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def mismatches(self, cfg: Config) -> list[str]:
        """Rows whose instrument state differs from the table."""
        out = []
        if self.input_gain and len(cfg.channels) > len(self.input_gain):
            out.append(f"AI {len(self.input_gain) + 1}: the lock-in has only {len(self.input_gain)} inputs")
        for ch in cfg.channels:
            if ch.kh is not None and ch.shunt != "Open":
                avail = self.shunts.get(ch.kh // KH_CHANNELS_PER_CHASSIS)
                if avail is not None and ch.shunt not in avail:
                    out.append(f"AI {ch.ai}: shunt {ch.shunt} not fitted in chassis "
                               f"{kh_label(ch.kh)[0]} (has {', '.join(avail)})")
            if ch.kh is not None:
                chassis, idx = divmod(ch.kh, KH_CHANNELS_PER_CHASSIS)
                p = next((p for p in self.kh.get(chassis, []) if p.get("channel") == idx + 1), None)
                if p is None:
                    out.append(f"AI {ch.ai}: {kh_label(ch.kh)} not reported by the KH")
                else:
                    want = {"gain": ch.kh_gain, "shunt": ch.shunt, "couple": ch.couple, "filter": ch.filter}
                    if cfg.kh_override == "No Selection":
                        want["input"] = ch.input
                    for k, v in want.items():
                        if str(p.get(k)) != str(v):
                            out.append(f"AI {ch.ai} {kh_label(ch.kh)}: {k} is {p.get(k)!r}, table says {v!r}")
            if self.input_gain and ch.ai <= len(self.input_gain):
                if abs(self.input_gain[ch.ai - 1] - ch.lockin_gain) > 1e-9 * max(1.0, ch.lockin_gain):
                    out.append(f"AI {ch.ai}: lock-in input gain {self.input_gain[ch.ai - 1]}, table {ch.lockin_gain}")
        for o in cfg.outputs:
            if self.output_gain and o.ao <= len(self.output_gain):
                if abs(self.output_gain[o.ao - 1] - o.gain) > 1e-9 * max(1.0, abs(o.gain)):
                    out.append(f"AO {o.ao}: lock-in output gain {self.output_gain[o.ao - 1]}, table {o.gain}")
        return out


def adopt(cfg: Config, rb: Readback) -> list[str]:
    """Copy instrument state into the table: KH gain/shunt/couple/filter per row and the
    lock-in output gains. Types, electrodes and roles are not touched. Returns what changed."""
    changes = []
    for ch in cfg.channels:
        p = None
        if ch.kh is not None:
            chassis, idx = divmod(ch.kh, KH_CHANNELS_PER_CHASSIS)
            p = next((p for p in rb.kh.get(chassis, []) if p.get("channel") == idx + 1), None)
            # A channel that is OFF on the KH while the row expects it on was never
            # configured; its shunt and gain say nothing about the experiment.
            if p and p.get("input") == "OFF" and ch.input != "OFF":
                p = None
        if p:
            for attr, key in (("kh_gain", "gain"), ("couple", "couple"), ("filter", "filter")) + (
                    (("shunt", "shunt"),) if ch.type == "U" else ()):
                if str(p.get(key)) != getattr(ch, attr):
                    changes.append(f"AI {ch.ai}: {attr} {getattr(ch, attr)} -> {p.get(key)}")
                    setattr(ch, attr, str(p.get(key)))
        # The lock-in input gain is KH gain x external gain, so an external gain the
        # old Configure Experiment never saved can be recovered from it. Only for rows
        # still at the default 1, and only gains above 1 (SR830, preamp): a ratio
        # below 1 more likely means the KH gain was changed and the lock-in is stale.
        if ch.ext_gain == 1 and ch.ai <= len(rb.input_gain):
            kh_gain = float(ch.kh_gain) if ch.kh is not None else 1.0
            ext = float(rb.input_gain[ch.ai - 1]) / kh_gain
            if ext > 1 + 1e-9:
                changes.append(f"AI {ch.ai}: ext_gain 1 -> {ext:g} (from the lock-in input gain)")
                ch.ext_gain = ext
    for o in cfg.outputs:
        if o.ao <= len(rb.output_gain) and rb.output_gain[o.ao - 1] != o.gain:
            changes.append(f"AO {o.ao}: gain {o.gain:g} -> {rb.output_gain[o.ao - 1]:g}")
            o.gain = float(rb.output_gain[o.ao - 1])
    return changes


class Rig:
    """The instruments one configuration drives."""

    def __init__(self, cfg: Config, timeout: float = 3.0):
        self.khs = [KH7008(a, timeout) for a in cfg.instruments.kh_addresses]
        self.lockin = Lockin(cfg.instruments.lockin_address, timeout)

    def read(self) -> Readback:
        rb = Readback()
        for i, kh in enumerate(self.khs):
            try:
                rb.kh[i] = kh.get_all_channels()
                avail = available_shunts(kh.get_shunt_resistors())
                if avail is not None:
                    rb.shunts[i] = avail
            except Exception as err:
                rb.errors.append(f"KH {chr(65 + i)}: {err}")
        try:
            rb.input_gain = self.lockin.get_input_gain()
            rb.output_gain = self.lockin.get_output_gain()
        except Exception as err:
            rb.errors.append(f"Lock-in: {err}")
        return rb

    def apply(self, cfg: Config) -> Readback:
        before = self.read()
        if before.errors:
            return before
        for chassis, props in kh_settings(cfg, before.kh).items():
            self.khs[chassis].set_all_channels(props)
        self.lockin.set_input_gain(input_gains(cfg, len(before.input_gain)))
        self.lockin.set_output_gain(output_gains(cfg, len(before.output_gain)))
        return self.read()

    def serials(self) -> tuple[str, list[str]]:
        """Serial numbers from IDN, for the measurement record."""
        return (str(self.lockin.idn().get("serial", "")),
                [str(kh.idn().get("serial", "")) for kh in self.khs])

    def close(self) -> None:
        for kh in self.khs:
            kh.close()
        self.lockin.close()
