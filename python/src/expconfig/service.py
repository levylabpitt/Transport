"""The configurator's own remote API, served the Instrument Framework way
(JSON-RPC 2.0 over ZMQ REP), so FLEX can drive it like any other instrument.

Methods:
  ACK, IDN, HELP
  getChannelConfig             -> {"Channels": [...], "Outputs": [...]}
  setChannelConfig {"Channels": [entries], "apply": true}
                               -> {"Channels": [...], "applied": bool, "mismatches": [...]}
  setOutputs {"Outputs": [{"AO": 4, "Name": "Vbg", "Gain": 25}]}
  getTopology                  -> the wiring graph
  getChecks                    -> validation issues
  applyConfig                  -> {"mismatches": [...]}

setChannelConfig entries use the #182 keys (AI, Electrode, Minus, Type, Role,
KH, Shunt, KH Gain, Couple, Filter, External Gain, AO). A bad request is
rejected whole, with the first issue's code and every issue in error.data.
"""

from __future__ import annotations

import copy
from typing import Callable

from . import rules, topology
from .model import Config
from .rpc import RpcError, Server

DEFAULT_PORT = 29180

METHODS = ("ACK", "IDN", "HELP", "getChannelConfig", "setChannelConfig", "setOutputs",
           "getTopology", "getChecks", "applyConfig")


def _issues(issues):
    return [{"code": i.code, "AI": i.ai, "field": i.field, "message": i.message} for i in issues]


class ConfigService:
    """get_cfg/set_cfg/apply let the app keep the configuration on its own thread."""

    def __init__(self, get_cfg: Callable[[], Config], set_cfg: Callable[[Config], None],
                 apply: Callable[[Config], list[str]] | None = None):
        self.get_cfg = get_cfg
        self.set_cfg = set_cfg
        self.apply = apply

    def handle(self, method: str, params):
        params = params or {}
        cfg = self.get_cfg()
        if method == "ACK":
            return "ACK"
        if method == "IDN":
            return {"Manufacturer": "Levylab", "Model": "expconfig", "Version": "0.1"}
        if method == "HELP":
            return list(METHODS)
        if method == "getChannelConfig":
            return {"Channels": [c.to_dict() for c in cfg.channels],
                    "Outputs": [o.to_dict() for o in cfg.outputs]}
        if method == "getTopology":
            return topology.build(cfg)
        if method == "getChecks":
            return _issues(rules.validate(cfg))
        if method == "setChannelConfig":
            entries = params.get("Channels")
            if not isinstance(entries, list):
                raise RpcError("params.Channels must be a list of entries", rules.E_AI_MISSING)
            try:
                new = rules.apply_entries(cfg, entries)
            except rules.EntryError as err:
                raise RpcError(str(err), err.issues[0].code, _issues(err.issues)) from err
            self.set_cfg(new)
            mism, applied = [], False
            if params.get("apply", True) and self.apply:
                mism, applied = self.apply(new), True
            return {"Channels": [c.to_dict() for c in new.channels], "applied": applied, "mismatches": mism}
        if method == "setOutputs":
            new = copy.deepcopy(cfg)
            for e in params.get("Outputs", []):
                o = new.output(e.get("AO"))
                if o is None:
                    raise RpcError(f"AO {e.get('AO')} not in the outputs table", rules.E_AO)
                o.name = str(e.get("Name", o.name))
                o.electrode = str(e.get("Electrode", o.electrode))
                if "Gain" in e:
                    try:
                        o.gain = float(e["Gain"])
                    except (TypeError, ValueError):
                        raise RpcError(f"AO {o.ao}: Gain not a number", rules.E_VALUE) from None
            self.set_cfg(new)
            return {"Outputs": [o.to_dict() for o in new.outputs]}
        if method == "applyConfig":
            if not self.apply:
                raise RpcError("no instruments connected", 5014)
            return {"mismatches": self.apply(cfg)}
        raise RpcError(f"command not supported: {method}", 4001)


def serve(service: ConfigService, port: int = DEFAULT_PORT) -> Server:
    return Server(f"tcp://*:{port}", service.handle).start()
