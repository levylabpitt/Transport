# expconfig: experiment configurator (prototype)

A stand-alone replacement for the configuration part of `Configure Experiment.vi`: describe the wiring, apply it to the Krohn-Hite 7008 and the multichannel lock-in, and record it in a form a machine can read. Spec: `../documentation/python-config-spec.md`. Branch `feature/python-config`; this is a trial.

## Run

From this folder, in a VS Code terminal:

```bash
uv sync
uv run expconfig --demo
```

- `uv run expconfig` opens what you last saved. Save (Ctrl+S, in the toolbar and in the Wiring window) writes `%LOCALAPPDATA%\Levylab\expconfig\Control Experiment.json`; both windows show whether the configuration is saved, and closing with unsaved changes asks. If `%LOCALAPPDATA%\Levylab\Control Experiment\Control Experiment.json` was written after your last Save (Configure Experiment, or "Write Control Experiment.json"), the app opens that instead. Window size, table split, tab and the diagram window are remembered.
- `--demo` starts from the demo configuration: a current source, a voltage pair, a backgate through a 25× amplifier, an SR830 input and a teed 6/7 pair. Save it to continue from it next time with a plain `uv run expconfig`.
- `--sim` starts a simulated KH and lock-in on free ports and connects to them. Add `--apply` to apply once at startup.
- `uv run expconfig-sim` runs the simulators on their own, by default on the real ports (29160 KH, 29170 lock-in). Close the LabVIEW instrument apps first, or use `--base-port`.
- `uv run pytest` runs the tests: model, rules, file import/export, topology, the ZMQ protocol against the simulators, and the UI offscreen.

## What is where

| Module | Contents |
| --- | --- |
| `model.py` | `Channel` (one per lock-in AI), `Output` (one per AO), `Config`; KH channel labels A1..B8 |
| `rules.py` | Derivation (KH input, name, forced shunt), validation with the #182 error codes, `apply_entries` for partial JSON updates |
| `topology.py` | The wiring as a graph (electrodes, KH terminals, AI, AO, gain stages) and `path_to_ai` |
| `legacy.py` | Import of the old `configuration.ini` / `Control Experiment.json`; export that keeps the legacy keys and adds `Channels`, `Outputs`, `Topology`, `Configurator` |
| `rpc.py` | JSON-RPC 2.0 over ZMQ REQ/REP, the Instrument Framework protocol (same as FLEX `flex.inst.base`) |
| `instruments.py`, `hardware.py` | KH 7008 and lock-in clients; rows to `setAllChannels` and gain lists; apply, read back, mismatches, adopt |
| `sim.py` | Simulated KH chassis and lock-in |
| `db.py` | Lab database: user and station lookups, measurement record (credentials from pgpass) |
| `app.py`, `tablemodels.py`, `wiringview.py` | The PySide6 application |
| `diagrammodel.py`, `diagramtypes.py`, `wiringweb.py` | The data the wiring diagram draws, its types (generated into TypeScript), and the Qt window that shows it |
| `diagram/` | The wiring diagram (TypeScript, React Flow), built into `src/expconfig/diagram_dist/index.html` |

## Wiring diagram (diagram/)

Needs Node.js. From `diagram/`:

```bash
npm install
npm run build
npm test
```

- `npm run build` typechecks and writes `src/expconfig/diagram_dist/index.html`, which the app loads. Rebuild after changing anything in `diagram/src`.
- `npm test` runs the layout tests on real models: cables at right angles, no two cables sharing a line, none through a box, evenly spaced elbows, every card connector drawn in front-panel order.
- The data Python sends is described once, in `diagramtypes.py`. After changing it or `diagrammodel.py`, run `uv run python -m expconfig.diagramtypes`: it rewrites `diagram/src/model.gen.ts` and the test fixtures in `diagram/test/fixtures/`. `uv run pytest` fails until you do.
- The layout knows where each terminal sits (`anchor()` in `layout.ts`) so the tests can check cables without a browser. If a box's CSS moves a terminal, the page logs "cable ... layout expects ..." in the browser console.

## Remote API (for FLEX)

While the app runs, it serves JSON-RPC 2.0 over ZMQ on `tcp://*:29180` (`--api-port`, 0 = off). This is the Instrument Framework protocol, so FLEX's base class talks to it unchanged:

```python
from flex.inst.base import Instrument
cfg = Instrument("tcp://localhost:29180")
cfg.call("getChannelConfig")      # {"Channels": [...], "Outputs": [...]}
cfg.call("setChannelConfig", {"Channels": [{"AI": 2, "Type": "U", "Electrode": "5", "Shunt": "50k"}]})
cfg.call("setOutputs", {"Outputs": [{"AO": 4, "Name": "Vbg", "Gain": 25}]})
cfg.call("getTopology")           # the wiring graph
```

- **`setChannelConfig`** updates the open window and, unless `"apply": false`, applies to the instruments like CONFIRM. It returns the rows plus any read-back mismatches.
- **A bad request is rejected whole.** The error code is the first issue's #182 code, for example 5001 for an unknown AI, and `error.data` lists every issue.
- **Other methods:** `getChecks`, `applyConfig`, `ACK`, `IDN`, `HELP`.

## Using it from Python or marimo

The model has no UI dependency:

```python
from expconfig import legacy, rules, topology, hardware
cfg = legacy.import_legacy()
cfg = rules.apply_entries(cfg, [{"AI": 3, "Type": "V", "Electrode": "7", "Role": "V1+"}])
graph = topology.build(cfg)
topology.path_to_ai(graph, 3)   # ['electrode:7']
hardware.Rig(cfg).apply(cfg)    # writes the KH and lock-in, returns the read-back
```

## Known gaps

- **Multiple KH chassis** are assumed to be one server address each (A = first). Check how the LabVIEW side addresses chassis B.
- **Untested against LabVIEW.** Writing `Control Experiment.json` keeps every key LabVIEW reads, but whether `JSON to Control Experiment Class.vi` tolerates the added keys has not been tried. The app refuses to overwrite the file with a configuration that has no instrument classes.
- **Database:** the app reads `db.levylab.org` at startup for the dropdowns (`--no-db` to skip). It writes only on "Log measurement", after confirmation. `EXPCONFIG_LIVE_DB=1 uv run pytest` adds a read-only test against the real database.
- **Not yet handled:** the `non KH` electrode list (kept from the old file but not editable) and the database (PGSQL) fields.
