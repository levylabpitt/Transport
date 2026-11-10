"""Trial: the wiring diagram on a QGraphicsScene.

The strips are drawn by the same WiringDrawing code as the plain view, but each
strip is a scene item, and the parts of a strip that correspond to a table cell
(pad, KH channel, shunt, gain, AO, role, ...) are hover and click targets:

- hover shows the value and outlines the part;
- click selects that cell in the channel table and pops up its choices (KH gain,
  shunt, coupling, filter, type, role, ...) or a field for a number, right there;
- double-click opens the cell's editor in the table instead;
- selecting a cell in the table outlines the matching part here;
- the diagram fits the pane's width; Ctrl + wheel zooms, Ctrl+0 fits again;
- drag a pad from the Pads column onto a row's pad slot (left of KH + or -), or
  drag from one terminal (pad, KH +/-/out, AI, AO, GND) to another, to cable them:
  the cable becomes table edits (wiringedit.connect), or is refused with the reason;
- right-click a KH input to disconnect it.
"""

from __future__ import annotations

from PySide6.QtCore import QLineF, QPoint, QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QKeySequence, QPainter, QPen, QShortcut, QTransform
from PySide6.QtWidgets import (
    QGraphicsEllipseItem, QGraphicsItem, QGraphicsLineItem, QGraphicsRectItem, QGraphicsScene,
    QGraphicsSimpleTextItem, QGraphicsView, QMenu,
)

from .model import Config
from .palette import border, electrode_color
from .wiringview import KH_W, KH_X, LI_X, PAD, PAD_W, PAD_X, STRIP_H, WIDTH, WiringDrawing

PALETTE_X = -96              # the pad palette sits left of the strips
PORT_PEN = QPen(QColor(40, 110, 220), 1.6)
CANDIDATE_BRUSH = QBrush(QColor(40, 110, 220, 60))

HOVER_PEN = QPen(QColor(40, 110, 220), 1.6)
HOVER_BRUSH = QBrush(QColor(40, 110, 220, 28))
CURRENT_PEN = QPen(QColor(220, 120, 0), 2.0)


class StripItem(QGraphicsItem):
    """One channel's strip, painted by WiringDrawing."""

    def __init__(self, drawing: WiringDrawing, ch):
        super().__init__()
        self.drawing, self.ch = drawing, ch

    def boundingRect(self) -> QRectF:
        return QRectF(0, 0, WIDTH, STRIP_H)

    def paint(self, p: QPainter, option, widget=None):
        self.drawing.prepare(p)
        self.drawing._strip(p, self.ch, 0)

    def mousePressEvent(self, ev):
        self.scene().rowClicked.emit(self.ch.ai)


class FooterItem(QGraphicsItem):
    def __init__(self, drawing: WiringDrawing):
        super().__init__()
        self.drawing = drawing

    def boundingRect(self) -> QRectF:
        return QRectF(0, 0, WIDTH, self.drawing.footer_height() + 12)

    def paint(self, p: QPainter, option, widget=None):
        self.drawing.prepare(p)
        self.drawing._footer(p, 0)


class Hotspot(QGraphicsRectItem):
    """A part of a strip that stands for one table cell."""

    def __init__(self, rect: QRectF, ai: int, key: str, tip: str, parent: QGraphicsItem):
        super().__init__(rect, parent)
        self.ai, self.key, self.current = ai, key, False
        self.setAcceptHoverEvents(True)
        self.setToolTip(f"{tip}\nclick: change it here, double-click: edit in the table")
        self.setCursor(Qt.PointingHandCursor)
        self._style(False)

    def _style(self, hover: bool):
        if hover:
            self.setPen(HOVER_PEN)
            self.setBrush(HOVER_BRUSH)
        elif self.current:
            self.setPen(CURRENT_PEN)
            self.setBrush(Qt.NoBrush)
        else:
            self.setPen(Qt.NoPen)
            self.setBrush(Qt.NoBrush)

    def set_current(self, on: bool):
        self.current = on
        self._style(False)

    def hoverEnterEvent(self, ev):
        self._style(True)

    def hoverLeaveEvent(self, ev):
        self._style(False)

    def mousePressEvent(self, ev):
        self.scene().cellClicked.emit(self.ai, self.key)
        if ev.button() == Qt.LeftButton:
            self.scene().cellMenu.emit(self.ai, self.key, ev.screenPos())

    def mouseDoubleClickEvent(self, ev):
        self.scene().cellEdit.emit(self.ai, self.key)


