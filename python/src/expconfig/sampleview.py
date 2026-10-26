"""Sample view: each electrode and everything cabled to it.

The wiring view reads from the instruments' side (one strip per AI); this one
reads from the device's side. A teed electrode shows every channel it feeds on
one line, and an electrode driven by an AO shows the source.
"""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPen
from PySide6.QtWidgets import QWidget

from .model import MINUS_AO, Config, kh_label
from .wiringview import electrode_color

ROW_H = 30
PAD = 8
E_W = 96
CHIP_GAP = 8
WIDTH = 560


@dataclass
class Chip:
    text: str
    ai: int | None
    kind: str  # "measure", "reference", "source", "direct"


def _natural(s: str):
    return (0, int(s)) if s.isdigit() else (1, s)


def connections(cfg: Config) -> dict[str, list[Chip]]:
    """electrode name -> what it is cabled to."""
    out: dict[str, list[Chip]] = {}

    def add(e: str, chip: Chip) -> None:
        if e:
            out.setdefault(e, []).append(chip)

    for ch in cfg.channels:
        if ch.type == "n.c." and not ch.electrode:
            continue
        label = ch.name or ch.type
        role = f" [{ch.role}]" if ch.role else ""
        if ch.kh is None:
            add(ch.electrode, Chip(f"AI {ch.ai} direct  {label}{role}", ch.ai, "direct"))
            continue
        k = kh_label(ch.kh)
        if ch.type == "Ground":
            add(ch.electrode, Chip(f"{k}+  grounded (AI {ch.ai})", ch.ai, "reference"))
            continue
        add(ch.electrode, Chip(f"{k}+ → AI {ch.ai}  {label}{role}", ch.ai, "measure"))
        if ch.minus_is_electrode:
            add(ch.minus, Chip(f"{k}− → AI {ch.ai}  {label}", ch.ai, "reference"))
        if ch.type == "U" and ch.minus == MINUS_AO and ch.ao is not None:
            o = cfg.output(ch.ao)
            amp = f" ×{o.gain:g}" if o and o.gain != 1 else ""
            name = f" {o.name}" if o and o.name else ""
            add(ch.electrode, Chip(f"driven by AO {ch.ao}{name} via {k} {ch.shunt}{amp}", ch.ai, "source"))
    for o in cfg.outputs:
        if o.electrode:
            amp = f" ×{o.gain:g}" if o.gain != 1 else ""
            add(o.electrode, Chip(f"driven by AO {o.ao} {o.name}{amp}".rstrip(), None, "source"))
    return dict(sorted(out.items(), key=lambda kv: _natural(kv[0])))


CHIP_FILL = {"measure": QColor(232, 232, 250), "reference": QColor(236, 236, 236),
             "source": QColor(225, 240, 225), "direct": QColor(250, 232, 222)}


class SampleView(QWidget):
    rowClicked = Signal(int)

    def __init__(self, cfg: Config):
        super().__init__()
        self.cfg = cfg
        self.selected_ai: int | None = None
        self._hit: list[tuple[QRectF, int]] = []
        self._layout: list[tuple[str, list[tuple[QRectF, Chip]]]] = []
        self.setMinimumWidth(WIDTH)

    def set_config(self, cfg: Config) -> None:
        self.cfg = cfg
        self._relayout()
        self.updateGeometry()
        self.update()

    def select(self, ai: int | None) -> None:
        self.selected_ai = ai
        self.update()

    def _relayout(self) -> None:
        fm = QFontMetrics(self._font())
        width = max(self.width(), WIDTH)
        y = PAD
        self._layout = []
        for e, chips in connections(self.cfg).items():
            x = PAD + E_W + 14
            row_top = y
            placed = []
            for c in chips:
                w = fm.horizontalAdvance(c.text) + 16
                if x + w > width - PAD and placed:
                    x = PAD + E_W + 14
                    y += ROW_H
                placed.append((QRectF(x, y + 3, w, ROW_H - 6), c))
                x += w + CHIP_GAP
            self._layout.append((e, placed, row_top, y + ROW_H))
            y += ROW_H + 6
        self._height = y + PAD

    def _font(self) -> QFont:
        f = QFont(self.font())
        f.setPointSizeF(8.5)
        return f

    def sizeHint(self) -> QSize:
        self._relayout()
        return QSize(WIDTH, max(self._height, 60))

    def minimumSizeHint(self) -> QSize:
        return self.sizeHint()

    def resizeEvent(self, ev):
        self._relayout()
        self.updateGeometry()

    def mousePressEvent(self, ev):
        for _e, placed, _t, _b in self._layout:
            for r, c in placed:
                if r.contains(ev.position()) and c.ai is not None:
                    self.rowClicked.emit(c.ai)
                    return

    def paintEvent(self, ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.fillRect(self.rect(), QColor(252, 252, 250))
        p.setFont(self._font())
        if not self._layout:
            p.setPen(QColor(120, 120, 120))
            p.drawText(self.rect(), Qt.AlignCenter, "No electrodes entered yet")
            return
        sel_electrodes = set()
        if self.selected_ai is not None:
            ch = self.cfg.channel(self.selected_ai)
            if ch:
                sel_electrodes = {ch.electrode, ch.minus}
        for e, placed, top, bottom in self._layout:
            box = QRectF(PAD, top + 3, E_W, bottom - top - 6)
            if e in sel_electrodes:
                p.fillRect(QRectF(0, top, self.width(), bottom - top), QColor(225, 236, 255))
            p.setPen(QPen(QColor(90, 90, 90), 1))
            p.setBrush(electrode_color(e))
            p.drawRoundedRect(box, 5, 5)
            f = self._font()
            f.setBold(True)
            p.setFont(f)
            p.setPen(QColor(30, 30, 30))
            p.drawText(box, Qt.AlignCenter, e)
            p.setFont(self._font())
            p.setPen(QPen(QColor(110, 110, 110), 1.2))
            row_starts = {}
            for r, _c in placed:
                row_starts.setdefault(r.top(), r)
            for r in row_starts.values():
                p.drawLine(box.right(), box.center().y(), r.left(), r.center().y())
            for r, c in placed:
                selected = c.ai is not None and c.ai == self.selected_ai
                p.setPen(QPen(QColor(40, 90, 200) if selected else QColor(110, 110, 110), 2 if selected else 1,
                              Qt.DashLine if c.kind == "reference" else Qt.SolidLine))
                p.setBrush(CHIP_FILL[c.kind])
                p.drawRoundedRect(r, 4, 4)
                p.setPen(QColor(30, 30, 30))
                p.drawText(r, Qt.AlignCenter, c.text)
        p.end()
