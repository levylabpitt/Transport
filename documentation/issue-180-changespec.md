# Issue #180 - Experiment VIs: blocking error dialog, and one failed getStatus ends Lockin_sweep (change spec)

**Problem.** Any error in an experiment VI goes to the JKI `Error Handler` state, which opens a **modal** `General Error Handler` dialog. Nothing runs until someone clicks OK, which stalls an overnight field sweep. Separately, `Lockin_sweep` treats one failed `getStatus` poll as "the sweep is over" and exits.

**Scope.** Error handling in `src/Transport/Private/Lockin_sweep.vi`, plus the dialog in `Lockin_time.vi` and `THz_TimeDelay.vi`. No API, notifier or file-format change. Every location below was read with lvkit on `develop` (2.6.5.64) on 2026-10-13. Check multi-value frames and Diagram Disable structures in LabVIEW: lvkit shows only the first value of a multi-value frame, and has misreported which frame of a Diagram Disable structure is enabled. The upstream causes are levylabpitt/RemoteControl.ZMQ#1, levylabpitt/Instrument-Framework#200 and levylabpitt/Multichannel-Lockin#183. This spec does not depend on them shipping first.

**Policy.**
1. Never block during a run.
2. Log every error.
3. Retry transient communication errors.
4. Always save what was acquired.
5. Stop the run only for an error that is not transient, or when the lock-in has been unreachable for longer than a set grace period.

The experiment VIs are launched call-and-forget by `Inst.Transport.CallByReference.vi`, so their errors never reach the server. The log written here is the only record.

## Current behaviour (Lockin_sweep.vi)

- Run order: `Macro: Initialize` ... `Macro: Start Sweep` (`Sweep: Initialize`, `File: Write JSON`, ..., `Sweep: Start`, `Measure: DAQ`, ...).
- While the run is going, the event-structure `[0] Timeout` queues `Sweep: Check State` whenever the queue is empty.
- `Sweep: Check State`: `getStatus`. If the state is `sweeping`, queue `Macro: Sweep`. **Anything else** (including the default `state` that `getStatus` returns on error) queues `Macro: Exit`.
- `Macro: Exit` queues `Macro: Stop Sweep` (`Sweep: Stop`, `Measure: DAQ Sweep`, graph updates, `File: Save Lockin`, then `Sweep: Return to Start`), then `Data: Close Instruments`, `Data: Cleanup`, `Exit`.
- `Error Handler`: queues `/* Post Error States` in front, calls `Clear Errors` (4000), then `General Error Handler.vi` with the dialog type unwired (modal OK), then clears the error. The rest of the queue then carries on.

## Edits

### 1. New `Private/Experiment Error Policy.vi` (shared by the three VIs)

A member of `Transport.lvclass`, **public** scope: it uses no class data, and public lets a test in `Tests/` call it. It follows the pattern already used in Multichannel-Lockin: classify by a list of known codes (`Instrument.DAQ` `DAQ.ErrorHandler.vi`, `DAQmx.Error Handler.vi`), and keep the shape of JKI SMO `Handle Error.vi` (`Unhandled error` / `handling error`). No dialog, as in `DAQmx.Error Handler.vi`.

Connector pane:

| Terminal | Type | Notes |
| --- | --- | --- |
| `error in` | Error | |
| `state` | String | The JKI state that failed |
| `C.E.` | `Control Experiment.lvclass` | Used to find the data folder |
| `log folder override` | Path | Empty means use the experiment folder. For tests. |
| `Comm Error?` | TF | The code is in the transient list (mirrors `DAQmx Error?`) |
| `Unhandled error` | Error | No error when `Comm Error?`, `error in` otherwise |
| `handling error` | Error | The log write's own error. Reported here, **never** merged into `Unhandled error`, so logging can never cause another Error Handler pass. |
| `message` | String | One readable line for the front panel |

What it does:

