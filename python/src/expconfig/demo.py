"""A demonstration configuration covering the cases discussed in #182."""

from __future__ import annotations

from . import rules
from .model import Config, Experiment


def demo_daq() -> tuple[list[dict], list[dict]]:
    """The DAQ channels the lock-in would report for the demo rig (getInputDAQ, getOutputDAQ)."""
    def kind(c):
        return "USB-4431" if c.startswith("Dev1") else "PXI-4461"
    ai = [f"PXI1Slot{2 + i // 2}/ai{i % 2}" for i in range(8)] + [f"Dev1/ai{i}" for i in range(4)]
    ao = [f"PXI1Slot{2 + i // 2}/ao{i % 2}" for i in range(8)] + ["Dev1/ao0"]
    return [{"Channels": c, "Type": kind(c)} for c in ai], [{"Channels": c, "Type": kind(c)} for c in ao]


def demo_devices() -> list[dict]:
    """getDevices for the demo rig, as the development lock-in reports it (simulated)."""
    pxi = [{"DeviceName": f"PXI1Slot{s}", "ProductType": "PXI-4461", "DeviceSerialNumber": str(7342 + s),
            "DevIsSimulated": True, "ChassisNumber": 1, "SlotNumber": s, "ChassisSerialNumber": "9A2265"}
           for s in range(2, 6)]
    return [{"DeviceName": "Dev1", "ProductType": "USB-4431", "DeviceSerialNumber": "100000018",
             "DevIsSimulated": True, "ChassisNumber": 0, "SlotNumber": 0, "ChassisSerialNumber": ""}, *pxi]


def demo_config() -> Config:
    cfg = Config(experiment=Experiment(sample="SA4017", device="20261026", user="Patrick",
                                       description="Hall bar, backgate sweep", path="C:\\temp",
                                       station="PPMS (sim)", station_type="Cryo"))
    cfg.resize(12, 9)   # four 4461s (2 AI, 2 AO each) and a 4431 (4 AI, 1 AO), like the lab's rig
    # A 28-pad device with pads 1-5, 14 and 26-28 bonded; the backgate is off-chip.
    # The top gate (pad 14) is driven straight from AO 9: no KH, AI 9 unused.
    rows = {
        1: dict(Type="U", Electrode="1", Role="I+", Shunt="5k"),
        2: dict(Type="V", Electrode="2", Role="V1+"),
        3: dict(Type="V", Electrode="3", Role="V1-"),
        4: dict(Type="U", Mode="gate", Electrode="28", Role="Vbg"),   # backgate, on carrier pin 28
        5: dict(Type="V", Electrode="5", KH="none", **{"External Gain": 2000}),
        6: dict(Type="V", Electrode="26", Role="V2+"),
        7: dict(Type="V", Electrode="27", Role="V2-"),
        8: dict(Type="V", Electrode="26", Minus="27", Role="dV1"),
        9: dict(Type="U", Mode="gate", Electrode="14", KH="none", Role="Vtg"),   # AO 9 drives pad 14
    }
    cfg = rules.apply_entries(cfg, [{"AI": ai, **r} for ai, r in rows.items()])
    cfg.outputs[3].gain = 25  # backgate amplifier
    return cfg
