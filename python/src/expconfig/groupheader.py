"""A table header with a band of column-group titles above the column titles."""

from __future__ import annotations

from PySide6.QtCore import QRect, QSize, Qt
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QHeaderView


class GroupHeader(QHeaderView):
    def __init__(self, groups: list[str], tints: dict[str, QColor], parent=None):
        super().__init__(Qt.Horizontal, parent)
        self.groups = groups  # group name per logical column
        self.tints = tints
        self.setSectionsClickable(False)

    def _band(self) -> int:
        return self.fontMetrics().height() + 6

    def sizeHint(self) -> QSize:
        s = super().sizeHint()
        return QSize(s.width(), s.height() + self._band())

    def paintSection(self, painter: QPainter, rect: QRect, logical: int) -> None:
        super().paintSection(painter, rect.adjusted(0, self._band(), 0, 0), logical)

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        p = QPainter(self.viewport())
        band = self._band()
        i = 0
        n = self.count()
        while i < n:
            name = self.groups[i]
            j = i
            while j + 1 < n and self.groups[j + 1] == name:
                j += 1
            x0 = self.sectionViewportPosition(i)
            x1 = self.sectionViewportPosition(j) + self.sectionSize(j)
            r = QRect(x0, 0, x1 - x0, band)
            p.fillRect(r, self.tints.get(name, QColor(240, 240, 240)).darker(104))
            p.setPen(QPen(QColor(150, 150, 150)))
            p.drawLine(r.topRight(), r.bottomRight())
            p.drawLine(r.bottomLeft(), r.bottomRight())
            f = p.font()
            f.setBold(True)
            p.setFont(f)
            p.setPen(QColor(50, 50, 50))
            p.drawText(r, Qt.AlignCenter, name)
            i = j + 1
        p.end()
