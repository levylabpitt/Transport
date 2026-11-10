"""Wiring view: one strip per channel, drawn as the cables run.

Left to right: the device pads, the Krohn-Hite channel (with its shunt drawn
between the - and + inputs), any external gain stage, the lock-in card (AI n
and the AO that feeds the KH - input, which sit on the same hardware), and
what the channel measures. Colours are the channel table's group colours;
electrodes get warm colours by name, so a teed electrode shows up in the same
colour on every row it feeds.
"""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen, QPolygonF
from PySide6.QtWidgets import QWidget

from .model import MINUS_AO, MINUS_GND, MINUS_NC, Config, kh_label
from .palette import FILL, border, electrode_color

STRIP_H = 60
OUT_H = 34
PAD = 8

PAD_X, PAD_W = 8, 64         # device pads
AMP_X = 78                   # amplifier between the KH + input and the pad
KH_X, KH_W = 112, 186
EXT_X, EXT_W = 302, 42
LI_X, LI_W = 348, 112        # lock-in card: AI row on top, AO row below
MEAS_X, MEAS_W = 468, 74
TERM_R = 5.5                 # KH terminal circle, with its sign inside
LEGEND_H = 92
WIDTH = MEAS_X + MEAS_W + 8

GREY = QColor(244, 244, 244)
WIRE = QColor(60, 60, 60)

# Kept for callers that colour electrodes outside the view.
__all__ = ["WiringDrawing", "WiringView", "electrode_color"]


