"""The diagram's data is described once (expconfig/diagramtypes.py): build() must send
exactly those fields, and the generated TypeScript and the diagram's test fixtures must
be current. If one of these fails after a change: uv run python -m expconfig.diagramtypes"""

import json

from expconfig import diagramtypes


def test_build_sends_exactly_the_described_fields():
    for name, m in diagramtypes.fixtures().items():
        assert diagramtypes.check_model(m) == [], name


def test_generated_typescript_is_current():
    assert diagramtypes.GENERATED.read_text(encoding="utf-8") == diagramtypes.typescript()


def test_diagram_fixtures_are_current():
    for name, m in diagramtypes.fixtures().items():
        saved = json.loads((diagramtypes.FIXTURES / f"{name}.json").read_text(encoding="utf-8"))
        assert saved == json.loads(json.dumps(m)), name


def test_cards_say_what_hardware_they_are():
    from expconfig import diagrammodel
    from expconfig.demo import demo_config, demo_daq, demo_devices
    from expconfig.tablemodels import ChannelModel
    cfg = demo_config()
    cm = ChannelModel(cfg, lambda: None)
    ai, ao = demo_daq()
    by = {c["device"]: c for c in diagrammodel.cards(cfg, cm, ai, ao, demo_devices())}
    assert (by["PXI1Slot3"]["type"], by["PXI1Slot3"]["serial"], by["PXI1Slot3"]["slot"]) == \
        ("PXI-4461", "7345", "chassis 1, slot 3")
    assert (by["Dev1"]["type"], by["Dev1"]["slot"], by["Dev1"]["simulated"]) == ("USB-4431", "", True)
    # Without getDevices (lock-in before 3.11): the type from the DAQ lists, no serial.
    by = {c["device"]: c for c in diagrammodel.cards(cfg, cm, ai, ao)}
    assert (by["Dev1"]["type"], by["Dev1"]["serial"]) == ("USB-4431", "")
    # A lock-in that sends Type "None": nothing claimed.
    old = [{**e, "Type": "None"} for e in ai]
    assert all(c["type"] == "" for c in diagrammodel.cards(cfg, cm, old, []))
