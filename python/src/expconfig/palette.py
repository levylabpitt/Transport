"""Colours shared by the channel table and the wiring view, so a group looks the
same in both: the view uses FILL for its boxes, the table a paler TINT of it."""

from __future__ import annotations

import hashlib

from PySide6.QtGui import QColor

FILL = {
    "Device": QColor(252, 240, 200),       # yellow
    "Measurement": QColor(234, 222, 248),  # purple
    "Krohn-Hite": QColor(206, 238, 218),   # green
    "Lock-in": QColor(212, 224, 252),      # blue
    "Other": QColor(252, 222, 204),        # orange: amplifiers and external gain stages
}


def tint(color: QColor, keep: float = 0.4) -> QColor:
    """color blended toward white, keeping `keep` of its distance from white."""
    return QColor(*(round(255 - keep * (255 - c)) for c in (color.red(), color.green(), color.blue())))


def border(color: QColor) -> QColor:
    return color.darker(150)


# Warm hues (red, orange, yellow, pink, purple) so electrodes never look like KH or lock-in boxes.
_ELECTRODE_HUES = (0, 18, 32, 46, 56, 275, 295, 315, 335)


def electrode_color(name: str) -> QColor:
    """One colour per electrode name, so a teed electrode is the same colour on every row."""
    h = int(hashlib.md5(name.encode()).hexdigest()[:6], 16)
    return QColor.fromHsv(_ELECTRODE_HUES[h % len(_ELECTRODE_HUES)], 85, 250)
