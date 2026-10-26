import json
from pathlib import Path

from expconfig import legacy, rules, topology
from expconfig.model import Output

FIXTURES = Path(__file__).parent / "fixtures" / "legacy"


def test_import_old_tables():
    cfg = legacy.import_legacy(FIXTURES)
    assert len(cfg.channels) == 8
    assert [c.role for c in cfg.channels] == ["I+", "I-", "V1-", "V1+", "I+", "I+", "", ""]
    assert [c.type for c in cfg.channels] == ["U", "U", "V", "V", "U", "U", "Ground", "Ground"]
    assert [c.kh for c in cfg.channels] == list(range(8))
    assert [c.shunt for c in cfg.channels[:3]] == ["5k", "5k", "Open"]
    assert cfg.instruments.kh_addresses == ["tcp://localhost:29160"]
    assert cfg.instruments.lockin_address == "tcp://localhost:29170"
    assert cfg.experiment.device_name == "TEST.20261019"
    assert cfg.experiment.path == "C:\\temp"


def test_export_keeps_legacy_keys_and_adds_new(tmp_path):
    cfg = legacy.import_legacy(FIXTURES)
    cfg.channels[2].electrode, cfg.channels[2].minus = "3", "4"
    rules.derive_all(cfg)
    out = legacy.export_json(cfg)
    assert out["Experiment"]["Instruments"] == cfg.legacy["Experiment"]["Instruments"]
    assert out["Wiring Configuration"]["KH"]["Labels"][:2] == ["I+", "I-"]
    assert out["Wiring Configuration"]["KH"]["Electrodes"][2] == "3-4"
    assert out["Channels"][2]["name"] == "dV3-4"
    meta = json.loads(out["json"])
    assert meta["Channels"][2]["kh"] == "A3"
    # round trip through the file
    legacy.save(cfg, tmp_path)
    again = legacy.import_legacy(tmp_path)
    assert [c.to_dict() for c in again.channels] == [c.to_dict() for c in cfg.channels]


def test_topology_answers_what_an_ai_measures():
    cfg = legacy.import_legacy(FIXTURES)
    for ai, (e, m) in {6: ("6", ""), 7: ("7", ""), 8: ("6", "7")}.items():
        ch = cfg.channel(ai)
        ch.electrode, ch.minus = e, m
        rules.set_type(ch, "V", cfg.default_shunt)
    cfg.outputs[3] = Output(ao=4, name="Vbg", gain=25, electrode="gate")
    g = topology.build(cfg)
    assert topology.path_to_ai(g, 8) == ["electrode:6", "electrode:7"]
    assert topology.path_to_ai(g, 6) == ["electrode:6"]
    amp = next(n for n in g["nodes"] if n["id"] == "amp:ao4")
    assert amp["gain"] == 25
    assert {"from": "amp:ao4", "to": "electrode:gate", "kind": "cable"} in g["edges"]


def test_backgate_amplifier_sits_after_the_kh():
    from expconfig.demo import demo_config
    cfg = demo_config()  # AI 4: U on gate via A4 from AO 4, AO 4 gain 25
    g = topology.build(cfg)
    assert {"from": "electrode:gate", "to": "amp:ao4", "kind": "cable"} in g["edges"]
    assert {"from": "amp:ao4", "to": "kh:A4:+", "kind": "cable"} in g["edges"]
    assert {"from": "ao:4", "to": "kh:A4:-", "kind": "cable"} in g["edges"]
    assert topology.path_to_ai(g, 4) == ["electrode:gate"]


def test_own_file_round_trips_experiment_and_instruments(tmp_path):
    from expconfig.demo import demo_config
    cfg = demo_config()
    cfg.instruments.kh_addresses = ["tcp://a:1", "tcp://b:2"]
    cfg.kh_override = "All Ground"
    legacy.save(cfg, tmp_path)
    again = legacy.import_legacy(tmp_path)
    assert again.experiment == cfg.experiment
    assert again.instruments == cfg.instruments
    assert again.kh_override == "All Ground"
    assert legacy.missing_instruments(again)  # demo has no instrument classes


def test_imported_file_keeps_instrument_classes():
    cfg = legacy.import_legacy(FIXTURES)
    assert not legacy.missing_instruments(cfg)
