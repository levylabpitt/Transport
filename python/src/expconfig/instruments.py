"""Thin clients for the Instrument Framework servers this app talks to.

Command names and payload shapes follow FLEX (flex/inst/levylab/*.py).
"""

from __future__ import annotations

from .rpc import Client


class KH7008:
    """One Krohn-Hite 7008 chassis (8 channels)."""

    def __init__(self, address: str, timeout: float = 3.0):
        self.rpc = Client(address, timeout)

    def ack(self) -> None:
        self.rpc.call("ACK")

    def get_all_channels(self) -> list[dict]:
        return self.rpc.call("getAllChannels")["allChannelProperties"]

    def set_all_channels(self, channels: list[dict]) -> None:
        self.rpc.call("setAllChannels", {"allChannelProperties": channels})

    def get_shunt_resistors(self):
        return self.rpc.call("getShuntResistor")["ShuntResistor"]

    def close(self) -> None:
        self.rpc.close()


class Lockin:
    """Multichannel lock-in. Gain lists are one value per channel, in channel order."""

    def __init__(self, address: str, timeout: float = 3.0):
        self.rpc = Client(address, timeout)

    def ack(self) -> None:
        self.rpc.call("ACK")

    def get_input_gain(self) -> list[float]:
        return list(self.rpc.call("getInputGain"))

    def set_input_gain(self, gains: list[float]) -> None:
        self.rpc.call("setInputGain", list(gains))

    def get_output_gain(self) -> list[float]:
        return list(self.rpc.call("getOutputGain"))

    def set_output_gain(self, gains: list[float]) -> None:
        self.rpc.call("setOutputGain", list(gains))

    def close(self) -> None:
        self.rpc.close()
