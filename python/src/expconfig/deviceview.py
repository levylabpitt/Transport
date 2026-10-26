"""Device view: the device with its bond pads, and one Krohn-Hite channel per AI
cabled to them, drawn like the lab's wiring sketches.

Each channel is a triangle beside the device: + to its pad, R_sh between + and
-, - to its DAC (AO) or a second pad, the output to its ADC (AI). Pads are laid
out like a chip carrier in a logical order: 1..N/2 down the left side, the rest
up the right. A physical layout (e.g. from KLayout) can replace `pad_layout`
later. A pad that feeds several channels (teed) fans out to free slots.
"""

from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen, QPolygonF
from PySide6.QtWidgets import QToolTip, QWidget

from .model import Config, kh_label
from .tablemodels import exception, reference_text
from .wiringview import electrode_color

SLOT = 30         # vertical spacing of pads and channel slots
DEV_W = 150
SIDE = 200        # room beside the device for the channels and their labels
TOP = 40
PAD = 14
TRI = 24
RED = QColor(205, 40, 40)
BLUE = QColor(30, 60, 200)
EXC = QColor(20, 80, 200)


def pad_layout(n: int, off_chip: list[str]) -> dict[str, tuple[int, int]]:
    """pad name -> (side, slot): side -1 = left, +1 = right; slot counts from the top."""
    half = math.ceil(n / 2)
    out = {}
    for p in range(1, n + 1):
        out[str(p)] = (-1, p - 1) if p <= half else (1, n - p)
    for i, name in enumerate(off_chip):
        out[name] = (-1, half + 1 + i)  # below the device, after a gap
    return out


