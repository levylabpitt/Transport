# Issue #163 - Configure Experiment forgets its instruments (change spec)

**Problem.** The instrument set is saved as absolute class paths in `%LOCALAPPDATA%\Levylab\Control Experiment\Control Experiment.json`. When a path no longer resolves (32/64-bit, LabVIEW version, package moved), the instrument is dropped silently, and the next save writes the loss to disk.

**Scope.** Stop the configuration being destroyed. The file format does not change. Every location below was checked against develop (after 2.5.1.55) with lvkit and LabVIEW 2019 renders on 2026-09-24. Paths are relative to `src/Control Experiment/`.

**Order.** Do the edits in the order below. Edits 1 and 2 must ship together: edit 2 alone lets the wrong instrument be configured.

## Edits

### 1. `subVIs/Find Class by Name.vi`

Today it uses a substring/regex match against the full qualified class name. On no match it returns the last installed class. Its `Found?` output is an array, and it is not on the connector pane.

1. Inside the For loop, pass `Get LV Class Name.vi`'s output through `Shorten Class name.vi`.
2. Replace `Match Pattern` and `> 0` with `Equal?`(short name, `Name`), and wire it to the stop terminal.
3. Change the `Found?` output tunnel from auto-indexing to last-value.
4. `Instrument out` = `Select`(`Found?`, loop element, `Instrument.lvclass` constant).
5. Put `Found?` on connector pane terminal 2, then relink the only caller, `Load Instrument Classes.vi`.

### 2. `subVIs/Installed Classes to Rings.vi`

Today, if the saved instrument isn't installed, its ring is set to 0 (blank), and the blank is then saved.

All the edits are inside the outer For loop, at the right-hand end:

1. Replace the final `Select` (the one fed by the `AND`, with the `0` constant) with a Case structure on the `AND` output.
   - **True:** pass the matched `Value` through, as today.
   - **False:** add a nested Case on the `equal` output of the "T if this type equals previous type" loop.
     - **False:** output `0`, because no instrument is saved for this role.
     - **True:** call `Append Ring StringsAndValues.vi`. Ring in = the ring reference from the append loop's shift register. String = the saved short name + ` (not installed)`. Value = the append loop's iteration count + 1. Output that Value as EXT.
2. Wire the ring reference and the error through the Case to the `Value` property node, so the item is appended before the value is set.

### 3. `subVIs/Load Instrument Classes.vi`

Today, closing the dialog with the X rebuilds the set just like OK does, and instruments that fail to resolve are dropped with no message.

1. **Event `[1] "OK": Value Change`:** queue `Instruments: Init Instruments` then `Macro: Exit`.
2. **Event `[2] Panel Close?`:** keep queuing only `Macro: Exit`.
3. **State `Macro: Exit`:** remove `Instruments: Init Instruments` from its queue.
4. Add an output `Cancelled?` (TF) to the connector pane, True when the dialog closed through Panel Close?.
5. **State `Instruments: Init Instruments`, `Default` frame of the Case on `RingText`:** collect `RingText` wherever `Find Class by Name.vi`'s `Found?` (edit 1) or `Insert Instrument Class by Name.vi`'s `Found?` is False. Use a conditional auto-indexing tunnel into a new `Unresolved` ([String]) array, and put `Unresolved` on the connector pane.
6. If `Unresolved` isn't empty, show a one-button dialog listing the names, and return the input `C.E.` instead of the rebuilt one.

Keep the constant `Instrument Classes` reset at the start of `Instruments: Init Instruments` (the #148 comment).

### 4. `subVIs/JSON to Control Experiment Class.vi` and `API (File)/Control Experiment FGV.vi`

Today a missing or unreadable JSON file gives an empty configuration and **no error**: `From JSON Text` returns defaults, and the loop's error comes from `Insert Instrument Class by Name.vi`, which clears it.

1. **`JSON to Control Experiment Class.vi`:**
   - Add an output `Loaded?` = no error out of `From JSON Text`.
   - Put the `Bundle By Name` into `C.E.` inside a Case on that error. On error, pass `Control Experiment in` through unchanged.
   - Add an output `Unresolved on load` ([String]): the `class path` of every entry where `Get LV Class Default Value.vi` errored or Insert's `Found?` is False.
2. **`Control Experiment FGV.vi`:** pass `Loaded?` and `Unresolved on load` out of the `read` frame, and put them on the connector pane.

Don't change `error out`. The FGV is also read by `Lockin_time.vi`, `Lockin_sweep.vi`, `THz_TimeDelay.vi`, `Inst.Transport` `Process.vi` and the Sweep Control VIs, and a new error would change what they do.

### 5. `Configure Experiment.vi`

Today `Metadata: Write FGV` always writes. It runs from `Macro: Instrument Configuration Changed`, and also from `Macro: Output`, which runs on Create Output and automatically when the VI isn't run top-level.

1. Add a boolean `Instruments OK?` to the data cluster.
2. **`Metadata: Read FGV`:** set `Instruments OK?` = `Loaded?` AND `Unresolved on load` is empty. If there's no saved configuration or entries are unresolved, tell the user: error 7 means "no saved configuration"; show other errors as they are.
3. **`Instruments: Load Classes`:**
   - If `Cancelled?` is True, leave `C.E.` and `Instruments OK?` unchanged.
   - Otherwise set `Instruments OK?` = `Unresolved` is empty.
4. **`Metadata: Write FGV`:** put the `Control Experiment FGV.vi` (write) call inside a Case on `Instruments OK?`. When it is False, skip the write and show why.

### 6. `API (File)/Control Experiment FGV.vi`: test only

`Write to Text File` given a path replaces the file's contents, so no edit is expected. Run the file-contents test below. Also check that `%LOCALAPPDATA%\Levylab\Control Experiment\` exists before the first write on a new machine; nothing in the FGV creates it.

## Tests

1. Configure an instrument, then close and reopen Configure Experiment. The list is unchanged.
2. Open the Configure dialog and close it with the window X. The list and `Control Experiment.json` (contents and timestamp) are unchanged.
3. Rename the folder of an installed instrument class, then open Configure.
   - The ring shows `<name> (not installed)`.
   - OK shows a message naming the class.
   - The list and the JSON file are unchanged.
   - Pressing Create Output doesn't change the JSON file either.
4. Delete `Control Experiment.json` and start Configure Experiment. The user is told there's no saved configuration, and no empty file is written.
5. With two installed classes whose names share a prefix (`Instrument.Lockin`, `Instrument.LockinAPI`), each resolves to itself.
6. Save several instruments, then fewer. `Control Experiment.json` holds exactly the shorter set and parses.

## Later, not in this round

- **Portable identity.** Add `class name` to `Typedefs/Instruments--cluster.ctl`, write it in `Control Experiment Class to JSON.vi`, and resolve by name before path in `JSON to Control Experiment Class.vi`. Move the `Rings: List Installed` scan into one shared VI (it overlaps #137).
- **One instrument set per Type/Station.** Today there is a single global file, which overlaps #45.
- **Dead code.** Remove or finish the unused `Instrument Types` field in the UI cluster.

Related: #137, #148, #150, #45.
