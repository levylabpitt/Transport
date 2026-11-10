"""Read and write the files Configure Experiment.vi uses.

- `configuration.ini` ([UI] section): the old Lockin/KH tables, used to import
  an existing setup.
- `Control Experiment.json`: read by Transport (prepareTransport), FLEX
  CESession and, through its "json" string, the TDMS <ControlExperiment>
  property. We keep its existing keys and add Channels, Outputs, Topology.
"""

from __future__ import annotations

import json
import os
import re
import socket
from datetime import datetime
from pathlib import Path

from . import rules, topology
from dataclasses import asdict

from .model import (
    ROLE_STRINGS, Channel, Config, Experiment, Instruments, Output, parse_kh_label,
)

DEFAULT_DIR = Path(os.environ.get("LOCALAPPDATA", ".")) / "Levylab" / "Control Experiment"
INI_NAME = "configuration.ini"
JSON_NAME = "Control Experiment.json"

# Configure Experiment's electrode configs, as (type, mode).
_OLD_TYPE = {
    "Current": ("U", "I"), "Gate": ("U", "gate"), "Voltage (SE)": ("V", "V"), "Voltage (Diff)": ("V", "dV"),
    "Ground": ("Ground", ""),
}


def read_ini(path: Path) -> dict[str, str]:
    """LabVIEW config-file VIs write `key = "value"`; configparser chokes on the
    quoting and the duplicate-looking keys, so parse the [UI] section by hand."""
    values: dict[str, str] = {}
    section = None
    for line in Path(path).read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if line.startswith("[") and line.endswith("]"):
            section = line[1:-1]
            continue
        if section != "UI" or "=" not in line:
            continue
        key, _, value = line.partition("=")
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] == '"':
            value = value[1:-1]
        values[key.strip()] = value
    return values


def _array(values: dict[str, str], key: str) -> list[str]:
    """Either 'key = "<size(s)=8> 1 2 3"' or 'key.<size(s)> = "8"' plus 'key 0', 'key 1', ..."""
    if key in values:
        m = re.match(r"<size\(s\)=(\d+)>\s*(.*)", values[key])
        if m:
            return m.group(2).split()[: int(m.group(1))]
    n = values.get(f"{key}.<size(s)>")
    if n is not None:
        return [values.get(f"{key} {i}", "") for i in range(int(n))]
    return []


def import_legacy(directory: Path = DEFAULT_DIR) -> Config:
    directory = Path(directory)
    cfg = Config()
    raw = {}
    json_path = directory / JSON_NAME
    if json_path.exists():
        raw = json.loads(json_path.read_text(encoding="utf-8"))
        cfg.legacy = raw
        exp = raw.get("Experiment", {})
        insts = exp.get("Instruments", [])
        kh = [i["Address"] for i in insts if i.get("Type") == "Amplifier" and i.get("Address")]
        lockin = next((i["Address"] for i in insts if i.get("Type") == "DAQ" and i.get("Address")), None)
        cfg.instruments = Instruments(
            kh_addresses=kh or Instruments().kh_addresses,
            lockin_address=lockin or Instruments().lockin_address,
        )
        cfg.experiment.user = exp.get("User", "")
        cfg.experiment.description = exp.get("Device Description", "")
        cfg.experiment.station = exp.get("Instrument", "")
        # A newer file written by this app carries the tables directly.
        if raw.get("Channels"):
            cfg.channels = [Channel.from_dict(d) for d in raw["Channels"]]
            cfg.outputs = [Output.from_dict(d) for d in raw.get("Outputs", [])]
            own = raw.get("Configurator", {})
            if "experiment" in own:
                cfg.experiment = Experiment(**own["experiment"])
            if "instruments" in own:
                cfg.instruments = Instruments(**own["instruments"])
            cfg.kh_override = own.get("kh_override", cfg.kh_override)
            cfg.default_shunt = own.get("default_shunt", cfg.default_shunt)
            return rules.derive_all(cfg)

    ini_path = directory / INI_NAME
    if ini_path.exists():
        v = read_ini(ini_path)
        cfg.experiment = Experiment(
            sample=v.get("Sample", ""), device=v.get("Device", ""), user=v.get("Username", cfg.experiment.user),
            description=v.get("Description", cfg.experiment.description),
            path=_lv_path(v.get("Default Path", "")), station=v.get("Instrument", cfg.experiment.station),
            station_type=v.get("Station Type", ""),
        )
        ais = _array(v, "Lockin.AI")
        electrodes = _array(v, "Lockin.Electrode")
        labels = _array(v, "Lockin.Label")
        configs = _array(v, "Lockin.Electrode Config")
        khs = _array(v, "KH.KH #")
        gains = _array(v, "KH.KH Gain")
        shunts = _array(v, "KH.KH Shunt Resistor")
        couple = "DC" if v.get("KH.DC Coupled", "FALSE").upper() == "TRUE" else "AC"
        filt = "ON" if v.get("KH.Filter", "FALSE").upper() == "TRUE" else "OFF"
        cfg.channels = []
        for i, ai in enumerate(ais):
            role_idx = int(labels[i]) if i < len(labels) and labels[i].isdigit() else 0
            try:
                kh = parse_kh_label(khs[i]) if i < len(khs) else i
            except ValueError:
                kh = None
            ch = Channel(
                ai=int(ai),
                electrode=electrodes[i] if i < len(electrodes) else "",
                type=_OLD_TYPE.get(configs[i] if i < len(configs) else "", ("n.c.", ""))[0],
                mode=_OLD_TYPE.get(configs[i] if i < len(configs) else "", ("n.c.", ""))[1],
                role=ROLE_STRINGS[role_idx] if role_idx < len(ROLE_STRINGS) else "",
                kh=kh,
                shunt=shunts[i] if i < len(shunts) else "Open",
                kh_gain=gains[i] if i < len(gains) else "1",
                couple=couple, filter=filt, ao=int(ai),
            )
            cfg.channels.append(rules.derive(ch))
        cfg.outputs = [Output(ao=c.ai) for c in cfg.channels]
    return cfg


