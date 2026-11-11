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


def test_u_row_with_no_kh_cells(qapp):
    w = MainWindow(demo_config(), "test")
    m = w.channel_model
    row = 8  # AI 9: U, gate, pad 14, no KH: AO 9 drives the pad
    assert m.data(m.index(row, col("ai"))) == "unused"
    assert m.data(m.index(row, col("ao"))) == "9"
    assert m.data(m.index(row, col("kh"))) == "none"
    assert m.data(m.index(row, col("mode"))) == "gate" and m.data(m.index(row, col("name"))) == "U14"
    assert m.flags(m.index(row, col("out_gain"))) & Qt.ItemIsEditable
    assert m.flags(m.index(row, col("kh"))) & Qt.ItemIsEditable      # give it a KH channel
    assert not m.flags(m.index(row, col("shunt"))) & Qt.ItemIsEditable
    assert m.setData(m.index(row, col("out_gain")), "2")
    assert w.cfg.output(9).gain == 2


def test_mode_column_and_shunt_choices(qapp):
    from expconfig.tablemodels import choices
    w = MainWindow(demo_config(), "test")
    m = w.channel_model
    assert m.data(m.index(0, col("mode"))) == "I"
    assert choices(w.cfg, "shunt", w.cfg.channel(1))[0] == ["50", "500", "5k", "50k"]
    assert m.setData(m.index(0, col("mode")), "gate")
    assert (w.cfg.channel(1).shunt, w.cfg.channel(1).name) == ("10M", "U1")
    assert choices(w.cfg, "mode", w.cfg.channel(2))[0] == ["V", "dV"]
    # The KH input mode is the V/dV choice on a V row, and fixed (DIFF) on a U row.
    assert not m.flags(m.index(0, col("input"))) & Qt.ItemIsEditable
    assert m.setData(m.index(1, col("input")), "DIFF")
    assert (w.cfg.channel(2).mode, w.cfg.channel(2).input) == ("dV", "DIFF")
    assert m.setData(m.index(1, col("input")), "SE+") and w.cfg.channel(2).mode == "V"
    assert not m.flags(m.index(0, col("mode") - 1)) & Qt.ItemIsEditable or col("mode") - 1 == col("type")


def test_output_offset_column_and_daq_tooltips(qapp):
    w = MainWindow(demo_config(), "test")
    w.start_sim()
    m = w.channel_model
    row = 3  # AI 4: the backgate row on AO 4, amp x25
    assert m.setData(m.index(row, col("out_offset")), "0.02")
    assert w.cfg.output(4).offset == 0.02
    assert m.data(m.index(row, col("out_offset"))) == "0.02"
    assert "PXI1Slot3/ai1" in m.data(m.index(row, col("ai")), Qt.ToolTipRole)
    w.apply()
    assert w.statusBar().currentMessage() == "Apply: matches the table"


def test_scene_trial_links_parts_to_table_cells(qapp):
    w = MainWindow(demo_config(), "test")
    spots = w.scene.spots
    assert {(1, "shunt"), (4, "out_gain"), (5, "ext_gain"), (9, "ao")} <= set(spots)
    w.scene.cellClicked.emit(4, "out_gain")         # click the backgate amplifier
    cur = w.table.currentIndex()
    assert (cur.row(), CHANNEL_COLUMNS[cur.column()].key) == (3, "out_gain")
    w.table.setCurrentIndex(w.channel_model.index(0, col("shunt")))   # and back
    assert spots[(1, "shunt")].current and not spots[(4, "out_gain")].current


def test_clicking_a_diagram_part_offers_its_choices(qapp):
    from PySide6.QtCore import QPoint
    from PySide6.QtWidgets import QMenu
    w = MainWindow(demo_config(), "test")
    w._cell_menu(1, "kh_gain", QPoint(100, 100))
    menu = next(m for m in w.findChildren(QMenu) if m.isVisible())
    gains = {a.text(): a for a in menu.actions() if a.isCheckable()}
    assert set(gains) == {"1", "10", "100", "1000"} and gains["1"].isChecked()
    gains["100"].trigger()
    assert w.cfg.channel(1).kh_gain == "100" and w.cfg.channel(1).lockin_gain == 100
    menu.close()


def test_diagram_window_opens_and_closes(qapp):
    w = MainWindow(demo_config(), "test")
    w.show()
    assert not w.wiring_window.isVisible()        # no diagram until asked for
    w.diagram_action.trigger()
    assert w.wiring_window.isVisible() and w.diagram_action.isChecked()
    w.wiring_window.close()                        # its own close button
    assert not w.diagram_action.isChecked()
    w.diagram_action.trigger()
    w.close()                                      # closing the main window closes it too
    assert not w.wiring_window.isVisible()


