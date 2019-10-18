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
It also provides methods for saving ITX and DAT filetypes. Future releases may include other data formats (HDF5? TDMS? other binary?). 

[SweepControl.lvclass]
- Sweep Control.vi: Sequencer for stepping multiple parameters. Calls VIs in Transport.lvclass
- Continuous B sweep.vi: For sweeping B continuously while asynchronously calling VIs in Transport.lvclass

[Transport.lvclass]
Basic transport measurements.
- Lockin Sweep Mode (Lockin_sweep.vi )
- Lockin vs Vsg (or Vbg) (Lockin_Vsg.vi)
- Lockin vs Time (Lockin_time.vi)
- IV curves (IV.vi)

## Contributing

Please contact [Patrick Irvin](p.irvin@levylab.org)

## License

[BSD-3](https://opensource.org/licenses/BSD-3-Clause)