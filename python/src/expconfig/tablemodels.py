"""Qt table models for the channel and output tables."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt
from PySide6.QtGui import QBrush, QColor

from . import rules
from .model import (
    CHANNEL_TYPES, KH_CHANNELS_PER_CHASSIS, KH_COUPLINGS, KH_FILTERS, KH_GAINS, KH_SHUNTS,
    MINUS_AO, ROLE_STRINGS, Config, kh_label, normalize_minus, parse_kh_label,
)


@dataclass(frozen=True)
class Column:
    key: str
    title: str
    editable: bool
    tip: str
    group: str = ""


# Grouped as in Configure Experiment: what the lock-in input measures, then the
# Krohn-Hite channel in front of it, then the gain outside the instruments.
CHANNEL_COLUMNS = [
    Column("ai", "AI", False, "Lock-in analog input: the data columns AIn, Xn, Yn", "Lock-in"),
    Column("electrode", "Electrode", True, "Electrode cabled to the Krohn-Hite + input", "Lock-in"),
    Column("minus", "Reference", True,
           "What the Krohn-Hite - input is cabled to: an AO (normal cabling), GND, n.c., "
           "or a second electrode to measure a difference", "Lock-in"),
    Column("type", "Type", True, "U: sourced through the shunt; V: voltage; n.c.; Ground", "Lock-in"),
    Column("role", "Role", True, "Label the experiment VIs use to find channels (I+, V1+, Vbg, ...)", "Lock-in"),
    Column("name", "Name", False, "Derived: U<e>, V<e>, dV<e>-<reference>", "Lock-in"),
    Column("kh", "KH #", True, "Krohn-Hite channel cabled to this AI (A1..A8, B1..), or none", "Krohn-Hite"),
    Column("input", "Config", False, "Krohn-Hite input mode, derived from Type and Reference", "Krohn-Hite"),
    Column("kh_gain", "Gain", True, "Krohn-Hite gain", "Krohn-Hite"),
    Column("shunt", "Shunt", True, "Shunt resistor; only used by U rows", "Krohn-Hite"),
    Column("couple", "Couple", True, "AC or DC coupling", "Krohn-Hite"),
    Column("filter", "Filter", True, "Bandwidth filter", "Krohn-Hite"),
    Column("ext_gain", "Ext. gain", True, "Gain between the source and the AI (e.g. SR830: 10 V / sensitivity)",
           "Other"),
    Column("lockin_gain", "Total", False, "KH gain x external gain, sent to the lock-in", "Other"),
]

OUTPUT_COLUMNS = [
    Column("ao", "AO", False, "Lock-in analog output"),
    Column("name", "Name", True, "What it drives (Vbg, I source, ...)"),
    Column("gain", "Gain", True, "Amplifier between AO and device (lock-in output gain)"),
    Column("electrode", "Electrode", True, "Electrode it drives when it does not go through a KH channel"),
]

GROUP_TINT = {"Lock-in": QColor(246, 248, 255), "Krohn-Hite": QColor(243, 251, 247), "Other": QColor(255, 248, 243)}
ERROR_BG = QColor(255, 205, 205)
WARN_BG = QColor(255, 236, 190)
MISMATCH_BG = QColor(255, 220, 160)
DERIVED_FG = QColor(110, 110, 110)


def _natural(s: str):
    return (0, int(s)) if s.isdigit() else (1, s)


def reference_text(ch) -> str:
    if ch.minus == MINUS_AO:
        return f"AO {ch.ao}" if ch.ao is not None else "AO ?"
    return ch.minus


def choices(cfg: Config, key: str) -> tuple[list[str], bool]:
    """Options for a column's editor, and whether free text is allowed."""
    if key == "type":
        return list(CHANNEL_TYPES), False
    if key == "shunt":
        return list(KH_SHUNTS), False
    if key == "kh_gain":
        return list(KH_GAINS), False
    if key == "couple":
        return list(KH_COUPLINGS), False
    if key == "filter":
        return list(KH_FILTERS), False
    if key == "kh":
        return [kh_label(i) for i in range(KH_CHANNELS_PER_CHASSIS * cfg.kh_chassis)] + ["none"], False
    if key == "role":
        return list(ROLE_STRINGS), True
    if key == "minus":
        electrodes = sorted({c.electrode for c in cfg.channels if c.electrode}, key=_natural)
        return [f"AO {o.ao}" for o in cfg.outputs] + ["GND", "n.c."] + electrodes, True
    return [], True


