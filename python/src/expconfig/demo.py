"""A demonstration configuration covering the cases discussed in #182."""

from __future__ import annotations

from . import rules
from .model import Config, Experiment, Output


def demo_config() -> Config:
    cfg = Config(experiment=Experiment(sample="SA4017", device="20261026", user="Patrick",
                                       description="Hall bar, backgate sweep", path="C:\\temp",
                                       station="PPMS (sim)", station_type="Cryo"))
    cfg.resize(8, 4)
    rows = {
        1: dict(Type="U", Electrode="1", Role="I+", Shunt="5k"),
        2: dict(Type="V", Electrode="2", Role="V1+"),
        3: dict(Type="V", Electrode="3", Role="V1-"),
        4: dict(Type="U", Electrode="gate", Role="Vbg", Shunt="10M"),
        5: dict(Type="V", Electrode="4", KH="none", **{"External Gain": 2000}),
        6: dict(Type="V", Electrode="6", Role="V2+"),
        7: dict(Type="V", Electrode="7", Role="V2-"),
        8: dict(Type="V", Electrode="6", Minus="7", Role="dV1"),
    }
    cfg = rules.apply_entries(cfg, [{"AI": ai, **r} for ai, r in rows.items()])
    cfg.outputs[0] = Output(ao=1, name="I source")
    cfg.outputs[3] = Output(ao=4, name="Vbg", gain=25)
    return cfg
