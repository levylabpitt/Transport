"""Simulated Krohn-Hite 7008 and lock-in servers, same protocol as the real ones.

Run `uv run expconfig-sim` and point the app at the printed addresses
(the defaults are the real instruments' ports, so close those apps first,
or use --base-port).
"""

from __future__ import annotations

import argparse
import copy
import time

from .model import KH_COUPLINGS, KH_FILTERS, KH_GAINS, KH_INPUTS, KH_SHUNTS
from .rpc import RpcError, Server

_FRAMEWORK = {"ACK": lambda p: "ACK",
              "IDN": lambda p: {"vendor": "Levylab", "model": "simulated", "serial": "sim", "firmware": "0"}}


class SimKH:
    def __init__(self, shunts=KH_SHUNTS):
        self.shunts = list(shunts)
        self.channels = [{"channel": i, "gain": "1", "input": "OFF", "shunt": "Open", "couple": "AC", "filter": "OFF"}
                         for i in range(1, 9)]

    def handle(self, method, params):
        if method in _FRAMEWORK:
            return _FRAMEWORK[method](params)
        if method == "getAllChannels":
            return {"allChannelProperties": copy.deepcopy(self.channels)}
        if method == "setAllChannels":
            new = params["allChannelProperties"]
            for p in new:
                for key, allowed in (("gain", KH_GAINS), ("input", KH_INPUTS), ("shunt", self.shunts),
                                     ("couple", KH_COUPLINGS), ("filter", KH_FILTERS)):
                    if p.get(key) not in allowed:
                        raise RpcError(f"channel {p.get('channel')}: {key} {p.get(key)!r} not supported", 5000)
            self.channels = sorted(copy.deepcopy(new), key=lambda p: p["channel"])
            return None
        if method == "getShuntResistor":
            # The real server names the optional resistor fitted, as one string.
            return {"ShuntResistor": "10M" if "500" not in self.shunts else ("500" if "10M" not in self.shunts else "")}
        if method == "getChassis":
            return {"Chassis": 1}
        raise RpcError(f"command not supported: {method}", 4001)


class SimLockin:
    def __init__(self, n_ai=8, n_ao=4):
        self.input_gain = [1.0] * n_ai
        self.output_gain = [1.0] * n_ao
        self.output_offset = [0.0] * n_ao
        # Two channels per simulated card, like the PXI 4461s.
        self.input_daq = [{"Channels": f"PXI1Slot{2 + i // 2}/ai{i % 2}", "Coupling": "DC", "Range": "0.316",
                           "Terminal": "Pseudodifferential", "Type": "None"} for i in range(n_ai)]
        self.output_daq = [{"Channels": f"PXI1Slot{2 + i // 2}/ao{i % 2}", "Range": "0.1",
                            "Terminal": "Differential", "Type": "None"} for i in range(n_ao)]

    def handle(self, method, params):
        if method in _FRAMEWORK:
            return _FRAMEWORK[method](params)
        if method == "getInputDAQ":
            return copy.deepcopy(self.input_daq)
        if method == "getOutputDAQ":
            return copy.deepcopy(self.output_daq)
        if method == "getInputGain":
            return self.input_gain
        if method == "getOutputGain":
            return self.output_gain
        if method == "getOutputOffset":
            return self.output_offset
        if method in ("setInputGain", "setOutputGain", "setOutputOffset"):
            target = {"setInputGain": self.input_gain, "setOutputGain": self.output_gain,
                      "setOutputOffset": self.output_offset}[method]
            if len(params) != len(target):
                raise RpcError(f"{method}: expected {len(target)} values, got {len(params)}", 5000)
            target[:] = [float(x) for x in params]
            return None
        raise RpcError(f"command not supported: {method}", 4001)


def start(kh_addresses: list[str], lockin_address: str, n_ai=8, n_ao=4, shunts=None):
    """Start simulators; returns (servers, sim objects) so tests can inspect state.
    shunts: optional list (one per chassis) of fitted shunt values."""
    khs = [SimKH(shunts[i]) if shunts else SimKH() for i in range(len(kh_addresses))]
    lockin = SimLockin(n_ai, n_ao)
    servers = [Server(a, k.handle).start() for a, k in zip(kh_addresses, khs)]
    servers.append(Server(lockin_address, lambda m, p: lockin.handle(m, p)).start())  # tests may swap handle
    return servers, khs, lockin


def main() -> None:
    ap = argparse.ArgumentParser(description="Simulated KH 7008 chassis and lock-in")
    ap.add_argument("--base-port", type=int, default=0, help="use base, base+1.. instead of the real ports")
    ap.add_argument("--chassis", type=int, default=1)
    ap.add_argument("--ai", type=int, default=8)
    ap.add_argument("--ao", type=int, default=4)
    a = ap.parse_args()
    if a.base_port:
        lockin = f"tcp://127.0.0.1:{a.base_port}"
        khs = [f"tcp://127.0.0.1:{a.base_port + 1 + i}" for i in range(a.chassis)]
    else:
        lockin = "tcp://127.0.0.1:29170"
        khs = [f"tcp://127.0.0.1:{29160 + i}" for i in range(a.chassis)]
    start(khs, lockin, a.ai, a.ao)
    print("lock-in:", lockin)
    for i, k in enumerate(khs):
        print(f"KH {chr(65 + i)}:", k)
    print("Ctrl+C to stop")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
