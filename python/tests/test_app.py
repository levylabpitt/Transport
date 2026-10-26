import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QPA_FONTDIR", "C:/Windows/Fonts")

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from expconfig.app import MainWindow  # noqa: E402
from expconfig.demo import demo_config  # noqa: E402
from expconfig.tablemodels import CHANNEL_COLUMNS  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def col(key):
    return next(i for i, c in enumerate(CHANNEL_COLUMNS) if c.key == key)


def test_cells_enable_per_row(qapp):
    w = MainWindow(demo_config(), "test")
    m = w.channel_model
    u_row, v_row, no_kh_row = 0, 1, 4  # AI 1 = U, AI 2 = V, AI 5 = KH none
    assert m.flags(m.index(u_row, col("shunt"))) & Qt.ItemIsEditable
    assert not m.flags(m.index(v_row, col("shunt"))) & Qt.ItemIsEditable
    assert not m.flags(m.index(no_kh_row, col("kh_gain"))) & Qt.ItemIsEditable
    assert not m.flags(m.index(u_row, col("name"))) & Qt.ItemIsEditable


def test_editing_type_rederives_and_flags_conflicts(qapp):
    w = MainWindow(demo_config(), "test")
    m = w.channel_model
    assert m.setData(m.index(1, col("type")), "U")
    ch = w.cfg.channel(2)
    assert (ch.input, ch.shunt, ch.name) == ("DIFF", w.cfg.default_shunt, "U2")
    m.setData(m.index(1, col("kh")), "A1")
    assert (2, "kh") in m.issues and m.issues[(2, "kh")].code == 5009
    assert not w.apply_action.isEnabled()
    m.setData(m.index(1, col("kh")), "A2")
    assert w.apply_action.isEnabled()


def test_set_all_coupling(qapp):
    w = MainWindow(demo_config(), "test")
    w.couple_all.setCurrentIndex(2)  # "All DC"
    w._set_all("couple", w.couple_all, ("AC", "DC"))
    assert {c.couple for c in w.cfg.channels} == {"DC"}
    assert w.couple_all.currentIndex() == 0


def test_sim_apply_round_trip(qapp):
    w = MainWindow(demo_config(), "test")
    w.start_sim()
    w.apply()
    assert w.statusBar().currentMessage() == "Apply: matches the table"


def test_remote_api_updates_window_and_applies(qapp):
    import socket
    import threading
    from expconfig.rpc import Client, RpcError

    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    w = MainWindow(demo_config(), "test", api_port=port)
    w.start_sim()
    result, errors = {}, []

    def client():
        c = Client(f"tcp://127.0.0.1:{port}", timeout=5)
        try:
            result["set"] = c.call("setChannelConfig", {"Channels": [{"AI": 2, "Type": "U", "Shunt": "50k"}]})
            result["get"] = c.call("getChannelConfig")
            try:
                c.call("setChannelConfig", {"Channels": [{"AI": 99}]})
            except RpcError as err:
                result["err"] = (err.code, err.data)
        except Exception as err:
            errors.append(err)

    t = threading.Thread(target=client)
    t.start()
    while t.is_alive():  # the GUI thread must keep processing events for the bridge
        qapp.processEvents()
        t.join(0.01)
    assert not errors, errors
    assert result["set"]["applied"] and result["set"]["mismatches"] == []
    assert w.cfg.channel(2).type == "U" and w.cfg.channel(2).shunt == "50k"
    row2 = next(c for c in result["get"]["Channels"] if c["ai"] == 2)
    assert row2["name"] == "U2" and row2["input"] == "DIFF"
    assert result["err"][0] == 5001 and result["err"][1][0]["AI"] == 99
    w.api.stop()


def test_database_lookups_fill_the_rings(qapp):
    from expconfig import db
    w = MainWindow(demo_config(), "test")
    w.db_settings = db.DbSettings()
    w._lookups_ready(db.Lookups(users=["Ana", "Patrick"], station_types=["Cryo", "AFM"],
                                stations={"Cryo": ["PPMS 1", "MNK"], "AFM": ["Cypher"]}))
    assert [w.ed["user"].itemText(i) for i in range(w.ed["user"].count())] == ["Ana", "Patrick"]
    assert w.ed["user"].text() == "Patrick"  # current value kept
    w._exp_edit("station_type", "AFM")
    assert [w.ed["station"].itemText(i) for i in range(w.ed["station"].count())] == ["Cypher"]
    w._lookups_ready(db.Lookups(error="offline"))
    assert w.db_label.text() == "offline"
