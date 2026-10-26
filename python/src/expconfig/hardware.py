"""Turn the configuration into instrument settings, apply them, read them back."""

from __future__ import annotations

from dataclasses import dataclass, field

from .instruments import KH7008, Lockin
from .model import KH_CHANNELS_PER_CHASSIS, Config, kh_label


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


@dataclass
class Readback:
    kh: dict[int, list[dict]] = field(default_factory=dict)
    input_gain: list[float] = field(default_factory=list)
    output_gain: list[float] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def mismatches(self, cfg: Config) -> list[str]:
        """Rows whose instrument state differs from the table."""
        out = []
        for ch in cfg.channels:
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

    def close(self) -> None:
        for kh in self.khs:
            kh.close()
        self.lockin.close()
