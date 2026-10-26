# Issue #182 - Channel configuration: one table, remote set/get (change spec)

**Goal.** Replace the Lockin and Krohn-Hite tables in `Configure Experiment.vi` with one table: an array of clusters, one row per lock-in AI. The user enters the cabling, type, role and shunt. The KH input and the channel name are derived. Add Transport Server commands `setChannelConfig` and `getChannelConfig` that act on the same rows. A remote set takes effect at once, like pressing CONFIRM. Write the rows into every TDMS data file, so the files carry a machine-readable channel map.

**Scope.** Read with lvkit on `develop` at 2.7.0.65 (2026-10-22/23). The CONFIRM path and both label mappings were confirmed by a LabVIEW render. lvkit scrambles local-variable names and class private-data field labels, so check field names on the diagram.

## Model

Standard cabling: KH + to an electrode, KH - to an AO, KH output to AI. Shunt (including Open) is set per channel in software.

- **Numbering.** AI and AO are numbered continuously from 1, because their clocks are synchronized whatever the chassis, card and channel layout. KH channels are A1..A8, B1..B8, C1.., with at most 8 per chassis.
- **Each row is one AI.** Row n is AI n. By default it uses KH channel n (A1 for AI 1, B1 for AI 9) and AO n. The user can change both per row, for example to skip a broken KH channel or to route an AI around the KH (`none`).