1. **Classify** with OpenG `Filter Error Codes (Array)__ogtk.vi`, as `DAQ.ErrorHandler.vi` does. The list, in one array constant labelled `transient codes`:
   - **123** ("LabVIEW: A timeout occurred."), what the ZMQ client returns for a request with no reply from RemoteControl.ZMQ 1.4.0.32 on;
   - **56** (network timeout, other transports);
   - **91** (bad reply type), what RemoteControl.ZMQ 1.3.7.30 and earlier produced instead of a timeout;
   - the "empty reply" code that Instrument-Framework#200 adds.

   Not **1556** ("The reference is invalid"): it is generic. RemoteControl.ZMQ already handles its own 1556 inside `ZMQ.Handle Error.vi` (it reconnects), so a 1556 that reaches this code means some other reference died (for example, `Inst.Transport` `onStop.vi` destroying the notifiers), and the run should stop, not retry.

   `Comm Error?` = `Error Filtered?`; `Unhandled error` = `Error Out`. When #200 ships, call its `Is Transient Comm Error.vi` here instead of keeping a local list.
2. **Message:** `<state>: <code> <description>`, using `Error Code Database.vi` for the description, as `DAQmx.Error Handler.vi` does.
3. **Log path:**
   - `log folder override` if it is not empty;
   - otherwise `Control Experiment:Read Experiment Path.vi`, which is the data **folder** (e.g. `C:\temp\TEST.20261014\01 - test experiment error policy`). Create it with `Create Directory Recursive`, because an error can come before the first save creates it. Do **not** append `Read Device.vi`: that is the data **file** base name (`TEST.20261014`, saved as `TEST.20261014.000000.tdms`), not a folder;
   - if the experiment path is empty or cannot be created, `%LOCALAPPDATA%\Levylab\Transport`.

   The file is `<Device> errors.log` (e.g. `TEST.20261014 errors.log`, next to the `.tdms` files), or `Transport errors.log` when `Read Device` is empty.
4. **Append one line**, for every error, transient or not:
   ```
   <ISO time> <VI name> <message> <source, first 200 chars>
   ```
   Take the VI name from `Call Chain` (index 1, the caller). Use `Open/Create/Replace File` (open or create), `Set File Position` to the end, `Write to Text File` with CRLF, `Close File`. Run this chain on a cleared error, and send its error only to `handling error`.

### 2. `Error Handler` state (all three VIs)

1. Delete `General Error Handler.vi`. Keep `Clear Errors` (4000).
2. Call `Experiment Error Policy.vi` with the error and the name of the state that failed. `Parse State Queue` does not output the previous state; on an error it returns `Error Handler` as the state. So add a shift register `last state` to the main loop, write the `State` output into it every iteration, and read its left side in the `Error Handler` frame: that is the state that failed.
3. Add two fields to the data cluster:
   - `Error count` (I32), shown on the front panel next to the status;
   - `Last error` (String), shown on the front panel, set to `message`.
4. If `Comm Error?` is True: carry on with the rest of the queue, as today.
5. If `Comm Error?` is False:
   - **during a run**: queue `Macro: Exit` in front, so the sweep is stopped, read and saved before the VI closes;
   - **already in `Macro: Exit`'s states**: queue `Data: Cleanup` and `Exit` only, so a broken instrument cannot loop through Exit forever.

   Track "already exiting" with a boolean in the data cluster, set in `Macro: Exit`.
6. Give up after a ceiling: if `Error count` passes 1000, treat any error as non-transient. This guards against an error storm filling the disk.
7. Wire `handling error` nowhere except, optionally, a front-panel indicator. A failed log write must not end a run.

Lockin_time and THz_TimeDelay need only edits 1 and 2. List their own polling states while doing this, and if any of them reads `getStatus` the way `Sweep: Check State` does, apply edit 3 there too.

### 3. `Lockin_sweep.vi` `Sweep: Check State`

1. Add `Last good status (ms)` (U32) to the data cluster. Set it in `Sweep: Start`, and on every `getStatus` call with no error.
2. Put the existing `state` -> next-state case inside a case on the `getStatus` error:
   - **No Error:** as today, and update `Last good status (ms)`.
   - **Error, transient** (`Experiment Error Policy.vi`): log it, clear it, and queue **nothing**. The timeout event queues `Sweep: Check State` again on the next refresh. If `Tick Count - Last good status` is more than **60 s**, raise error **5162**, "Gave up: the lock-in did not answer getStatus for %g s; sweep stopped" (non-transient). The Error Handler turns that into `Macro: Exit`. This is the same shape as `DAQmx.Recovery Error Handler.vi`: retry within a budget, then give up with a clear error of your own (5161 there).
   - **Error, not transient:** pass it on (Error Handler -> `Macro: Exit`).
