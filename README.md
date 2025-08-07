# Transport

VIs for scripting and performing transport measurments.

## Installation
- Transport VIs are developed and published in LabVIEW 2019
- Please install using the [VI Package Manager](https://vipm.jki.net/)

## Usage

### Configure (`Control Experiment.lvclass`)

`Control Experiment.vi` is an entry point for the following tasks:
- record information about your sample & device
- record how the lockin is connected to your device
- configure the Krohn Hite amplifier
- sets the base path for saving data.

`Control Experiment.lvclass` also contains:
- Share configuration with Transport VIs or FLEX
- It also provides methods for saving ITX, TDMS, and DAT (TSV) filetypes.

### Transport (`Transport.lvclass`)

Basic transport measurements:
- Lockin Sweep (`Lockin_sweep.vi`)
- Lockin vs Time (`Lockin_time.vi`)
- Lockin vs TimeDelay (`THz_TimeDelay.vi`)

### (_new!_) Transport Server

#### Basics:
![2025-08-07_08-46-11](https://github.com/user-attachments/assets/2d8cc81f-a3bd-4e51-9e05-218afdd00316)

#### Start, Stop, Get Status:
![2025-08-07_08-47-57](https://github.com/user-attachments/assets/0a02b939-bc92-4a92-8ebb-91af588322de)

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

