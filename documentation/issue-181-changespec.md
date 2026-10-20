# Issue #181 - Sweep config: tables only in sweepChannels[].Table; rename Return to Start (change spec)

**Problem.** `Lockin_Sweep JSON--Cluster`, the sweep configuration that `setSweepConfig` receives, holds sweep tables twice: in each `sweepChannels[]` element's `Table`, and again in `sweepTables: [{Ch, Table}]`. `Lockin_sweep` sends both, the second overwriting the first, and the second path also hits levylabpitt/Multichannel-Lockin#185 (only the last table applied). The cluster also uses `Return to Start` where the lock-in uses `returnToStart` (renamed in #164). FLEX already sends `returnToStart`, so that value is silently ignored today.

**Scope.** A wire change to the JSON keys of `setSweepConfig` and `getSweepConfig`. Read with lvkit on `develop` (after 265062d) on 2026-10-20. lvkit scrambles class private-data field names, so check field names on the diagram.

## FLEX today (levylabpitt/FLEX `develop`, the same as `main` for these files)

- `src/flex/inst/levylab/TransportServer.py` `setSweepConfig` passes the caller's dict through unchanged.
- `tests/afm-litho/chiral_phase_sweep.py` sends `sweepTime`, `initialWaitTime`, `returnToStart`, `sweepChannels`, with tables in `sweepChannels[].Table`.
- Nothing in FLEX sends `sweepTables`.

So current FLEX code keeps working after this change, and `returnToStart` starts taking effect. `src/flex/exp/PiezoScanner.py` still uses the pre-#164 labels (`Sweep Time (s)`, `Initial Wait (s)`, `Return to Start`, `Channels`), which are ignored now and after this change; that is a separate FLEX fix.

## Edits

### 1. `src/Transport/Typedefs/Lockin_Sweep JSON--Cluster.ctl`

Today: `{initialWaitTime, sweepTime, Return to Start, sweepChannels[], sweepTables[{Ch, Table}]}`.

1. Rename the label `Return to Start` to **`returnToStart`**.
2. Delete **`sweepTables`**.
3. Keep `sweepChannels` as the lock-in's `Sweep.Channel` cluster (`Enable?`, `Channel`, `Start`, `End`, `Pattern`, `Table`).

Every VI that bundles or unbundles these fields by name relinks when the typedef is saved; open and save its callers so none are left stale.

### 2. `src/Transport/Private/Lockin_sweep.vi`, `Sweep: Initialize`

Today the state unbundles the configuration from the Transport class, bundles `sweepTime`, `initialWaitTime`, `returnToStart` and `sweepChannels` into the lock-in's `Sweep.Configuration--Cluster`, calls `setSweep`, then loops over `sweepTables` and calls `setSweepTable.vim`.

1. Map `returnToStart` (renamed) to `returnToStart`.
2. Remove the `sweepTables` For loop and the `setSweepTable.vim` call. Wire `setSweep`'s outputs straight on.

### 3. `src/Transport/API (class)/Write Sweep Table.vi`

No callers. Delete it, and remove it from `Transport.lvclass`.

### 4. Check, no edit expected

- `Transport Server/Inst.Transport/API/setSweepConfig.vi`, `getSweepConfig.vi` and `Overrides/Commands/Handle Command.vi`: they carry the cluster through, so they pick up the new keys from the typedef. Confirm that `getSweepConfig` returns `returnToStart` and no `sweepTables`.
- `src/Transport/API (file)/Read Lockin_Sweep.json.vi`: reads saved sweep files. A file written before this change has `Return to Start` and maybe `sweepTables`. After it, those are ignored: `returnToStart` reads as False, and tables in `sweepTables` are lost. If old files must keep working, read both keys and merge `sweepTables` into `sweepChannels[].Table` in this VI only.
- Front-panel indicators that show the sweep configuration (in `Lockin_sweep` and the Transport Server UI) update from the typedef. Check the labels read sensibly.

## Tests

1. `setSweepConfig` from FLEX with two channels using `Pattern: "Table"` and different tables, and `returnToStart: true`. Run `Lockin_sweep`: both channels sweep their own tables, the output returns to start, and `getSweepConfig` returns the same keys.
2. The same config with `"Return to Start"` / `"sweepTables"` keys: they are ignored. This is the documented behaviour for old payloads; note it in the release notes.
3. The existing Transport and Inst.Transport tests still pass.

## Release

A wire change: release with release notes that name the new keys, and tell @pgwijesinghe (FLEX). Release together with levylabpitt/Multichannel-Lockin#185 if possible.
