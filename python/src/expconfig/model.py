"""Configuration model: one Channel per lock-in AI, one Output per AO.

Field values that end up on an instrument use the instrument's own enum
strings (Krohn-Hite `input`, `gain`, `shunt`, `couple`, `filter`), so a row
maps one-to-one onto a KH `channelProperties` entry.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field, fields

# Drive: AO n drives the pad directly (through its output gain), no KH, AI n unused.
CHANNEL_TYPES = ("U", "V", "n.c.", "Ground", "Drive")
KH_INPUTS = ("OFF", "SE+", "SE-", "DIFF")
KH_GAINS = ("1", "10", "100", "1000")
KH_SHUNTS = ("Open", "50", "500", "5k", "50k", "10M")
KH_COUPLINGS = ("AC", "DC")
KH_FILTERS = ("OFF", "ON")
KH_OVERRIDES = ("No Selection", "All Ground", "All Differential")
KH_CHANNELS_PER_CHASSIS = 8

# Minus-input values that are not electrode names.
MINUS_AO = ""
MINUS_GND = "GND"
MINUS_NC = "n.c."
MINUS_KEYWORDS = (MINUS_AO, MINUS_GND, MINUS_NC)

# Role labels the experiment VIs look up (Get Channel Indices.vi), in the
# order of the old Configure Experiment label ring.
ROLE_STRINGS = (
    "", "I+", "I-", "V1+", "V1-", "V2+", "V2-", "V3+", "V3-", "V4+", "V4-",
    "dV1", "dV2", "dV3", "Vsg", "Vbg", "Vtg",
)


def kh_label(index: int | None) -> str:
    """0 -> 'A1', 9 -> 'B2', None -> 'none'."""
    if index is None:
        return "none"
    chassis, channel = divmod(index, KH_CHANNELS_PER_CHASSIS)
    return f"{chr(ord('A') + chassis)}{channel + 1}"


def parse_kh_label(text: str) -> int | None:
    """Inverse of kh_label. Accepts 'A1', 'a 1', 'none'. Raises ValueError."""
    t = text.strip().replace(" ", "").upper()
    if t in ("NONE", ""):
        return None
    m = re.fullmatch(r"([A-Z])([1-8])", t)
    if not m:
        raise ValueError(f"KH channel {text!r} is not a letter followed by 1-8, or 'none'")
    return (ord(m.group(1)) - ord("A")) * KH_CHANNELS_PER_CHASSIS + int(m.group(2)) - 1


def normalize_minus(text: str) -> str:
    t = text.strip()
    if t.lower() in ("nc", "n.c.", "n.c"):
        return MINUS_NC
    if t.lower() in ("gnd", "ground"):
        return MINUS_GND
    if t.lower() in ("ao", "(ao)"):
        return MINUS_AO
    return t


@dataclass
class Channel:
    """One lock-in AI and how it is cabled. Derived fields are filled by rules.derive."""

    ai: int
    electrode: str = ""
    minus: str = MINUS_AO
    type: str = "n.c."
    role: str = ""
    kh: int | None = None
    shunt: str = "Open"
    kh_gain: str = "1"
    couple: str = "AC"
    filter: str = "OFF"
    ext_gain: float = 1.0
    ao: int | None = None
    # derived
    input: str = "OFF"
    name: str = ""

    @property
    def lockin_gain(self) -> float:
        return float(self.kh_gain) * self.ext_gain if self.kh is not None else self.ext_gain

    @property
    def minus_is_electrode(self) -> bool:
        return self.minus not in MINUS_KEYWORDS

    def to_dict(self) -> dict:
        d = asdict(self)
        d["kh"] = kh_label(self.kh)
        d["lockin_gain"] = self.lockin_gain
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "Channel":
        names = {f.name for f in fields(cls)}
        kw = {k: v for k, v in d.items() if k in names}
        if isinstance(kw.get("kh"), str):
            kw["kh"] = parse_kh_label(kw["kh"])
        return cls(**kw)


@dataclass
class Output:
    """One lock-in AO: what it drives, the gain between it and the device, and the
    offset (in output units, at the device) the lock-in subtracts to trim the amplifier."""

    ao: int
    name: str = ""
    gain: float = 1.0
    electrode: str = ""
    offset: float = 0.0

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Output":
        names = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in d.items() if k in names})


@dataclass
class Experiment:
    sample: str = ""
    device: str = ""
    user: str = ""
    description: str = ""
    path: str = ""
    station: str = ""
    station_type: str = ""
    pads: int = 28  # bond pads on the device, numbered 1..pads

    @property
    def device_name(self) -> str:
        return ".".join(p for p in (self.sample, self.device) if p)


@dataclass
class Instruments:
    kh_addresses: list[str] = field(default_factory=lambda: ["tcp://localhost:29160"])
    lockin_address: str = "tcp://localhost:29170"


@dataclass
class Config:
    experiment: Experiment = field(default_factory=Experiment)
    channels: list[Channel] = field(default_factory=list)
    outputs: list[Output] = field(default_factory=list)
    instruments: Instruments = field(default_factory=Instruments)
    kh_override: str = "No Selection"
    default_shunt: str = "5k"
    # Untouched parts of Control Experiment.json (instrument classes, sweep, ...).
    legacy: dict = field(default_factory=dict)

    @property
    def kh_chassis(self) -> int:
        return len(self.instruments.kh_addresses)

    def channel(self, ai: int) -> Channel | None:
        return next((c for c in self.channels if c.ai == ai), None)

    def output(self, ao: int) -> Output | None:
        return next((o for o in self.outputs if o.ao == ao), None)

    def resize(self, n_ai: int, n_ao: int | None = None) -> None:
        """Grow or shrink the tables. New rows get the default cabling (KH n, AO n)."""
        n_ao = n_ai if n_ao is None else n_ao
        self.channels = self.channels[:n_ai]
        last = self.channels[-1] if self.channels else None
        for ai in range(len(self.channels) + 1, n_ai + 1):
            kh = ai - 1 if ai - 1 < KH_CHANNELS_PER_CHASSIS * self.kh_chassis else None
            self.channels.append(Channel(
                ai=ai, kh=kh, ao=ai if ai <= n_ao else None,
                couple=last.couple if last else "AC",
                filter=last.filter if last else "OFF",
            ))
        self.outputs = self.outputs[:n_ao]
        for ao in range(len(self.outputs) + 1, n_ao + 1):
            self.outputs.append(Output(ao=ao))
        limit = KH_CHANNELS_PER_CHASSIS * self.kh_chassis
        for c in self.channels:
            if c.kh is not None and c.kh >= limit:
                c.kh = None
