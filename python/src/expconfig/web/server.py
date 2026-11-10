"""Trial: expconfig in the browser.

The same Python core as the Qt app (model, rules, table logic, cable rules,
instrument I/O) behind a small FastAPI server. The wiring diagram is drawn by
the same WiringDrawing code, rendered to SVG; the page overlays the clickable
parts (the scene's hit areas, ports and pad slots) on top of it.

    uv run --extra web expconfig-web --demo          # http://127.0.0.1:8780
    uv run --extra web expconfig-web --host 0.0.0.0  # reachable from the lab network

Qt is used without a window (offscreen) and only from the server's event loop
thread: every endpoint is async, so they all run there.
"""

from __future__ import annotations

import argparse
import os
import webbrowser
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from fastapi import FastAPI, HTTPException  # noqa: E402
from fastapi.responses import FileResponse, Response  # noqa: E402
from pydantic import BaseModel  # noqa: E402
from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QRectF, QSize  # noqa: E402
from PySide6.QtGui import QFont, QPainter  # noqa: E402
from PySide6.QtSvg import QSvgGenerator  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from .. import diagrammodel, hardware, legacy, palette, rules, wiringedit  # noqa: E402
from ..demo import demo_config, demo_daq, demo_devices  # noqa: E402
from ..model import Config  # noqa: E402
from ..tablemodels import CHANNEL_COLUMNS, ChannelModel, choices, exception  # noqa: E402
from ..wiringscene import Hotspot, PadBlock, PortItem, SlotItem, WiringScene  # noqa: E402

STATIC = Path(__file__).parent / "static"
DIAGRAM = Path(__file__).parent.parent / "diagram_dist" / "index.html"  # built from python/diagram


def _hex(c) -> str:
    return c.name()