def _lv_path(p: str) -> str:
    """LabVIEW writes paths as '/C/temp'."""
    m = re.match(r"^/([A-Za-z])/(.*)$", p)
    return f"{m.group(1)}:\\{m.group(2).replace('/', chr(92))}" if m else p


def export_json(cfg: Config, on_disk: dict | None = None) -> dict:
    """Control Experiment.json content: the legacy keys, kept or refreshed, plus the new ones.

    on_disk is the file as it is now. Keys this app does not own (instrument classes
    and addresses, sweep, anything another program added) are taken from it rather
    than from the copy read at startup, so a change made meanwhile is not undone.
    """
    base = on_disk if on_disk is not None else cfg.legacy
    out = json.loads(json.dumps(base)) if base else {}
    exp = out.setdefault("Experiment", {})
    e = cfg.experiment
    exp.update({
        "User": e.user, "Device": e.device_name,
        "Device Path": str(Path(e.path) / e.device_name) if e.path else exp.get("Device Path", ""),
        "Device Description": e.description, "Instrument": e.station,
    })
    exp.setdefault("Instruments", [])
    exp.setdefault("Sweep", [])
    wiring = {
        "Lockin Ch": [c.ai for c in cfg.channels],
        "KH": {
            "Electrodes": [f"{c.electrode}-{c.minus}" if c.minus_is_electrode else c.electrode
                           for c in cfg.channels],
            "Labels": [c.role for c in cfg.channels],
        },
        "not KH": out.get("Wiring Configuration", {}).get("not KH", {"Electrodes": [], "Labels": []}),
    }
    out["Wiring Configuration"] = wiring
    channels = [c.to_dict() for c in cfg.channels]
    outputs = [o.to_dict() for o in cfg.outputs]
    graph = topology.build(cfg)
    out["Channels"] = channels
    out["Outputs"] = outputs
    out["Topology"] = graph
    out["Configurator"] = {
        "experiment": asdict(e), "instruments": asdict(cfg.instruments),
        "kh_override": cfg.kh_override, "default_shunt": cfg.default_shunt,
    }
    # The embedded "json" string becomes the TDMS <ControlExperiment> property.
    meta = {
        "Device": {
            "Device": e.device_name, "User": e.user,
            "Time": datetime.now().astimezone().isoformat(timespec="milliseconds"),
            "Computer Name": socket.gethostname(),
        },
        "Wiring": {
            "Lockin Ch": wiring["Lockin Ch"],
            "KH Electrodes": wiring["KH"]["Electrodes"], "KH Labels": wiring["KH"]["Labels"],
            "Other Electrodes": wiring["not KH"]["Electrodes"], "Other Labels": wiring["not KH"]["Labels"],
        },
        "Channels": channels, "Outputs": outputs, "Topology": graph,
    }
    out["json"] = json.dumps(meta)
    return out


def missing_instruments(cfg: Config, directory: Path | None = None) -> bool:
    """True when the file would carry no instrument classes. Transport's
    prepareTransport needs them, so such a file must not replace the real one."""
    if directory is not None and (Path(directory) / JSON_NAME).exists():
        try:
            disk = json.loads((Path(directory) / JSON_NAME).read_text(encoding="utf-8"))
            if disk.get("Experiment", {}).get("Instruments"):
                return False  # the merge keeps them
        except (OSError, ValueError):
            pass
    return not cfg.legacy.get("Experiment", {}).get("Instruments")


def save(cfg: Config, directory: Path = DEFAULT_DIR) -> Path:
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / JSON_NAME
    tmp = path.with_suffix(".tmp")
    on_disk = None
    if path.exists():
        try:
            on_disk = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            on_disk = None
    content = export_json(cfg, on_disk)
    cfg.legacy = {k: v for k, v in content.items()}
    tmp.write_text(json.dumps(content, indent=1), encoding="utf-8")
    tmp.replace(path)
    return path
