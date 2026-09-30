# Transport

VIs for scripting and performing transport measurements.

## Installation
- Transport VIs are developed and published in LabVIEW 2019
- Please install using the [VI Package Manager](https://vipm.jki.net/)
- The `Transport` package includes Transport, Control Experiment, and Transport Server. The separate Control Experiment and Transport Server packages have been retired; their old releases remain available for existing users.

## Usage

Start with `Configure Experiment.vi` (in `Control Experiment.lvclass`). It is the entry point for everything else: it opens a Transport Server instance and shows its UI (`Open`, `showUI`, `hideUI` and `Close` from the Transport Server API), so you do not launch the server separately.

<img width="892" height="770" alt="image" src="https://github.com/user-attachments/assets/c3b29084-441d-402d-908b-ebd48c112efd" />

### Configure Experiment (`Control Experiment.lvclass`)

From `Configure Experiment.vi` you can:
- record information about your sample & device
- record how the lockin is connected to your device
- configure the Krohn Hite amplifier
- set the base path for saving data
- open the Transport Server to set the experiment folder and comments and to start and stop experiments

`Control Experiment.lvclass` also contains:
- Share configuration with Transport VIs or FLEX
- Methods for saving ITX, TDMS, and DAT (TSV) filetypes.

### Transport (`Transport.lvclass`)

Basic transport measurements, launched by the Transport Server:
- Lockin Sweep (`Lockin_sweep.vi`)
- Lockin vs Time (`Lockin_time.vi`)
- Lockin vs TimeDelay (`THz_TimeDelay.vi`)

### Transport Server (`Inst.Transport`)

An Instrument Framework (JKI SMO) server for running Transport experiments locally or remotely. `Configure Experiment.vi` spawns it; other programs can also send it the commands below. It is the single place to control and view the experiment folder, comments, and sweep configuration; the fields in `Lockin_sweep.vi` and the other experiment VIs are indicators only.

Commands (public API VIs under `Inst.Transport\API`):
- `startTransport` / `stopTransport`: launch and stop an experiment. A second start is refused while a run is active.
- `getStatus`: report idle or running.
- `setRefreshTime`: change the refresh time of a running experiment. The JSON key is `RefreshTime`.
- `setExptFolder` / `getExptFolder`, `setExptComments` / `getExptComments`: experiment folder and description.
- `setExptParam` / `appendExptParam` / `clearExptParam`: experiment parameters.
- `setSweepConfig` / `getSweepConfig`: sweep configuration.
- `showUI` / `hideUI`: show or hide the server UI (`Inst UI.Transport`).

Experiments run asynchronously, so the server stays responsive during a run.

<img width="602" height="608" alt="image" src="https://github.com/user-attachments/assets/500c8536-d69b-4038-ae3a-237dda1e8da9" />

### Sequence Experiments (`SweepControl.lvclass`)

- `Sweep Control.vi`: Sequencer for stepping multiple parameters. Calls VIs in `Transport.lvclass`
- `Continuous B sweep.vi`: Continusouly sweep B while asynchronously calling VIs in `Transport.lvclass`
- _note:_ Development on these sequencers is being phased out and will be replaced by [FLEX](https://github.com/levylabpitt/FLEX)

## Sandbox
A test environment can be set up by configuring the following
- Multichannel Lock-in
  - Install [Multichannel Lock-In](https://github.com/levylabpitt/Multichannel-Lockin/releases/latest). Configure simulated PXIe devices in NI MAX (Described in the Multichannel Lock-In Readme)
- PPMS Cryostat
  - Install Quantum Design's **Simulate PPMS MultiVu** Software
  - Install Quantum Design's **QD Instrument Server**
  - Install [PPMS Monitor and Control](https://github.com/levylabpitt/PPMS-Monitor-and-Control/releases/latest). Run in Simulation mode (PPMSim)
- Check out or clone this repository and try to communicate with the virtual instruments

## Contributing

Please contact [Patrick Irvin](p.irvin@levylab.org)

## License

[BSD-3](https://opensource.org/licenses/BSD-3-Clause)

