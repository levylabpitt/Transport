# CLAUDE.md

Notes for working in this repo that are hard to rediscover from the code. See README.md for what the VIs do.

## Repo basics

- LabVIEW 2019 64-bit. Keep VIs saved in 2019; opening them in a newer LabVIEW mass-compiles them.
- git-flow: work on `develop`; releases are merged to `main` and tagged there.
- One product: the `Transport` VIPM package (`build support\Transport.vipb`), installed under user.lib. No application or installer is built.
- Layout:
  - `src\Transport` - `Transport.lvclass`: the experiment VIs `Lockin_time.vi`, `Lockin_sweep.vi`, `THz_TimeDelay.vi`, plus `API (class)` (notifier API, dependencies, sweep config).
  - `src\Transport Server` - `Inst.Transport` (the Instrument Framework / JKI SMO server: `Handle Command.vi`, `Process.vi`, public API VIs under `API`) and `Inst UI.Transport`.
  - `src\Control Experiment` - `Control Experiment.lvclass` and `Control Experiment.vi` (sample, lockin wiring, amplifier, data path configuration).
  - `Sweep Control` - a separate nested project with its own .vipb and build config. It depends on Transport, not the other way round, and is superseded by FLEX.
- The Control Experiment and Transport Server packages were retired. Their source stays under `src` and ships inside the Transport package; their old .vip files remain published for existing users.

## Build and release

`build support\build.cfg` configures the shared `build.bat` (it is not in this repo):

- `build.bat "<repo root>" release` builds the package and runs the git release step (commit, merge, tag, push, GitHub release).
- `build.bat "<repo root>" test` builds only, with no git.
- `BUILD_VIP=true`, `BUILD_INSTALLER=false`, `DO_RELEASE=true`, `VIPB=Transport.vipb`. LabVIEW version and bitness default to the .vipb's `Package_LabVIEW_Version`.
- The build number is bumped by VIPM inside the VIP build, before the release commit, so a release commit carries it.
- Tags are bare versions (`2.5.0.54`, no prefix).
- Do not put an inline comment after a value in build.cfg; it becomes part of the value.

Release tags sit on the merge commits on `main`, so `git describe` on `develop` reports an older release (at 2.5.0.54 it said `2.4.1.48-17-...`). To get the current release use:

```bash
gh release view --json tagName -q .tagName
```

## Command path (Transport Server)

A command travels: public API VI (e.g. `Inst.Transport\API\setRefreshTime.vi`) -> `Client.vi` -> `Inst.Transport` `Handle Command.vi` -> `Process.vi` state `Transport: <command>` -> `Transport.lvclass`.

- In `Handle Command.vi`, several commands share one multi-value "forward to child process" frame that calls `Inst.Transport.sendMessageToProcess.vi`. `startTransport` and `stopTransport` have their own frames: they send the Stop notifier (False and True respectively) and then forward.
- `Process.vi` receives forwarded commands as the MessageToProcess user event, checks the name against the Public and Protected command enums, and queues the state `Transport: <command>`. `startTransport` goes through `Macro: Transport` (`Transport: prepareTransport` then `Transport: startTransport`).
- Unhandled commands fall to the parent `Instrument.lvclass:Handle Command.vi` (Instrument Framework, outside this repo). Its only built-ins are ACK, HELP, IDN, GET, SET, getAll, setAll, setIDN and setConfiguration; anything else raises error 4001 "command not supported". A new command therefore probably needs an entry in the Inst.Transport command enum, a `Handle Command.vi` frame and a `Process.vi` state.

## Experiment VIs and notifiers

- `Inst.Transport.CallByReference.vi` runs Lockin_time, Lockin_sweep and THz_TimeDelay with a synchronous Call By Reference and passes the Transport object by value. Later writes to the object never reach a running VI; only refnums inside it stay live.
- Those refnums are the notifiers in `Transport.lvclass` private data (`Notifiers`: Stop, RefreshTime, RunningStatus), added in 2.5.0.54. `Inst.Transport` `onStart.vi` creates them once (`Init Notifiers.vi`, unnamed notifiers) and `onStop.vi` destroys them (`Destroy Notifiers.vi`). Use the Get/Send VIs in `src\Transport\API (class)`.
- The Get VIs read the latest value with Get Notifier Status; they do not wait. A sent value therefore stays "current" until another is sent. That is why `startTransport` sends Stop=False before starting. Get RefreshTime returns 0 if nothing has been sent yet; its `valid?` output only means the refnum is valid.
- Each experiment VI polls Stop and RefreshTime in its `Data: Check Notifier` state, and sends RunningStatus True in `Data: Initialize Top Level` and False in `Data: Cleanup`. `Process.vi` polls RunningStatus in its event timeout to report running/idle.
- The `setRefreshTime` payload key is `RefreshTime` (it was `Refresh Time` before 2.5.0.54).

## JSON command payloads

The Instrument Framework parses payloads with `JSON to LVtype.vim`, which silently ignores unknown keys and returns defaults. A wrong key looks like "received, no error, no effect". Check key names against the request typedef (e.g. `RefreshTime--Request--Cluster.ctl`) first.

## Control Experiment persistence

Control Experiment persists to `%LOCALAPPDATA%\Levylab\Control Experiment\`: `configuration.ini` holds the UI, and `Control Experiment.json` holds the instrument set as absolute class paths (see issue #163, "Configure Experiment forgets previous configuration"). Verified at 2.4.3.52 only; lvkit found no literal path constants, so the path is assembled at runtime.

## Reading LabVIEW code

- .vi files are binary; do not grep them. Use lvkit first (index, query, read_vi, diff, `lvkit describe --format lvnet`).
- lvkit is wrong in known ways: multi-value case frames report only their first value, local variable names and class private-data field labels are unreliable, and event-structure timeouts are not modelled. Never conclude something is missing or unused from lvkit alone. Render it first with the lv-vi-index skill (`--version 2019`).
- In lvkit output, the JKI `Add State(s) to Queue` terminals are numbers: 0 = states in front, 5 = states in the middle (usually the remaining queue), 7 = states at back.
- When rendering from a script, give LabVIEW Windows paths with backslashes; forward slashes fail with error 0x76 "folder path does not exist".
- The LabVIEW 2019 instance and lvkit may be in use by other sessions on this machine. Ask before starting renders, and never answer a LabVIEW dialog you did not cause.
