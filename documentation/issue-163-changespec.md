# Issue #163 - Configure Experiment forgets its instruments (change spec)

Instructions first; the evidence is at the bottom. Scope is **Stage 1 only**: stop the configuration being destroyed, without changing the file format. Stage 2 (portable class identity) and Stage 3 (per-station sets, dead field) are listed after it for reference.

**Status: all seven changes verified against develop (after 2.5.1.55) with lvkit and LabVIEW 2019 renders, 2026-09-24. None is implemented yet.** The analysis in the issue was written against an earlier version (the storage layout was confirmed at 2.4.3.52; current release is 2.5.1.55), and it is wrong in places. Where it is, the change below says so and gives a revised fix. lvkit misreports multi-value case frames, local names and private-data labels, so a location is only confirmed once it is seen on the render.

All paths are relative to `src/Control Experiment/`.

## Changes

| # | What | Why | Priority |
|---|---|---|---|
| 1 | Keep a saved-but-not-installed class in its ring instead of falling through to blank | this is what turns "cannot resolve" into "erased" | **first**, highest value - open; **verified** (lvkit + render) 2026-09-24; land with 4 |
| 2 | Queue `Instruments: Init Instruments` from OK only, not from `Macro: Exit`; add `Cancelled?` | closing the dialog with the X rewrites the set | high - open; **verified** 2026-09-24 |
| 3 | Collect instruments that fail to resolve in `Init Instruments`, report them, return the input set | a dropped instrument currently produces no error anywhere | high - open; **verified** 2026-09-24 (claim true for this caller, false for `Installed Classes to Rings.vi`) |
| 4 | Exact name match in `Find Class by Name.vi`, `Found?` on the pane, no last-element fallback | substring/regex match can configure the wrong class | medium - open; **verified** 2026-09-24 |
| 5 | Add `Loaded?` to `JSON to Control Experiment Class.vi` and the FGV; keep `C.E.` on a failed read | a missing or bad JSON gives an empty set **with no error**, so the issue's "case on the error" cannot work | high - open; **verified** 2026-09-24; **fix revised** |
| 6 | Gate the write inside `Metadata: Write FGV` on an `Instruments OK?` flag | a partial or empty set is written over a good file, from two macros | high, depends on 2, 3, 5 - open; **verified** 2026-09-24; **scope widened** |
| 7 | Test only: confirm the write replaces the file; handle a missing folder | `Write to Text File` with a path replaces the contents, so the truncation theory is unlikely | low - open; **verified** 2026-09-24 |

Suggested order: 4 and 1 together (1 alone can configure the wrong instrument), then 2, then 3, 5 and 6 together (6 consumes the flags 2, 3 and 5 produce), then the 7 test.

### Change 1 - keep an uninstalled class in its ring

**Where.** `subVIs/Installed Classes to Rings.vi`, the `Select` that picks the ring value for each saved instrument.

**Today.** The saved instrument is pre-selected only if its shortened class name matches an entry in the fresh `<user.lib>\LevyLab` scan. On no match the `Select` falls through to value 0, the blank entry. `Instruments: Init Instruments` then builds the slot from the blank `RingText`, which gives a bare `Instrument.lvclass`.

**Change.** On no match, append the saved name to that ring as an extra item, for example `<name> (not installed)`, and select it. The round trip through `RingText` then carries the name instead of blank.

**lvkit read, 2026-09-24 (develop after 2.5.1.55). Render-confirmed; see below.** The VI is one outer For loop, one iteration per ring. The loop index is converted to `Instrument Types--enum`, so ring i is instrument role i. Its only callers are `Load Instrument Classes.vi` and itself. Inside the outer loop, in order:

