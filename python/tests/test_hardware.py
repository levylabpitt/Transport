import socket

import pytest

from expconfig import hardware, rules, sim
from expconfig.model import Config
from expconfig.rpc import Client, RpcError


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def rig():
    kh = [f"tcp://127.0.0.1:{free_port()}" for _ in range(2)]
    lk = f"tcp://127.0.0.1:{free_port()}"
    servers, khs, lockin = sim.start(kh, lk, n_ai=10, n_ao=4)
    cfg = Config()
    cfg.instruments.kh_addresses = kh
    cfg.instruments.lockin_address = lk
    cfg.resize(10, 4)
    yield cfg, khs, lockin
    for s in servers:
        s.stop()


def test_rpc_errors_and_unknown_methods(rig):
    cfg, _, _ = rig
    c = Client(cfg.instruments.lockin_address)
    assert c.call("ACK") == "ACK"
    with pytest.raises(RpcError) as e:
        c.call("frobnicate")
    assert e.value.code == 4001


def test_timeout_resets_socket():
    c = Client(f"tcp://127.0.0.1:{free_port()}", timeout=0.2)
    with pytest.raises(TimeoutError):
        c.call("ACK")
    with pytest.raises(TimeoutError):  # a stuck REQ socket would raise EFSM instead
        c.call("ACK")


def test_apply_writes_kh_and_gains_and_reads_back(rig):
    cfg, khs, lockin = rig
    new = rules.apply_entries(cfg, [
        {"AI": 1, "Type": "U", "Electrode": "1", "Shunt": "5k", "KH Gain": "10"},
        {"AI": 3, "Type": "V", "Electrode": "3", "KH": "B5", "Couple": "DC", "Filter": "ON"},
        {"AI": 4, "KH": "none", "External Gain": 2000},
    ])
    new.outputs[3].gain = 25
    r = hardware.Rig(new)
    rb = r.apply(new)
    assert not rb.errors
    assert rb.mismatches(new) == []
    a1 = khs[0].channels[0]
    assert (a1["input"], a1["shunt"], a1["gain"]) == ("DIFF", "5k", "10")
    b5 = khs[1].channels[4]
    assert (b5["input"], b5["couple"], b5["filter"]) == ("SE+", "DC", "ON")
    assert khs[0].channels[2]["input"] == "OFF"  # A3 lost its row to B5, keeps defaults
    assert lockin.input_gain[0] == 10 and lockin.input_gain[3] == 2000
    assert lockin.output_gain[3] == 25
    r.close()


def test_all_ground_override_does_not_change_rows(rig):
    cfg, khs, _ = rig
    new = rules.apply_entries(cfg, [{"AI": 1, "Type": "U", "Electrode": "1"}])
    new.kh_override = "All Ground"
    rb = hardware.Rig(new).apply(new)
    assert khs[0].channels[0]["input"] == "OFF"
    assert new.channel(1).input == "DIFF"
    assert rb.mismatches(new) == []


def test_mismatch_reported_when_instrument_changed_behind_our_back(rig):
    cfg, khs, lockin = rig
    r = hardware.Rig(cfg)
    r.apply(cfg)
    lockin.input_gain[1] = 7.0
    assert any("AI 2" in m for m in r.read().mismatches(cfg))


def test_adopt_pulls_gains_set_on_the_instruments(rig):
    cfg, khs, lockin = rig
    lockin.output_gain[3] = 25.0           # set on the lock-in UI
    khs[0].channels[0]["gain"] = "100"     # set on the KH
    changes = hardware.adopt(cfg, hardware.Rig(cfg).read())
    assert cfg.output(4).gain == 25 and cfg.channel(1).kh_gain == "100"
    assert len(changes) == 2  # A1 is OFF on the KH and the row is n.c.: gain adopted, nothing else


def test_adopt_recovers_external_gain_and_skips_unconfigured_channels(rig):
    cfg, khs, lockin = rig
    cfg = rules.apply_entries(cfg, [{"AI": 1, "Type": "U", "Electrode": "1", "Shunt": "5k"},
                                    {"AI": 2, "Type": "U", "Electrode": "2", "Shunt": "5k"}])
    khs[0].channels[0].update(input="DIFF", gain="100", shunt="5k")   # A1 configured
    lockin.input_gain[0] = 5000.0                                       # 100 x 50
    hardware.adopt(cfg, hardware.Rig(cfg).read())
    assert cfg.channel(1).kh_gain == "100" and cfg.channel(1).ext_gain == 50
    assert cfg.channel(2).shunt == "5k"  # A2 is OFF on the KH: not adopted


def test_shunt_not_fitted_is_reported():
    kh = [f"tcp://127.0.0.1:{free_port()}"]
    lk = f"tcp://127.0.0.1:{free_port()}"
    servers, _, _ = sim.start(kh, lk, shunts=[["Open", "50", "5k", "50k", "10M"]])  # 10M fitted, no 500
    try:
        cfg = Config()
        cfg.instruments.kh_addresses, cfg.instruments.lockin_address = kh, lk
        cfg.resize(8, 8)
        cfg = rules.apply_entries(cfg, [{"AI": 1, "Type": "U", "Electrode": "1", "Shunt": "500"}])
        mism = hardware.Rig(cfg).read().mismatches(cfg)
        assert any("500 not fitted" in m for m in mism)
    finally:
        for s in servers:
            s.stop()


def test_available_shunts_from_the_real_reply_shape():
    assert hardware.available_shunts("") is None
    assert "10M" not in hardware.available_shunts("500")
    assert "500" not in hardware.available_shunts("10M")


def test_read_collects_idn_serials(rig):
    cfg, _, _ = rig
    r = hardware.Rig(cfg)
    rb = r.read()
    r.close()
    assert rb.lockin_idn.get("serial") == "sim"
    assert sorted(rb.kh_idn) == [0, 1]
    assert rb.serials() == ("sim", ["sim", "sim"])


def test_counts_and_names_come_from_the_daq_lists(rig):
    cfg, _, lockin = rig
    lockin.input_gain.extend([1.0] * 4)  # a stale gain list (the old 16-entry bug) must not add rows
    rb = hardware.Rig(cfg).read()
    assert (rb.n_ai, rb.n_ao) == (10, 4)
    assert hardware.daq_text(rb.input_daq[2]) == "PXI1Slot3/ai0, ±0.316 V, DC, Pseudodifferential"


def test_output_offset_applied_read_back_and_adopted(rig):
    cfg, _, lockin = rig
    cfg.outputs[3].gain, cfg.outputs[3].offset = 25, 0.02
    r = hardware.Rig(cfg)
    rb = r.apply(cfg)
    assert lockin.output_offset == [0, 0, 0, 0.02]
    assert rb.mismatches(cfg) == []
    lockin.output_offset[3] = 0.03                  # changed on the lock-in UI
    assert any("AO 4: lock-in output offset" in m for m in r.read().mismatches(cfg))
    assert "AO 4: offset 0.02 -> 0.03" in hardware.adopt(cfg, r.read())
    assert cfg.output(4).offset == 0.03


def test_older_lockin_without_daq_or_offset_commands(rig):
    cfg, _, lockin = rig
    real = lockin.handle

    def old(method, params):
        if method in ("getInputDAQ", "getOutputDAQ", "getOutputOffset", "setOutputOffset"):
            raise RpcError(f"command not supported: {method}", 4001)
        return real(method, params)
    lockin.handle = old
    cfg.outputs[0].offset = 0.5
    rb = hardware.Rig(cfg).apply(cfg)
    assert not rb.errors and (rb.n_ai, rb.n_ao) == (10, 4) and rb.output_offset == []