class WiringDrawing:
    """Draws the diagram onto any QPainter, so the plain widget below and the
    QGraphicsScene trial (wiringscene.py) look the same."""

    def __init__(self, cfg: Config | None = None, **_):
        # cfg may be None: PySide's QWidget.__init__ calls this cooperatively, before WiringView sets it.
        self.cfg = cfg
        self.selected_ai: int | None = None
        self.ai_daq: list[dict] = []  # getInputDAQ / getOutputDAQ, once read
        self.ao_daq: list[dict] = []

    def _rows(self):
        return [c for c in self.cfg.channels if not (c.type == "n.c." and not c.electrode)]

    def _idle(self) -> str:
        idle = [c.ai for c in self.cfg.channels if c.type == "n.c." and not c.electrode]
        if not idle:
            return ""
        spans, start = [], idle[0]
        for prev, cur in zip(idle, idle[1:] + [None]):
            if cur != prev + 1:
                spans.append(f"{start}" if start == prev else f"{start}-{prev}")
                start = cur
        return f"AI {', '.join(spans)}: not connected"

    @staticmethod
    def _uses_ao(ch) -> bool:
        """The row's cable runs from its AO: a Drive row, or a KH row whose - input (used) is the AO."""
        return ch.ao is not None and (ch.direct or (
            ch.kh is not None and ch.minus == MINUS_AO and ch.input == "DIFF"))

    def _other_outputs(self):
        """Outputs with settings that no row draws (no row's cable uses that AO)."""
        used = {c.ao for c in self.cfg.channels if self._uses_ao(c)}
        return [o for o in self.cfg.outputs
                if o.ao not in used and (o.name or o.gain != 1 or o.offset or o.electrode)]

    def footer_height(self) -> float:
        """Below the strips: the idle note, outputs no row uses, and the legend."""
        outs = self._other_outputs()
        return (24 if self._idle() else 0) + ((30 + len(outs) * OUT_H) if outs else 0) + LEGEND_H

    def total_height(self) -> float:
        return PAD + len(self._rows()) * STRIP_H + self.footer_height() + PAD

    # ---- drawing helpers -------------------------------------------------

    def _box(self, p: QPainter, r: QRectF, lines: list[str], fill: QColor, dashed=False, bold_first=True,
             align=Qt.AlignCenter):
        p.setPen(QPen(border(fill) if not dashed else QColor(140, 140, 140), 1,
                      Qt.DashLine if dashed else Qt.SolidLine))
        p.setBrush(fill)
        p.drawRoundedRect(r, 5, 5)
        self._text(p, r, lines, bold_first, align)

    def _text(self, p: QPainter, r: QRectF, lines: list[str], bold_first=True, align=Qt.AlignCenter,
              color=QColor(30, 30, 30)):
        p.setPen(color)
        f = p.font()
        n = len(lines)
        for i, text in enumerate(lines):
            fb = QFont(f)
            fb.setBold(bold_first and i == 0)
            p.setFont(fb)
            lr = QRectF(r.x() + 5, r.y() + r.height() * i / n, r.width() - 10, r.height() / n)
            p.drawText(lr, align | Qt.AlignVCenter, text)
        p.setFont(f)

    def _wire(self, p: QPainter, a: QPointF, b: QPointF, dashed=False):
        """Square-cornered cable from a to b: across, down or up halfway, across."""
        p.setPen(QPen(WIRE, 1.4, Qt.DashLine if dashed else Qt.SolidLine))
        path = QPainterPath(a)
        if abs(a.y() - b.y()) > 0.5:
            mx = round((a.x() + b.x()) / 2)
            path.lineTo(mx, a.y())
            path.lineTo(mx, b.y())
        path.lineTo(b)
        p.setBrush(Qt.NoBrush)
        p.drawPath(path)

    def _poly(self, p: QPainter, pts: list[QPointF]):
        p.setPen(QPen(WIRE, 1.4))
        p.setBrush(Qt.NoBrush)
        path = QPainterPath(pts[0])
        for q in pts[1:]:
            path.lineTo(q)
        p.drawPath(path)

    def _amp(self, p: QPainter, tip_left: bool, x: float, y: float, gain: float, offset: float = 0.0):
        """Amplifier triangle 22 wide centred on (x, y); the signal leaves at the tip."""
        w, h = 22, 18
        if tip_left:
            tri = [QPointF(x + w / 2, y - h / 2), QPointF(x + w / 2, y + h / 2), QPointF(x - w / 2, y)]
        else:
            tri = [QPointF(x - w / 2, y - h / 2), QPointF(x - w / 2, y + h / 2), QPointF(x + w / 2, y)]
        fill = FILL["Other"]
        p.setPen(QPen(border(fill), 1.2))
        p.setBrush(fill)
        p.drawPolygon(QPolygonF(tri))
        label = f"x{gain:g}" + (f"  {offset:+g}" if offset else "")
        p.setPen(QColor(120, 60, 20))
        p.drawText(QRectF(x - 40, y - h / 2 - 13, 80, 12), Qt.AlignCenter, label)

    def _resistor(self, p: QPainter, x: float, y0: float, y1: float, label: str):
        """Vertical zigzag between y0 and y1 at x, labelled to its right."""
        p.setPen(QPen(WIRE, 1.3))
        p.setBrush(Qt.NoBrush)
        lead = (y1 - y0) * 0.22
        path = QPainterPath(QPointF(x, y0))
        path.lineTo(x, y0 + lead)
        n, top, bot = 6, y0 + lead, y1 - lead
        for i in range(1, n + 1):
            path.lineTo(x + (4 if i % 2 else -4) if i < n else x, top + (bot - top) * i / n)
        path.lineTo(x, y1)
        p.drawPath(path)
        p.setPen(QColor(40, 90, 60))
        p.drawText(QRectF(x + 6, (y0 + y1) / 2 - 7, 40, 14), Qt.AlignLeft | Qt.AlignVCenter, label)

    def _ground(self, p: QPainter, x: float, y: float):
        p.setPen(QPen(WIRE, 1.3))
        for i, half in enumerate((7, 4.5, 2)):
            p.drawLine(QPointF(x - half, y + 3 * i), QPointF(x + half, y + 3 * i))

    def _terminal(self, p: QPainter, pt: QPointF, sign: str, used=True):
        """A KH input or output: a circle with its sign inside, so wires never cover the label."""
        p.setPen(QPen(border(FILL["Krohn-Hite"]) if used else QColor(170, 170, 170), 1))
        p.setBrush(QColor(255, 255, 255))
        p.drawEllipse(pt, TERM_R, TERM_R)
        p.save()
        f = QFont(p.font())
        f.setPointSizeF(7.5)
        f.setBold(True)
        p.setFont(f)
        p.setPen(QColor(30, 30, 30) if used else QColor(160, 160, 160))
        p.drawText(QRectF(pt.x() - TERM_R, pt.y() - TERM_R - 0.5, 2 * TERM_R, 2 * TERM_R), Qt.AlignCenter, sign)
        p.restore()

    def _card(self, ch) -> str:
        """The lock-in card name for this row (PXI1Slot2), when the lock-in reported it."""
        n = ch.ai if not ch.direct else ch.ao
        daq = self.ai_daq if not ch.direct else self.ao_daq
        if n and 1 <= n <= len(daq):
            return str(daq[n - 1].get("Channels", "")).split("/")[0]
        return ""

    # ---- hit areas (the QGraphicsScene trial makes these clickable) -------

    def hotspots(self, ch) -> list[tuple[QRectF, str, str]]:
        """(rect in strip coordinates, channel-table column key, tooltip) for each part of
        the strip that maps onto one table cell. Mirrors the geometry in _strip."""
        plus_y, minus_y, lane_y = 16, 40, STRIP_H - 5
        kh = QRectF(KH_X, 5, KH_W, STRIP_H - 16)
        li = QRectF(LI_X, 4, LI_W, STRIP_H - 8)
        ai_row = QRectF(li.x(), li.y(), li.width(), li.height() / 2)
        ao_row = QRectF(li.x(), li.center().y(), li.width(), li.height() / 2)
        meas = QRectF(MEAS_X, 9, MEAS_W, STRIP_H - 18)
        out = self.cfg.output(ch.ao) if ch.ao is not None else None
        spots = [(QRectF(PAD_X, plus_y - 10, PAD_W, 20), "electrode", f"Electrode: {ch.electrode or '(none)'}"),
                 (QRectF(meas.x(), meas.y(), meas.width(), meas.height() / 2), "type", f"Type: {ch.type}"),
                 (QRectF(meas.x(), meas.center().y(), meas.width(), meas.height() / 2), "mode",
                  f"Mode: {ch.mode or '(none)'}")]
        if not ch.direct:
            spots.append((ai_row, "ai", f"AI {ch.ai}"))
        if self._uses_ao(ch):
            half = ao_row.width() / 2
            spots.append((QRectF(ao_row.x(), ao_row.y(), half, ao_row.height()), "ao", f"AO {ch.ao}"))
            spots.append((QRectF(ao_row.x() + half, ao_row.y(), half, ao_row.height()), "out_gain",
                          f"AO {ch.ao} output gain x{out.gain:g}" if out else "Output gain"))
            if out is not None and (out.gain != 1 or out.offset):
                if ch.direct:
                    ax = (PAD_X + PAD_W + 18 + KH_X) / 2 + 60
                    spots.append((QRectF(ax - 13, lane_y - 22, 26, 30), "out_gain", f"Output gain x{out.gain:g}"))
                else:
                    spots.append((QRectF(AMP_X - 2, plus_y - 22, 26, 32), "out_gain", f"Output gain x{out.gain:g}"))
        if ch.direct:
            return spots
        if ch.kh is None:
            spots.append((kh, "kh", "No Krohn-Hite: the pad goes straight to the AI"))
        else:
            text = QRectF(kh.left() + 60, kh.top(), kh.width() - 90, kh.height())
            spots += [
                (QRectF(kh.left(), kh.top(), 54, kh.height()), "kh", f"KH channel {kh_label(ch.kh)}"),
                (QRectF(text.x(), text.y(), text.width(), text.height() / 2), "kh_gain", f"KH gain x{ch.kh_gain}"),
                (QRectF(text.x(), text.center().y(), 24, text.height() / 2), "couple", f"Coupling {ch.couple}"),
                (QRectF(text.x() + 24, text.center().y(), text.width() - 24, text.height() / 2), "filter",
                 f"Filter {ch.filter}"),
                (QRectF(PAD_X, minus_y - 10, KH_X - PAD_X - 4, 20), "minus", "KH \u2212 input"),
            ]
            if ch.type == "U":
                spots.append((QRectF(kh.left() + 28, plus_y + 2, 30, minus_y - plus_y - 4), "shunt",
                              f"Shunt {ch.shunt}"))
        if ch.ext_gain != 1:
            spots.append((QRectF(EXT_X, ai_row.center().y() - 11, EXT_W, 22), "ext_gain",
                          f"External gain x{ch.ext_gain:g}"))
        return spots

    # ---- painting --------------------------------------------------------

    @staticmethod
    def prepare(p: QPainter) -> None:
        p.setRenderHint(QPainter.Antialiasing)
        f = p.font()
        f.setPointSizeF(8.5)
        p.setFont(f)

    def paint_all(self, p: QPainter) -> None:
        self.prepare(p)
        y = PAD
        for ch in self._rows():
            self._strip(p, ch, y)
            y += STRIP_H
        self._footer(p, y)

    def _footer(self, p: QPainter, y: float) -> None:
        idle = self._idle()
        if idle:
            p.setPen(QColor(120, 120, 120))
            p.drawText(QRectF(PAD_X, y + 2, WIDTH, 20), Qt.AlignLeft | Qt.AlignVCenter, idle)
            y += 24
        outs = self._other_outputs()
        if outs:
            p.setPen(QColor(80, 80, 80))
            p.drawText(QRectF(PAD_X, y + 6, 400, 18), Qt.AlignLeft | Qt.AlignVCenter,
                       "Outputs set up but not cabled to any channel")
            y += 30
            for o in outs:
                self._out_strip(p, o, y)
                y += OUT_H
        self._legend(p, y + 10)

    def _legend(self, p: QPainter, y: float):
        """What the colours and symbols mean."""
        p.setPen(QPen(QColor(200, 200, 200), 1))
        p.drawLine(QPointF(PAD_X, y), QPointF(WIDTH - 8, y))
        p.setPen(QColor(80, 80, 80))
        p.drawText(QRectF(PAD_X, y + 4, 200, 16), Qt.AlignLeft | Qt.AlignVCenter, "Legend")
        row1, row2, row3 = y + 30, y + 52, y + 74

        def swatch(x, yc, fill, text, dashed=False, w=26):
            self._box(p, QRectF(x, yc - 7, w, 14), [], fill, dashed=dashed)
            p.setPen(QColor(50, 50, 50))
            p.drawText(QRectF(x + w + 5, yc - 8, 120, 16), Qt.AlignLeft | Qt.AlignVCenter, text)

        x = PAD_X
        for key, text in (("Krohn-Hite", "Krohn-Hite"), ("Lock-in", "Lock-in card"),
                          ("Measurement", "Measured as"), ("Other", "Gain stage")):
            swatch(x, row1, FILL[key], text)
            x += 112
        swatch(x, row1, GREY, "Not used", dashed=True)

        for i, name in enumerate(("1", "2", "3")):
            self._box(p, QRectF(PAD_X + i * 14, row2 - 7, 12, 14), [], electrode_color(name))
        p.setPen(QColor(50, 50, 50))
        p.drawText(QRectF(PAD_X + 47, row2 - 8, WIDTH, 16), Qt.AlignLeft | Qt.AlignVCenter,
                   "Device pad: one colour per electrode, so a teed pad has the same colour on every row")

        x = PAD_X + 8
        self._resistor(p, x, row3 - 8, row3 + 8, "")
        p.setPen(QColor(50, 50, 50))
        p.drawText(QRectF(x + 10, row3 - 8, 90, 16), Qt.AlignLeft | Qt.AlignVCenter, "Shunt (R_sh)")
        x += 112
        tri = [QPointF(x - 9, row3 - 7), QPointF(x - 9, row3 + 7), QPointF(x + 9, row3)]
        p.setPen(QPen(border(FILL["Other"]), 1.2))
        p.setBrush(FILL["Other"])
        p.drawPolygon(QPolygonF(tri))
        p.setPen(QColor(50, 50, 50))
        p.drawText(QRectF(x + 14, row3 - 8, 90, 16), Qt.AlignLeft | Qt.AlignVCenter, "Amplifier")
        x += 112
        self._ground(p, x, row3 - 3)
        p.setPen(QColor(50, 50, 50))
        p.drawText(QRectF(x + 12, row3 - 8, 60, 16), Qt.AlignLeft | Qt.AlignVCenter, "Ground")
        x += 80
        self._terminal(p, QPointF(x, row3), "+")
        p.setPen(QColor(50, 50, 50))
        p.drawText(QRectF(x + 10, row3 - 8, 160, 16), Qt.AlignLeft | Qt.AlignVCenter, "KH input (grey: not used)")

    def _strip(self, p: QPainter, ch, y: float):
        idle = ch.type == "n.c." and not ch.electrode
        if ch.ai == self.selected_ai:
            p.fillRect(QRectF(0, y, WIDTH, STRIP_H), QColor(225, 236, 255))
        elif ch.ai % 2 == 0:
            p.fillRect(QRectF(0, y, WIDTH, STRIP_H), QColor(246, 246, 243))
        p.setOpacity(0.45 if idle else 1.0)

        plus_y, minus_y, lane_y = y + 16, y + 40, y + STRIP_H - 5
        pad_top = QRectF(PAD_X, plus_y - 10, PAD_W, 20)
        kh = QRectF(KH_X, y + 5, KH_W, STRIP_H - 16)
        li = QRectF(LI_X, y + 4, LI_W, STRIP_H - 8)
        ai_row = QRectF(li.x(), li.y(), li.width(), li.height() / 2)
        ao_row = QRectF(li.x(), li.center().y(), li.width(), li.height() / 2)
        meas = QRectF(MEAS_X, y + 9, MEAS_W, STRIP_H - 18)
        out = self.cfg.output(ch.ao) if ch.ao is not None else None

        # Device pad on the + side.
        if ch.electrode:
            self._box(p, pad_top, [ch.electrode], electrode_color(ch.electrode), bold_first=False)
        else:
            self._box(p, pad_top, ["(none)"], GREY, dashed=True, bold_first=False)

        # Lock-in card: AI on top, AO below, one box because they are the same hardware.
        uses_ao = self._uses_ao(ch)
        p.setPen(QPen(border(FILL["Lock-in"]), 1))
        p.setBrush(FILL["Lock-in"])
        p.drawRoundedRect(li, 5, 5)
        p.setPen(QPen(border(FILL["Lock-in"]), 0.8, Qt.DotLine))
        p.drawLine(QPointF(li.left() + 6, li.center().y()), QPointF(li.right() - 6, li.center().y()))
        card = self._card(ch)
        if card:
            p.setPen(QColor(90, 100, 140))
            sf = QFont(p.font())
            sf.setPointSizeF(7)
            p.save()
            p.setFont(sf)
            p.drawText(ai_row.adjusted(0, 1, -6, 0), Qt.AlignRight | Qt.AlignTop, card)
            p.restore()
        ai_used = not ch.direct
        self._text(p, ai_row, [f"AI {ch.ai}" + ("" if ai_used else "  unused")], align=Qt.AlignLeft,
                   color=QColor(30, 30, 30) if ai_used else QColor(140, 140, 140))
        if uses_ao:
            ao_label = f"AO {ch.ao}" + (f"  {out.name}" if out and out.name else "")
            self._text(p, ao_row, [ao_label], bold_first=True, align=Qt.AlignLeft)
        else:
            self._text(p, ao_row, ["AO not used"], bold_first=False, align=Qt.AlignLeft,
                       color=QColor(150, 150, 150))

        # What the row measures.
        if ch.direct:
            lines = [ch.name or "drives pad", ch.mode]
        else:
            lines = [ch.name or ch.type] + ([ch.mode] if ch.mode else [])
        self._box(p, meas, lines, FILL["Measurement"])

        if ch.direct:
            self._drive_strip(p, ch, out, pad_top, kh, ao_row, lane_y)
        elif ch.kh is not None:
            self._kh_strip(p, ch, out, y, pad_top, kh, ao_row, ai_row, plus_y, minus_y, lane_y)
        else:
            # The wire crosses the top half, so the label sits in the bottom half.
            self._box(p, kh, ["", "no Krohn-Hite"], GREY, dashed=True, bold_first=False)
            self._to_ai(p, ch, y, QPointF(pad_top.right(), pad_top.center().y()), ai_row)
        if ai_used:
            self._wire(p, QPointF(li.right(), ai_row.center().y()), QPointF(meas.left(), meas.center().y()),
                       dashed=True)
        p.setOpacity(1.0)

    def _to_ai(self, p, ch, y, src: QPointF, ai_row: QRectF):
        """From src through the external gain stage, if any, into the AI."""
        if ch.ext_gain != 1:
            ext = QRectF(EXT_X, ai_row.center().y() - 11, EXT_W, 22)
            self._box(p, ext, [f"x{ch.ext_gain:g}"], FILL["Other"], bold_first=False)
            self._wire(p, src, QPointF(ext.left(), ext.center().y()))
            src = QPointF(ext.right(), ext.center().y())
        self._wire(p, src, QPointF(ai_row.left(), ai_row.center().y()))

    def _kh_strip(self, p, ch, out, y, pad_top, kh, ao_row, ai_row, plus_y, minus_y, lane_y):
        mode = ch.input if self.cfg.kh_override == "No Selection" else (
            "OFF" if self.cfg.kh_override == "All Ground" else "DIFF")
        self._box(p, kh, [], FILL["Krohn-Hite"] if mode != "OFF" else GREY)
        t_plus, t_minus = QPointF(kh.left() + 11, plus_y), QPointF(kh.left() + 11, minus_y)
        t_out = QPointF(kh.right() - 11, kh.center().y())
        text = QRectF(kh.left() + 60, kh.top(), kh.width() - 60 - 30, kh.height())
        self._text(p, text, [f"{kh_label(ch.kh)}  {mode}  x{ch.kh_gain}", f"{ch.couple}  filter {ch.filter}"],
                   align=Qt.AlignLeft)
        uses_minus = ch.input == "DIFF" or ch.minus_is_electrode
        if ch.type == "U" and ch.shunt != "Open":
            rx = t_plus.x() + 26
            self._resistor(p, rx, plus_y + 4, minus_y - 4, ch.shunt)
            self._poly(p, [t_plus + QPointF(TERM_R, 0), QPointF(rx, plus_y), QPointF(rx, plus_y + 4)])
            self._poly(p, [t_minus + QPointF(TERM_R, 0), QPointF(rx, minus_y), QPointF(rx, minus_y - 4)])
        self._terminal(p, t_plus, "+")
        self._terminal(p, t_minus, "−", used=uses_minus)
        out_on = mode != "OFF"
        self._terminal(p, t_out, "", used=out_on)
        p.setPen(QColor(60, 90, 70) if out_on else QColor(160, 160, 160))
        p.drawText(QRectF(t_out.x() - TERM_R - 26, t_out.y() - 7, 22, 14), Qt.AlignRight | Qt.AlignVCenter, "out")

        # + input: pad -> (amplifier, for a U row sourced from an amplified AO) -> KH +.
        pad_out = QPointF(pad_top.right(), pad_top.center().y())
        amplified = ch.type == "U" and ch.minus == MINUS_AO and out is not None and (out.gain != 1 or out.offset)
        if amplified:
            self._amp(p, True, AMP_X + 11, plus_y, out.gain, out.offset)
            self._poly(p, [pad_out, QPointF(AMP_X, plus_y)])
            self._poly(p, [QPointF(AMP_X + 22, plus_y), t_plus - QPointF(TERM_R, 0)])
        else:
            self._poly(p, [pad_out, t_plus - QPointF(TERM_R, 0)])

        # - input.
        if not uses_minus:
            pass
        elif ch.minus == MINUS_AO:
            # Back from the lock-in AO along the bottom lane, into the - input.
            ao_out = QPointF(ao_row.left(), ao_row.center().y())
            x_in = kh.left() - 12
            self._poly(p, [ao_out, QPointF(ao_out.x() - 8, ao_out.y()), QPointF(ao_out.x() - 8, lane_y),
                           QPointF(x_in, lane_y), QPointF(x_in, minus_y), t_minus - QPointF(TERM_R, 0)])
        elif ch.minus == MINUS_GND:
            gx = kh.left() - 16
            self._poly(p, [t_minus - QPointF(TERM_R, 0), QPointF(gx, minus_y), QPointF(gx, minus_y + 4)])
            self._ground(p, gx, minus_y + 5)
        elif ch.minus == MINUS_NC:
            p.setPen(QColor(130, 130, 130))
            p.drawText(QRectF(kh.left() - 36, minus_y - 7, 32, 14), Qt.AlignRight | Qt.AlignVCenter, "n.c.")
        else:
            pad_bot = QRectF(PAD_X, minus_y - 10, PAD_W, 20)
            self._box(p, pad_bot, [ch.minus], electrode_color(ch.minus), bold_first=False)
            self._poly(p, [QPointF(pad_bot.right(), minus_y), t_minus - QPointF(TERM_R, 0)])

        # Output -> (external gain) -> AI.
        if out_on:
            self._to_ai(p, ch, y, t_out + QPointF(TERM_R, 0), ai_row)

    def _drive_strip(self, p, ch, out, pad_top, kh, ao_row, lane_y):
        """AO -> (amplifier) -> pad, no Krohn-Hite."""
        self._box(p, kh, ["no Krohn-Hite"], GREY, dashed=True, bold_first=False)
        if ch.ao is None:
            return
        ao_out = QPointF(ao_row.left(), ao_row.center().y())
        pad_in = QPointF(pad_top.right(), pad_top.center().y())
        x_up = pad_top.right() + 18
        if out is not None and (out.gain != 1 or out.offset):
            ax = (x_up + kh.left()) / 2 + 60
            self._poly(p, [ao_out, QPointF(ao_out.x() - 8, ao_out.y()), QPointF(ao_out.x() - 8, lane_y),
                           QPointF(ax + 11, lane_y)])
            self._amp(p, True, ax, lane_y, out.gain, out.offset)
            self._poly(p, [QPointF(ax - 11, lane_y), QPointF(x_up, lane_y), QPointF(x_up, pad_in.y()), pad_in])
        else:
            self._poly(p, [ao_out, QPointF(ao_out.x() - 8, ao_out.y()), QPointF(ao_out.x() - 8, lane_y),
                           QPointF(x_up, lane_y), QPointF(x_up, pad_in.y()), pad_in])

    def _out_strip(self, p: QPainter, o, y: float):
        """An AO with settings but no row cabled to it: AO -> amplifier -> electrode."""
        ao = QRectF(PAD_X, y + 4, 110, 26)
        self._box(p, ao, [f"AO {o.ao}  {o.name}".strip()], FILL["Lock-in"])
        src = QPointF(ao.right(), ao.center().y())
        x = ao.right() + 30
        if o.gain != 1 or o.offset:
            self._amp(p, False, x, ao.center().y(), o.gain, o.offset)
            self._poly(p, [src, QPointF(x - 11, src.y())])
            src, x = QPointF(x + 11, src.y()), x + 40
        if o.electrode:
            e = QRectF(x, y + 7, PAD_W, 20)
            self._box(p, e, [o.electrode], electrode_color(o.electrode), bold_first=False)
            self._poly(p, [src, QPointF(e.left(), src.y())])


class WiringView(QWidget, WiringDrawing):
    """The diagram as a plain widget: click a strip to select its row."""

    rowClicked = Signal(int)  # AI number

    def __init__(self, cfg: Config):
        QWidget.__init__(self)
        WiringDrawing.__init__(self, cfg)
        self.setMouseTracking(True)
        self.setMinimumWidth(WIDTH)

    def set_config(self, cfg: Config) -> None:
        self.cfg = cfg
        self.updateGeometry()
        self.update()

    def set_daq(self, ai_daq: list[dict], ao_daq: list[dict]) -> None:
        self.ai_daq, self.ao_daq = list(ai_daq), list(ao_daq)
        self.update()

    def select(self, ai: int | None) -> None:
        self.selected_ai = ai
        self.update()

    def sizeHint(self) -> QSize:
        return QSize(WIDTH, int(self.total_height()))

    def minimumSizeHint(self) -> QSize:
        return self.sizeHint()

    def mousePressEvent(self, ev):
        row = int((ev.position().y() - PAD) // STRIP_H)
        rows = self._rows()
        if 0 <= row < len(rows):
            self.rowClicked.emit(rows[row].ai)

    def paintEvent(self, ev):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(252, 252, 250))
        self.paint_all(p)
        p.end()
