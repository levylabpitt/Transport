# Experiment configurator in Python (prototype spec)

**Branch.** `feature/python-config`. This is a trial and may be thrown away. Whatever happens to the branch, the LabVIEW #182 spec (`issue-182-changespec.md`) still describes the model this prototype implements.

**Goal.** A stand-alone application with a proper UI that lets the user:
- describe the experiment's wiring topology;
- apply the resulting settings to the Krohn-Hite 7008 and the multichannel lock-in;
- record the result in a form a machine can read, in the data files and the lab database.

It replaces `Configure Experiment.vi`. The experiment VIs, Transport Server, lock-in and instrument drivers stay in LabVIEW.

## Architecture

| Component | Language | Responsibility |
| --- | --- | --- |
| **Launcher** (new, compiled exe) | LabVIEW | Starts and owns the Transport Server SMO, starts expconfig, stops both on exit. Window hidden. |
| **Transport Server** (`Inst.Transport`) | LabVIEW | Runs experiments. Owns the instrument classes (chosen in its UI, see below). Receives experiment info and wiring from expconfig. |
| **expconfig** (this app) | Python | Wiring topology, KH and lock-in settings, experiment info, device folder, lab database. Serves its own API to FLEX. |
| **KH 7008, Multichannel-Lockin** | LabVIEW exes | Unchanged. expconfig and FLEX are clients of their ZMQ servers. |
| **FLEX** | Python | Experiment scripts. Reads the configuration from expconfig's API (and Transport's), not from a file. |

What `Configure Experiment.vi` does today, and where it goes:

| Today in Configure Experiment.vi | Goes to |
| --- | --- |
| Lockin / KH tables, label → KH settings, CONFIRM (`KH: set KH 0/1/2`) | expconfig (done) |
| Experiment form: sample, device, user, description, path, station | expconfig (done; user and station dropdowns from the database) |
| Database: users, stations, measurement record (`PGSQL: Write`) | expconfig (done, see Database) |
| Device folder (`Metadata: Build Path`) | expconfig (to do; trivial) |
| Instrument classes (`Instruments: Load Classes`, Configure dialog) | Transport Server UI |
| Create / start / stop the Transport Server SMO | Launcher |
| Opening the Lockin and KH apps | Later (launcher or expconfig) |
| Data-file comments | Already Transport (`Generate Comments` inside `Save Transport TDMS File`) |

## Seams with the LabVIEW side

- **Instrument protocol.** Every Instrument Framework application is a ZMQ REP server that speaks JSON-RPC 2.0: `{"jsonrpc":"2.0","method":...,"params":...,"id":...}` in, `result` or `error` out. FLEX `flex/inst/base.py` is the reference client.
  - KH 7008 (default `tcp://localhost:29160`): `getAllChannels` / `setAllChannels` with `allChannelProperties: [{channel, gain, input, shunt, couple, filter}]` as enum-name strings, plus `getChassis`, `IDN` (`serial`) and `getShuntResistor`. `getShuntResistor` returns one string naming the optional resistor fitted ("500" means no 10M position; anything else non-empty means no 500 position).
  - Lock-in (default `tcp://localhost:29170`): `getInputGain` / `setInputGain` and `getOutputGain` / `setOutputGain`, each a bare list with one value per channel; `IDN` (`serial`).
  - Tested 2026-10-26 against the LabVIEW KH and lock-in applications, running on simulated hardware.
