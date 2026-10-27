"""Experiment configurator: the main window."""

from __future__ import annotations

import argparse
import copy
import json
import socket
import sys
from pathlib import Path

from PySide6.QtCore import QModelIndex, QObject, Qt, QTimer, Signal
from PySide6.QtGui import QAction, QFont, QKeySequence
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QComboBox, QFileDialog, QFormLayout, QGridLayout, QGroupBox, QHBoxLayout,
    QHeaderView, QLabel, QLineEdit, QListWidget, QListWidgetItem, QMainWindow, QMessageBox,
    QPlainTextEdit, QScrollArea, QSpinBox, QSplitter, QStyledItemDelegate, QTableView, QTabWidget,
    QVBoxLayout, QWidget,
)

import threading

from . import db, hardware, legacy, rules, service, sim, topology
from .demo import demo_config
from .model import KH_COUPLINGS, KH_FILTERS, KH_OVERRIDES, KH_SHUNTS, Config
from .groupheader import GroupHeader
from .tablemodels import CHANNEL_COLUMNS, GROUP_TINT, ChannelModel, choices
from .wiringview import WiringView


def _idn_text(d: dict) -> str:
    """'Multichannel-Lockin  SN 2674814sim  fw 3.8.6.97' from an IDN reply."""
    if not d:
        return "not read"
    return "  ".join(x for x in (str(d.get("model", "")), f"SN {d.get('serial', '?')}",
                                 f"fw {d['firmware']}" if d.get("firmware") else "") if x)

class ChoiceDelegate(QStyledItemDelegate):
    """Combo-box editors whose options depend on the column (and the current config)."""

    def __init__(self, window: "MainWindow"):
        super().__init__(window)
        self.window = window

    def createEditor(self, parent, option, index):
        key = CHANNEL_COLUMNS[index.column()].key
        opts, free = choices(self.window.cfg, key)
        if not opts:
            return super().createEditor(parent, option, index)
        box = QComboBox(parent)
        box.setEditable(free)
        box.addItems(opts)
        box.activated.connect(lambda _=None, b=box: self.commitData.emit(b))
        return box

    def setEditorData(self, editor, index):
        if isinstance(editor, QComboBox):
            text = index.data(Qt.EditRole)
            i = editor.findText(text)
            if i >= 0:
                editor.setCurrentIndex(i)
            elif editor.isEditable():
                editor.setEditText(text)
            editor.showPopup() if not editor.isEditable() else None
        else:
            super().setEditorData(editor, index)

    def setModelData(self, editor, model, index):
        if isinstance(editor, QComboBox):
            model.setData(index, editor.currentText(), Qt.EditRole)
        else:
            super().setModelData(editor, model, index)


class _Bridge(QObject):
    """Run a callable on the GUI thread and wait for it (used by the remote API thread)."""

    run = Signal(object)

    def __init__(self):
        super().__init__()
        self.run.connect(self._run, Qt.BlockingQueuedConnection)

    @staticmethod
    def _run(job):
        job()

    def call(self, fn):
        box = {}

        def job():
            try:
                box["value"] = fn()
            except Exception as err:  # re-raised in the caller's thread
                box["error"] = err

        self.run.emit(job)
        if "error" in box:
            raise box["error"]
        return box.get("value")


class ChoiceEdit(QComboBox):
    """Editable combo box with a line-edit interface: choices from the database,
    free text when the database is unreachable or the value is not listed."""

    committed = Signal(str)

    def __init__(self, text: str = ""):
        super().__init__()
        self.setEditable(True)
        self.setInsertPolicy(QComboBox.NoInsert)
        self.setEditText(text)
        self.lineEdit().editingFinished.connect(lambda: self.committed.emit(self.currentText()))
        self.activated.connect(lambda _i: self.committed.emit(self.currentText()))

    def text(self) -> str:
        return self.currentText().strip()

    def setText(self, text: str) -> None:
        self.setEditText(text)

    def set_choices(self, items: list[str]) -> None:
        keep = self.currentText()
        self.blockSignals(True)
        self.clear()
        self.addItems(items)
        self.setEditText(keep)
        self.blockSignals(False)