class DeviceView(QWidget):
    rowClicked = Signal(int)

    def __init__(self, cfg: Config):
        super().__init__()
        self.cfg = cfg
        self.selected_ai: int | None = None
        self._glyphs: list[tuple[QRectF, int, str]] = []
        self.setMouseTracking(True)

    def set_config(self, cfg: Config) -> None:
        self.cfg = cfg
        self.updateGeometry()
        self.update()

    def select(self, ai: int | None) -> None:
        self.selected_ai = ai
        self.update()

    def _off_chip(self) -> list[str]:
        names = []
        for ch in self.cfg.channels:
            for e in (ch.electrode, ch.minus if ch.minus_is_electrode else ""):
                if e and not (e.isdigit() and 1 <= int(e) <= self.cfg.experiment.pads) and e not in names:
                    names.append(e)
        return names

    def _rows(self) -> int:
        return math.ceil(self.cfg.experiment.pads / 2) + (1 + len(self._off_chip()) if self._off_chip() else 0)

    def sizeHint(self) -> QSize:
        return QSize(DEV_W + 2 * SIDE + 20, TOP + (self._rows() + 1) * SLOT + 40)

    def minimumSizeHint(self) -> QSize:
        return self.sizeHint()

    # ---- interaction -----------------------------------------------------

    def _hit(self, pos):
        for r, ai, tip in self._glyphs:
            if r.contains(pos):
                return ai, tip
        return None, None

    def mousePressEvent(self, ev):
        ai, _ = self._hit(ev.position())
        if ai is not None:
            self.rowClicked.emit(ai)

    def mouseMoveEvent(self, ev):
        _, tip = self._hit(ev.position())
        if tip:
            QToolTip.showText(ev.globalPosition().toPoint(), tip, self)
        else:
            QToolTip.hideText()

    # ---- drawing ---------------------------------------------------------

    def paintEvent(self, ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.fillRect(self.rect(), QColor(252, 252, 250))
        base = QFont(self.font())
        base.setPointSizeF(8)
        p.setFont(base)

        n = self.cfg.experiment.pads
        half = math.ceil(n / 2)
        x0 = max(SIDE, (self.width() - DEV_W) / 2)
        x1 = x0 + DEV_W
        off = self._off_chip()
        layout = pad_layout(n, off)

        def pad_point(name: str) -> tuple[QPointF, int]:
            side, slot = layout[name]
            return QPointF(x0 if side < 0 else x1, TOP + (slot + 1) * SLOT), side

        used: dict[str, list[int]] = {}
        for ch in self.cfg.channels:
            for e in (ch.electrode, ch.minus if ch.minus_is_electrode else ""):
                if e:
                    used.setdefault(e, []).append(ch.ai)

        # the device
        p.setPen(QPen(QColor(30, 30, 30), 1.5))
        p.setBrush(QColor(255, 255, 255))
        dev = QRectF(x0, TOP, DEV_W, (half + 1) * SLOT)
        p.drawRect(dev)
        f = QFont(base)
        f.setPointSizeF(10)
        f.setBold(True)
        p.setFont(f)
        p.drawText(QRectF(x0, TOP + 6, DEV_W, 20), Qt.AlignCenter, self.cfg.experiment.device_name or "Device")
        p.setFont(base)
        p.setPen(QColor(130, 130, 130))
        p.drawText(QRectF(x0, dev.bottom() - 34, DEV_W, 30), Qt.AlignCenter | Qt.TextWordWrap,
                   f"{n} pads, logical order")
        if off:
            p.drawText(QRectF(x0 + 60, TOP + (half + 2) * SLOT - 8, 120, 16), Qt.AlignLeft | Qt.AlignVCenter,
                       "← off-chip contacts")

        # pads
        for name in layout:
            pt, side = pad_point(name)
            bonded = name in used
            r = QRectF(pt.x() - (0 if side < 0 else PAD), pt.y() - PAD / 2, PAD, PAD)
            p.setPen(QPen(QColor(130, 60, 170) if bonded else QColor(195, 195, 195), 1.2))
            p.setBrush(electrode_color(name) if bonded else QColor(250, 250, 250))
            p.drawRect(r)
            p.setPen(QColor(40, 40, 40) if bonded else QColor(175, 175, 175))
            lr = QRectF(pt.x() + (PAD + 2 if side < 0 else -PAD - 42), pt.y() - 8, 40, 16)
            p.drawText(lr, (Qt.AlignLeft if side < 0 else Qt.AlignRight) | Qt.AlignVCenter, name)

        # channels: each in the slot of its pad, or the nearest free slot on that side
        taken: dict[int, set[int]] = {-1: set(), 1: set()}
        self._glyphs = []
        for ch in self.cfg.channels:
            if not ch.electrode or ch.electrode not in layout:
                continue
            side, slot = layout[ch.electrode]
            for d in sorted(range(-40, 41), key=abs):
                s = slot + d
                if s >= 0 and s not in taken[side]:
                    taken[side].add(s)
                    break
            pad_pt, _ = pad_point(ch.electrode)
            minus_pt = pad_point(ch.minus)[0] if ch.minus_is_electrode and ch.minus in layout else None
            self._channel(p, ch, pad_pt, side, TOP + (s + 1) * SLOT, minus_pt, base)

        idle = [c.ai for c in self.cfg.channels if not c.electrode]
        if idle:
            p.setPen(QColor(120, 120, 120))
            p.drawText(QRectF(8, self.height() - 22, self.width() - 16, 18), Qt.AlignLeft | Qt.AlignVCenter,
                       "No pad: " + ", ".join(f"AI {a}" for a in idle))
        p.end()

    def _channel(self, p: QPainter, ch, pad: QPointF, side: int, y: float, minus_pt, font: QFont):
        out = QPointF(side, 0)
        base_c = QPointF(pad.x() + side * (PAD + 34), y)
        tip = base_c + out * TRI
        selected = ch.ai == self.selected_ai
        exc = any(exception(ch, k) for k in ("kh", "minus", "ext_gain"))
        pad_edge = QPointF(pad.x() + side * PAD, pad.y())

        p.setPen(QPen(RED, 1.4))
        p.setBrush(Qt.NoBrush)
        if ch.kh is None:
            path = QPainterPath(pad_edge)
            path.cubicTo(pad_edge + out * 14, tip - out * 14, tip)
            p.drawPath(path)
            self._label(p, ch, tip, side, font, selected, exc, direct=True)
            return

        plus = QPointF(base_c.x(), y - 6)
        minus = QPointF(base_c.x(), y + 6)
        path = QPainterPath(pad_edge)
        path.cubicTo(pad_edge + out * 14, plus - out * 14, plus)
        p.drawPath(path)
        if minus_pt is not None:  # a second pad on the - input: dashed
            m_edge = QPointF(minus_pt.x() + side * PAD, minus_pt.y())
            path = QPainterPath(m_edge)
            path.cubicTo(m_edge + out * 22, minus - out * 22, minus)
            p.setPen(QPen(RED, 1.2, Qt.DashLine))
            p.drawPath(path)
        if ch.type == "U" and ch.shunt != "Open":  # R_sh between - and +
            p.setPen(QPen(RED, 1, Qt.DotLine))
            p.drawLine(QPointF(base_c.x() - side * 5, y - 6), QPointF(base_c.x() - side * 5, y + 6))
        tri = QPolygonF([QPointF(base_c.x(), y - 11), QPointF(base_c.x(), y + 11), tip])
        p.setPen(QPen(BLUE if selected else RED, 2.2 if selected else 1.4))
        p.setBrush(QColor(255, 236, 236) if ch.input != "OFF" else QColor(240, 240, 240))
        p.drawPolygon(tri)
        f = QFont(font)
        f.setPointSizeF(6.5)
        p.setFont(f)
        p.setPen(RED)
        p.drawText(QRectF(base_c.x() + (2 if side > 0 else -12), y - 13, 10, 10), Qt.AlignCenter, "+")
        p.drawText(QRectF(base_c.x() + (2 if side > 0 else -12), y + 2, 10, 10), Qt.AlignCenter, "−")
        p.setFont(font)
        self._label(p, ch, tip, side, font, selected, exc, direct=False)

    def _label(self, p: QPainter, ch, tip: QPointF, side: int, font: QFont, selected, exc, direct):
        name = ch.name or ch.type
        line1 = f"AI {ch.ai}  {name}" + (f"  ×{ch.ext_gain:g}" if ch.ext_gain != 1 else "")
        if direct:
            line2 = "no KH, straight to ADC"
        else:
            ref = reference_text(ch).replace(" ", "")
            line2 = f"{kh_label(ch.kh)} {ch.input}" + (f" ← {ref}" if ch.input == "DIFF" else "")
        w, h = SIDE - 80, 26
        r = QRectF(tip.x() + 5 if side > 0 else tip.x() - 5 - w, tip.y() - h / 2, w, h)
        align = (Qt.AlignLeft if side > 0 else Qt.AlignRight) | Qt.AlignVCenter
        f = QFont(font)
        f.setBold(True)
        p.setFont(f)
        p.setPen(EXC if exc else (BLUE if selected else QColor(30, 30, 30)))
        p.drawText(r, align, f"{line1}\n{line2}")
        p.setFont(font)
        tip_text = (f"AI {ch.ai}  {name}" + (f"  role {ch.role}" if ch.role else "")
                    + f"\n+ pad {ch.electrode}"
                    + ("" if direct else f"   − {reference_text(ch)}   {kh_label(ch.kh)} {ch.input}"
                       f"  gain {ch.kh_gain}  R_sh {ch.shunt}  {ch.couple}  filter {ch.filter}")
                    + (f"\nexternal gain {ch.ext_gain:g}" if ch.ext_gain != 1 else ""))
        for k in ("kh", "minus", "ext_gain"):
            why = exception(ch, k)
            if why:
                tip_text += f"\n{why}"
        self._glyphs.append((r.united(QRectF(tip.x() - 30 * side - 6, tip.y() - 12, 36, 24)), ch.ai, tip_text))
