"""Qt table model for the channel table."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt
from PySide6.QtGui import QBrush, QColor, QFont

from . import hardware, palette, rules
from .model import (
    CHANNEL_TYPES, KH_CHANNELS_PER_CHASSIS, KH_COUPLINGS, KH_FILTERS, KH_GAINS, KH_SHUNTS,
    MINUS_AO, MODES, SHUNTS_BY_MODE, Config, kh_label, normalize_minus, parse_kh_label,
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
    Column("type", "Type", True,
           "U: the pad is sourced (a voltage from the AO); V: the pad is measured; n.c.; Ground. "
           "A U row with KH # none: the AO drives the pad directly and the AI is not used", "Measurement"),
    Column("mode", "Mode", True,
           "U: I drives a current (shunt 50 to 50k) or gate applies a potential, I -> 0 (shunt 50k or 10M). "
           "V: V single-ended, or dV against a second pad on the \u2212 input", "Measurement"),
    Column("name", "Label", False,
           "Automatic channel label, saved with the data: U<pad>, V<pad>, or V<pad>-<pad> for a difference; the Mode column says I, gate, V or dV",
           "Measurement"),
    Column("kh", "KH #", True, "Krohn-Hite channel whose output goes to this AI. Standard: channel n", "Krohn-Hite"),
    Column("plus", "+", False, "What the Krohn-Hite + input is cabled to: the electrode", "Krohn-Hite"),
    Column("minus", "\u2212", True,
           "What the Krohn-Hite \u2212 input is cabled to. Standard: the DAC (the AO in the Lock-in group). "
           "Also GND, n.c., or a second pad to measure a difference", "Krohn-Hite"),
    Column("input", "Config", True, "Krohn-Hite input mode. U rows are always DIFF. On a V row, SE+ measures "
           "one pad (mode V) and DIFF the difference to a second pad on the \u2212 input (mode dV)", "Krohn-Hite"),
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
           "Belongs to the AO, so rows sharing an AO share it", "Lock-in"),
    Column("out_offset", "Output offset", True,
           "Trims the amplifier's offset: in output units (at the device), subtracted from the requested "
           "value before the output gain. Belongs to the AO, like the output gain", "Lock-in"),
]

# Same hues as the wiring view's boxes, paler.
GROUP_TINT = {"": QColor(244, 244, 244), **{g: palette.tint(c) for g, c in palette.FILL.items()}}
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
    if ch.direct:
        if key in ("type", "kh"):
            return f"No Krohn-Hite: AO {ch.ao} drives the pad directly; AI {n} is not used"
        if key == "ao" and ch.ao != n:
            return f"Standard would be AO {n}"
        return ""
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


def choices(cfg: Config, key: str, ch=None) -> tuple[list[str], bool]:
    """Options for a column's editor, and whether free text is allowed. Some depend on the row (ch)."""
    if key == "mode":
        return list(MODES.get(ch.type, ())) if ch else ["I", "gate", "V", "dV"], False
    if key == "input":
        return ["SE+", "DIFF"], False
    if key == "shunt" and ch is not None and ch.type == "U" and ch.mode in SHUNTS_BY_MODE:
        return list(SHUNTS_BY_MODE[ch.mode]), False
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
    if key == "minus":
        return ["AO", "GND", "n.c."] + [str(i) for i in range(1, cfg.experiment.pads + 1)], True
    if key == "ao":
        return [str(o.ao) for o in cfg.outputs] + ["none"], False
    return [], True