class Session:
    """The configuration being edited, shared by every browser that has the page open."""

    def __init__(self, cfg: Config, source: str):
        self.cfg = cfg
        self.source = source
        self.version = 0
        self.status = f"Loaded {source}"
        self.log: list[str] = []
        self.model = ChannelModel(cfg, lambda: None)
        self.scene = WiringScene(cfg)
        self.idn = ""
        self.ai_daq: list[dict] = []
        self.ao_daq: list[dict] = []
        self.devices: list[dict] = []

    def changed(self, msg: str = "") -> None:
        rules.derive_all(self.cfg)
        self.model.refresh()
        self.scene.set_config(self.cfg)
        self.version += 1
        if msg:
            self.status = msg
            self.log.append(msg)

    # ---- what the page draws -----------------------------------------

    def svg(self) -> str:
        rect = self.scene.sceneRect()
        buf = QBuffer()
        buf.open(QIODevice.WriteOnly)
        gen = QSvgGenerator()
        gen.setOutputDevice(buf)
        gen.setSize(QSize(int(rect.width()), int(rect.height())))
        gen.setViewBox(QRectF(0, 0, rect.width(), rect.height()))
        p = QPainter(gen)
        self.scene.render(p, QRectF(0, 0, rect.width(), rect.height()), rect)
        p.end()
        return bytes(buf.data()).decode("utf-8")

    def overlay(self) -> dict:
        """The diagram's interactive parts, in SVG coordinates (scene minus its top-left)."""
        o = self.scene.sceneRect().topLeft()

        def box(item):
            r = item.sceneBoundingRect().translated(-o)
            return [round(r.x(), 1), round(r.y(), 1), round(r.width(), 1), round(r.height(), 1)]

        spots, ports, slots, pads = [], [], [], []
        for it in self.scene.items():
            if isinstance(it, Hotspot):
                spots.append({"ai": it.ai, "key": it.key, "box": box(it), "tip": it.toolTip()})
            elif isinstance(it, PortItem):
                ports.append({"port": list(it.port), "box": box(it), "tip": it.toolTip()})
            elif isinstance(it, SlotItem):
                slots.append({"port": list(it.port), "box": box(it)})
            elif isinstance(it, PadBlock):
                pads.append({"port": list(it.port), "box": box(it), "tip": it.toolTip()})
        r = self.scene.sceneRect()
        return {"width": r.width(), "height": r.height(), "spots": spots, "ports": ports, "slots": slots,
                "pads": pads}

    def table(self) -> dict:
        rows = []
        for ch in self.cfg.channels:
            cells = {}
            for col in CHANNEL_COLUMNS:
                k = col.key
                issue = self.model.issues.get((ch.ai, k))
                mism = ""
                if k in ("kh", "input") and ch.ai in self.model.mismatch:
                    mism = self.model.mismatch[ch.ai]
                if k in ("out_gain", "out_offset") and self.model._drives_ao(ch) and ch.ao in self.model.ao_mismatch:
                    mism = self.model.ao_mismatch[ch.ao]
                cells[k] = {"text": self.model.display(ch, k), "edit": self.model._cell_editable(ch, k),
                            "why": exception(ch, k), "mismatch": mism,
                            "issue": {"code": issue.code, "message": issue.message, "error": issue.is_error}
                            if issue else None}
            rows.append({"ai": ch.ai, "cells": cells})
        groups = {g: _hex(palette.tint(c)) for g, c in palette.FILL.items()}
        return {"columns": [{"key": c.key, "title": c.title, "group": c.group, "tip": c.tip} for c in CHANNEL_COLUMNS],
                "rows": rows, "groups": groups}

    def state(self) -> dict:
        e = self.cfg.experiment
        found = rules.validate(self.cfg)
        return {
            "version": self.version, "status": self.status, "log": self.log[-30:], "idn": self.idn,
            "experiment": {"sample": e.sample, "device": e.device, "user": e.user, "description": e.description,
                           "station": e.station, "pads": e.pads},
            "instruments": {"kh": self.cfg.instruments.kh_addresses, "lockin": self.cfg.instruments.lockin_address},
            "issues": [{"ai": i.ai, "code": i.code, "message": i.message, "error": i.is_error} for i in found],
            "table": self.table(),
            "diagram": self.overlay(),
        }

    # ---- edits ----------------------------------------------------------

    def set_cell(self, ai: int, key: str, value: str) -> None:
        row = next((i for i, c in enumerate(self.cfg.channels) if c.ai == ai), None)
        col = next((i for i, c in enumerate(CHANNEL_COLUMNS) if c.key == key), None)
        if row is None or col is None:
            raise HTTPException(404, f"no cell AI {ai} {key}")
        index = self.model.index(row, col)
        if not self.model._cell_editable(self.cfg.channels[row], key):
            raise HTTPException(409, f"AI {ai} {CHANNEL_COLUMNS[col].title} cannot be edited on this row")
        if not self.model.setData(index, value):
            raise HTTPException(422, f"{value!r} is not a valid {CHANNEL_COLUMNS[col].title}")
        self.changed(f"AI {ai}: {CHANNEL_COLUMNS[col].title} = {value}")

    def readback(self, apply: bool) -> None:
        rig = hardware.Rig(self.cfg, timeout=2.0)
        try:
            rb = rig.apply(self.cfg) if apply else rig.read()
        finally:
            rig.close()
        what = "Apply" if apply else "Read back"
        if rb.errors:
            self.status = f"{what} failed: {'; '.join(rb.errors)}"
            self.log.append(self.status)
            self.version += 1
            return
        self.idn = f"lock-in {rb.lockin_idn.get('model', '?')} SN {rb.lockin_idn.get('serial', '?')}"
        self.scene.set_daq(rb.input_daq, rb.output_daq)
        self.ai_daq, self.ao_daq = rb.input_daq, rb.output_daq
        self.devices = rb.devices
        mism = rb.mismatches(self.cfg)
        self.model.mismatch, self.model.ao_mismatch = {}, {}
        for m in mism:
            head = m.split(":")[0].split()
            target = self.model.mismatch if head[0] == "AI" else self.model.ao_mismatch
            target[int(head[1])] = m
        self.changed(f"{what}: {'matches the table' if not mism else f'{len(mism)} differences'}")
        self.log.extend(mism)


class Cell(BaseModel):
    ai: int
    key: str
    value: str


class Cable(BaseModel):
    a: list
    b: list


class Unplug(BaseModel):
    port: list