1. **Candidates.** A loop over `Installed` calls `Insert Instrument Class by Name.vi` for this role and collects the classes that fit through an auto-indexing conditional tunnel. The condition source is not shown by lvkit, but it is probably `Found?` (see Change 3).
2. **Saved instrument for this role.** A loop over `Experiment.Instruments` (lvkit labels the unbundle `Sweep`, a known private-data label misread; the type is `[Instruments--cluster]`) compares each `Type` with this role. It takes `class path` -> `Strip Path` -> `Shorten Class name.vi`. Pass-through tunnels give out `equal` (call it A: "a saved instrument has this role") and the short name.
3. **Rebuild the ring.** `Empty Ring StringsAndValues.vi` resets the ring to one item `{'' , 0}`. A loop then calls `Append Ring StringsAndValues.vi` for each candidate with String = shortened class name and Value = i+1, and also collects the short names.
4. **Name lookup.** `Build Array` prepends `''` to the short names. A loop compares each name with the saved short name, **case-sensitive** (B). Another loop compares the lower-cased `StringsAndValues[]` strings with the lower-cased result, **case-insensitive** (C), and unbundles `Value`.
5. **Select.** `Compound Arithmetic` (A, B, C) drives `Select`: True gives the found `Value`, False gives the EXT constant **0**, which is the `''` item. That value goes through `To Variant` to the ring's `Value` property.

So the claim holds: whenever the saved class is not among this role's candidates, the ring is set to 0, the blank entry.

**Render-confirmed, 2026-09-24 (LabVIEW 19.0.1f5).** The diagram matches the lvkit read, with these points settled:
- The unbundle is `Experiment.Instruments` (comment: "previously selected instruments"), not `Sweep`.
- All three lookup loops have a Stop-if-True terminal wired from their `Equal?`, so the pass-through tunnels carry the matched element and its flag.
- `Compound Arithmetic` is in AND mode (labelled "AND").
- `Select` takes the AND output as selector, the matched `Value` on True and a `0` constant on False, into the ring's `Value` property. The comment reads: "if found from previous set to that, else set to 0 = """.
- The candidates loop's conditional tunnel is driven by `Insert Instrument Class by Name.vi`'s `Found?` (comment: "all installed instruments of THIS type").
- `Rings` enters the outer loop through an auto-indexing tunnel. The loop index becomes the `Instrument Types--enum` role (comment: "this type").
- The `Value` property node takes the ring reference from the append loop's shift register (the `Rings` element after its items were added).

**Change, refined.** After step 4, when A is True and (B AND C) is False, call `Append Ring StringsAndValues.vi` once more on the ring reference coming out of the step-3 loop's shift register. Use String = `<short name> (not installed)` and Value = number of candidates + 1, and select that Value instead of 0. When A is False (no saved instrument for this role), blank stays correct. The two helpers already do what is needed. `Empty Ring StringsAndValues.vi` takes element 0 of the current `StringsAndValues[]` and sets it to `{'' , 0}`. `Append Ring StringsAndValues.vi` reads `StringsAndValues[]`, builds `{String, Value}` and writes the array back.

**Edit steps** (all inside the outer For loop, right-hand side of the render):
1. Replace the `Select` with a Case structure whose selector is the existing `AND` output.
   - **True frame:** pass the matched `Value` through. This is what `Select` does today.
   - **False frame:** a nested Case on A, the `equal` output of the "T if this type equals previous type" loop.
     - **A False:** output `0`. There is no saved instrument for this role, so blank is correct.
     - **A True:** call `Append Ring StringsAndValues.vi`. Ring in = the ring reference from the append loop's shift register output. String = the saved short name (that loop's second pass-through tunnel) concatenated with ` (not installed)`. Value = the append loop's iteration count + 1 (candidates + 1). Output that Value, converted to EXT.
2. Route the ring reference and the error through the new Case, and wire them on to the `Value` property node. That makes the node run after the extra item is appended. In frames that do not append, pass both through unchanged.
3. Keep `To Variant` -> `Value` as today.

**Depends on Change 4 (or 3 + 6).** The ring text `<name> (not installed)` goes on to `Instruments: Init Instruments` in `Load Instrument Classes.vi`. If that path goes through today's `Find Class by Name.vi`, there is no match, the VI returns the **last installed class**, and if that class casts to the role, the wrong instrument is configured. Change 1 alone therefore turns "blank" into "maybe wrong". Land it together with Change 4, or at least with Changes 3 and 6 so the unresolved entry blocks the write. Not yet checked that Init goes through `Find Class by Name.vi`; that is part of Change 3's read.