def test_typescript_diagram_bridge(qapp):
    import json
    w = MainWindow(demo_config(), "test")
    b = w.diagram_bridge
    m = json.loads(b.model())
    assert [r["ai"] for r in m["rows"]] == list(range(1, 13)) and m["pads"][0]["name"] == "1"
    assert [c["ais"] for c in m["cards"]] == [[i] for i in range(1, 13)]   # not read: one card per AI
    assert not any(c["read"] for c in m["cards"])
    from expconfig import diagrammodel
    from expconfig.demo import demo_daq
    cards = diagrammodel.cards(w.cfg, w.channel_model, *demo_daq())
    assert [(c["device"], c["ais"], [o["ao"] for o in c["aos"]]) for c in cards] == [
        ("PXI1Slot2", [1, 2], [1, 2]), ("PXI1Slot3", [3, 4], [3, 4]), ("PXI1Slot4", [5, 6], [5, 6]),
        ("PXI1Slot5", [7, 8], [7, 8]), ("Dev1", [9, 10, 11, 12], [9])]
    assert cards[1]["aos"][1]["usedBy"] == 4 and cards[4]["aos"][0]["usedBy"] == 9   # AO 4: backgate row
    pushed = []
    b.modelChanged.connect(pushed.append)
    assert b.cable('["pad", "4"]', '["kh+", 3]') == ""          # pad 4 onto row 3
    assert w.cfg.channel(3).electrode == "4" and pushed
    assert b.setCell(1, "kh_gain", "10") == "" and w.cfg.channel(1).kh_gain == "10"
    assert b.setCell(2, "shunt", "5k").startswith("AI 2")         # V row: no shunt
    assert b.cable('["ai", 1]', '["ao", 1]').startswith("Not cabled")
    assert json.loads(b.choices(1, "couple")) == {"options": ["AC", "DC"], "free": False}
    assert json.loads(b.choices(1, "shunt"))["options"] == ["50", "500", "5k", "50k"]   # by the row's mode


def test_log_measurement_stores_the_daq_cards_with_the_wiring(qapp, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    from expconfig import app as appmod, db
    from expconfig.demo import demo_devices
    w = MainWindow(demo_config(), "test")
    w.db_settings = db.DbSettings()

    class FakeRig:
        def serials(self):
            return "300995sim", ["sim"]

        def devices(self):
            return demo_devices()
    w._rig = lambda: FakeRig()
    asked, stored = [], {}
    monkeypatch.setattr(QMessageBox, "question", lambda *a: asked.append(a[2]) or QMessageBox.Yes)
    monkeypatch.setattr(appmod.db, "record_measurement", lambda settings, wiring, **v: stored.update(wiring) or 7)
    w.log_measurement()
    assert "DAQ cards (with the wiring): Dev1 USB-4431 #100000018 (simulated)" in asked[0]
    assert [c["type"] for c in stored["lockin_daq"]] == ["USB-4431"] + ["PXI-4461"] * 4
    assert all(c["serial"] == "" for c in stored["lockin_daq"])   # simulated: no serials stored


def test_save_keeps_the_wiring_and_says_whether_it_is_saved(qapp, tmp_path, monkeypatch):
    import os
    from PySide6.QtWidgets import QMessageBox
    from expconfig import legacy, wiringedit
    session, shared = tmp_path / "expconfig", tmp_path / "Control Experiment"
    w = MainWindow(demo_config(), "demo configuration", session_dir=session)
    assert w.saved_label.text() == "Demo, not saved" and not w.isWindowModified()
    w.close()                                                # the untouched demo: nothing to ask
    assert not (session / legacy.JSON_NAME).exists()

    w = MainWindow(demo_config(), "demo configuration", session_dir=session)
    wiringedit.connect(w.cfg, ("pad", "20"), ("ai", 10))   # an edit made in the diagram
    w.changed()
    assert "Unsaved" in w.saved_label.text() and w.isWindowModified()
    assert w.wiring_window.saved_label.text() == w.saved_label.text()
    assert w.wiring_window.save_button.isEnabled() and w.wiring_window.isWindowModified()
    w._exp_edit("sample", "SA9999")                          # the experiment form counts too
    w.wiring_window.save_button.click()                      # Save in the diagram window
    assert "Saved" in w.saved_label.text() and not w.modified and not w.wiring_window.save_button.isEnabled()
    assert legacy.startup_source(session, shared) == session
    again = legacy.import_legacy(session)
    assert again.channel(10).electrode == "20" and again.experiment.sample == "SA9999"
    assert [c.to_dict() for c in again.channels] == [c.to_dict() for c in w.cfg.channels]
    assert [o.to_dict() for o in again.outputs] == [o.to_dict() for o in w.cfg.outputs]

    # Closing with changes asks; Cancel keeps the window open, Discard closes without saving.
    w._exp_edit("sample", "SA0000")
    answers = [QMessageBox.Cancel, QMessageBox.Discard]
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: answers.pop(0))
    assert not w.close()
    assert w.close() and legacy.import_legacy(session).experiment.sample == "SA9999"

    # Control Experiment.json written later (Configure Experiment, another tool): that wins.
    legacy.save(demo_config(), shared)
    t = (session / legacy.JSON_NAME).stat().st_mtime + 5
    os.utime(shared / legacy.JSON_NAME, (t, t))
    assert legacy.startup_source(session, shared) == shared
    assert legacy.startup_source(tmp_path / "none", tmp_path / "nothing") is None


def test_without_a_save_folder_nothing_is_saved_or_asked(qapp):
    w = MainWindow(demo_config(), "test")
    w.cfg.experiment.sample = "changed"
    w.changed()
    assert w.modified and not w.save()
    assert w.close()   # no question in the tests
