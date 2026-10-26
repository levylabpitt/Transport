"""Wiring view: one strip per AI showing the signal chain, plus the AO chains.

Electrode boxes are coloured by electrode name, so a teed electrode shows
up in the same colour on every row it feeds.
"""

from __future__ import annotations

import hashlib

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QWidget

from .model import MINUS_AO, MINUS_GND, MINUS_NC, Config, kh_label

STRIP_H = 50
OUT_H = 34
PAD = 8

COL_MINUS = 8
COL_PLUS = 8
BOX_E_W = 84
COL_KH = 118
KH_W = 158
COL_EXT = 298
EXT_W = 58
COL_AI = 378
AI_W = 178
WIDTH = COL_AI + AI_W + 8


def electrode_color(name: str) -> QColor:
    h = int(hashlib.md5(name.encode()).hexdigest()[:6], 16)
    return QColor.fromHsv(h % 360, 70, 245)


class WiringView(QWidget):
    rowClicked = Signal(int)  # AI number

    def __init__(self, cfg: Config):
        super().__init__()
        self.cfg = cfg
        self.selected_ai: int | None = None
        self.setMouseTracking(True)
        self.setMinimumWidth(WIDTH)

    def set_config(self, cfg: Config) -> None:
        self.cfg = cfg
        self.updateGeometry()
        self.update()

    def select(self, ai: int | None) -> None:
        self.selected_ai = ai
        self.update()

    def _outputs_shown(self):
        return [o for o in self.cfg.outputs if o.name or o.gain != 1 or o.electrode]

    def sizeHint(self) -> QSize:
        h = PAD + len(self.cfg.channels) * STRIP_H + 30 + len(self._outputs_shown()) * OUT_H + PAD
        return QSize(WIDTH, h)

    def minimumSizeHint(self) -> QSize:
        return self.sizeHint()

    def mousePressEvent(self, ev):
        row = int((ev.position().y() - PAD) // STRIP_H)
        if 0 <= row < len(self.cfg.channels):
            self.rowClicked.emit(self.cfg.channels[row].ai)

    # ---- drawing -------------------------------------------------------

    def _box(self, p: QPainter, r: QRectF, lines: list[str], fill: QColor, dashed=False, bold_first=True):
        pen = QPen(QColor(90, 90, 90), 1, Qt.DashLine if dashed else Qt.SolidLine)
        p.setPen(pen)
        p.setBrush(fill)
        p.drawRoundedRect(r, 5, 5)
        p.setPen(QColor(30, 30, 30))
        f = p.font()
        n = len(lines)
        for i, text in enumerate(lines):
            fb = QFont(f)
            fb.setBold(bold_first and i == 0)
            p.setFont(fb)
            lr = QRectF(r.x() + 4, r.y() + r.height() * i / n, r.width() - 8, r.height() / n)
            p.drawText(lr, Qt.AlignCenter, text)
        p.setFont(f)

    def _wire(self, p: QPainter, a: QPointF, b: QPointF, color=QColor(60, 60, 60), dashed=False):
        p.setPen(QPen(color, 1.4, Qt.DashLine if dashed else Qt.SolidLine))
        path = QPainterPath(a)
        mx = (a.x() + b.x()) / 2
        path.cubicTo(QPointF(mx, a.y()), QPointF(mx, b.y()), b)
        p.setBrush(Qt.NoBrush)
        p.drawPath(path)

    def paintEvent(self, ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.fillRect(self.rect(), QColor(252, 252, 250))
        f = p.font()
        f.setPointSizeF(8.5)
        p.setFont(f)
        y = PAD
        for ch in self.cfg.channels:
            self._strip(p, ch, y)
            y += STRIP_H
        outs = self._outputs_shown()
        if outs:
            p.setPen(QColor(80, 80, 80))
            p.drawText(QRectF(COL_PLUS, y + 6, 300, 18), Qt.AlignLeft | Qt.AlignVCenter, "Outputs")
            y += 30
            for o in outs:
                self._out_strip(p, o, y)
                y += OUT_H
        p.end()

    def _strip(self, p: QPainter, ch, y: float):
        idle = ch.type == "n.c." and not ch.electrode
        if ch.ai == self.selected_ai:
            p.fillRect(QRectF(0, y, self.width(), STRIP_H), QColor(225, 236, 255))
        elif ch.ai % 2 == 0:
            p.fillRect(QRectF(0, y, self.width(), STRIP_H), QColor(245, 245, 242))
        p.setOpacity(0.45 if idle else 1.0)
        top = QRectF(COL_PLUS, y + 4, BOX_E_W, 19)
        bot = QRectF(COL_MINUS, y + 27, BOX_E_W, 19)
        kh = QRectF(COL_KH, y + 4, KH_W, 42)
        ai = QRectF(COL_AI, y + 4, AI_W, 42)

        out = self.cfg.output(ch.ao) if ch.ao is not None else None
        amp = f" (x{out.gain:g})" if out and out.gain != 1 and ch.type == "U" and ch.minus == MINUS_AO else ""
        if ch.electrode:
            self._box(p, top, [f"+  {ch.electrode}{amp}"], electrode_color(ch.electrode), bold_first=False)
        else:
            self._box(p, top, ["+  (none)"], QColor(240, 240, 240), dashed=True, bold_first=False)

        if ch.kh is not None:
            unused = ch.input in ("SE+", "OFF") and not ch.minus_is_electrode
            if unused:
                label, fill = "-  not used", QColor(245, 245, 245)
            elif ch.minus == MINUS_AO:
                label, fill = (f"-  AO {ch.ao}" if ch.ao else "-  AO ?"), QColor(225, 240, 225)
            elif ch.minus == MINUS_GND:
                label, fill = "-  GND", QColor(230, 230, 230)
            elif ch.minus == MINUS_NC:
                label, fill = "-  n.c.", QColor(245, 245, 245)
            else:
                label, fill = f"-  {ch.minus}", electrode_color(ch.minus)
            self._box(p, bot, [label], fill, dashed=unused or ch.minus == MINUS_NC, bold_first=False)
            mode = ch.input if self.cfg.kh_override == "No Selection" else (
                "OFF" if self.cfg.kh_override == "All Ground" else "DIFF")
            shunt = f"shunt {ch.shunt}" if ch.shunt != "Open" else "no shunt"
            self._box(p, kh, [f"{kh_label(ch.kh)}   {mode}   x{ch.kh_gain}",
                              f"{shunt}  {ch.couple}  filter {ch.filter}"],
                      QColor(214, 240, 232) if mode != "OFF" else QColor(232, 232, 232))
            self._wire(p, QPointF(top.right(), top.center().y()), QPointF(kh.left(), kh.top() + 10))
            if not unused and ch.minus != MINUS_NC:
                self._wire(p, QPointF(bot.right(), bot.center().y()), QPointF(kh.left(), kh.bottom() - 10))
            src = QPointF(kh.right(), kh.center().y())
        else:
            self._box(p, kh, ["no KH", "direct to AI"], QColor(248, 248, 248), dashed=True)
            src = QPointF(top.right(), top.center().y())

        if ch.ext_gain != 1:
            ext = QRectF(COL_EXT, y + 12, EXT_W, 26)
            self._box(p, ext, [f"x{ch.ext_gain:g}"], QColor(250, 222, 210))
            self._wire(p, src, QPointF(ext.left(), ext.center().y()))
            src = QPointF(ext.right(), ext.center().y())
        self._wire(p, src, QPointF(ai.left(), ai.center().y()))

        name = ch.name or ch.type
        role = f"  role {ch.role}" if ch.role else ""
        self._box(p, ai, [f"AI {ch.ai}   {name}", f"lock-in gain {ch.lockin_gain:g}{role}"], QColor(232, 232, 250))
        p.setOpacity(1.0)

    def _out_strip(self, p: QPainter, o, y: float):
        users = [c for c in self.cfg.channels
                 if c.ao == o.ao and c.kh is not None and c.minus == MINUS_AO and c.type == "U"]
        x = COL_PLUS
        ao = QRectF(x, y + 4, 104, 26)
        self._box(p, ao, [f"AO {o.ao}  {o.name}".strip()], QColor(225, 240, 225))
        src = QPointF(ao.right(), ao.center().y())
        x = ao.right() + 18
        if users:
            c = users[0]
            r = QRectF(x, y + 4, 150, 26)
            self._box(p, r, [f"{kh_label(c.kh)} shunt {c.shunt} (AI {c.ai})"], QColor(214, 240, 232), bold_first=False)
            self._wire(p, src, QPointF(r.left(), r.center().y()))
            src, x = QPointF(r.right(), r.center().y()), r.right() + 18
        if o.gain != 1:
            amp = QRectF(x, y + 4, 76, 26)
            self._box(p, amp, [f"amp x{o.gain:g}"], QColor(250, 222, 210))
            self._wire(p, src, QPointF(amp.left(), amp.center().y()))
            src, x = QPointF(amp.right(), amp.center().y()), amp.right() + 18
        target = o.electrode or (users[0].electrode if users else "")
        if target:
            e = QRectF(x, y + 4, 96, 26)
            self._box(p, e, [target], electrode_color(target), bold_first=False)
            self._wire(p, src, QPointF(e.left(), e.center().y()))