class PortItem(QGraphicsEllipseItem):
    """A cable end. Invisible until hovered, or until a drag shows where a cable can go."""

    R = 6
    source = True   # a drag can start here
    target = True   # a drag can end here

    def __init__(self, center: QPointF, port: tuple, tip: str, parent: QGraphicsItem):
        super().__init__(QRectF(center.x() - self.R, center.y() - self.R, 2 * self.R, 2 * self.R), parent)
        self.port = port
        self.setZValue(10)
        self.setAcceptHoverEvents(True)
        self.setCursor(Qt.CrossCursor)
        self.setToolTip(f"{tip}\ndrag to another terminal to cable it"
                        + ("\nright-click to disconnect" if port[0] in ("kh+", "kh-") else ""))
        self.show_as(False)

    def show_as(self, on: bool, candidate=False):
        self.setPen(PORT_PEN if on or candidate else Qt.NoPen)
        self.setBrush(CANDIDATE_BRUSH if candidate else Qt.NoBrush)

    def hoverEnterEvent(self, ev):
        self.show_as(True)

    def hoverLeaveEvent(self, ev):
        self.show_as(False, self.scene().dragging is not None)

    def contextMenuEvent(self, ev):
        if self.port[0] not in ("kh+", "kh-"):
            return
        menu = QMenu()
        sign = "+" if self.port[0] == "kh+" else "\u2212"
        act = menu.addAction(f"Disconnect the KH {sign} input")
        if menu.exec(ev.screenPos()) is act:
            self.scene().disconnectRequested.emit(self.port)


class PadBlock(QGraphicsRectItem):
    """A whole pad box in the Pads column: drag it onto a row's pad slot."""

    source, target = True, True

    def __init__(self, rect: QRectF, port: tuple, tip: str, parent: QGraphicsItem):
        super().__init__(rect, parent)
        self.port = port
        self.setZValue(10)
        self.setAcceptHoverEvents(True)
        self.setCursor(Qt.OpenHandCursor)
        self.setToolTip(f"{tip}\ndrag onto a row's pad slot, left of KH + (or \u2212)")
        self.show_as(False)

    def show_as(self, on: bool, candidate=False):
        self.setPen(PORT_PEN if on else Qt.NoPen)
        self.setBrush(Qt.NoBrush)

    def hoverEnterEvent(self, ev):
        self.show_as(True)

    def hoverLeaveEvent(self, ev):
        self.show_as(False)


class SlotItem(QGraphicsRectItem):
    """Where a pad lands on a strip: the box left of KH + (or of KH -). Drop target only."""

    source, target = False, True

    def __init__(self, rect: QRectF, port: tuple, parent: QGraphicsItem):
        super().__init__(rect, parent)
        self.port = port
        self.setZValue(5)
        self.show_as(False)

    def show_as(self, on: bool, candidate=False):
        self.setPen(QPen(QColor(40, 110, 220), 1.4, Qt.DashLine) if on or candidate else Qt.NoPen)
        self.setBrush(CANDIDATE_BRUSH if on else Qt.NoBrush)


def strip_slots(ch) -> list[tuple[QRectF, tuple]]:
    """Pad slots on one strip: + side (or the pad a Drive row or a no-KH row uses), and - side."""
    plus = QRectF(PAD_X - 3, 3, PAD_W + 6, 26)
    minus = QRectF(PAD_X - 3, 28, PAD_W + 6, 26)
    if ch.direct:
        return [(plus, ("ao", ch.ao))] if ch.ao is not None else []
    if ch.kh is None:
        return [(plus, ("ai", ch.ai))]
    return [(plus, ("kh+", ch.ai)), (minus, ("kh-", ch.ai))]


def strip_ports(drawing: WiringDrawing, ch) -> list[tuple[QPointF, tuple, str]]:
    """Cable ends on one strip, in strip coordinates (the geometry of WiringDrawing._strip)."""
    ports = []
    if ch.electrode:
        ports.append((QPointF(PAD_X + PAD_W, 16), ("pad", ch.electrode), f"Pad {ch.electrode}"))
    if ch.kh is not None and not ch.direct:
        ports += [(QPointF(KH_X + 11, 16), ("kh+", ch.ai), "KH + input"),
                  (QPointF(KH_X + 11, 40), ("kh-", ch.ai), "KH \u2212 input"),
                  (QPointF(KH_X + KH_W - 11, 27), ("khout", ch.ai), "KH output")]
        if ch.minus_is_electrode:
            ports.append((QPointF(PAD_X + PAD_W, 40), ("pad", ch.minus), f"Pad {ch.minus}"))
    if not ch.direct:
        ports.append((QPointF(LI_X, 17), ("ai", ch.ai), f"AI {ch.ai}"))
    ao = ch.ao if drawing._uses_ao(ch) else (ch.ai if drawing.cfg.output(ch.ai) else None)
    if ao is not None:
        ports.append((QPointF(LI_X, 43), ("ao", ao), f"AO {ao}"))
    return ports