**Minor.** Step 4's two comparisons disagree on case (B is case-sensitive, C is not), so a saved name that differs only in case from the installed one gives blank. Low risk; fix by using one comparison when editing.

**Verify.** How to verify step 4: rename the folder of an installed instrument class, open Configure. The ring shows `<name> (not installed)`, not blank.

### Change 2 - rebuild the instrument set on OK only

**Where.** `subVIs/Load Instrument Classes.vi`, the event structure and state `Macro: Exit`. Also its caller, `Configure Experiment.vi` state `Instruments: Load Classes`.

**lvkit read and render-confirmed, 2026-09-24.**
- The event structure has three events: `[0] Timeout`, `[1] "OK": Value Change` and `[2] Panel Close?`. OK and Panel Close? both queue `Macro: Exit` in front. Panel Close? also sets `Discard?` = True. There is no Cancel button, so the X is the only way to cancel.
- `Macro: Exit` queues `Instruments: Init Instruments` in front, then `UI: Front Panel State >> Close` if `Close Panel on Exit?`, then `Data: Cleanup` and `Exit` at the back. The claim holds: closing with the X runs Init.
- After the state machine exits, the VI always passes the data cluster's `C.E.` through `Control Experiment Class to JSON.vi` and returns it as `Control Experiment`. In `Configure Experiment.vi`, `Instruments: Load Classes` bundles that output into its `C.E.` unconditionally. `Macro: Instrument Configuration Changed` then queues `UI: View Instruments` and `Metadata: Write FGV`.

**Change, refined.**
1. OK event: queue `Instruments: Init Instruments` then `Macro: Exit`. Panel Close? event: queue `Macro: Exit` only.
2. Remove `Instruments: Init Instruments` from `Macro: Exit`.
3. Add a boolean output `Cancelled?` to the connector pane, True when the dialog closed through Panel Close?. `Configure Experiment.vi` uses it in Change 6 to skip the write.

Without step 3, a cancel still returns the incoming `C.E.` and `Metadata: Write FGV` writes it back. That is harmless only if the set loaded cleanly at startup. If the restore already dropped an instrument (root cause 1), writing back makes the loss permanent.

**Render-confirmed.** `Data: Initialize` bundles the input `C.E.` into the data cluster. So without Init, the output is the input `C.E.` after its round trip through `Control Experiment Class to JSON.vi`, which the main diagram does after the state machine exits.

**Verify.** How to verify step 2: open the Configure dialog and dismiss it with the window X. The Configured Instruments list and `Control Experiment.json` (contents and timestamp) are unchanged.

### Change 3 - report instruments that could not be inserted

**Where.** `subVIs/Load Instrument Classes.vi`, state `Instruments: Init Instruments`.

**Render-confirmed: `Insert Instrument Class by Name.vi` and `Cast Instrument to Instrument Type.vi`.**
- **`Insert Instrument Class by Name.vi`:** `Found?` is NOT(status) of the cast's error. The comment reads "T == Class could be cast". `error out` then goes through `Clear Errors.vi`, so the VI never returns an error. `Found?` is on the connector pane.
- **`Cast Instrument to Instrument Type.vi`:** a Case on `Type` has one frame per role. Each frame does `To More Specific Class` onto that role's slot. A `Select` on the cast error keeps the slot's existing value, and outside the Case a second `Select` on the error returns a bare `Instrument.lvclass`. The error is passed out.