def make_app(session: Session) -> FastAPI:
    app = FastAPI(title="expconfig (web trial)")

    def port(p: list) -> tuple:
        kind, pid = p
        return (kind, pid if kind in ("pad", "gnd") else int(pid))

    @app.get("/")
    async def index():
        return FileResponse(STATIC / "index.html")

    @app.get("/app.js")
    async def script():
        return FileResponse(STATIC / "app.js", media_type="text/javascript")

    @app.get("/app.css")
    async def style():
        return FileResponse(STATIC / "app.css", media_type="text/css")

    @app.get("/api/state")
    async def state():
        return session.state()

    @app.get("/api/version")
    async def version():
        return {"version": session.version}

    @app.get("/diagram")
    async def diagram_page():
        """The TypeScript diagram (python/diagram), the same page the Qt app shows."""
        return FileResponse(DIAGRAM)

    @app.get("/api/model")
    async def model():
        return diagrammodel.build(session.cfg, session.model, session.ai_daq, session.ao_daq,
                                  devices=session.devices)

    @app.get("/api/diagram.svg")
    async def diagram():
        return Response(session.svg(), media_type="image/svg+xml")

    @app.get("/api/choices")
    async def get_choices(key: str, ai: int | None = None):
        opts, free = choices(session.cfg, key, session.cfg.channel(ai) if ai else None)
        return {"options": opts, "free": free}

    @app.post("/api/cell")
    async def cell(c: Cell):
        session.set_cell(c.ai, c.key, c.value)
        return session.state()

    @app.post("/api/connect")
    async def connect(c: Cable):
        try:
            msg = wiringedit.connect(session.cfg, port(c.a), port(c.b))
        except wiringedit.WiringError as err:
            raise HTTPException(422, f"Not cabled: {err}") from None
        session.changed(msg)
        return session.state()

    @app.post("/api/disconnect")
    async def disconnect(u: Unplug):
        try:
            msg = wiringedit.disconnect(session.cfg, port(u.port))
        except wiringedit.WiringError as err:
            raise HTTPException(422, str(err)) from None
        session.changed(msg)
        return session.state()

    @app.post("/api/readback")
    async def readback():
        session.readback(apply=False)
        return session.state()

    @app.post("/api/apply")
    async def apply():
        if any(i.is_error for i in rules.validate(session.cfg)):
            raise HTTPException(409, "fix the errors in Checks before applying")
        session.readback(apply=True)
        return session.state()

    return app


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description="expconfig in the browser (trial)")
    src = ap.add_mutually_exclusive_group()
    src.add_argument("--demo", action="store_true", help="start with the demonstration configuration")
    src.add_argument("--import-dir", type=Path, help="import a Configure Experiment folder")
    ap.add_argument("--host", default="127.0.0.1",
                    help="127.0.0.1 (default) = this PC only; 0.0.0.0 = anyone on the network, no login")
    ap.add_argument("--port", type=int, default=8780)
    ap.add_argument("--no-browser", action="store_true")
    a = ap.parse_args(argv)

    import uvicorn

    qt = QApplication.instance() or QApplication([])
    # Named in the SVG, so the browser draws the same face (offscreen Qt otherwise picks a generic one).
    qt.setFont(QFont("Segoe UI", 9))
    if a.import_dir:
        cfg, source = legacy.import_legacy(a.import_dir), str(a.import_dir)
    elif a.demo or not (legacy.DEFAULT_DIR / legacy.JSON_NAME).exists():
        cfg, source = demo_config(), "demo configuration"
    else:
        cfg, source = legacy.import_legacy(), str(legacy.DEFAULT_DIR)
    session = Session(cfg, source)
    if source == "demo configuration":
        session.ai_daq, session.ao_daq = demo_daq()   # as if read from the lock-in
        session.devices = demo_devices()
    app = make_app(session)
    url = f"http://127.0.0.1:{a.port}"
    if a.host != "127.0.0.1":
        print(f"WARNING: listening on {a.host}: anyone who can reach this PC can change the configuration "
              "and apply it to the instruments.")
    print(f"expconfig web trial: {url}")
    if not a.no_browser:
        webbrowser.open(url)
    uvicorn.run(app, host=a.host, port=a.port, log_level="warning", loop="asyncio")


if __name__ == "__main__":
    main()