def _natural(s: str):
    return (0, int(s), "") if s.isdigit() else (1, 0, s)


class PaletteItem(QGraphicsItem):
    """Every device pad (1..N, plus named electrodes such as 'gate') and ground, to drag cables from."""

    ROW = 22

    def __init__(self, cfg: Config):
        super().__init__()
        used = {c.electrode for c in cfg.channels} | {c.minus for c in cfg.channels if c.minus_is_electrode}
        used.discard("")
        names = sorted({str(i) for i in range(1, cfg.experiment.pads + 1)} | used, key=_natural)
        self.entries = [("GND", ("gnd", None), False)] + [(n, ("pad", n), n in used) for n in names]
        for i, (name, port, _) in enumerate(self.entries):
            tip = "Ground" if port[0] == "gnd" else f"Pad {name}"
            PadBlock(self._box(i), port, tip, self)

    def _box(self, i: int) -> QRectF:
        return QRectF(4, 21 + i * self.ROW, 50, 18)

    def boundingRect(self) -> QRectF:
        return QRectF(0, 0, 70, 30 + len(self.entries) * self.ROW)

    def paint(self, p: QPainter, option, widget=None):
        WiringDrawing.prepare(p)
        p.setPen(QColor(80, 80, 80))
        p.drawText(QRectF(0, 2, 70, 16), Qt.AlignLeft | Qt.AlignVCenter, "Pads")
        for i, (name, port, used) in enumerate(self.entries):
            # Free pads stand out; pads already cabled are faded, so the column shows what is left.
            r = self._box(i)
            gnd = port[0] == "gnd"
            p.setOpacity(0.3 if used else 1.0)
            fill = QColor(225, 225, 225) if gnd else (electrode_color(name) if used else QColor(255, 255, 255))
            p.setPen(QPen(border(fill) if used or gnd else QColor(120, 120, 120), 1))
            p.setBrush(fill)
            p.drawRoundedRect(r, 4, 4)
            p.setPen(QColor(30, 30, 30))
            p.drawText(r, Qt.AlignCenter, name)
        p.setOpacity(1.0)