**`Instruments: Init Instruments`, lvkit read and render-confirmed 2026-09-24.**
1. **Reset.** It first bundles a constant `Instrument Classes` cluster into `C.E.`, resetting every slot to its role's base class. The diagram comment reads "#148 clear instrument classes after reading previously installed". lvkit labels the bundle `Rotator`, but the value is the whole cluster: DAQ = `Instrument.LockinAPI`, Amplifier = `Instrument.Amplifier`, Temperature/Magnet/Rotator/Level = `Instrument.Cryostat`, Capacitance = `Instrument.CBridge`, Delay Line = `Instrument.DelayLine`, Strain Cell = `Instrument.Strain`, VNA = `Instrument.VNA`, Source = `Instrument.VSource`.
2. **Per ring.** It loops over the address names and the ring references. For each ring it reads `RingText.Text` and `Label.Text`, and `Scan From String` turns the ring's **label** into the role enum. So the ring labels must match the enum item names.
3. **Case on `RingText`.** There are two frames, `""` and `Default`. lvkit reported the first as `"0"`.
   - **Blank frame:** inserts a bare `Instrument.lvclass`.
   - **Default frame:** `Find Class by Name.vi`(RingText, Installed) -> `Write SMO Address.vi`(address) -> `Set IsConfigured.vi`(True) -> `Insert Instrument Class by Name.vi`.
4. **Errors.** Neither Insert call uses `Found?` (render: its TF output is unwired in both frames), so the claim holds for this caller. Errors are auto-indexed and merged, but Insert has already cleared them, so the merge is always clean.

A failed cast therefore leaves the role's reset base class (unconfigured) in the slot, with no error and no message.

**Other callers of Insert.**
- `Installed Classes to Rings.vi` does use `Found?` (Change 1, render-confirmed).
- `JSON to Control Experiment Class.vi` has one call, with `Found?` unused (render-confirmed). That is root cause 1, handled in Change 5.

**Change, refined.**
1. In the default frame, after Change 4 use `Find Class by Name.vi`'s new `Found?` together with Insert's `Found?`. Collect the `RingText` of every ring where either is False through a conditional auto-indexing tunnel, into `Unresolved` ([String]).
2. Show the list to the user. The front panel already has a `Status` string indicator that is not on the pane; a one-button dialog naming each class is more visible.
3. Put `Unresolved` on the connector pane.
4. If `Unresolved` is not empty, return the **input** `C.E.` rather than the rebuilt one. The in-memory configuration then also survives, not just the file. The cost is that other edits made in that dialog session are dropped, and the dialog has just listed why. Keep the #148 reset for the clean path. It is deliberate (see the comment above), and it is also why a failed insert leaves an unconfigured base class rather than the previous instrument.

**Verify.** How to verify step 4: with a renamed class folder, clicking OK shows a message naming the class, and the Configured Instruments list keeps it.

### Change 4 - exact match in Find Class by Name

**Where.** `subVIs/Find Class by Name.vi`. Its only caller is `Load Instrument Classes.vi` (`Instruments: Init Instruments`, default frame).

**Render-confirmed, 2026-09-24.**
- A For loop auto-indexes `Installed Instruments`. Inside, `Get LV Class Name.vi` feeds `Match Pattern`, with string = the **qualified** class name (for example `Instrument.Lockin.lvlib:Instrument.Lockin.lvclass`) and regular expression = `Name`. `offset past match > 0` goes to a Stop-if-True terminal.
- `Instrument out` leaves through a last-value tunnel, so when nothing matches it is the **last installed class**.
- `Found?` leaves through an **auto-indexing** tunnel, so it is an array of booleans, and it is **not** on the connector pane. The pane is `Installed Instruments` 11, `Name` 10, `error in` 8, `Instrument out` 3, `error out` 0.
- The errors are auto-indexed and merged.

Matching the short name against the qualified name is why it has to be a substring search today. An exact comparison has to shorten first.

**Change, refined.**
1. Inside the loop, pass `Get LV Class Name.vi`'s output through `Shorten Class name.vi`, as `Installed Classes to Rings.vi` does to build the ring text. Compare with `Name` using `Equal?` and wire that to the stop terminal.
2. Change the `Found?` tunnel to last-value, so it is a scalar TF.
3. `Instrument out` = `Select`(`Found?`, loop element, `Instrument.lvclass` constant).
4. Put `Found?` on connector pane terminal 2, which is free in pattern 4815. Relink the caller.

