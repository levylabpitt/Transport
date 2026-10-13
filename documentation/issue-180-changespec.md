# Issue #180 - Experiment VIs: blocking error dialog, and one failed getStatus ends Lockin_sweep (change spec)

**Problem.** Any error in an experiment VI goes to the JKI `Error Handler` state, which opens a **modal** `General Error Handler` dialog. Nothing runs until someone clicks OK, which stalls an overnight field sweep. Separately, `Lockin_sweep` treats one failed `getStatus` poll as "the sweep is over" and exits.

**Scope.** Error handling in `src/Transport/Private/Lockin_sweep.vi`, plus the dialog in `Lockin_time.vi` and `THz_TimeDelay.vi`. No API, notifier or file-format change. Every location below was read with lvkit on `develop` (2.6.5.64) on 2026-10-13; check multi-value frames in LabVIEW, because lvkit shows only the first value. The upstream causes are levylabpitt/RemoteControl.ZMQ#1, levylabpitt/Instrument-Framework#200 and levylabpitt/Multichannel-Lockin#183. This spec does not depend on them shipping first.

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

Inputs:
- `error in`
- `state` (String, the JKI state that failed)
- `log path` (Path)

Outputs:
- `transient?` (TF)
- `error out`: cleared when transient, passed through otherwise
- `message` (String, one line, for the front panel)

What it does:

1. Transient codes: **123** ("LabVIEW: A timeout occurred.", what the ZMQ client returns for a request with no reply from RemoteControl.ZMQ 1.4.0.32 on), **56** (network timeout, other transports), **91** (bad reply type, what RemoteControl.ZMQ 1.3.7.30 and earlier produced instead of a timeout), **1556** (ZMQ reconnect), and the "empty reply" code that Instrument-Framework#200 adds. When #200 ships, call its `Is Transient Comm Error.vi` here instead of keeping a local list.
2. Append one line to `log path`, transient or not:
   ```
   <ISO time> <VI name> <state> <code> <source, first 200 chars>
   ```
   Use `Open/Create/Replace File` (open or create), `Set File Position` to the end, then write and close. Any error from the logging itself is dropped, so logging can never cause a new Error Handler pass.
3. Log path: the folder that `Control Experiment.lvclass:Save Transport TDMS File.vi` saves to, file `Transport errors.log`. If that folder is not known yet, use `%LOCALAPPDATA%\Levylab\Transport\Transport errors.log`, creating the folder if needed.

### 2. `Error Handler` state (all three VIs)

1. Delete `General Error Handler.vi`. Keep `Clear Errors` (4000).
2. Call `Experiment Error Policy.vi` with the error and the name of the state that failed. The JKI `Parse State Queue` "previous state" output already gives this; if it doesn't, keep the last state in the data cluster.
3. Add two fields to the data cluster:
   - `Error count` (I32), shown on the front panel next to the status;
   - `Last error` (String), shown on the front panel, set to `message`.
4. If `transient?` is True: carry on with the rest of the queue, as today.
5. If `transient?` is False:
   - **during a run**: queue `Macro: Exit` in front, so the sweep is stopped, read and saved before the VI closes;
   - **already in `Macro: Exit`'s states**: queue `Data: Cleanup` and `Exit` only, so a broken instrument cannot loop through Exit forever.

   Track "already exiting" with a boolean in the data cluster, set in `Macro: Exit`.
6. Give up after a ceiling: if `Error count` passes 1000, treat any error as non-transient. This guards against an error storm filling the disk.

Lockin_time and THz_TimeDelay need only edits 1 and 2. List their own polling states while doing this, and if any of them reads `getStatus` the way `Sweep: Check State` does, apply edit 3 there too.

### 3. `Lockin_sweep.vi` `Sweep: Check State`

1. Add `Last good status (ms)` (U32) to the data cluster. Set it in `Sweep: Start`, and on every `getStatus` call with no error.
2. Put the existing `state` -> next-state case inside a case on the `getStatus` error:
   - **No Error:** as today, and update `Last good status (ms)`.
   - **Error, transient** (`Experiment Error Policy.vi`): log it, clear it, and queue **nothing**. The timeout event queues `Sweep: Check State` again on the next refresh. If `Tick Count - Last good status` is more than **60 s**, set error 5000 + "Lock-in unreachable for 60 s" (non-transient), which the Error Handler turns into `Macro: Exit`.
   - **Error, not transient:** pass it on (Error Handler -> `Macro: Exit`).
3. Put the 60 s limit in a constant labelled `Status grace period (ms)`. Later it can be read from the sweep configuration.

### 4. `Lockin_sweep.vi` `Sweep: Start`, `Sweep: Stop`, `Sweep: Return to Start`

After `waitStatusSweepingStarted` / `waitStatusSweepingStopped`, call `Experiment Error Policy.vi`. Clear a transient error and carry on:
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

Run `Lockin_sweep` with a sweep of about 5 minutes against a running Multichannel Lockin. Check `Transport errors.log` after each test.

1. Normal run: no log lines, file saved, the VI exits on its own (regression check).
2. Pause the lock-in for 3 s mid-sweep (breakpoint in its `Handle Command.vi`, then continue):
   - no dialog;
   - log lines with code 123 (RemoteControl.ZMQ 1.4.0.32) or 91 (older versions);
   - the sweep carries on and the file is complete.
3. Pause the lock-in for 3 s straight after `startSweep`: same as test 2. This is the field case.
4. Close the Lockin exe mid-sweep:
   - no dialog;
   - after about 60 s, "Lock-in unreachable" is logged;
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
