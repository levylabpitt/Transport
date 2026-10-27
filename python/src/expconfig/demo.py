"""A demonstration configuration covering the cases discussed in #182."""

from __future__ import annotations

from . import rules
from .model import Config, Experiment


def demo_config() -> Config:
    cfg = Config(experiment=Experiment(sample="SA4017", device="20261026", user="Patrick",
                                       description="Hall bar, backgate sweep", path="C:\\temp",
                                       station="PPMS (sim)", station_type="Cryo"))
    cfg.resize(9, 9)
    # A 28-pad device with pads 1-5, 14 and 26-28 bonded; the backgate is off-chip.
    # The top gate (pad 14) is driven straight from AO 9: no KH, AI 9 unused.
    rows = {
        1: dict(Type="U", Electrode="1", Role="I+", Shunt="5k"),
        2: dict(Type="V", Electrode="2", Role="V1+"),
        3: dict(Type="V", Electrode="3", Role="V1-"),
        4: dict(Type="U", Electrode="gate", Role="Vbg", Shunt="10M"),
        5: dict(Type="V", Electrode="5", KH="none", **{"External Gain": 2000}),
        6: dict(Type="V", Electrode="26", Role="V2+"),
        7: dict(Type="V", Electrode="27", Role="V2-"),
        8: dict(Type="V", Electrode="26", Minus="27", Role="dV1"),
        9: dict(Type="Drive", Electrode="14", Role="Vtg"),
    }
    cfg = rules.apply_entries(cfg, [{"AI": ai, **r} for ai, r in rows.items()])
    cfg.outputs[3].gain = 25  # backgate amplifier
    return cfg