With Change 1's `<name> (not installed)` ring text, there is then no match and `Found?` is False, and Change 3 reports it.

**Verify.** How to verify step 6: two installed classes whose names share a prefix (`Instrument.Lockin`, `Instrument.LockinAPI`) each resolve to themselves. Also, a ring set to `<name> (not installed)` resolves to nothing, not to the last installed class.

### Change 5 - do not wipe the configuration on a failed read

**Where.** `subVIs/JSON to Control Experiment Class.vi` and `Configure Experiment.vi` state `Metadata: Read FGV`.

**lvkit read 2026-09-24. `JSON to Control Experiment Class.vi` and `Control Experiment FGV.vi` render-confirmed; `Configure Experiment.vi` `Metadata: Read FGV` render-confirmed: the FGV's `C.E.` input is unwired and its output goes straight into `Bundle By Name` `C.E.`.**
- `Metadata: Read FGV` calls `Control Experiment FGV.vi` (read) with its `C.E.` input **unwired** (the default object). It then bundles the result into the data cluster's `C.E.` unconditionally. It is queued only from `Macro: Initialize`, after `Data: Load Configuration`.
- `Control Experiment FGV.vi` read: `Read from Text File` -> `JSON to Control Experiment Class.vi`, with the errors chained.
- `JSON to Control Experiment Class.vi`:
  - `From JSON Text` (JSONtext) gets the read error as `error in`, so on error it returns its default constant, an empty `Experiment` with an empty `Instruments` array. The result is bundled into `C.E.` unconditionally. lvkit labels those bundle terminals `User` / `Electrodes` (label misread); by type they are `Experiment`, `Wiring Configuration` and `json`.
  - The instrument loop auto-indexes `Experiment.Instruments` (lvkit label `Sweep`, same misread as in Change 1).
  - The VI's `error out` is a plain (last-value) loop tunnel from Insert's `error out`, which Insert always clears. With no entries the loop runs zero times and the tunnel gives the default, no error. **So the VI never returns an error.**

**The issue's fix does not work as written.** A missing file (error 7) or malformed JSON gives an empty configuration **with no error**, so casing on the error in `Metadata: Read FGV` would never fire.

**Change, refined.**
1. In `JSON to Control Experiment Class.vi`, add a `Loaded?` output: True only when `From JSON Text` returned no error. Wrap the bundle into `C.E.` in a Case on that error, so that on error `Control Experiment in` passes through unchanged. Also count entries whose `Get LV Class Default Value.vi` failed, or whose Insert `Found?` is False, into `Unresolved on load` (a Stage 1 hook for root cause 1).
2. Add the same `Loaded?` to `Control Experiment FGV.vi` (read frame) and put it on the pane.
3. In `Metadata: Read FGV`, keep today's bundle but also store `Loaded?` and `Unresolved on load` in the data cluster, for Change 6.

**Prefer a new output to a changed `error out`.** `Control Experiment FGV.vi` read is also called by `Lockin_time.vi`, `Lockin_sweep.vi`, `THz_TimeDelay.vi`, `Inst.Transport` `Process.vi`, three Sweep Control VIs, `Load Instrument Classes.vi` (when run top-level) and two tests. Today all of them get an empty configuration silently when the file is missing. Starting to return error 7 would change their behavior, so each would need checking first.

**Verify.** How to verify step 5: delete `Control Experiment.json` and start Configure Experiment. No empty file is written back (Change 6), and the user is told there was no saved configuration.

### Change 6 - never write a partial set

**Where.** `Configure Experiment.vi`, state `Metadata: Write FGV`.

