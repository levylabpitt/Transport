# Transport

VIs for scripting and performing transport measurments.

## Installation

Unless otherwise noted, all software is written with LabVIEW. Please install using the [VI Package Manager](https://vipm.jki.net/)

## Usage

[Control Experiment.lvclass]
Control Experiment.vi provides a uniform way to record information about your sample & device, how the lockin is connected to the device, configures the Krohn Hite amplifier (and Pickering switch if you have one), and sets the base path for saving data.

[SweepControl.lvclass]
Sweep Control.vi: Sequencer for stepping multiple parameters. Calls VIs in Transport.lvclass
Continuous B sweep.vi: For sweeping B continuously while asynchronously calling VIs in Transport.lvclass

[Transport.lvclass]
Basic transport measurments.
- Lockin vs Vsg (or Vbg) (Lockin_Vsg.vi)
- Lockin vs Time (Lockin_time.vi)
- Lockin Sweep Mode (Lockin_sweep.vi (under development)
- IV curves (IV.vi)

## Contributing

Please contact [Patrick Irvin](p.irvin@levylab.org)

## License

[BSD-3](https://opensource.org/licenses/BSD-3-Clause)