class MainWindow(QMainWindow):
    lookupsReady = Signal(object)
    instrumentsReady = Signal(object)

    def __init__(self, cfg: Config, source: str, api_port: int = 0, db_settings: db.DbSettings | None = None,
                 query_instruments: bool = False):
        super().__init__()
        self.cfg = cfg
        self.source = source
        self.rig: hardware.Rig | None = None
        self.setWindowTitle("Experiment configurator (prototype)")
        self.resize(1500, 900)

        self.channel_model = ChannelModel(cfg, self.changed)

        # --- left: forms, set-all bar, tables, issues ---
        left = QWidget()
        lv = QVBoxLayout(left)
        lv.setContentsMargins(6, 6, 6, 6)
        lv.addWidget(self._header())
        lv.addLayout(self._setall_bar())

        self.table = QTableView()
        self.table.setHorizontalHeader(GroupHeader([c.group for c in CHANNEL_COLUMNS], GROUP_TINT))
        self.table.setModel(self.channel_model)
        self.table.setItemDelegate(ChoiceDelegate(self))
        self.table.setEditTriggers(QAbstractItemView.DoubleClicked | QAbstractItemView.SelectedClicked
                                   | QAbstractItemView.EditKeyPressed | QAbstractItemView.AnyKeyPressed)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setMinimumSectionSize(44)
        self.table.verticalHeader().setDefaultSectionSize(24)
        self.table.verticalHeader().setVisible(False)  # the Ch column is the row number
        self.table.selectionModel().currentRowChanged.connect(self._row_selected)

        self.issues = QListWidget()
        self.issues.itemClicked.connect(self._issue_clicked)

        ig = QGroupBox("Checks")
        QVBoxLayout(ig).addWidget(self.issues)

        tables = QSplitter(Qt.Vertical)
        cg = QGroupBox("Channels (one row per lock-in AI)")
        QVBoxLayout(cg).addWidget(self.table)
        tables.addWidget(cg)
        tables.addWidget(ig)
        tables.setSizes([640, 170])
        lv.addWidget(tables, 1)

        # --- right: wiring view, machine view, log ---
        self.wiring = WiringView(cfg)
        self.wiring.rowClicked.connect(self._select_ai)
        scroll = QScrollArea()
        scroll.setWidget(self.wiring)
        scroll.setWidgetResizable(True)
        self.machine = QPlainTextEdit(readOnly=True)
        self.machine.setFont(QFont("Consolas", 9))
        self.log = QPlainTextEdit(readOnly=True)
        self.tabs = QTabWidget()
        self.tabs.addTab(scroll, "Wiring")
        self.tabs.addTab(self.machine, "Machine view (topology JSON)")
        self.tabs.addTab(self.log, "Instrument log")

        split = QSplitter(Qt.Horizontal)
        split.addWidget(left)
        split.addWidget(self.tabs)
        split.setSizes([930, 570])
        self.setCentralWidget(split)
        self._actions()
        self.changed()
        self.statusBar().showMessage(f"Loaded {source}")
        self.api = None
        if api_port:
            self._start_api(api_port)
        self.db_settings = db_settings
        self.lookups = db.Lookups(error="not loaded")
        self.lookupsReady.connect(self._lookups_ready)
        if db_settings:
            self.db_label.setText("loading…")
            threading.Thread(target=lambda: self.lookupsReady.emit(db.lookups(db_settings)),
                             daemon=True).start()
        self.instrumentsReady.connect(self._instruments_ready)
        if query_instruments:
            self.conn.setText("querying…")
            cfg_copy = copy.deepcopy(cfg)

            def query():
                rig = hardware.Rig(cfg_copy, timeout=2.0)
                try:
                    self.instrumentsReady.emit(rig.read())
                finally:
                    rig.close()
            threading.Thread(target=query, daemon=True).start()

    serials: tuple[str, list[str]] = ("", [])

    def _instruments_ready(self, rb: hardware.Readback) -> None:
        self._show_readback(rb, "Startup read")

    def _adopt_counts(self, rb: hardware.Readback) -> None:
        """The table has as many rows as the lock-in has inputs and outputs."""
        if not rb.input_gain:
            return
        n_ai, n_ao = len(rb.input_gain), len(rb.output_gain)
        for w, v in ((self.n_ai, n_ai), (self.n_ao, n_ao)):
            w.blockSignals(True)
            w.setValue(v)
            w.setEnabled(False)
            w.setToolTip("Read from the lock-in")
            w.blockSignals(False)
        if (n_ai, n_ao) != (len(self.cfg.channels), len(self.cfg.outputs)):
            self.log.appendPlainText(f"Table resized to the lock-in: {n_ai} AI, {n_ao} AO "
                                     f"(was {len(self.cfg.channels)} AI, {len(self.cfg.outputs)} AO)")
            self._resize()

    def _lookups_ready(self, lk: db.Lookups) -> None:
        self.lookups = lk
        if lk.error:
            self.db_label.setText("offline")
            self.db_label.setToolTip(lk.error)
            self.log.appendPlainText(f"Database: {lk.error}")
            return
        self.db_label.setText(f"{self.db_settings.host}: {len(lk.users)} users, "
                              f"{sum(map(len, lk.stations.values()))} stations")
        self.ed["user"].set_choices(lk.users)
        self.ed["station_type"].set_choices(lk.station_types)
        self.ed["station"].set_choices(lk.stations_of(self.cfg.experiment.station_type))

    def _start_api(self, port: int) -> None:
        bridge = _Bridge()
        self._bridge = bridge
        svc = service.ConfigService(
            get_cfg=lambda: bridge.call(lambda: copy.deepcopy(self.cfg)),
            set_cfg=lambda c: bridge.call(lambda: self._remote_set(c)),
            apply=lambda c: bridge.call(lambda: self._remote_apply(c)),
        )
        try:
            self.api = service.serve(svc, port)
            self.api_label.setText(f"tcp://*:{port}")
        except Exception as err:
            self.api_label.setText(f"not started: {err}")

    def _remote_set(self, cfg: Config) -> None:
        self.cfg = cfg
        self.channel_model.set_config(cfg)
        self.changed()
        self.log.appendPlainText("Remote: configuration changed")
        self.statusBar().showMessage("Configuration changed by a remote client")

    def _remote_apply(self, cfg: Config) -> list[str]:
        rb = self._rig().apply(cfg)
        self._show_readback(rb, "Remote apply")
        if rb.errors:
            raise RuntimeError("; ".join(rb.errors))
        return rb.mismatches(cfg)

    # ---- layout pieces ---------------------------------------------------

    def _header(self) -> QWidget:
        w = QWidget()
        h = QHBoxLayout(w)
        h.setContentsMargins(0, 0, 0, 0)
        e = self.cfg.experiment
        eg = QGroupBox("Experiment")
        grid = QGridLayout(eg)
        grid.setContentsMargins(8, 4, 8, 6)
        grid.setVerticalSpacing(4)
        self.ed = {}
        layout = (
            (("sample", "Sample"), ("device", "Device"), ("user", "User")),
            (("station_type", "Station type"), ("station", "Station"), ("path", "Data path")),
        )
        for r, row in enumerate(layout):
            for c, (key, label) in enumerate(row):
                grid.addWidget(QLabel(label), r, 2 * c)
                grid.addWidget(self._exp_field(key, getattr(e, key)), r, 2 * c + 1)
        self.pads = QSpinBox(minimum=1, maximum=256, value=e.pads)
        self.pads.setToolTip("Bond pads on the device, numbered 1..N: the Electrode dropdown")
        self.pads.valueChanged.connect(self._pads_changed)
        grid.addWidget(QLabel("Pads"), 2, 0)
        grid.addWidget(self.pads, 2, 1)
        grid.addWidget(QLabel("Description"), 2, 2)
        grid.addWidget(self._exp_field("description", e.description), 2, 3, 1, 3)
        for c in (1, 3, 5):
            grid.setColumnStretch(c, 1)
        h.addWidget(eg, 3)

        ig = QGroupBox("Instruments")
        f = QFormLayout(ig)
        f.setContentsMargins(8, 4, 8, 6)
        f.setVerticalSpacing(3)
        self.kh_addr = QLineEdit(", ".join(self.cfg.instruments.kh_addresses))
        self.kh_addr.setToolTip("One ZMQ address per Krohn-Hite chassis: A, B, ...")
        self.kh_addr.editingFinished.connect(self._instruments_edit)
        self.lockin_addr = QLineEdit(self.cfg.instruments.lockin_address)
        self.lockin_addr.editingFinished.connect(self._instruments_edit)
        self.n_ai = QSpinBox(minimum=1, maximum=64, value=len(self.cfg.channels))
        self.n_ao = QSpinBox(minimum=0, maximum=64, value=len(self.cfg.outputs))
        for sb in (self.n_ai, self.n_ao):
            sb.setToolTip("Set from the lock-in when it is reachable")
            sb.valueChanged.connect(self._resize)
        self.default_shunt = QComboBox()
        self.default_shunt.addItems(KH_SHUNTS[1:])
        self.default_shunt.setCurrentText(self.cfg.default_shunt)
        self.default_shunt.setToolTip("Shunt given to a row when its type becomes U")
        self.default_shunt.currentTextChanged.connect(lambda t: setattr(self.cfg, "default_shunt", t))
        counts = QHBoxLayout()
        for lbl, wdg in (("AI", self.n_ai), ("AO", self.n_ao), ("default shunt", self.default_shunt)):
            counts.addWidget(QLabel(lbl))
            counts.addWidget(wdg)
        counts.addStretch(1)
        f.addRow("Krohn-Hite", self.kh_addr)
        f.addRow("Lock-in", self.lockin_addr)
        f.addRow("Channels", counts)
        self.conn = QLabel("not connected")
        self.lockin_id = QLabel("not read")
        self.kh_id = QLabel("not read")
        for lbl in (self.lockin_id, self.kh_id):
            lbl.setToolTip("From IDN; the serial numbers are what Log measurement records")
        self.api_label = QLabel("off")
        self.api_label.setToolTip("This app's own JSON-RPC server (getChannelConfig, setChannelConfig, ...)")
        self.db_label = QLabel("off")
        for lbl, wdg in (("Status", self.conn), ("Lock-in ID", self.lockin_id), ("KH ID", self.kh_id),
                         ("Remote API", self.api_label), ("Database", self.db_label)):
            wdg.setTextInteractionFlags(Qt.TextSelectableByMouse)
            f.addRow(lbl, wdg)
        h.addWidget(ig, 2)
        return w

    def _exp_field(self, key: str, value: str) -> QWidget:
        if key in ("user", "station_type", "station"):
            le = ChoiceEdit(value)
            le.committed.connect(lambda t, k=key: self._exp_edit(k, t))
        else:
            le = QLineEdit(value)
            le.editingFinished.connect(lambda k=key, le=le: self._exp_edit(k, le.text()))
        self.ed[key] = le
        return le

    def _setall_bar(self) -> QHBoxLayout:
        bar = QHBoxLayout()
        self.couple_all = QComboBox()
        self.couple_all.addItems(["Coupling (all)…"] + [f"All {c}" for c in KH_COUPLINGS])
        self.couple_all.activated.connect(lambda i: self._set_all("couple", self.couple_all, KH_COUPLINGS))
        self.filter_all = QComboBox()
        self.filter_all.addItems(["Filter (all)…"] + [f"All {c}" for c in KH_FILTERS])
        self.filter_all.activated.connect(lambda i: self._set_all("filter", self.filter_all, KH_FILTERS))
        self.override = QComboBox()
        self.override.addItems(KH_OVERRIDES)
        self.override.setCurrentText(self.cfg.kh_override)
        self.override.setToolTip("Applied at the next Apply only; the rows keep their types")
        self.override.currentTextChanged.connect(self._override)
        bar.addWidget(self.couple_all)
        bar.addWidget(self.filter_all)
        bar.addSpacing(20)
        bar.addWidget(QLabel("KH override at apply:"))
        bar.addWidget(self.override)
        bar.addStretch(1)
        return bar

    def _actions(self) -> None:
        tb = self.addToolBar("Main")
        tb.setMovable(False)

        def act(text, slot, key=None, tip=""):
            a = QAction(text, self)
            a.triggered.connect(slot)
            if key:
                a.setShortcut(QKeySequence(key))
            a.setToolTip(tip or text)
            tb.addAction(a)
            return a

        act("Import from Configure Experiment", self.import_legacy,
            tip=f"Read {legacy.DEFAULT_DIR}")
        act("Open…", self.open_file, "Ctrl+O")
        act("Save as…", self.save_as, "Ctrl+Shift+S")
        act("Write Control Experiment.json", self.save_legacy,
            tip="Write the file Transport and FLEX read")
        act("Export topology…", self.export_topology, tip="Save the wiring graph as JSON")
        act("Log measurement…", self.log_measurement,
            tip="Write this measurement (user, station, device, serials, wiring) to the lab database")
        tb.addSeparator()
        act("Read back", self.read_back, "F5", "Read the KH channels and lock-in gains")
        self.apply_action = act("Apply to instruments", self.apply, "Ctrl+Return",
                                "Write KH channels and lock-in gains, then read back")
        act("Adopt instrument state", self.adopt,
            tip="Copy KH gain/shunt/coupling/filter and lock-in output gains into the table")
        tb.addSeparator()
        act("Simulated instruments", self.start_sim, tip="Start simulated KH + lock-in on free ports")

    # ---- edits -----------------------------------------------------------

    def changed(self) -> None:
        self.channel_model.refresh()
        self.wiring.set_config(self.cfg)
        found = rules.validate(self.cfg)
        self.issues.clear()
        for i in found:
            where = f"AI {i.ai}" if i.ai is not None else i.field
            item = QListWidgetItem(f"{'Error' if i.is_error else 'Note'} [{i.code}] {where}: {i.message}")
            item.setData(Qt.UserRole, i.ai)
            item.setForeground(Qt.darkRed if i.is_error else Qt.darkYellow)
            self.issues.addItem(item)
        for msg in self.channel_model.mismatch.values():
            self.issues.addItem(QListWidgetItem(f"Instrument differs: {msg}"))
        if not found and not self.channel_model.mismatch:
            self.issues.addItem("No problems found.")
        errors = sum(i.is_error for i in found)
        self.apply_action.setEnabled(errors == 0)
        self.machine.setPlainText(json.dumps(topology.build(self.cfg), indent=1))

    def _pads_changed(self, n: int) -> None:
        self.cfg.experiment.pads = n
        self.changed()

    def _exp_edit(self, key, text):
        setattr(self.cfg.experiment, key, text.strip())
        if key == "station_type" and not self.lookups.error:
            self.ed["station"].set_choices(self.lookups.stations_of(text.strip()))

    def _instruments_edit(self):
        addrs = [a.strip() for a in self.kh_addr.text().split(",") if a.strip()]
        self.cfg.instruments.kh_addresses = addrs
        self.cfg.instruments.lockin_address = self.lockin_addr.text().strip()
        self.cfg.resize(len(self.cfg.channels), len(self.cfg.outputs))
        self._disconnect()
        self.changed()

    def _resize(self):
        self.channel_model.beginResetModel()
        self.cfg.resize(self.n_ai.value(), self.n_ao.value())
        rules.derive_all(self.cfg)
        self.channel_model.endResetModel()
        self.changed()

    def _set_all(self, attr, box, values):
        i = box.currentIndex()
        if i > 0:
            rules.set_all(self.cfg, attr, values[i - 1])
            self.statusBar().showMessage(f"Set {attr} = {values[i - 1]} on every row")
        box.setCurrentIndex(0)
        self.changed()

    def _override(self, text):
        self.cfg.kh_override = text
        self.changed()

    def _row_selected(self, cur: QModelIndex, _prev):
        if cur.isValid():
            self.wiring.select(self.cfg.channels[cur.row()].ai)

    def _select_ai(self, ai: int):
        row = next(i for i, c in enumerate(self.cfg.channels) if c.ai == ai)
        self.table.selectRow(row)
        self.wiring.select(ai)

    def _issue_clicked(self, item):
        ai = item.data(Qt.UserRole)
        if ai:
            self._select_ai(ai)

    def set_config(self, cfg: Config, source: str) -> None:
        self.cfg = cfg
        self.source = source
        self.channel_model.set_config(cfg)
        e = cfg.experiment
        for key, le in self.ed.items():
            le.setText(getattr(e, key))
        self.pads.blockSignals(True)
        self.pads.setValue(e.pads)
        self.pads.blockSignals(False)
        for w, v in ((self.n_ai, len(cfg.channels)), (self.n_ao, len(cfg.outputs))):
            w.blockSignals(True)
            w.setValue(v)
            w.blockSignals(False)
        self.kh_addr.setText(", ".join(cfg.instruments.kh_addresses))
        self.lockin_addr.setText(cfg.instruments.lockin_address)
        self.override.setCurrentText(cfg.kh_override)
        self._disconnect()
        self.changed()
        self.statusBar().showMessage(f"Loaded {source}")

    # ---- files -----------------------------------------------------------

    def import_legacy(self):
        d = QFileDialog.getExistingDirectory(self, "Configure Experiment folder", str(legacy.DEFAULT_DIR))
        if d:
            self.set_config(legacy.import_legacy(Path(d)), d)

    def open_file(self):
        path, _ = QFileDialog.getOpenFileName(self, "Open configuration", str(legacy.DEFAULT_DIR), "JSON (*.json)")
        if path:
            self.set_config(legacy.import_legacy(Path(path).parent), path)

    def save_as(self):
        d = QFileDialog.getExistingDirectory(self, "Folder for Control Experiment.json")
        if d:
            p = legacy.save(self.cfg, Path(d))
            self.statusBar().showMessage(f"Wrote {p}")

    def export_topology(self):
        path, _ = QFileDialog.getSaveFileName(self, "Export topology", "topology.json", "JSON (*.json)")
        if path:
            Path(path).write_text(json.dumps(topology.build(self.cfg), indent=1), encoding="utf-8")
            self.statusBar().showMessage(f"Wrote {path}")

    def save_legacy(self):
        target = legacy.DEFAULT_DIR / legacy.JSON_NAME
        if legacy.missing_instruments(self.cfg, legacy.DEFAULT_DIR):
            QMessageBox.warning(self, "Write configuration",
                                "This configuration has no instrument classes (it was not imported from "
                                "Configure Experiment). Transport needs them, so it will not replace "
                                f"{target}.\n\nImport from Configure Experiment first, or use Save as.")
            return
        if QMessageBox.question(self, "Write configuration",
                                f"Overwrite {target}?\n\nTransport (prepareTransport) and FLEX read this file.") \
                != QMessageBox.Yes:
            return
        p = legacy.save(self.cfg)
        self.statusBar().showMessage(f"Wrote {p}")

    # ---- instruments -----------------------------------------------------

    def _disconnect(self):
        if self.rig:
            self.rig.close()
            self.rig = None
        self.conn.setText("not connected")

    def _rig(self) -> hardware.Rig:
        if self.rig is None:
            self.rig = hardware.Rig(self.cfg, timeout=2.0)
        return self.rig

    def _show_idn(self, rb: hardware.Readback) -> None:
        self.lockin_id.setText(_idn_text(rb.lockin_idn))
        self.kh_id.setText("; ".join(f"{chr(65 + i)}: {_idn_text(rb.kh_idn.get(i, {}))}" for i in sorted(rb.kh))
                           or "not read")
        if rb.lockin_idn or rb.kh_idn:
            self.serials = rb.serials()

    def _show_readback(self, rb: hardware.Readback, what: str):
        self._show_idn(rb)
        for e in rb.errors:
            self.log.appendPlainText(f"ERROR {e}")
        if rb.errors:
            self.conn.setText("error, see log")
            self._disconnect()
            self.statusBar().showMessage(f"{what} failed: {rb.errors[0]}")
            return
        self._adopt_counts(rb)
        self.log.appendPlainText(f"{what}: KH {json.dumps(rb.kh)}")
        self.log.appendPlainText(f"{what}: input gain {rb.input_gain}, output gain {rb.output_gain}")
        mism = rb.mismatches(self.cfg)
        self.channel_model.mismatch = {}
        self.channel_model.ao_mismatch = {}
        for m in mism:
            head = m.split(":")[0].split()
            if head[0] == "AI":
                self.channel_model.mismatch[int(head[1])] = m
            elif head[0] == "AO":
                self.channel_model.ao_mismatch[int(head[1])] = m
        self.conn.setText(f"connected, {len(self.cfg.instruments.kh_addresses)} KH chassis")
        self.changed()
        self.statusBar().showMessage(f"{what}: {'matches the table' if not mism else f'{len(mism)} differences'}")

    def read_back(self):
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            self._show_readback(self._rig().read(), "Read back")
        finally:
            QApplication.restoreOverrideCursor()

    def apply(self):
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            self._show_readback(self._rig().apply(self.cfg), "Apply")
        except Exception as err:
            self.log.appendPlainText(f"ERROR {err}")
            self.statusBar().showMessage(f"Apply failed: {err}")
            self._disconnect()
        finally:
            QApplication.restoreOverrideCursor()

    def adopt(self):
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            rb = self._rig().read()
        finally:
            QApplication.restoreOverrideCursor()
        if rb.errors:
            self._show_readback(rb, "Adopt")
            return
        changes = hardware.adopt(self.cfg, rb)
        rules.derive_all(self.cfg)
        for c in changes:
            self.log.appendPlainText(f"Adopted {c}")
        self._show_readback(rb, "Adopt")
        self.statusBar().showMessage(f"Adopted {len(changes)} settings from the instruments")

    def log_measurement(self):
        if not self.db_settings:
            QMessageBox.information(self, "Log measurement", "The database is turned off (--no-db).")
            return
        e = self.cfg.experiment
        try:
            lockin_sn, kh_sns = self._rig().serials()
        except Exception as err:
            # Instruments not answering now: use the serials from the last read, if any.
            lockin_sn, kh_sns = self.serials
            self.log.appendPlainText(f"Serial numbers not read now ({err}); using the last read")
        values = {
            "user": e.user, "station": e.station, "device": e.device_name,
            "measurement": str(Path(e.path) / e.device_name) if e.path else e.device_name,
            "lockin_serial": lockin_sn, "kh_serial": ", ".join(kh_sns),
        }
        text = "\n".join(f"{k}: {v or '(empty, stored as NULL)'}" for k, v in values.items())
        target = f"{self.db_settings.host}/{self.db_settings.dbname} (llab_001)"
        if QMessageBox.question(self, "Log measurement", f"Insert into {target}?\n\n{text}") != QMessageBox.Yes:
            return
        try:
            wid = db.record_measurement(self.db_settings, wiring=db.wiring_document(self.cfg), **values)
            self.statusBar().showMessage(f"Measurement logged to the database (wiring {wid})")
            self.log.appendPlainText(f"Database: logged {values}")
        except Exception as err:
            QMessageBox.warning(self, "Log measurement", f"Not logged:\n{err}")

    def start_sim(self):
        n_ai, n_ao = len(self.cfg.channels), len(self.cfg.outputs)
        kh = [f"tcp://127.0.0.1:{_free_port()}" for _ in self.cfg.instruments.kh_addresses]
        lk = f"tcp://127.0.0.1:{_free_port()}"
        sim.start(kh, lk, n_ai, n_ao)
        self.kh_addr.setText(", ".join(kh))
        self.lockin_addr.setText(lk)
        self._instruments_edit()
        self.log.appendPlainText(f"Simulated instruments: KH {kh}, lock-in {lk}")
        self.read_back()


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description="Experiment configurator prototype")
    src = ap.add_mutually_exclusive_group()
    src.add_argument("--demo", action="store_true", help="start with the demonstration configuration")
    src.add_argument("--import-dir", type=Path, help="import a Configure Experiment folder")
    ap.add_argument("--sim", action="store_true", help="start simulated instruments and connect")
    ap.add_argument("--apply", action="store_true", help="apply once at startup (with --sim)")
    ap.add_argument("--select", type=int, help="select this AI at startup")
    ap.add_argument("--tab", type=int, default=0, help="right-hand tab to show")
    ap.add_argument("--screenshot", type=Path, help="render the window to this PNG and exit")
    ap.add_argument("--no-db", action="store_true", help="do not contact the lab database")
    ap.add_argument("--offline", action="store_true", help="do not query the instruments at startup")
    ap.add_argument("--wait", type=int, default=300, help="ms to wait before --screenshot")
    ap.add_argument("--api-port", type=int, default=service.DEFAULT_PORT,
                    help=f"port for the remote API (default {service.DEFAULT_PORT}, 0 = off)")
    a = ap.parse_args(argv)

    app = QApplication.instance() or QApplication(sys.argv[:1])
    if a.import_dir:
        cfg, source = legacy.import_legacy(a.import_dir), str(a.import_dir)
    elif a.demo or not (legacy.DEFAULT_DIR / legacy.JSON_NAME).exists():
        cfg, source = demo_config(), "demo configuration"
    else:
        cfg, source = legacy.import_legacy(), str(legacy.DEFAULT_DIR)
    w = MainWindow(cfg, source, api_port=a.api_port, db_settings=None if a.no_db else db.DbSettings(),
                   query_instruments=not (a.offline or a.sim))
    if a.sim:
        w.start_sim()
        if a.apply:
            w.apply()
    if a.select:
        w._select_ai(a.select)
    w.tabs.setCurrentIndex(a.tab)
    w.show()
    if a.screenshot:
        def shot():
            w.grab().save(str(a.screenshot))
            app.quit()
        QTimer.singleShot(a.wait, shot)
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