- **expconfig's own API.** expconfig serves JSON-RPC over ZMQ itself (default port 29180): `getChannelConfig`, `setChannelConfig`, `setOutputs`, `getTopology`, `getChecks`, `applyConfig`. This takes over the role of the Transport Server commands in the #182 spec, using the same payload keys and error codes.
- **`Control Experiment.json`** (`%LOCALAPPDATA%\Levylab\Control Experiment\`). Used for now; see the next section.
- **Import.** expconfig reads the old `configuration.ini` and `Control Experiment.json`, so an existing setup opens without retyping.

## Control Experiment.json: from shared file to APIs

The file was the hand-off from Configure Experiment to Transport, and later to FLEX. Once the Transport Server owns the instrument configuration and receives the wiring from expconfig directly, nothing needs it.

**Readers today:**
- Transport `prepareTransport`, through `Control Experiment FGV.vi`, which reads the file on every call. It takes the experiment folder, description and dictionary, and the instrument classes. The Control Experiment object read here also carries:
  - the v1 wiring that `Get Channel Indices.vi` uses to find the R/G channels by role;
  - the `json` string that becomes the TDMS `<ControlExperiment>` property.
- `Load Instrument Classes.vi` (Configure Experiment).
- FLEX `CESession`.
- Sweep Control (superseded).

**Now (trial):** a shared file.
- Transport (Configure Experiment for now) owns `Experiment.Instruments` and `Experiment.Sweep`; expconfig owns the rest.
- expconfig re-reads the file before writing and keeps what it does not own (done).

**Target:** no shared file.
- **Transport** owns the instrument classes (its UI, its own settings file).
- **expconfig pushes** the experiment info and wiring to Transport, on Apply and whenever it connects:
  - `setExperimentInfo`: device, user, description, folder. This extends `setExptFolder` / `setExptComments`.
  - `setWiring`: the `Channels` rows. Transport builds the v1 wiring (roles in `KH.Labels`) and the `json` string into its Control Experiment object, so `Get Channel Indices` and `<ControlExperiment>` keep working.
- **`prepareTransport`** uses what Transport holds instead of reading the file.
- **FLEX** uses `getChannelConfig` (expconfig) and Transport's getters.
- **expconfig** keeps its own settings in its own file.

## Database

Ported from `src\Control Experiment\subVIs\DB *.vi`; `db.py` in expconfig.

- **Connection:**
  - Server: PostgreSQL `db.levylab.org:5432`, database `levylab`.
  - Credentials: the standard pgpass file `%APPDATA%\postgresql\pgpass.conf`, as the LabVIEW PGPASS connection manager uses. libpq reads it, so no credentials are in the code.
  - Logins: reads as `llab_reader`, writes as `llab_writer`.
- **Lookups** (they fill the experiment form's dropdowns, read in the background at startup):
  - users: `SELECT first_name FROM public.users WHERE end_date IS NULL AND role NOT IN ('InfoTech', 'Support Staff, Lab Organizer')`;
  - station types: `SELECT DISTINCT type FROM public.stations`;
  - stations per type: `public.stations.name`.
- **Measurement record:** `INSERT INTO public.llab_001 ("time", user_id, station_id, device_id, measurement_id, lockin_id, kh_id)`. User and station are looked up by name; the serial numbers come from the instruments' `IDN`.
  - Values are passed as parameters. The LabVIEW VI formats them into the SQL and quotes `'NULL'`, so empty fields there are stored as the text "NULL". Python stores real NULLs.
  - **`measurement_id` is never filled today.** Every recent row has the text "NULL", because Configure Experiment passes an empty value and the format string quotes it. expconfig leaves it as a real NULL until we decide what it should hold (data folder? experiment ID?).
- **The actual schema (read 2026-10-26)** is smaller than the planned one:
  - `users`, `stations` and `table_index`;
  - 155 `llab_*` tables, which are TimescaleDB hypertables plus their `_index` tables;
  - no foreign keys.

  `llab_001` is a hypertable of about 10k rows since 2025-05. It gets a row per CONFIRM, often several identical ones.
- **Wiring in the database.** `public.wiring` (created 2026-10-26, an ordinary table, not a hypertable): `wiring_id serial PK, created, user_id, station_id, device_id, sha256 UNIQUE, wiring jsonb`. `llab_001` has a nullable `wiring_id`.
  - "Log measurement" stores the wiring document (`levylab.wiring/1`: channels, outputs, override, topology graph, about 7 KB) unless one with the same hash is already there.
  - It then inserts the `llab_001` row with that `wiring_id`. Both inserts are one transaction.
  - Both statements were checked against the real database with `EXPLAIN` (no rows written).
  - The sequence and constraints still carry the old name `wirings_*` from before the rename; this is harmless.
  - `llab_001.wiring_id` is a plain integer, not a foreign key, like `user_id` and `station_id`.
- **When to log.** Configure Experiment logs on every CONFIRM unless "I'm Finished Taking Data!" is set. expconfig logs only on "Log measurement", after showing the values. Decide whether Apply should log automatically.

## Launcher (LabVIEW, to build)

A small LabVIEW application, built as an exe like the KH and lock-in apps, in its own project or a new build spec in this one. It replaces the server-hosting part of `Configure Experiment.vi`, whose states to copy are `Transport Server: Create`, `Start`, `Stop`, `Destroy` and `Events: Register`.

1. **Start.** `Create Instrument SMO.vi` for `Inst.Transport` (as `Transport Server: Create` does), then `SMO.lvclass:Start.vi`.
2. **Start expconfig.** System Exec, without waiting for completion, of a command line from the launcher's configuration file. For the trial: `uv run --project <path to python> expconfig`. Later: a packaged `expconfig.exe`.
3. **Run.** Register for Transport's public events.
   - `UI State` (from `showUI` / `hideUI`) can show or hide the launcher window, or the Transport Server UI, which is the "show server" path.
   - Keep the window hidden by default.
4. **Exit.** On window close or a quit command: `SMO.lvclass:Stop.vi` and `Destroy.vi`. Leave expconfig running or close it; decide which.
5. **Instrument classes** are no longer chosen in Configure Experiment. Until the Transport Server UI has them (next section), the launcher can leave the instrument section of `Control Experiment.json` as Configure Experiment last wrote it.

## Instrument classes in the Transport Server UI (LabVIEW, to build)

- **The UI.** Move the instrument class selection (Configure dialog, `Instruments: Load Classes`, `Load Instrument Classes.vi`, `Installed Classes to Rings.vi`) to `Inst UI.Transport`.
- **Persistence.** Transport persists the choice itself:
  - During the trial: write `Experiment.Instruments` in `Control Experiment.json`, keeping the other sections.
  - Target: its own configuration file.
- **New command `getInstruments`** returning `[{Type, Address, class path}]`. expconfig then reads the KH and lock-in addresses from it instead of from the file.

## Model

One `Channel` row per lock-in AI, plus one `Output` row per AO. Field meanings and rules are those of the #182 spec:

- **Channel:**
  - Entered: `ai`, `electrode`, `minus`, `type` (U, V, n.c., Ground, Drive: AO n drives the pad directly through its output gain, no KH, AI n unused), `role`, `kh` (A1.., or none), `shunt`, `kh_gain`, `couple`, `filter`, `ext_gain`, `ao`.
  - Derived: `input`, `name`, `lockin_gain` = `kh_gain` × `ext_gain`.
  - `ext_gain` is the gain between the KH (or the sample) and the AI, for example an SR830 output: 10 V / sensitivity.
- **Output:**
  - Fields: `ao`, `name` (e.g. `Vbg`), `gain`, `electrode`.
  - `gain` is the lock-in output gain, i.e. the amplifier between the AO and the device, such as the 25× backgate amplifier. When a U row sources through a KH channel from that AO, the amplifier sits after the KH.
- **Derivation:**
  - U → DIFF, with the shunt as set.
  - V → SE+, or DIFF when `minus` is an electrode.
  - n.c. / Ground → OFF.
  - Name: `U<e>`, `V<e>`, `dV<e>-<minus>`.
  - All Ground and All Differential act as an apply-time override.
- **Validation:** the #182 error codes, as structured issues per row and field. Electrodes may repeat across rows (teed); KH channels may not. Read-back also reports a shunt a chassis does not have.
- **Topology:** a graph exported with the configuration (`levylab.topology/1`). Nodes are electrodes, KH channel terminals (`kh:A6:+`, `kh:A6:-`, `kh:A6:out`), AIs, AOs, ground and gain stages; edges are the cables, plus the shunt.
- **Adopt instrument state** copies the KH gain, shunt, coupling and filter, and the lock-in output gains, into the table. It also recovers the external gain (never saved by the old Configure Experiment) as lock-in input gain ÷ KH gain, for rows still at 1. KH channels that were never configured (OFF) are skipped.

## Application

- PySide6 desktop app, run from VS Code (`uv run expconfig`). `--no-db` skips the database; `--demo` and `--sim` give a configuration and instruments that need no hardware.
- Main parts:
  - experiment info, with user and station dropdowns from the database;
  - the channel table, with per-cell editors, derived columns read-only, and invalid cells marked with the reason;
  - set-all controls: Coupling, Filter, All Ground / All Differential;
  - no separate outputs table: AO and output gain are columns of the channel row, and a Drive row covers an AO that drives a pad without a KH channel;
  - the wiring view and the topology JSON;
  - instrument connections: Read back, Adopt, Apply;
  - Log measurement.
- Apply writes the KH (one `setAllChannels` per chassis) and the lock-in input and output gains, then reads them back and shows any difference.
- A simulated KH and lock-in (`uv run expconfig-sim`) speak the same protocol, so the app and the tests run without hardware.
- A marimo notebook is possible later on the same package.

## Open questions

- **Multiple KH chassis.** The prototype assumes one KH server address per chassis (A = first). Check against how `KH: Open` builds its KH class array.
- **LabVIEW reading a Python-written file.** Whether `JSON to Control Experiment Class.vi` accepts the added keys is untested. This matters only during the trial.
- **`measurement_id`.** Decide what it should hold, and whether Apply should log automatically.
- **Home.** This repo, FLEX, or a package of its own.