class ChannelModel(QAbstractTableModel):
    def __init__(self, cfg: Config, on_change: Callable[[], None]):
        super().__init__()
        self.cfg = cfg
        self.on_change = on_change
        self.issues: dict[tuple[int, str], rules.Issue] = {}
        self.mismatch: dict[int, str] = {}
        self.revalidate()

    def set_config(self, cfg: Config) -> None:
        self.beginResetModel()
        self.cfg = cfg
        self.revalidate()
        self.endResetModel()

    def revalidate(self) -> list[rules.Issue]:
        found = rules.validate(self.cfg)
        self.issues = {}
        for i in found:
            if i.ai is not None:
                # AO problems show on the Reference column, where the AO is chosen.
                self.issues[(i.ai, "minus" if i.field == "ao" else i.field)] = i
        return found

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.cfg.channels)

    def columnCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(CHANNEL_COLUMNS)

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if orientation == Qt.Horizontal:
            if role == Qt.DisplayRole:
                return CHANNEL_COLUMNS[section].title
            if role == Qt.ToolTipRole:
                return CHANNEL_COLUMNS[section].tip
        return None

    def _cell_editable(self, ch, key: str) -> bool:
        col = next(c for c in CHANNEL_COLUMNS if c.key == key)
        if not col.editable:
            return False
        if key == "shunt":
            return ch.type == "U" and ch.kh is not None
        if key in ("kh_gain", "couple", "filter", "minus") and ch.kh is None:
            return False
        return True

    def flags(self, index):
        ch = self.cfg.channels[index.row()]
        key = CHANNEL_COLUMNS[index.column()].key
        f = Qt.ItemIsSelectable | Qt.ItemIsEnabled
        if self._cell_editable(ch, key):
            f |= Qt.ItemIsEditable
        return f

    def display(self, ch, key: str) -> str:
        if key == "kh":
            return kh_label(ch.kh)
        if key == "minus":
            return reference_text(ch) if ch.kh is not None else ""
        if key in ("ext_gain", "lockin_gain"):
            return f"{getattr(ch, key):g}"
        if key in ("input", "kh_gain", "shunt", "couple", "filter") and ch.kh is None:
            return ""
        return str(getattr(ch, key))

    def data(self, index, role=Qt.DisplayRole):
        ch = self.cfg.channels[index.row()]
        col = CHANNEL_COLUMNS[index.column()]
        key = col.key
        issue = self.issues.get((ch.ai, key))
        if role in (Qt.DisplayRole, Qt.EditRole):
            return self.display(ch, key)
        if role == Qt.BackgroundRole:
            if issue:
                return QBrush(ERROR_BG if issue.is_error else WARN_BG)
            if key in ("kh", "input") and ch.ai in self.mismatch:
                return QBrush(MISMATCH_BG)
            return QBrush(GROUP_TINT.get(col.group, QColor(255, 255, 255)))
        if role == Qt.ForegroundRole:
            if not self._cell_editable(ch, key):
                return QBrush(DERIVED_FG)
        if role == Qt.ToolTipRole:
            parts = []
            if issue:
                parts.append(f"[{issue.code}] {issue.message}")
            if key in ("kh", "input") and ch.ai in self.mismatch:
                parts.append(self.mismatch[ch.ai])
            return "\n".join(parts) or col.tip
        if role == Qt.TextAlignmentRole and key in ("ai", "ext_gain", "lockin_gain"):
            return int(Qt.AlignRight | Qt.AlignVCenter)
        return None

    def setData(self, index, value, role=Qt.EditRole):
        if role != Qt.EditRole:
            return False
        ch = self.cfg.channels[index.row()]
        key = CHANNEL_COLUMNS[index.column()].key
        text = str(value).strip()
        try:
            if key == "kh":
                ch.kh = parse_kh_label(text)
            elif key == "minus":
                m = re.fullmatch(r"AO\s*(\d+)", text, re.IGNORECASE)
                if m:
                    ch.minus, ch.ao = MINUS_AO, int(m.group(1))
                else:
                    ch.minus = normalize_minus(text)
            elif key == "type":
                rules.set_type(ch, text, self.cfg.default_shunt)
            elif key == "ext_gain":
                ch.ext_gain = float(text)
            else:
                setattr(ch, key, text)
        except ValueError:
            return False
        rules.derive(ch)
        self.revalidate()
        self.dataChanged.emit(self.index(0, 0), self.index(self.rowCount() - 1, self.columnCount() - 1))
        self.on_change()
        return True

    def refresh(self) -> None:
        self.revalidate()
        self.dataChanged.emit(self.index(0, 0), self.index(self.rowCount() - 1, self.columnCount() - 1))


class OutputModel(QAbstractTableModel):
    def __init__(self, cfg: Config, on_change: Callable[[], None]):
        super().__init__()
        self.cfg = cfg
        self.on_change = on_change
        self.mismatch: dict[int, str] = {}

    def set_config(self, cfg: Config) -> None:
        self.beginResetModel()
        self.cfg = cfg
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.cfg.outputs)

    def columnCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(OUTPUT_COLUMNS)

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if orientation == Qt.Horizontal:
            if role == Qt.DisplayRole:
                return OUTPUT_COLUMNS[section].title
            if role == Qt.ToolTipRole:
                return OUTPUT_COLUMNS[section].tip
        return None

    def flags(self, index):
        f = Qt.ItemIsSelectable | Qt.ItemIsEnabled
        if OUTPUT_COLUMNS[index.column()].editable:
            f |= Qt.ItemIsEditable
        return f

    def data(self, index, role=Qt.DisplayRole):
        o = self.cfg.outputs[index.row()]
        key = OUTPUT_COLUMNS[index.column()].key
        if role in (Qt.DisplayRole, Qt.EditRole):
            v = getattr(o, key)
            return f"{v:g}" if isinstance(v, float) else str(v)
        if role == Qt.BackgroundRole and key == "gain" and o.ao in self.mismatch:
            return QBrush(MISMATCH_BG)
        if role == Qt.ToolTipRole:
            return self.mismatch.get(o.ao) if key == "gain" and o.ao in self.mismatch else OUTPUT_COLUMNS[index.column()].tip
        return None

    def setData(self, index, value, role=Qt.EditRole):
        if role != Qt.EditRole:
            return False
        o = self.cfg.outputs[index.row()]
        key = OUTPUT_COLUMNS[index.column()].key
        try:
            setattr(o, key, float(value) if key == "gain" else str(value).strip())
        except ValueError:
            return False
        self.dataChanged.emit(index, index)
        self.on_change()
        return True
