# Issue #182 - Channel configuration: one table, remote set/get (change spec)

**Goal.** Replace the Lockin and Krohn-Hite tables in `Configure Experiment.vi` with one table, one row per channel (AI = KH channel). The user enters the cabling, type, role and shunt. The KH input and the channel name are derived. Add Transport Server commands `setChannelConfig` and `getChannelConfig` that act on the same rows. A remote set takes effect at once, like pressing CONFIRM.

**Scope.** Read with lvkit on `develop` at 2.7.0.65 (2026-10-22). The CONFIRM path and both label mappings were confirmed by a LabVIEW render. lvkit scrambles local-variable names and class private-data field labels, so check field names on the diagram.

## Model

Standard cabling: KH + to an electrode, KH - to an AO (normally the same index), KH output to AI. Shunt (including Open) is set per channel in software.

| Type | Minus | KH input | Shunt | Name |
| --- | --- | --- | --- | --- |
| U | "" (the row's AO) | DIFF | as set | `U<electrode>` |
| V | "", `GND` or `n.c.` | SE+ | Open | `V<electrode>` |
| V | an electrode | DIFF | Open | `V<electrode>-<minus>` = V(+) - V(-) |
| n.c. / Ground | any | OFF | Open | "" |

- **Role** is separate from Name. It is the label the experiments use to find channels: `I+`, `I-`, `V1+`, `V1-`, `V2+`, `V2-`, `dV1`, `Vsg`, and so on. `Get Channel Indices.vi` (used by Lockin_time and Lockin_sweep for R and G) looks channels up by these names. Example: `U1` with role `I+` is the current source; `U2` with role `Vbg` is a gate.
- **KH Configuration (All Ground / All Differential), DC Coupled and BW Filter** stay global, applied over the rows as today. A remote command for them (`setKHConfig`) is a later issue.
- **`Control Experiment.json` stays.** FLEX `src/flex/exp/CESession.py` reads its `Wiring Configuration` (`Lockin Ch`, `KH.Electrodes`, `KH.Labels`). Keep writing v1 with `Labels` = Role, and add the rows next to it.
- **The server answers from its own cache, not the file.** Configure Experiment pushes the rows to Inst.Transport after every apply, with a protected command. Handle Command validates and answers get from that cache, so errors reach the client.

## Edits

### 1. Typedefs in `src\Control Experiment\Typedefs`

1. **New `Channel Type--enum.ctl`**: `U, V, n.c., Ground`.
2. **Reshape `Wiring Description--v2--cluster.ctl`**. Nothing uses it today: `Write Wiring Configuration v2.vi` has no callers.
   - `AI { Channel U32, Gain DBL }`. Gain is the external gain (today's "Other: Gain" column), default 1.
   - `Device { Electrode String, Minus String, Type Channel Type--enum, Role String, Name String }`. Name is derived. Make Role and Minus combo boxes in the typedef.
   - `KH { Channel U16, Configuration Input--Enum, Gain gain--enum, Shunt Resistor shunt--enum }`. Channel is the KH # index, 0-15 = A 1 .. B 8. Configuration is derived.
   - `AO { Channel U32, Gain DBL }`.
3. **New `Channel Config Entry--cluster.ctl`** (one element of a remote set): `AI I32` (default -1), `AO I32` (default -1 = unchanged), `Gain DBL` (default NaN = unchanged), and `Electrode, Minus, Type, Role, Shunt, KH Gain` as **String** ("" = unchanged). Strings, because `JSON to LVtype.vim` silently defaults missing or misspelled keys. A typed enum would hide a bad value.
4. **`UI Controls --cluster.ctl`** (persisted to configuration.ini): add `Channels [Wiring Description--v2]`. Keep `Lockin` and `KH` for one release, read only by the migration (edit 3.7).

### 2. Control Experiment.lvclass: new methods (`src\Control Experiment\API` unless noted)

1. **`Role Strings.vi`**: returns the role list. Use today's list from `UI: Initialize`: `'', I+, I-, V1+, V1-, V2+, V2-, V3+, V3-, V4+, V4-, dV1, dV2, dV3, Vsg, Vbg, Vtg`.
2. **`Derive Channel.vi`** (row in, row out): sets `KH.Configuration`, forces `KH.Shunt Resistor` to Open unless Type = U, and builds `Device.Name`, all per the model table. This replaces the inline mappings in event [13] and `KH: set KH 1`.
3. **`Set Channel Configuration.vi`**
   - Inputs: rows, `[Channel Config Entry]`, Default Resistor.
   - Outputs: rows, error.
   - For each entry, find the row whose `AI.Channel` = AI and apply each field that is not unchanged. Parse `Type`, `Shunt` and `KH Gain` against the enum strings. Minus accepts `""`, `GND`, `n.c.`/`nc`, or any other text, which is taken as an electrode. When Type becomes U and the shunt is Open, use Default Resistor. Then call Derive Channel. Role is free text.
   - Errors (no partial apply: on any error, return the input rows unchanged):
     - 5000 `AI` missing
     - 5001 `AI` not in the table
     - 5002 bad `Type`
     - 5003 bad `Shunt`
     - 5004 bad `KH Gain`
     - 5005 Minus equals Electrode
   - Each error message names the entry index and the offending value.
4. **`Get Channel Configuration.vi`**: C.E. in, rows out (reads `Wiring Configuration v2`). Pair it with the existing `Write Wiring Configuration v2.vi`.
5. **`Rows to Wiring v1.vi`**: rows in, v1 `Wiring Description` out.
   - `Lockin Ch` ← AI.Channel, `KH.Electrodes` ← Electrode, `KH.Labels` ← Role.
   - `not KH` is passed through from the existing `non KH` control, which is unchanged in this issue.
6. **`Migrate Wiring v1 to v2.vi`**: old `Lockin` and `KH` UI clusters plus the old label list in, rows out.
   - Per index: Electrode as is; Role = label string; KH # and KH Gain as they were.
   - Shunt: kept for types that use one, Open otherwise.
   - Type: Current → U, Gate → U, Voltage (SE) → V, Voltage (Diff) → V, Ground → Ground.
   - AI.Gain = 1, AO = AI.
   - Old Voltage (Diff) rows lose their second electrode (old files never stored it). Note this in the release notes.
7. **`Apply Channel Configuration.vi`**: the body of today's `KH: set KH 1` plus `KH: set KH 2`, with rows as the input instead of the Lockin and KH clusters.
   - Inputs: C.E., rows, KH Configuration, DC Coupled, BW Filter, Channel Settings, KH class array, Lockin.
   - Outputs: C.E., Channel Settings, rows (with the KH read-back), error.
   - KH Configuration overrides per channel as today: All Ground → OFF; All Differential → DIFF + the row's shunt.
   - `Multiply Gains` takes AI.Gain from the rows.
   - Ends with `Write Wiring Configuration v2.vi`.

### 3. `src\Control Experiment\Configure Experiment.vi`

**Front panel**
1. Delete the `Lockin` and `KH` clusters, the `Gain` array and `Label Strings`. Add `Channels`, an array of `Wiring Description--v2` with a vertical scrollbar.
   - Columns: AI, Electrode, Minus, Type, Role, Shunt, KH #, KH Gain, External Gain, AO.
   - Derived: KH input and Name, disabled.
   - AI is disabled: it equals row + 1, which `Get Channel Indices.vi` assumes.
   - Use `Frontpanel Scratchpad.vi` as the layout start.

**Events**
2. Delete event [1] `Label Strings` and event [15] (scroll), and delete the state `UI: Link Scroll Bars`.
3. Replace event [13] `Lockin.Label` with `Channels: Value Change`: run `Derive Channel` on every row, write `Channels`, and set `Values have changed` True.
4. In event [14], replace the Lockin, KH and Gain sources with `Channels`.
5. In events [16] `AI Channels` and [17] `KH Chassis`, resize `Channels` instead of Lockin, KH and Gain.
   - New rows: AI = row + 1, KH # = row, AO = row + 1, Type = n.c., AI.Gain = 1.
   - Keep the queued states, with the changes in 3.10.

**States**
6. `UI: Initialize`: write `Role Strings.vi` to the Role combo box strings, and `"", GND, n.c.` to the Minus combo box strings.
7. `Data: Initialize`, `Data: Save Controls`, `UI: Update Controls`: use `Channels` in place of Lockin, KH and Gain.
   - After `Data: Load Configuration`: if `Channels` is empty and the old `Lockin.AI` is not, fill `Channels` with `Migrate Wiring v1 to v2.vi`.
8. `KH: set KH 0`: set the KH # ring strings on the `Channels` array element.
9. `UI: Disable KH SR`: set the shunt Disabled Items on the `Channels` array element.
10. `Metadata: Update AI`: resize `Channels` to AI Channels. Delete `Metadata: Update KH` and remove it from the queued strings in events [16]/[17] and in `Macro: Initialize Metadata`.
11. `Metadata: Update Wiring Configuration`: v1 from `Rows to Wiring v1.vi`, and `Write Wiring Configuration v2.vi` into C.E.
12. Replace the states `KH: set KH 1` and `KH: set KH 2` with one state, **`KH: Apply`**, that calls `Apply Channel Configuration.vi` and writes the read-back rows to `Channels`.
    - In `Macro: Output`'s string, replace `KH: set KH 1\nKH: set KH 2` with `KH: Apply\nTransport Server: Update Channel Config`.
    - In events [16]/[17], replace `KH: set KH 1` with `KH: Apply`.
13. New state **`Transport Server: Update Channel Config`**: call `Inst.Transport` `API\updateChannelConfig.vi` (edit 4.6) with `Channels`. Append it to the end of `Macro: Initialize` too, so the server has rows from startup.
14. `Events: Register`: register the new `Channel Config` public event next to `UI State`.
15. New event frame **`<Channel Config>: User Event`**:
    - Call `Set Channel Configuration.vi` with `Channels`, the event data and Default Resistor.
    - No error: write `Channels`, then queue `Macro: Output`, the same as CONFIRM.
    - Error: leave `Channels` unchanged and queue nothing. Do not route it to the dialog error handler, because Handle Command has already validated the request (edit 4.4), so an error here means the table changed in between.

### 4. Inst.Transport (`src\Transport Server\Inst.Transport`)

1. **`Typedefs\Inst.Transport.PublicCommands--Enum.ctl`**: append `setChannelConfig`, `getChannelConfig`.
2. **`Typedefs\Inst.Transport.ProtectedCommands--Enum.ctl`**: append `updateChannelConfig`.
3. **Private data**: add `Channel Config : [Wiring Description--v2]`.
4. **`Overrides\Commands\Handle Command.vi`**
   - New frame **`setChannelConfig`**:
     1. Parse with `JSON to LVtype.vim` against `setChannelConfig--Request--Cluster` (`{Channels: [Channel Config Entry]}`, new, in `Typedefs`).
     2. If the cached `Channel Config` is empty, return error 5006 "Channel configuration not available: Configure Experiment has not published it."
     3. If the cached status is running, return error 5007 "Experiment running: channel configuration not changed."
     4. Run `Set Channel Configuration.vi` on the cache and discard the rows, keeping only the error.
     5. No error: `sendMessageToProcess` with the parsed `Channels` as the Data variant.
   - **Check the status field:** the `setStatus` frame writes status into private data, but lvkit can't name the field reliably, so confirm it on the diagram. If no status field exists there, drop step 3 here; Process.vi still refuses (edit 4.5).
   - New frame **`getChannelConfig`**: Unbundle `Channel Config` and Bundle it into `getChannelConfig--Reply--Cluster` (`{Channels: [Wiring Description--v2]}`, new). Return error 5006 if it is empty.
   - New frame **`updateChannelConfig`** (protected): Variant To Data `[Wiring Description--v2]` into `Channel Config`. Nothing is forwarded, as in the `setStatus` frame.
5. **`Process.vi`**
   - In the MessageToProcess event frame, add a `setChannelConfig` case that stores Data and queues `Transport: setChannelConfig`, like `setSweepConfig`.
   - New state **`Transport: setChannelConfig`**:
     - If `Status` = running, queue `Action: Status >> Experiment running: channel configuration not changed` (as `Transport: startTransport` does).
     - Otherwise Generate User Event on the `Channel Config` public event with the stored entries.
6. **API VIs**, modelled on `setSweepConfig.vi`, `getSweepConfig.vi` and `showUI.vi`:
   - `API\setChannelConfig.vi` (Channels in)
   - `API\getChannelConfig.vi` (Channels out, via `JSON to LVtype.vim` on Client's reply)
   - `API\updateChannelConfig.vi` (protected; Write Client Type Local like `showUI.vi`)
7. **`Typedefs\PublicEvents--Cluster.ctl`**: add `Channel Config : UserEvent refnum{[Channel Config Entry]}`.
   - **Render `Overrides\CreatePublicEvents.vi` before editing it.** lvkit shows it bundling a bare refnum while `GetPublicEvents` unbundles a cluster.
   - Create the new event there, the same way as `UI State`. `DestroyPublicEvents.vi` destroys every field by Type Cast, so it needs no change.
8. **Help**: add the three commands to `Overrides\SMO\Get SMO HELP.vi` and `Documentation.vi`, as for the #181 commands.

### 5. Control Experiment.json

1. In `subVIs\Control Experiment Class to JSON.vi` and `JSON to Control Experiment Class.vi`, add the key **`Channels`** (`Wiring Configuration v2`) next to `Wiring Configuration`.
   - FLEX ignores unknown keys, and v1 keeps its meaning.
   - An old file without `Channels` loads with an empty array; that is not an error.

### 6. Check, no edit expected

- **Configure Experiment.vi**: Search for remaining uses of the deleted Lockin, KH, Gain and Label Strings controls, using the local-variable list. Local names in lvkit are wrong, so check on the diagram. The VI will not run until all of them are gone.
- **`Get Channel Indices.vi`, `Comments.Add Wiring Description.vi`, Sweep Control `Continuous B sweep.vi`**: they read v1. They get Role in `Labels` as before.
- **`Mini Configure Experiment.vi`**: touches only Experiment fields.

## Tests

1. Start Configure Experiment from an old configuration.ini. The table is migrated from the old Lockin/KH, roles match the old labels, and CONFIRM writes the same KH settings as before the change for the same channels.
2. In the UI, set row 1 to U, electrode 1, role I+, 5k, and row 3 to V, electrode 3, Minus 4, role V1+. Names show `U1` and `V3-4`; KH input DIFF and DIFF; row 3 shunt is forced to Open. After CONFIRM, `getAllChannels` reads back the same values.
3. Run Lockin_time: R and G find their channels by role, as before.
4. `setChannelConfig` with `{"Channels":[{"AI":2,"Type":"V","Electrode":"7"}]}`: the reply has no error. The table and the KH change without pressing CONFIRM. `getChannelConfig` returns row 2 as `V7`, SE+.
5. `setChannelConfig` errors, each returned to the client, with nothing changed:
   - missing `AI` (5000)
   - `AI: 99` (5001)
   - `Type: "X"` (5002)
   - `Shunt: "7k"` (5003)
   - while an experiment runs (5007, or the Action: Status message if 4.4's status check was dropped)
   - before Configure Experiment is open (5006)
6. `Control Experiment.json` after CONFIRM has `Wiring Configuration` with roles in `KH.Labels`, plus `Channels`. FLEX `CESession` still shows the wiring.
7. The existing Transport and Inst.Transport tests still pass.

## Release

Feature release.
- Release notes: the new table, roles vs names, the two commands and their payload, and the error codes. Also say that old dV rows need their second electrode re-entered.
- Tell @pgwijesinghe (FLEX): `getChannelConfig` replaces reading the wiring from the json file, and `Channels` is now in the file.