class ChannelModel(QAbstractTableModel):
    def __init__(self, cfg: Config, on_change: Callable[[], None]):
        super().__init__()
        self.cfg = cfg
        self.on_change = on_change
        self.issues: dict[tuple[int, str], rules.Issue] = {}
        self.mismatch: dict[int, str] = {}     # AI -> KH/lock-in input readback difference
        self.ao_mismatch: dict[int, str] = {}  # AO -> lock-in output gain/offset difference
        self.ai_daq: list[dict] = []            # getInputDAQ, one entry per AI; empty until read
        self.ao_daq: list[dict] = []
        self.revalidate()

    def set_daq(self, ai_daq: list[dict], ao_daq: list[dict]) -> None:
        self.ai_daq, self.ao_daq = list(ai_daq), list(ao_daq)

    def _daq(self, ch, key: str) -> str:
        """Physical channel behind the AI or AO cell, from the lock-in."""
        if key == "ai" and not ch.direct and 1 <= ch.ai <= len(self.ai_daq):
            return f"AI {ch.ai}: {hardware.daq_text(self.ai_daq[ch.ai - 1])}"
        if key == "ao" and self._drives_ao(ch) and 1 <= ch.ao <= len(self.ao_daq):
            return f"AO {ch.ao}: {hardware.daq_text(self.ao_daq[ch.ao - 1])}"
        return ""

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

    def _drives_ao(self, ch) -> bool:
        """The row's AO column applies: a U row with no KH, or a KH row whose - input is the DAC."""
        return ch.ao is not None and (ch.direct or (ch.kh is not None and ch.minus == MINUS_AO))

    def _cell_editable(self, ch, key: str) -> bool:
        col = next(c for c in CHANNEL_COLUMNS if c.key == key)
        if not col.editable:
            return False
        if key == "mode":
            return ch.type in MODES
        if key == "input":   # SE+ or DIFF is the V/dV choice; a U row is always DIFF
            return ch.type == "V" and ch.kh is not None
        if ch.direct:
            return key in ("electrode", "type", "kh", "ao") or (
                key in ("out_gain", "out_offset") and self.cfg.output(ch.ao) is not None)
        if key == "shunt":
            return ch.type == "U" and ch.kh is not None
        if key in ("kh_gain", "couple", "filter", "minus", "ao") and ch.kh is None:
            return False
        if key == "ao":
            return ch.minus == MINUS_AO
        if key in ("out_gain", "out_offset"):
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
        if ch.direct and key in ("ai", "ext_gain", "lockin_gain"):
            return "unused" if key == "ai" else ""
        if key == "kh":
            return kh_label(ch.kh)
        if key == "channel":
            return str(ch.ai)
        if key == "ai":
            return str(ch.ai)
        if key == "plus":
            return ch.electrode if ch.kh is not None else ""
        if key == "minus":
            return ("AO" if ch.minus == MINUS_AO else ch.minus) if ch.kh is not None else ""
        if key in ("ao", "out_gain", "out_offset"):
            if not self._drives_ao(ch):
                return ""
            o = self.cfg.output(ch.ao)
            if key == "ao":
                return str(ch.ao)
            return (f"{o.gain:g}" if key == "out_gain" else f"{o.offset:g}") if o else ""
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
            if key in ("out_gain", "out_offset") and self._drives_ao(ch) and ch.ao in self.ao_mismatch:
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
            if key in ("out_gain", "out_offset") and self._drives_ao(ch) and ch.ao in self.ao_mismatch:
                parts.append(self.ao_mismatch[ch.ao])
            if daq := self._daq(ch, key):
                parts.append(daq)
            return "\n".join(parts) or col.tip
        if role == Qt.TextAlignmentRole:
            if key in ("ext_gain", "lockin_gain", "out_gain", "out_offset"):
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
            elif key == "out_offset":
                self.cfg.output(ch.ao).offset = float(text)
            elif key == "type":
                rules.set_type(ch, text, self.cfg.default_shunt)
            elif key == "mode":
                rules.set_mode(ch, text, self.cfg.default_shunt)
            elif key == "input":
                if text not in ("SE+", "DIFF"):
                    raise ValueError(text)
                rules.set_mode(ch, "dV" if text == "DIFF" else "V", self.cfg.default_shunt)
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
