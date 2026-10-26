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