**lvkit read and render-confirmed, 2026-09-24.** `Metadata: Write FGV` writes the data cluster's `C.E.` unconditionally. It is queued from **two** macros:
- `Macro: Instrument Configuration Changed` (event `[9] "Instrument Configuration": Value Change`): `Instruments: Load Classes`, `UI: View Instruments`, `Metadata: Write FGV`, `Instrument: Lockin Status`, `Instrument: KH Status`.
- `Macro: Write Metadata` (`Metadata: Update Comments`, `Metadata: Write JSON`, `Metadata: Write FGV`). It is queued from `Macro: Output` unless `I'm Finished Taking Data!` is True. `Macro: Output` is queued by event `[10] "Create Output": Value Change`, and also by `Data: Initialize Top Level` (together with `Macro: Exit`) whenever `Configure Experiment.vi` is **not** run top-level. The frame comment says so: "if not top level, automatically run Macro: Output, Macro: Exit". `Macro: Output`'s own comment is "Set KH7008, Write Metadata to FGV.JSON, Write Metadata to PGSQL".

The second path is not in the issue. Pressing Create Output, or running the VI as a subVI, writes the file back with whatever `Metadata: Read FGV` produced: an empty set after a failed read (Change 5), or unconfigured slots after a failed restore (root cause 1).

**Change, refined.** Gate the `Control Experiment FGV.vi` call **inside** `Metadata: Write FGV`, so both macros are covered. Keep a flag `Instruments OK?` in the data cluster:
- Set False in `Metadata: Read FGV` when `Loaded?` is False or `Unresolved on load` is not empty (Change 5).
- Set False in `Instruments: Load Classes` when `Unresolved` is not empty (Change 3). Leave it unchanged when `Cancelled?` is True (Change 2).
- Set True after a clean `Instruments: Load Classes` with no unresolved instruments. That is how a user deliberately replaces a broken set.

When the flag is False, skip the write and show why.

**Verify.** How to verify step 4: with a renamed class folder, click OK in Configure. `Control Experiment.json` is unchanged (contents and timestamp). Repeat with Create Output.

### Change 7 - file write truncation and read errors

**Where.** `API (File)/Control Experiment FGV.vi`.

**lvkit read and render-confirmed, 2026-09-24.** `read` is also the Default frame.
- The path is `Get System Directory` (type 3, LOCALAPPDATA) \ `Levylab` \ `Control Experiment` \ `Control Experiment.json`.
- Read: `Read from Text File` -> `JSON to Control Experiment Class.vi`.
- Write: `Control Experiment Class to JSON.vi` -> `Write to Text File`, with the **path** wired and no refnum.
- Nothing in the VI creates the folder.

**Truncation: likely a non-issue.** Given a path, `Write to Text File` opens or creates the file and replaces its previous contents. That is documented LabVIEW behavior, not read from this diagram. The trailing-bytes theory therefore probably does not explain the bug. Keep the check as a test and make no code change unless it fails.

**Read errors** are covered by Change 5. Separating "file does not exist" from other errors belongs in the new `Loaded?` logic there: on error 7 show "no saved configuration", on anything else show the error.

