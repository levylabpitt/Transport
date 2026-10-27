"""Qt table models for the channel and output tables."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt
from PySide6.QtGui import QBrush, QColor, QFont

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


# Read left to right: the channel, the pad it measures, what it means, then the
# Krohn-Hite channel in front of the lock-in, then the lock-in itself.
CHANNEL_COLUMNS = [
    # One row per channel n, read on lock-in AI n. The standard channel n is
    # AI n = AO n = KH channel n; anything else is shown as an exception.
    Column("channel", "Ch", False, "Channel number; data columns AIn, Xn, Yn", ""),
    Column("electrode", "Electrode", True,
           "Device pad cabled to the Krohn-Hite + input (or straight to the AI when KH # is none)", "Device"),
    Column("type", "Type", True, "U: sourced through R_sh; V: voltage; n.c.; Ground", "Measurement"),
    Column("role", "Role", True, "Label the experiment VIs use to find channels (I+, V1+, Vbg, ...)",
           "Measurement"),
    Column("name", "Name", False, "Derived: U<e>, V<e>, dV<e>-<second pad>", "Measurement"),
    Column("kh", "KH #", True, "Krohn-Hite channel whose output goes to this AI. Standard: channel n", "Krohn-Hite"),
    Column("plus", "+", False, "What the Krohn-Hite + input is cabled to: the electrode", "Krohn-Hite"),
    Column("minus", "\u2212", True,
           "What the Krohn-Hite \u2212 input is cabled to. Standard: the DAC (the AO in the Lock-in group). "
           "Also GND, n.c., or a second pad to measure a difference", "Krohn-Hite"),
    Column("input", "Config", False, "Input mode, derived from Type and the \u2212 input", "Krohn-Hite"),
    Column("kh_gain", "Gain", True, "Krohn-Hite gain", "Krohn-Hite"),
    Column("shunt", "R_sh", True, "Shunt resistor between the \u2212 and + inputs; only used by U rows",
           "Krohn-Hite"),
    Column("couple", "Couple", True, "AC or DC coupling", "Krohn-Hite"),
    Column("filter", "Filter", True, "Bandwidth filter", "Krohn-Hite"),
    Column("ai", "AI", False, "Lock-in analog input. Always the channel number", "Lock-in"),
    Column("ext_gain", "Ext. gain", True,
           "Gain between the Krohn-Hite (or the pad) and the ADC, e.g. SR830: 10 V / sensitivity", "Lock-in"),
    Column("lockin_gain", "Input gain", False, "KH gain x external gain, sent to the lock-in", "Lock-in"),
    Column("ao", "AO", True, "Lock-in analog output (DAC) on the Krohn-Hite \u2212 input. Standard: AO n",
           "Lock-in"),
    Column("out_gain", "Output gain", True,
           "Amplifier between that AO and the device, e.g. 25 for a backgate amplifier. "
           "Belongs to the AO: also in the Outputs table", "Lock-in"),
]

OUTPUT_COLUMNS = [
    Column("ao", "AO", False, "Lock-in analog output"),
    Column("name", "Name", True, "What it drives (Vbg, I source, ...)"),
    Column("gain", "Gain", True, "Amplifier between AO and device (lock-in output gain)"),
    Column("electrode", "Electrode", True, "Electrode it drives when it does not go through a KH channel"),
]

GROUP_TINT = {"": QColor(244, 244, 244), "Device": QColor(252, 250, 240), "Krohn-Hite": QColor(243, 251, 247),
              "Lock-in": QColor(246, 248, 255), "Measurement": QColor(250, 246, 252)}
EXCEPTION_FG = QColor(20, 80, 200)
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


def exception(ch, key: str) -> str:
    """Why this cell differs from the standard channel (AI n = AO n = KH n), or ""."""
    n = ch.ai
    if key == "kh":
        if ch.kh is None:
            return "No Krohn-Hite: the pad goes straight to the ADC"
        if ch.kh != n - 1:
            return f"Standard would be KH {kh_label(n - 1)}"
    if key == "minus" and ch.kh is not None and ch.minus != MINUS_AO:
        return f"Not the DAC: the \u2212 input is on {ch.minus}"
    if key == "ao" and ch.kh is not None and ch.minus == MINUS_AO and ch.ao != n:
        return f"Standard would be AO {n}"
    if key == "ext_gain" and ch.ext_gain != 1:
        return "An external gain stage sits before the ADC"
    return ""


def choices(cfg: Config, key: str) -> tuple[list[str], bool]:
    """Options for a column's editor, and whether free text is allowed."""
    if key == "electrode":
        return [str(i) for i in range(1, cfg.experiment.pads + 1)], True
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
        return ["AO", "GND", "n.c."] + electrodes, True
    if key == "ao":
        return [str(o.ao) for o in cfg.outputs] + ["none"], False
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
                self.issues[(i.ai, i.field)] = i
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
        if key in ("kh_gain", "couple", "filter", "minus", "ao") and ch.kh is None:
            return False
        if key == "ao":
            return ch.minus == MINUS_AO
        if key == "out_gain":
            return ch.kh is not None and ch.minus == MINUS_AO and self.cfg.output(ch.ao) is not None
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
        if key in ("channel", "ai"):
            return str(ch.ai)
        if key == "plus":
            return ch.electrode if ch.kh is not None else ""
        if key == "minus":
            return ("AO" if ch.minus == MINUS_AO else ch.minus) if ch.kh is not None else ""
        if key in ("ao", "out_gain"):
            if ch.kh is None or ch.minus != MINUS_AO or ch.ao is None:
                return ""
            o = self.cfg.output(ch.ao)
            return str(ch.ao) if key == "ao" else (f"{o.gain:g}" if o else "")
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
        why = exception(ch, key)
        if role == Qt.ForegroundRole:
            if why:
                return QBrush(EXCEPTION_FG)
            if not self._cell_editable(ch, key):
                return QBrush(DERIVED_FG)
        if role == Qt.FontRole and why:
            f = QFont()
            f.setBold(True)
            return f
        if role == Qt.ToolTipRole:
            parts = [why] if why else []
            if issue:
                parts.append(f"[{issue.code}] {issue.message}")
            if key in ("kh", "input") and ch.ai in self.mismatch:
                parts.append(self.mismatch[ch.ai])
            return "\n".join(parts) or col.tip
        if role == Qt.TextAlignmentRole:
            if key in ("ext_gain", "lockin_gain", "out_gain"):
                return int(Qt.AlignRight | Qt.AlignVCenter)
            if key in ("channel", "ai", "ao", "kh", "plus", "minus"):
                return int(Qt.AlignCenter)
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
                m = re.fullmatch(r"AO\s*(\d*)", text, re.IGNORECASE)
                if m:
                    ch.minus = MINUS_AO
                    if m.group(1):
                        ch.ao = int(m.group(1))
                    elif ch.ao is None:
                        ch.ao = ch.ai if self.cfg.output(ch.ai) else None
                else:
                    ch.minus = normalize_minus(text)
            elif key == "ao":
                ch.ao = None if text.lower() in ("", "none") else int(text)
            elif key == "out_gain":
                self.cfg.output(ch.ao).gain = float(text)
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

    def refresh(self) -> None:
        self.dataChanged.emit(self.index(0, 0), self.index(self.rowCount() - 1, self.columnCount() - 1))