| Type | Minus | KH input | Shunt | Name |
| --- | --- | --- | --- | --- |
| U | "" (the row's AO) | DIFF | as set | `U<electrode>` |
| V | "", `GND` or `n.c.` | SE+ | Open | `V<electrode>` |
| V | an electrode | DIFF | Open | `V<electrode>-<minus>` = V(+) - V(-) |
| n.c. / Ground | any | OFF | Open | "" |

- **Role is separate from Name.** Role is the label the experiments use to find channels: `I+`, `I-`, `V1+`, `V1-`, `V2+`, `V2-`, `dV1`, `Vsg`, and so on. `Get Channel Indices.vi` (used for R and G in Lockin_time and Lockin_sweep) looks channels up by these names. Example: `U1` with role `I+` is the current source; `U2` with role `Vbg` is a gate.
- **AI is the data column index.** The experiment VIs name data columns by position (`AI3`, `X3`, `Y3`), and `Get Channel Indices.vi` assumes AI = row + 1. A file's columns therefore join to its rows on AI.
- **KH Configuration (All Ground / All Differential), DC Coupled and BW Filter** stay global, applied over the rows as today. The row stores the per-channel result as read back from the KH. A remote command for them (`setKHConfig`) is a later issue.
- **`Control Experiment.json` stays.** FLEX `src/flex/exp/CESession.py` reads its `Wiring Configuration` (`Lockin Ch`, `KH.Electrodes`, `KH.Labels`). Keep writing v1 with `Labels` = Role, and add the rows next to it.
- **The server answers from its own cache, not the file.** Configure Experiment pushes the rows to Inst.Transport after every apply, with a protected command. Handle Command validates and answers get from that cache, so errors reach the client.
- **Why an array of clusters.**
  - A row is one value, so rows cannot fall out of step. Today `Initialize KH Array.vi`, `Metadata: Update AI`/`KH` and `UI: Link Scroll Bars` exist to keep parallel arrays aligned.
  - It serializes as `[{...}]`, the shape API and Python clients want.
  - The cost: array-element properties apply to every row. A single cell cannot be greyed out, and different chassis cannot have different shunt Disabled Items. Rules are therefore enforced in `Derive Channel.vi`, not in the control, so the UI and the API share them.

## Edits

### 1. Typedefs in `src\Control Experiment\Typedefs`

1. **New `Channel Type--enum.ctl`**: `U, V, n.c., Ground`.
2. **New `Channel--cluster.ctl`** (one row; the layout starts from `Tests\Frontpanel Scratchpad.vi`):
   - `AI U32`: the data column index.
   - `Electrode String`.
   - `Minus String`: a combo box.
   - `Type Channel Type--enum`.
   - `Role String`: a combo box.
   - `Name String`: derived.
   - `KH # I32`: a 0-based index across chassis (A1..A8 = 0..7, B1..B8 = 8..15, ...), or -1 = `none` (not through a KH).
     - Show it as a ring whose Strings And Values are built at runtime from the chassis count (edit 3.8), so -1 can display as `none`.
     - Default: row - 1, or `none` if the row is beyond 8 × chassis.
     - User-editable.
   - `KH channelProperties--Cluster`: from the Krohn Hite 7008 package, `{channel, gain, input, shunt, couple, filter}`. Input is derived. After apply, the whole cluster holds the read-back.
   - `External Gain DBL`: today's "Other: Gain" column, default 1.
   - `Lockin Gain DBL`: derived, what `Multiply Gains` sends to `setInputGain`.
   - `AO U32`.
3. **New `Channel Config Entry--cluster.ctl`** (one element of a remote set):
   - `AI I32` (default -1).
   - `AO I32` (default -1 = unchanged).
   - `External Gain DBL` (default NaN = unchanged).
   - `Electrode, Minus, Type, Role, KH, Shunt, KH Gain` as **String** ("" = unchanged). `KH` takes the form `A1`, `B3` or `none`.
   - Strings, because `JSON to LVtype.vim` silently defaults missing or misspelled keys, so a typed enum would hide a bad value.
4. **`UI Controls --cluster.ctl`** (persisted to configuration.ini): add `Channels [Channel--cluster]`. Keep `Lockin` and `KH` for one release, read only by the migration (edit 3.7).
5. **`Control Experiment JSON--cluster.ctl`**: add `Channels [Channel--cluster]` after `Wiring`. This cluster becomes the TDMS file property `<ControlExperiment>` (edit 3.12).
6. **Delete `Wiring Description--v2--cluster.ctl`** and `API\Write Wiring Configuration v2.vi`. This is an abandoned design: the VI has no callers.

### 2. Control Experiment.lvclass

1. **Private data:** rename the field `Wiring Configuration v2` to **`Channels`** and retype it to `[Channel--cluster]`. Nothing reads it, and only `Write Wiring Configuration v2.vi` (no callers, deleted in 1.6) writes it. Confirmed by render, 2026-10-23.
   - `Comments.Add Wiring Description.vi` reads only `Wiring Configuration.{Lockin Ch, KH.Electrodes, KH.Labels, not KH.Electrodes, not KH.Labels}`.
   - `Get Channel Indices.vi` reads a `[String]` `Labels` field. The diagram shows it with a short name. It is a v1 Labels field, presumably `KH.Labels`: hover over the unbundle to confirm.
2. **New methods** (in `API`):
   1. **`Role Strings.vi`**: returns the role list. Use today's list from `UI: Initialize`: `'', I+, I-, V1+, V1-, V2+, V2-, V3+, V3-, V4+, V4-, dV1, dV2, dV3, Vsg, Vbg, Vtg`.
   2. **`Derive Channel.vi`** (row in, row out): sets `KH.input`, forces `KH.shunt` to Open unless Type = U, and builds `Name`, per the model table. This replaces the inline mappings in event [13] and `KH: set KH 1`.
   3. **`Set Channel Configuration.vi`**
      - Inputs: rows, `[Channel Config Entry]`, Default Resistor, KH chassis count. Outputs: rows, error.
      - For each entry, find the row with that `AI` and apply each field that is not unchanged. Parse `Type`, `Shunt` and `KH Gain` against the enum strings. Parse `KH` as letter + 1..8 (index = 8 × letter + channel - 1), or `none`. Minus accepts `""`, `GND`, `n.c.`/`nc`, or any other text, which is taken as an electrode. When Type becomes U and the shunt is Open, use Default Resistor. Then run Derive Channel.
      - Role is free text.
      - Errors: 5000 `AI` missing, 5001 `AI` not in the table, 5002 bad `Type`, 5003 bad `Shunt`, 5004 bad `KH Gain`, 5005 Minus equals Electrode, 5008 bad `KH` (malformed, or beyond the chassis count), 5009 the same KH channel on two rows (checked on the merged rows, so a swap in one request works). Each message names the entry index and the value.
      - On any error, return the input rows unchanged.
   4. **`Read Channels.vi` / `Write Channels.vi`**: accessors for the `Channels` field.
   5. **`Channels to Wiring v1.vi`**: rows in, v1 `Wiring Description` out.
      - `Lockin Ch` ← AI, `KH.Electrodes` ← Electrode, `KH.Labels` ← Role.
      - `not KH` is passed through from the existing `non KH` control, which is unchanged in this issue.
   6. **`Migrate Wiring v1 to Channels.vi`**: old `Lockin` and `KH` UI clusters plus the old label list in, rows out.
      - Per index: Electrode as is; Role = label string; KH gain as it was.
      - KH # as it was. The old ring's last item is `none` (value 8 × chassis); map it to -1.
      - Shunt: kept for types that use one, Open otherwise.
      - Type: Current → U, Gate → U, Voltage (SE) → V, Voltage (Diff) → V, Ground → Ground.
      - External Gain = 1, AO = AI.
      - Old Voltage (Diff) rows lose their second electrode (old files never stored it). Note this in the release notes.
   7. **`Apply Channel Configuration.vi`**: the body of today's `KH: set KH 1` plus `KH: set KH 2`, with rows as the input instead of the Lockin and KH clusters.
      - Inputs: C.E., rows, KH Configuration, DC Coupled, BW Filter, Channel Settings, KH class array, Lockin.
      - Outputs: C.E., Channel Settings, rows, error.
      - Each row writes the KH channel at its `KH #`: chassis = KH # div 8 selects the element of the KH class array, and channel = KH # mod 8 + 1 is the only number sent to that chassis's driver.
      - The letters in `A1`, `B1` are display-only: they are never sent to a chassis.
      - This replaces today's Scan From String of the ring text and `Letter to Number.vi`, which do the same thing.
      - Rows with `none` write nothing. KH channels that no row uses keep the defaults from `KH: set KH 0`.
      - KH Configuration overrides per channel as today: All Ground → OFF; All Differential → DIFF + the row's shunt.
      - DC Coupled and BW Filter set `couple` and `filter` on every row.
      - After `getAllChannels`, copy each channel's read-back into its row's `KH` cluster.
      - `Multiply Gains` takes External Gain from the rows; write its result to `Lockin Gain`.
      - Ends with `Write Channels.vi`.

### 3. `src\Control Experiment\Configure Experiment.vi`

**Front panel**
1. Delete the `Lockin` and `KH` clusters, the `Gain` array and `Label Strings`. Add `Channels`, an array of `Channel--cluster` with a vertical scrollbar.
   - Editable: Electrode, Minus, Type, Role, KH #, Shunt, KH gain, External Gain, AO.
   - Disabled: AI (= row + 1), input, couple, filter, Name, Lockin Gain.

**Events**
2. Delete event [1] `Label Strings` and event [15] (scroll), and delete the state `UI: Link Scroll Bars`.
3. Replace event [13] `Lockin.Label` with `Channels: Value Change`: run `Derive Channel` on every row, write `Channels`, and set `Values have changed` True.
4. In event [14], replace the Lockin, KH and Gain sources with `Channels`.
5. In events [16] `AI Channels` and [17] `KH Chassis`, resize `Channels` instead of Lockin, KH and Gain.
   - New rows: AI = row + 1, KH # = row (or `none` beyond 8 × chassis), AO = row + 1, Type = n.c., External Gain = 1.
   - Existing rows keep their KH #. After a chassis count change, set any KH # now beyond the count to `none`.
   - Keep the queued states, with the changes in 3.11.

**States**
6. `UI: Initialize`: write `Role Strings.vi` to the Role combo box strings, and `"", GND, n.c.` to the Minus combo box strings.
7. `Data: Initialize`, `Data: Save Controls`, `UI: Update Controls`: use `Channels` in place of Lockin, KH and Gain.
   - After `Data: Load Configuration`: if `Channels` is empty and the old `Lockin.AI` is not, fill `Channels` with `Migrate Wiring v1 to Channels.vi`.
8. `KH: set KH 0`: set Strings And Values on the `Channels` array element's KH # ring: `A1`..`A8`, `B1`.. per chassis (values 0..8 × chassis - 1), plus `none` = -1.
9. `UI: Disable KH SR`: keep the shunt check, but apply it in `Derive Channel` instead of Disabled Items. A shunt the chassis lacks becomes the nearest available value. Remove the Disabled Items write on the array element. Keep it on `Default Resistor`.
10. `Metadata: Update AI`: resize `Channels` to AI Channels. Delete `Metadata: Update KH`, and remove it from the queued strings in events [16]/[17] and in `Macro: Initialize Metadata`.
11. Replace the states `KH: set KH 1` and `KH: set KH 2` with one state, **`KH: Apply`**, that calls `Apply Channel Configuration.vi` and writes the read-back rows to `Channels`.
    - In `Macro: Output`'s string, replace `KH: set KH 1\nKH: set KH 2` with `KH: Apply\nTransport Server: Update Channel Config`.
    - In events [16]/[17], replace `KH: set KH 1` with `KH: Apply`.
12. `Metadata: Update Wiring Configuration`: v1 from `Channels to Wiring v1.vi`, and `Write Channels.vi` into C.E. `Metadata: Write JSON`: bundle `Channels` into `Control Experiment JSON--cluster`.
13. New state **`Transport Server: Update Channel Config`**: call `Inst.Transport` `API\updateChannelConfig.vi` (edit 4.6) with `Channels` and `KH Chassis`. Append it to the end of `Macro: Initialize` too, so the server has rows from startup.
14. `Events: Register`: register the new `Channel Config` public event next to `UI State`.
15. New event frame **`<Channel Config>: User Event`**:
    - Call `Set Channel Configuration.vi` with `Channels`, the event data and Default Resistor.
    - No error: write `Channels`, then queue `Macro: Output`, the same as CONFIRM.
    - Error: leave `Channels` unchanged and queue nothing. Do not route it to the dialog error handler, because Handle Command has already validated the request, so an error here means the table changed in between.

### 4. Inst.Transport (`src\Transport Server\Inst.Transport`)

1. **`Typedefs\Inst.Transport.PublicCommands--Enum.ctl`**: append `setChannelConfig`, `getChannelConfig`.
2. **`Typedefs\Inst.Transport.ProtectedCommands--Enum.ctl`**: append `updateChannelConfig`.
3. **Private data**: add `Channels : [Channel--cluster]` and `KH Chassis : I32` to the `Configuration` cluster (today `{Folder, Comments, Sweep}`).
   - `Set Channel Configuration.vi` needs the chassis count to check `KH`.
   - The update payload is `updateChannelConfig--Request--Cluster` = `{Channels, KH Chassis}` (new, in `Typedefs`).
4. **`Overrides\Commands\Handle Command.vi`**
   - New frame **`setChannelConfig`**:
     1. Parse with `JSON to LVtype.vim` against `setChannelConfig--Request--Cluster` (`{Channels: [Channel Config Entry]}`, new, in `Typedefs`).
     2. If the cached `Channels` is empty, return error 5006 "Channel configuration not available: Configure Experiment has not published it."
     3. If private-data `Status` is running, return error 5007 "Experiment running: channel configuration not changed."
     4. Run `Set Channel Configuration.vi` on the cache and discard the rows, keeping only the error.
     5. No error: `sendMessageToProcess` with the parsed `Channels` as the Data variant.
   - New frame **`getChannelConfig`**: Bundle the cached `Channels` into `getChannelConfig--Reply--Cluster` (`{Channels: [Channel--cluster]}`, new). Return error 5006 if it is empty.
   - New frame **`updateChannelConfig`** (protected): Variant To Data `updateChannelConfig--Request--Cluster` into the cache. Nothing is forwarded, as in the `setStatus` frame.
5. **`Process.vi`**
   - In the MessageToProcess event frame, add a `setChannelConfig` case that stores Data and queues `Transport: setChannelConfig`, like `setSweepConfig`.
   - New state **`Transport: setChannelConfig`**:
     - If `Status` = running, queue `Action: Status >> Experiment running: channel configuration not changed`, as `Transport: startTransport` does. This catches a run that started after Handle Command checked.
     - Otherwise Generate User Event on the `Channel Config` public event with the stored entries.
6. **API VIs**, modelled on `setSweepConfig.vi`, `getSweepConfig.vi` and `showUI.vi`:
   - `API\setChannelConfig.vi` (Channels in).
   - `API\getChannelConfig.vi` (Channels out, via `JSON to LVtype.vim` on Client's reply).
   - `API\updateChannelConfig.vi` (protected; Write Client Type Local like `showUI.vi`).
7. **`Typedefs\PublicEvents--Cluster.ctl`**: add `Channel Config : UserEvent refnum{[Channel Config Entry]}`.
   - In `Overrides\CreatePublicEvents.vi`, create it the same way as `UI State` and bundle it into `Public Events`.
   - `DestroyPublicEvents.vi` destroys every field by Type Cast, so it needs no change.
8. **Help**: add the three commands to `Overrides\SMO\Get SMO HELP.vi` and `Documentation.vi`, as for the #181 commands.

### 5. Control Experiment.json

1. In `subVIs\Control Experiment Class to JSON.vi` and `JSON to Control Experiment Class.vi`, add the key **`Channels`** next to `Wiring Configuration`.
   - FLEX ignores unknown keys, and v1 keeps its meaning.
   - An old file without `Channels` loads with an empty array; that is not an error.

### 6. Check, no edit expected

- **Configure Experiment.vi**: Search for remaining uses of the deleted Lockin, KH, Gain and Label Strings controls, using the local-variable list. Local names in lvkit are wrong, so check on the diagram. The VI will not run until all of them are gone.
- **v1 readers** (they get Role in `Labels` as before):
  - `Get Channel Indices.vi`
  - `Comments.Add Wiring Description.vi`
  - Sweep Control `Continuous B sweep.vi`
  - FLEX `CESession`
- **`Save Transport TDMS File.vi`**: no change. `Channels` reaches the file inside the `<ControlExperiment>` property that Lockin_time and Lockin_sweep already write (`File: Write JSON`).

## Tests

1. **Migration.** Start Configure Experiment from an old configuration.ini. The table is migrated from the old Lockin/KH, roles match the old labels, and CONFIRM writes the same KH settings as before the change for the same channels.
2. **UI.** Set row 1 to U, electrode 1, role I+, 5k, and row 3 to V, electrode 3, Minus 4, role V1+.
   - Names show `U1` and `V3-4`; KH input is DIFF and DIFF; row 3's shunt is forced to Open.
   - After CONFIRM, each row's `KH` cluster equals the `getAllChannels` read-back, including couple and filter.
   - With two chassis, set AI 3 to KH `B5` and AI 4 to `none`. After CONFIRM, B5 has row 3's settings, A3 keeps its defaults, and A4 is untouched.
3. **R and G.** Run Lockin_time: R and G find their channels by role, as before.
4. **Data file.** Run Lockin_sweep and open the TDMS file. `<ControlExperiment>` contains `Channels`, and `X3` joins to the row with `AI` 3.
5. **Remote set.** `setChannelConfig` with `{"Channels":[{"AI":2,"Type":"V","Electrode":"7"}]}`:
   - The reply has no error.
   - The table and the KH change without pressing CONFIRM.
   - `getChannelConfig` returns row 2 as `V7`, SE+.
6. **Remote errors.** Each is returned to the client, with nothing changed:
   - missing `AI` (5000)
   - `AI: 99` (5001)
   - `Type: "X"` (5002)
   - `Shunt: "7k"` (5003)
   - `KH: "C1"` with two chassis (5008)
   - AI 1 and AI 2 both on `A1` (5009)
   - while an experiment runs (5007)
   - before Configure Experiment is open (5006)
7. **Json file.** `Control Experiment.json` after CONFIRM has `Wiring Configuration` with roles in `KH.Labels`, plus `Channels`. FLEX `CESession` still shows the wiring.
8. **Existing tests.** The existing Transport and Inst.Transport tests still pass.

## Release

Feature release.
- Release notes: the new table, roles vs names, the two commands and their payload, the error codes, and `Channels` in `<ControlExperiment>`. Also say that old dV rows need their second electrode re-entered.
- Tell @pgwijesinghe (FLEX): `getChannelConfig` replaces reading the wiring from the json file, and `Channels` is now in the file and in TDMS data.

## Later (separate issues)

**Structured provenance in data files.** Today everything except `<ControlExperiment>`, `<LockinSweep>` and `Sweep-Data-Valid` is free text in the TDMS `Notes` property, written only on the first save to a path. Missing from the files:
- THz_TimeDelay writes no JSON property.
- Lockin_time's `<LockinTime>` write is disabled.
- No KH or lock-in serial numbers or addresses.
- No instrument classes.
- No Transport or LabVIEW version.
- The lock-in AO and reference settings exist only as text.
- The Sweep text accumulates on appends.

**`setKHConfig`.** KH Configuration (All Ground / All Differential), DC Coupled and BW Filter.