class WiringScene(QGraphicsScene):
    rowClicked = Signal(int)          # AI
    cellClicked = Signal(int, str)    # AI, channel-table column key
    cellEdit = Signal(int, str)
    cellMenu = Signal(int, str, QPoint)         # AI, column key, where to pop up the editor
    connectRequested = Signal(object, object)   # two ports (see wiringedit)
    disconnectRequested = Signal(object)

    def __init__(self, cfg: Config):
        super().__init__()
        self.drawing = WiringDrawing(cfg)
        self.spots: dict[tuple[int, str], Hotspot] = {}
        self.current: tuple[int, str] | None = None
        self.dragging: PortItem | None = None
        self._line: QGraphicsLineItem | None = None
        self.setBackgroundBrush(QColor(252, 252, 250))
        self.rebuild()

    def rebuild(self) -> None:
        self.clear()
        self.spots = {}
        self._line, self.dragging = None, None
        y = PAD
        for ch in self.drawing._rows():
            strip = StripItem(self.drawing, ch)
            strip.setPos(0, y)
            self.addItem(strip)
            for rect, key, tip in self.drawing.hotspots(ch):
                self.spots[(ch.ai, key)] = Hotspot(rect, ch.ai, key, tip, strip)
            for center, port, tip in strip_ports(self.drawing, ch):
                PortItem(center, port, tip, strip)
            for rect, port in strip_slots(ch):
                SlotItem(rect, port, strip)
            y += STRIP_H
        footer = FooterItem(self.drawing)
        footer.setPos(0, y)
        self.addItem(footer)
        pal = PaletteItem(self.drawing.cfg)
        pal.setPos(PALETTE_X, PAD)
        self.addItem(pal)
        h = max(self.drawing.total_height(), PAD + pal.boundingRect().height() + PAD)
        self.setSceneRect(QRectF(PALETTE_X - 4, 0, WIDTH - PALETTE_X + 4, h))
        if self.current in self.spots:
            self.spots[self.current].set_current(True)

    def set_config(self, cfg: Config) -> None:
        self.drawing.cfg = cfg
        self.rebuild()

    def set_daq(self, ai_daq: list[dict], ao_daq: list[dict]) -> None:
        self.drawing.ai_daq, self.drawing.ao_daq = list(ai_daq), list(ao_daq)
        self.update()

    def select(self, ai: int | None) -> None:
        self.drawing.selected_ai = ai
        self.update()

    def highlight(self, ai: int | None, key: str | None) -> None:
        """Outline the part that stands for the table's current cell, if the diagram has one."""
        if self.current in self.spots:
            self.spots[self.current].set_current(False)
        self.current = (ai, key) if ai is not None else None
        if self.current in self.spots:
            self.spots[self.current].set_current(True)


    # ---- drawing a cable ----------------------------------------------

    def _end_at(self, pos: QPointF, exclude=None, sources=False):
        """The cable end under pos: a source to start a drag from, or any target to drop on."""
        return next((i for i in self.items(pos) if hasattr(i, "port") and i is not exclude
                     and (i.source if sources else i.target)), None)

    def _ends(self):
        return [i for i in self.items() if hasattr(i, "port")]

    def mousePressEvent(self, ev):
        end = self._end_at(ev.scenePos(), sources=True) if ev.button() == Qt.LeftButton else None
        if end is None:
            super().mousePressEvent(ev)
            return
        self.dragging = end
        start = end.sceneBoundingRect().center()
        if isinstance(end, PadBlock):
            # Carry the pad itself: a copy of its box follows the mouse.
            r = end.rect()
            self._line = self.addRect(QRectF(0, 0, r.width(), r.height()), QPen(QColor(40, 110, 220), 1.4),
                                      QBrush(QColor(255, 255, 255, 220)))
            label = QGraphicsSimpleTextItem("GND" if end.port[0] == "gnd" else str(end.port[1]), self._line)
            label.setPos((r.width() - label.boundingRect().width()) / 2, 2)
            self._line.setPos(ev.scenePos() - QPointF(r.width() / 2, r.height() / 2))
        else:
            self._line = self.addLine(QLineF(start, start), QPen(QColor(40, 110, 220), 2, Qt.DashLine))
        self._line.setZValue(20)
        pad = isinstance(end, PadBlock)
        for e in self._ends():
            # A carried pad only lights up the pad slots; a wire lights up every other end.
            e.show_as(e is end, candidate=e is not end and e.target and (isinstance(e, SlotItem) or not pad))
        ev.accept()

    def mouseMoveEvent(self, ev):
        if self.dragging is not None and self._line is not None:
            if isinstance(self._line, QGraphicsLineItem):
                line = self._line.line()
                line.setP2(ev.scenePos())
                self._line.setLine(line)
            else:
                r = self._line.rect()
                self._line.setPos(ev.scenePos() - QPointF(r.width() / 2, r.height() / 2))
            ev.accept()
            return
        super().mouseMoveEvent(ev)

    def mouseReleaseEvent(self, ev):
        if self.dragging is None:
            super().mouseReleaseEvent(ev)
            return
        src = self.dragging
        self.removeItem(self._line)  # before looking: the carried pad copy sits under the mouse
        self._line, self.dragging = None, None
        target = self._end_at(ev.scenePos(), exclude=src)
        for e in self._ends():
            e.show_as(False)
        ev.accept()
        if target is not None:
            self.connectRequested.emit(src.port, target.port)  # the app rebuilds the scene from the table


class WiringSceneView(QGraphicsView):
    def __init__(self, scene: WiringScene):
        super().__init__(scene)
        self.setRenderHints(QPainter.Antialiasing | QPainter.TextAntialiasing)
        self.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.fit = True  # scale to the pane's width until the user zooms
        # A fixed scroll bar: otherwise fitting the width can show and hide it, which resizes
        # the viewport, which fits again, without end.
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOn)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        QShortcut(QKeySequence("Ctrl+0"), self, self._fit_width)

    def _fit_width(self):
        self.fit = True
        w = self.scene().sceneRect().width()
        if w > 0:
            f = min(1.3, max(0.5, (self.viewport().width() - 4) / w))
            # No anchor: keep the scroll position (the top, at first) instead of zooming about the mouse.
            self.setTransformationAnchor(QGraphicsView.NoAnchor)
            self.setTransform(QTransform.fromScale(f, f))
            self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        if self.fit:
            self._fit_width()

    def wheelEvent(self, ev):
        if ev.modifiers() & Qt.ControlModifier:
            self.fit = False
            f = 1.15 if ev.angleDelta().y() > 0 else 1 / 1.15
            self.scale(f, f)
        else:
            super().wheelEvent(ev)
