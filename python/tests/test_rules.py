import pytest

from expconfig import rules
from expconfig.model import Channel, Config, kh_label, parse_kh_label


def make(n=8, chassis=1):
    cfg = Config()
    cfg.instruments.kh_addresses = [f"tcp://x:{i}" for i in range(chassis)]
    cfg.resize(n)
    return rules.derive_all(cfg)


def test_kh_labels_round_trip():
    for i in (0, 7, 8, 15, 23):
        assert parse_kh_label(kh_label(i)) == i
    assert kh_label(9) == "B2"
    assert parse_kh_label("a 1") == 0
    assert parse_kh_label("none") is None
    with pytest.raises(ValueError):
        parse_kh_label("A9")


def test_default_rows_follow_index_and_chassis():
    cfg = make(10, chassis=1)
    assert [c.kh for c in cfg.channels[:8]] == list(range(8))
    assert cfg.channels[8].kh is None  # beyond one chassis
    assert cfg.channels[3].ao == 4


@pytest.mark.parametrize("typ,minus,inp,name,shunt", [
    ("U", "", "DIFF", "U1", "5k"),
    ("V", "", "SE+", "V1", "Open"),
    ("V", "GND", "SE+", "V1", "Open"),
    ("V", "7", "DIFF", "V1-7", "Open"),
    ("n.c.", "", "OFF", "", "Open"),
    ("Ground", "", "OFF", "", "Open"),
])
def test_derivation_table(typ, minus, inp, name, shunt):
    ch = Channel(ai=1, electrode="1", minus=minus, kh=0, shunt="5k")
    ch.type = typ
    rules.derive(ch)
    assert (ch.input, ch.name, ch.shunt) == (inp, name, shunt)


def test_teed_electrodes_are_allowed_but_kh_must_be_unique():
    cfg = make(8)
    rows = {6: ("6", ""), 7: ("7", ""), 8: ("6", "7")}
    for ai, (e, m) in rows.items():
        ch = cfg.channel(ai)
        ch.electrode, ch.minus = e, m
        rules.set_type(ch, "V", cfg.default_shunt)
    assert [cfg.channel(a).name for a in (6, 7, 8)] == ["V6", "V7", "V6-7"]
    assert [cfg.channel(a).input for a in (6, 7, 8)] == ["SE+", "SE+", "DIFF"]
    assert not [i for i in rules.validate(cfg) if i.is_error]
    cfg.channel(8).kh = cfg.channel(6).kh
    assert [i.code for i in rules.validate(cfg)] == [rules.E_KH_DUPLICATE]


def test_new_u_row_gets_default_shunt():
    cfg = make(2)
    rules.set_type(cfg.channel(1), "U", "50k")
    assert cfg.channel(1).shunt == "50k"


def test_apply_entries_merges_and_derives():
    cfg = make(8)
    new = rules.apply_entries(cfg, [{"AI": 2, "Type": "V", "Electrode": "7"},
                                    {"AI": 3, "Type": "U", "Electrode": "1", "Shunt": "500", "KH": "A5"},
                                    {"AI": 5, "KH": "none", "External Gain": 2000}])
    assert new.channel(2).name == "V7" and new.channel(2).input == "SE+"
    assert new.channel(3).kh == 4 and new.channel(3).shunt == "500"
    assert new.channel(5).kh is None and new.channel(5).lockin_gain == 2000
    assert cfg.channel(2).type == "n.c."  # original untouched


@pytest.mark.parametrize("entry,code", [
    ({"Type": "V"}, rules.E_AI_MISSING),
    ({"AI": 99}, rules.E_AI_UNKNOWN),
    ({"AI": 1, "Type": "X"}, rules.E_TYPE),
    ({"AI": 1, "Shunt": "7k"}, rules.E_SHUNT),
    ({"AI": 1, "Couple": "XC"}, rules.E_COUPLE),
    ({"AI": 1, "KH": "C1"}, rules.E_KH),
    ({"AI": 1, "KH": "A2"}, rules.E_KH_DUPLICATE),
    ({"AI": 1, "Electrode": "3", "Minus": "3", "Type": "V"}, rules.E_MINUS_SELF),
])
def test_apply_entries_rejects(entry, code):
    cfg = make(8)
    with pytest.raises(rules.EntryError) as exc:
        rules.apply_entries(cfg, [entry])
    assert code in [i.code for i in exc.value.issues]


def test_swap_kh_in_one_request_is_fine():
    cfg = make(8)
    new = rules.apply_entries(cfg, [{"AI": 1, "KH": "A2"}, {"AI": 2, "KH": "A1"}])
    assert (new.channel(1).kh, new.channel(2).kh) == (1, 0)


def test_lockin_gain_combines_kh_and_external_gain():
    ch = Channel(ai=1, kh=0, kh_gain="100", ext_gain=2000)
    assert ch.lockin_gain == 200000
    ch.kh = None
    assert ch.lockin_gain == 2000


