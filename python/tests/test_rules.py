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
    ("V", "7", "DIFF", "dV1-7", "Open"),
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
    assert [cfg.channel(a).name for a in (6, 7, 8)] == ["V6", "V7", "dV6-7"]
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
