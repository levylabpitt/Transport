"""The TypeScript wiring diagram (python/diagram, built into diagram_dist) inside the Qt app.

The page runs in Qt's browser (QWebEngineView) and talks to Python through
QWebChannel: it calls the slots of DiagramBridge for every edit, and Python sends
it a fresh model (diagrammodel.build) whenever the configuration changes. All the
rules stay in Python; the page only draws and reports what the user did.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Callable

from PySide6.QtCore import QObject, QUrl, Signal, Slot
from PySide6.QtWebChannel import QWebChannel
from PySide6.QtWebEngineCore import QWebEngineSettings
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import QVBoxLayout, QWidget

PAGE = Path(__file__).parent / "diagram_dist" / "index.html"


class DiagramBridge(QObject):
    """What the page can ask of Python. Edits return "" or the reason they were refused."""

    modelChanged = Signal(str)          # JSON from diagrammodel.build
    selectedChanged = Signal(int, str)  # AI, column key ("" for the row only)

    def __init__(self, model: Callable[[], dict], set_cell: Callable[[int, str, str], str],
                 cable: Callable[[list, list], str], unplug: Callable[[list], str],
                 choices: Callable[[int, str], dict], select: Callable[[int, str], None]):
        super().__init__()
        self._model, self._set_cell, self._cable = model, set_cell, cable
        self._unplug, self._choices, self._select = unplug, choices, select

    def push(self) -> None:
        self.modelChanged.emit(json.dumps(self._model()))

    @Slot(result=str)
    def model(self) -> str:
        return json.dumps(self._model())

    @Slot(int, str, str, result=str)
    def setCell(self, ai: int, key: str, value: str) -> str:
        return self._set_cell(ai, key, value)

    @Slot(str, str, result=str)
    def cable(self, a: str, b: str) -> str:
        return self._cable(json.loads(a), json.loads(b))

    @Slot(str, result=str)
    def unplug(self, port: str) -> str:
        return self._unplug(json.loads(port))

    @Slot(int, str, result=str)
    def choices(self, ai: int, key: str) -> str:
        return json.dumps(self._choices(ai, key))

    @Slot(int, str)
    def select(self, ai: int, key: str) -> None:
        self._select(ai, key)


class LazyDiagram(QWidget):
    """Holds the place of the diagram until it is first shown, so Qt's browser (Chromium,
    a few hundred MB) only starts when the Wiring window is opened."""

    def __init__(self, bridge: "DiagramBridge"):
        super().__init__()
        self.bridge = bridge
        self.view: DiagramView | None = None
        QVBoxLayout(self).setContentsMargins(0, 0, 0, 0)

    def showEvent(self, ev):
        if self.view is None:
            self.view = DiagramView(self.bridge)
            self.layout().addWidget(self.view)
        super().showEvent(ev)


class DiagramView(QWebEngineView):
    def __init__(self, bridge: DiagramBridge):
        super().__init__()
        self.bridge = bridge
        self.channel = QWebChannel(self)
        self.channel.registerObject("expconfig", bridge)
        self.page().setWebChannel(self.channel)
        s = self.settings()
        s.setAttribute(QWebEngineSettings.LocalContentCanAccessFileUrls, True)
        if PAGE.exists():
            self.load(QUrl.fromLocalFile(str(PAGE)))
        else:
            self.setHtml("<p style='font-family:Segoe UI;padding:20px'>The diagram is not built: run "
                         "<code>npm install</code> and <code>npm run build</code> in <code>python/diagram</code>.</p>")