def test_u_row_with_no_kh_is_driven_directly_and_returns_to_standard():
    cfg = make()
    cfg.outputs[2].gain = 10
    # "Drive" from an older caller becomes a U row with no KH (gate mode).
    cfg = rules.apply_entries(cfg, [{"AI": 3, "Type": "Drive", "Electrode": "14"}])
    ch = cfg.channel(3)
    assert (ch.type, ch.mode, ch.direct) == ("U", "gate", True)
    assert (ch.kh, ch.ao, ch.input, ch.name) == (None, 3, "OFF", "U14")
    assert not [i for i in rules.validate(cfg) if i.ai == 3]
    from expconfig import topology
    g = topology.build(cfg)
    assert {"from": "ao:3", "to": "amp:ao3", "kind": "cable"} in g["edges"]
    assert {"from": "amp:ao3", "to": "electrode:14", "kind": "cable"} in g["edges"]
    assert not any(n["id"] == "ai:3" for n in g["nodes"])
    cfg = rules.apply_entries(cfg, [{"AI": 3, "Type": "V"}])
    assert cfg.channel(3).kh == 2


def test_cables_drawn_in_the_diagram_become_table_edits():
    from expconfig import wiringedit
    from expconfig.demo import demo_config
    cfg = demo_config()
    wiringedit.connect(cfg, ("pad", "4"), ("kh+", 2))          # move V2 to pad 4
    assert cfg.channel(2).electrode == "4" and cfg.channel(2).name == "V4"
    wiringedit.connect(cfg, ("kh-", 2), ("pad", "3"))          # either order: differential
    assert (cfg.channel(2).minus, cfg.channel(2).input) == ("3", "DIFF")
    wiringedit.connect(cfg, ("ao", 3), ("kh-", 3))             # AO on the - input: sourced, type U
    assert (cfg.channel(3).type, cfg.channel(3).ao, cfg.channel(3).input) == ("U", 3, "DIFF")
    wiringedit.connect(cfg, ("khout", 6), ("ai", 7))           # KH channels trade places
    assert (cfg.channel(6).kh, cfg.channel(7).kh) == (6, 5)
    wiringedit.connect(cfg, ("pad", "20"), ("ao", 5))          # AO drives a pad: U row, no KH
    assert (cfg.channel(5).type, cfg.channel(5).electrode, cfg.channel(5).kh) == ("U", "20", None)
    with pytest.raises(wiringedit.WiringError):
        wiringedit.connect(cfg, ("ai", 1), ("ao", 1))
    wiringedit.disconnect(cfg, ("kh-", 2))
    assert cfg.channel(2).input == "SE+"


def test_modes_set_the_shunt_and_the_label():
    from expconfig.model import Channel
    ch = rules.derive(Channel(ai=1, electrode="4", kh=0, type="U"))
    assert (ch.mode, ch.name) == ("I", "U4")
    rules._fit_shunt(ch, "5k")
    assert ch.shunt == "5k"
    rules.set_mode(ch, "gate", "5k")                 # a gate: large shunt, I -> 0
    assert (ch.shunt, ch.name) == ("10M", "U4")
    rules.set_mode(ch, "I", "500")                   # back to I: the default shunt, within range
    assert ch.shunt == "500"
    with pytest.raises(ValueError):
        rules.set_mode(ch, "dV", "5k")                # not a U mode
    v = rules.derive(Channel(ai=2, electrode="2", kh=1, type="V"))
    rules.set_mode(v, "dV", "5k")                    # dV still needs its second pad
    cfg = make()
    cfg.channels[1] = v
    assert any(i.code == rules.W_DV_NO_PAD and i.ai == 2 for i in rules.validate(cfg))
    v.minus = "3"
    rules.derive(v)
    assert (v.mode, v.input, v.name) == ("dV", "DIFF", "V2-3")
    rules.set_mode(v, "V", "5k")                     # single-ended again: the second pad comes off
    assert (v.minus_is_electrode, v.input, v.name) == (False, "SE+", "V2")


def test_shunt_outside_the_mode_is_reported_and_older_files_still_load():
    from expconfig.model import Channel
    cfg = make()
    cfg = rules.apply_entries(cfg, [{"AI": 1, "Type": "U", "Electrode": "1", "Mode": "I"}])
    cfg.channel(1).shunt = "10M"
    assert any(i.code == rules.W_U_SHUNT and i.ai == 1 for i in rules.validate(cfg))
    old = Channel.from_dict({"ai": 3, "type": "Drive", "electrode": "14", "kh": "C3"})
    assert (old.type, old.kh, old.mode) == ("U", None, "gate")
    # A shunt given without a mode says which mode it is.
    cfg = rules.apply_entries(cfg, [{"AI": 2, "Type": "U", "Electrode": "2", "Shunt": "10M"}])
    assert cfg.channel(2).mode == "gate"
