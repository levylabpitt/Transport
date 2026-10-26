# Experiment configurator in Python (prototype spec)

**Branch.** `feature/python-config`. This is a trial and may be thrown away. Whatever happens to the branch, the LabVIEW #182 spec (`issue-182-changespec.md`) still describes the model this prototype implements.

**Goal.** A stand-alone application with a proper UI that lets the user:
- describe the experiment's wiring topology;
- apply the resulting settings to the Krohn-Hite 7008 and the multichannel lock-in;
- record the result in a form a machine can read.

It replaces the configuration part of `Configure Experiment.vi`. The experiment VIs, Transport Server, lock-in and instrument drivers stay in LabVIEW.

## Seams with the LabVIEW side

- **Instruments.** Every Instrument Framework application is a ZMQ REP server that speaks JSON-RPC 2.0: `{"jsonrpc":"2.0","method":...,"params":...,"id":...}` in, `result` or `error` out. FLEX `flex/inst/base.py` is the reference client.
  - KH 7008 (default `tcp://localhost:29160`): `getAllChannels` / `setAllChannels` with `allChannelProperties: [{channel, gain, input, shunt, couple, filter}]` as enum-name strings, plus `getChassis` and `getShuntResistor`.
  - Lock-in (default `tcp://localhost:29170`): `getInputGain` / `setInputGain` and `getOutputGain` / `setOutputGain`, each a bare list with one value per channel.
- **`Control Experiment.json`** (`%LOCALAPPDATA%\Levylab\Control Experiment\`). The app writes it in the existing format, so `Transport: prepareTransport`, FLEX `CESession` and the TDMS `<ControlExperiment>` property keep working.
  - It keeps `Experiment.Instruments` (class paths and addresses) untouched.
  - It writes v1 `Wiring Configuration` with `KH.Labels` = Role.
  - It adds `Channels`, `Outputs` and `Topology`.
- **Import.** The app reads the old `configuration.ini` and `Control Experiment.json`, so an existing setup opens without retyping.

## Model

One `Channel` row per lock-in AI, plus one `Output` row per AO. Field meanings and rules are those of the #182 spec:

- **Channel:**
  - Entered: `ai`, `electrode`, `minus`, `type` (U, V, n.c., Ground), `role`, `kh` (A1.., or none), `shunt`, `kh_gain`, `couple`, `filter`, `ext_gain`, `ao`.
  - Derived: `input`, `name`, `lockin_gain` = `kh_gain` × `ext_gain`.
  - `ext_gain` is the gain between the KH (or the sample) and the AI, for example an SR830 output: 10 V / sensitivity.
- **Output:**
  - Fields: `ao`, `name` (e.g. `Vbg`), `gain`.
  - `gain` is the lock-in output gain, i.e. the amplifier between the AO and the device, such as the 25× backgate amplifier.
- **Derivation:**
  - U → DIFF, with the shunt as set.
  - V → SE+, or DIFF when `minus` is an electrode.
  - n.c. / Ground → OFF.
  - Name: `U<e>`, `V<e>`, `dV<e>-<minus>`.
  - All Ground and All Differential act as an apply-time override.
- **Validation:** the #182 error codes, as structured issues per row and field. Electrodes may repeat across rows (teed); KH channels may not.
- **Topology:** a graph exported with the configuration. Nodes are electrodes, KH channel terminals (`A6.+`, `A6.-`, `A6.out`), AIs, AOs and external gain stages; edges are the cables. This is what "machine-readable wiring" means.

## Application

- PySide6 desktop app, run from VS Code (`uv run expconfig`).
- Main parts:
  - experiment info;
  - the channel table, with per-cell editors, derived columns read-only, and invalid cells marked with the reason;
  - set-all controls: Coupling, Filter, All Ground / All Differential;
  - the outputs table;
  - a topology view of the wiring;
  - instrument connections, with Apply and Read back.
- Apply writes the KH (one `setAllChannels` per chassis) and the lock-in input and output gains, then reads them back and shows any difference.
- A simulated KH and lock-in (`uv run expconfig-sim`) speak the same protocol, so the app and the tests run without hardware.
- A marimo notebook is possible later on the same package.

## Open questions

- **Multiple KH chassis.** The prototype assumes one KH server address per chassis (A = first). Check against how `KH: Open` builds its KH class array.
- **Lifecycle.** If the app replaces Configure Experiment.vi, something else must start the Transport Server and the instrument servers.
- **Home.** This repo, FLEX, or a package of its own.