**Possible new issue: a missing folder.** If `%LOCALAPPDATA%\Levylab\Control Experiment\` does not exist, the write fails with error 7. Check whether `Configuration.lvclass:Write Configuration.vi` (the ini, same folder) creates it first. On a fresh machine the order of `Data: Save Controls` and `Metadata: Write FGV` would then matter.

**Out of scope, checked.** `API (File)/Read Control Experiment.json.vi` has no callers. `API (File)/Save JSON File.vi` is called only by Sweep Control (`Sweep Control Cartesian.vi`) and `documentation/Tree.vi`. Neither is on the instrument-set path.

**Verify.** Save a set of several instruments, then a shorter set. `Control Experiment.json` holds exactly the shorter JSON and parses.

## Also checked

- `Mini Configure Experiment.vi` does not touch the FGV or the instrument set. It only bundles device, user and paths into `Control Experiment.lvclass`. Out of scope.
- The regression baseline for every change, How to verify step 1: configure an instrument, close and reopen Configure Experiment. The list is unchanged.

## Stage 2 - store a portable identity (not in this round)

| VI / file | Change |
| --- | --- |
| `Typedefs/Instruments--cluster.ctl` | Add a `class name` (String) field beside `class path`. This typedef backs both `Experiment.Instruments` in the class private data and the JSON schema. Old JSON files simply lack the field, and JSONtext fills it with the default, so `class path` continues to work as the fallback. |
| `subVIs/Control Experiment Class to JSON.vi` | The only place the stored identity is produced. It already calls `Get LV Class Path.vi` per configured instrument; also call `Get LV Class Name.vi` (shortened via `Shorten Class name.vi`, matching what the rings use) and bundle it into the new `class name` field. |
| `subVIs/JSON to Control Experiment Class.vi` | Resolve by `class name` against the installed list first, and fall back to `class path` only when the name is not found. Keep the original entry in the array when neither resolves, so the next save does not drop it, and add an output listing what could not be resolved. |
| new: `subVIs/List Installed Instrument Classes.vi` | Factor the `Rings: List Installed` scan out of `Load Instrument Classes.vi` so the reader above and the dialog share one implementation. That scan is also where #137's "user.lib path is not resolved properly inside a compiled exe" applies, and it should be fixed in one place. |

Verify with How to verify step 3: edit `Control Experiment.json` so a `class path` points somewhere nonexistent, simulating the 32-bit to 64-bit move. The entry survives via `class name`, and nothing is silently dropped.

## Stage 3 - related, separate work

- The instrument set is a single global file. The `Type` value-change event only queues `Data: Query Database`, which repopulates the `Station` ring from PostgreSQL. Nothing loads an instrument set per Type/Station, so an AFM/Cypher configuration and a PPMS configuration overwrite each other. This overlaps with #45.
- Remove the dead `Instrument Types` field from the UI cluster, or wire it up and drop the JSON's role. It should not stay half-implemented.

## How to verify (from the issue)

1. Configure an instrument, close and reopen Configure Experiment. The list is unchanged.
2. Open the Configure dialog and dismiss it with the window X. The list is unchanged.
3. Edit `Control Experiment.json` so a `class path` points somewhere nonexistent, simulating the 32-bit to 64-bit move. The entry survives via `class name`, and nothing is silently dropped. (Stage 2)
4. Rename the folder of an installed instrument class, then open Configure. A warning names the class, the entry is preserved in the ring, and clicking OK does not erase it.
5. Delete `Control Experiment.json` and start Configure Experiment. The in-memory configuration is not wiped and no empty file is written back.
6. Two instrument classes whose names share a prefix (`Instrument.Lockin`, `Instrument.LockinAPI`) both resolve to themselves.

## Evidence

From the issue body; not yet re-checked against 2.5.1.55.

### Symptom

`Configure Experiment.vi` intermittently loses the configured set of instruments shown in the **Configured Instruments** box. The instrument set is persisted as absolute class paths, and every failure to resolve one of those paths is silently swallowed. Once a class fails to resolve, the next visit to the **Configure** dialog writes the loss back to disk, so the configuration is destroyed rather than merely hidden.

### How the configuration is stored

The instrument set is not in the ini file. Two separate files are involved, both under `%LOCALAPPDATA%\Levylab\Control Experiment\`:

| File | Written by | Contents |
| --- | --- | --- |
| `configuration.ini` | `Configuration.lvclass:Write Configuration.vi`, from state `Data: Save Controls` | UI fields only: Sample, Device, Username, Description, Default Path, KH/Lockin wiring, and the `Type` / `Station` ring text |
| `Control Experiment.json` | `Control Experiment FGV.vi` (despite the name, a file read/write, not a FGV) | The serialized `Control Experiment.lvclass` object |

The instruments live in the class's private data as `Experiment.Instruments`, an array of the `Instruments--cluster` typedef `{class path, Address, Type}`, which serializes to `Experiment.Instruments` in the JSON. (`Experiment.Sweep`, in the same cluster, is unrelated sweep configuration.) The live objects are a separate private-data field, `Instrument Classes`, a cluster with one typed slot per instrument role: DAQ, Amplifier, Temperature, Magnet, Rotator, Level, Capacitance, Delay Line, Strain Cell, VNA, Source.

Relevant state sequences in `Configure Experiment.vi`:

- `Macro: Initialize` runs `Data: Load Configuration` (ini into the UI cluster), then `Metadata: Read FGV` (JSON into the `C.E.` wire), then `UI: View Instruments`, which renders the Configured Instruments string from `Experiment.Instruments`.
- `Macro: Instrument Configuration Changed`, fired by the **Configure** button, runs `Instruments: Load Classes`, `UI: View Instruments`, then `Metadata: Write FGV`. The dialog's result is persisted immediately.

### Root cause

Each instrument is stored as an absolute path to its `.lvclass`:

```json
{
  "class path": "C:\\Program Files (x86)\\National Instruments\\LabVIEW 2019\\user.lib\\LevyLab\\Lockin-Multichannel\\Instrument.Lockin\\Instrument.Lockin.lvclass",
  "Address": "",
  "Type": "Lockin"
}
```

That path breaks whenever any of these change: 32-bit vs 64-bit LabVIEW, the LabVIEW version, the machine, a package that reorganizes its folders on upgrade, or dev environment vs built EXE (see #137, the same class of problem). On one dev machine checked, the saved file points at `C:\Program Files (x86)\...` while LabVIEW 2019 is installed under `C:\Program Files\...`, and it also references `LevyLab\PPMS Instrument\instrument.PPMS.lvclass`, which is not installed there at all.

A broken path alone would be a visible failure. Three unchecked error paths turn it into silent data loss:

1. **The restore skips the instrument and reports nothing.** In `JSON to Control Experiment Class.vi`, `Get LV Class Default Value.vi` is called on the stored absolute path. When the path is gone it errors, and the downstream `To More Specific Class`, `Write SMO Address.vi` and `Set IsConfigured.vi` all skip on error, so the slot keeps the base `Instrument.lvclass`.
2. **`Insert Instrument Class by Name.vi` swallows the error.** See Change 3.
3. **The Configure dialog rebuilds the set from the ring controls and writes the loss back.** In `Load Instrument Classes.vi`, `Rings: List Installed` rescans `<user.lib>\LevyLab` for `*.lvclass` (excluding `Instrument Framework` and `Build Support`) and keeps only classes that cast to `Instrument.lvclass` without error. `Installed Classes to Rings.vi` then blanks any saved class not in that scan (Change 1), `Instruments: Init Instruments` builds a bare `Instrument.lvclass` from the blank ring, and `Metadata: Write FGV` persists it. Because Init is queued from `Macro: Exit`, closing the dialog with the X does this too (Change 2).

### Two further defects found while tracing this

- **`Find Class by Name.vi` can return the wrong class.** See Change 4. In practice the subsequent cast usually fails and the slot is left empty, but where the last-scanned class happens to cast, this silently configures the wrong instrument.
- **The `Instrument Types` field is dead code.** The persisted UI cluster carries an `Instrument Types` array. It is read from the ini in `Data: Load Configuration`, but it is never bundled in `Data: Save Controls` and never applied to `C.E.`. It looks like an abandoned attempt to solve exactly this problem (Stage 3).

## Affected files

- `src/Control Experiment/Configure Experiment.vi`
- `src/Control Experiment/subVIs/Load Instrument Classes.vi`
- `src/Control Experiment/subVIs/Installed Classes to Rings.vi`
- `src/Control Experiment/subVIs/JSON to Control Experiment Class.vi`
- `src/Control Experiment/subVIs/Control Experiment Class to JSON.vi`
- `src/Control Experiment/subVIs/Insert Instrument Class by Name.vi`
- `src/Control Experiment/subVIs/Cast Instrument to Instrument Type.vi`
- `src/Control Experiment/subVIs/Find Class by Name.vi`
- `src/Control Experiment/Typedefs/Instruments--cluster.ctl`
- `src/Control Experiment/API (File)/Control Experiment FGV.vi`

All ten exist on develop. Not in the issue but worth a look: `Mini Configure Experiment.vi`, `API (File)/Read Control Experiment.json.vi`, `API (File)/Save JSON File.vi`.

## Related

#137, #148, #150, #45