3. Put the 60 s limit in a constant labelled `Status grace period (ms)`. Later it can be read from the sweep configuration.

### 4. `Lockin_sweep.vi` `Sweep: Start`, `Sweep: Stop`, `Sweep: Return to Start`

After `waitStatusSweepingStarted` / `waitStatusSweepingStopped`, call `Experiment Error Policy.vi`. When `Comm Error?` is True, use its cleared `Unhandled error` and carry on:
- After start, `Sweep: Check State` (edit 3) decides whether the sweep is really running.
- After stop, `Measure: DAQ Sweep` reads whatever was acquired.

With Instrument-Framework#200 these waits already retry inside their 10 s; this edit covers older framework versions.

### 5. `Lockin_sweep.vi` `Measure: DAQ Sweep` and `File: Save Lockin`: save what was acquired

1. **`Measure: DAQ Sweep`:** put `getSweepData` in a For loop of up to 3 tries. Stop early on no error, and wait 500 ms between tries. Add `Sweep data valid?` (TF) to the data cluster: True if any try succeeded.
2. Check whether `Sweep_AO`, `Sweep_AI`, `Sweep_X` and `Sweep_Y` are reset in `Sweep: Initialize`. If they are not, reset them there, so a failed read can never save the previous sweep's data under the new file.
3. **`File: Save Lockin`:**
   - Clear errors on the state's input before `Save Transport TDMS File`, so saving does not depend on earlier states.
   - If `Sweep data valid?` is False, still write the file, with whatever scalar data there is, and log "sweep data not read; file has no sweep arrays".

## Tests

### Unit test: `Tests/Test Experiment Error Policy.vi`

Caraya, with `log folder override` pointing at a new temp folder that is deleted afterwards. The code list is exactly the kind of thing that drifts unnoticed, so test it:

| Input | Expect |
| --- | --- |
| Error 123, and each other code in the list | `Comm Error?` True, `Unhandled error` clear, one line added to the log |
| Error 7 | `Comm Error?` False, `Unhandled error` = 7, one line added |
| No error | `Comm Error?` False, nothing written |
| Log folder that cannot be written | `handling error` set, `Unhandled error` unaffected |

### Run tests

Run `Lockin_sweep` with a sweep of about 5 minutes against a running Multichannel Lockin. Check `Transport errors.log` after each test.

1. Normal run: no log lines, file saved, the VI exits on its own (regression check).
2. Pause the lock-in for 3 s mid-sweep (breakpoint in its `Handle Command.vi`, then continue):
   - no dialog;
   - log lines with code 123 (RemoteControl.ZMQ 1.4.0.32) or 91 (older versions);
   - the sweep carries on and the file is complete.
3. Pause the lock-in for 3 s straight after `startSweep`: same as test 2. This is the field case.
4. Close the Lockin exe mid-sweep:
   - no dialog;
   - after about 60 s, error 5162 ("Gave up: the lock-in did not answer getStatus...") is logged;
   - the VI saves what it has and exits;
   - `Error count` is shown on the front panel.
5. Error not from communication (for example, make the TDMS path read-only):
   - no dialog;
   - the error is logged;
   - the VI goes through `Macro: Exit` once and closes, without looping.
6. `Lockin_time` and `THz_TimeDelay`: force an error (close an instrument). The error is logged, there is no dialog, and the VI ends cleanly.

## Later, not in this round

- Report the error count and last error back to `Inst.Transport` through a notifier, like RunningStatus, so FLEX / the Transport UI can show them while a run is going.
- Make `Status grace period (ms)` part of the sweep configuration (a wire-protocol change; see the JSON-key rule in CLAUDE.md).
- Retry a sweep that ended early, if the experiment allows it.

Related: levylabpitt/RemoteControl.ZMQ#1 (fixed in 1.4.0.32), levylabpitt/Instrument-Framework#200, levylabpitt/Multichannel-Lockin#183.
