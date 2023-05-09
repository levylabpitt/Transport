# Transport

VIs for scripting and performing transport measurments.

## Installation
- LabVIEW 2016 32 bit is required.
- Please install using the [VI Package Manager](https://vipm.jki.net/)

## Usage

[Control Experiment.lvclass]
Control Experiment.vi provides a uniform way to:
- record information about your sample & device
- records how the lockin is connected to your device
- configures the Krohn Hite amplifier
- ~~configures the Pickering switch if you have one~~
- sets the base path for saving data.
It also provides methods for saving ITX, TDMS, and DAT (TSV) filetypes.

[Transport.lvclass]
Basic transport measurements.
- Lockin Sweep Mode (Lockin_sweep.vi )
- Lockin vs Vsg (Lockin_Vsg.vi (**Lockin_sweep.vi** is preferred)
- Lockin vs Time (Lockin_time.vi)
- IV curves (Lockin_sweep.vi ~~IV.vi~~)

[SweepControl.lvclass]
- Sweep Control.vi: Sequencer for stepping multiple parameters. Calls VIs in Transport.lvclass
- Continuous B sweep.vi: For sweeping B continuously while asynchronously calling VIs in Transport.lvclass

## Sandbox
A test environment can be set up by configuring the following
- Multichannel Lock-in
  - Install [Multichannel Lock-In](https://github.com/levylabpitt/Multichannel-Lockin/releases/latest). Configure simulated PXIe devices in NI MAX (Described in the Multichannel Lock-In Readme)
- PPMS Cryostat
  - Install Quantum Design's **Simulate PPMS MultiVu** Software
  - Install Quantum Design's **QD Instrument Server**
  - Install [PPMS Monitor and Control](https://github.com/levylabpitt/PPMS-Monitor-and-Control/releases/latest). Run in Simulation mode (PPMSim)
- Check out or clone this respoitory and try to communicate with the virtual instruments

## Contributing

Please contact [Patrick Irvin](p.irvin@levylab.org)

## License

[BSD-3](https://opensource.org/licenses/BSD-3-Clause)
