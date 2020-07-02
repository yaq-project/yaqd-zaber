__all__ = ["ZaberBinary"]

import asyncio
from typing import Dict, Any, List

from yaqd_core import ContinuousHardware
from zaber.serial import BinarySerial, BinaryCommand  # type: ignore

from ._serial import SerialDispatcher


class ZaberBinary(ContinuousHardware):
    _kind = "zaber-binary"
    serial_dispatchers: Dict[str, SerialDispatcher] = {}

    def __init__(self, name, config, config_filepath):
        self._axis = config["axis"]
        if config["serial_port"] in ZaberBinary.serial_dispatchers:
            self._serial = ZaberBinary.serial_dispatchers[config["serial_port"]]
        else:
            self._serial = SerialDispatcher(
                BinarySerial(
                    config["serial_port"], config["baud_rate"], timeout=0, inter_char_timeout=0.001
                )
            )
            ZaberBinary.serial_dispatchers[config["serial_port"]] = self._serial
        self._read_queue = asyncio.Queue()
        self._serial.workers[self._axis] = self._read_queue
        super().__init__(name, config, config_filepath)
        self._home_event = asyncio.Event()
        self._device_mode = 0
        self._serial.write(BinaryCommand(self._axis, 53, 40))  # device mode
        self._serial.write(BinaryCommand(self._axis, 53, 44))  # max position
        self._serial.write(BinaryCommand(self._axis, 53, 106))  # min position

    def _set_position(self, position):
        self._serial.write(BinaryCommand(self._axis, 20, round(position)))

    def home(self):
        self._loop.create_task(self._home())

    async def _home(self):
        self._busy = True
        self._serial.write(BinaryCommand(self._axis, 1))
        await self._home_event.wait()
        self._home_event.clear()
        self.set_position(self._state["destination"])

    async def update_state(self):
        """Continually monitor and update the current daemon state."""
        while True:
            reply = await self._read_queue.get()
            self.logger.debug(reply)
            # Commands which reply with the current position
            if reply.command_number in (20, 18, 23, 78, 9, 11, 13, 21, 1, 8, 10, 12, 60):
                self._state["position"] = reply.data
                if reply.command_number in (10, 12):
                    self._busy = True
                    self._state["destination"] = reply.data
                    self._serial.write(BinaryCommand(self._axis, 54))
                elif reply.command_number == 1:
                    self._home_event.set()
                elif reply.command_number == 8:
                    continue
                else:
                    self._busy = False
            elif reply.command_number == 40:
                self._device_mode = reply.data
            elif reply.command_number == 54:
                self._busy = reply.data != 0
            elif reply.command_number == 106:
                self._state["hw_limits"][0] = reply.data
            elif reply.command_number == 44:
                self._state["hw_limits"][1] = reply.data
            elif reply.command_number == 255:
                self.logger.error(f"Error Code: {reply.data}")
            else:
                self.logger.info(f"Unhandled reply: {reply}")

    def set_knob(self, enable):
        # Newer firmwares have a dedicated command (CMD 107), but this implementation works
        # in older firmwares as well as newer.
        # Zaber may remove the set_mode (CMD 40) at some point (they discourage its use)
        # KFS 2020-06-16
        knob_bit = 1 << 3
        move_tracking_bit = 1 << 4
        if enable:
            self._serial.write(
                BinaryCommand(self._axis, 40, self._device_mode & ~knob_bit | move_tracking_bit)
            )
        else:
            self._serial.write(
                BinaryCommand(self._axis, 40, self._device_mode | knob_bit | move_tracking_bit)
            )
        self._serial.write(BinaryCommand(self._axis, 53, 40))

    def direct_serial_write(self, command: bytes):
        self._busy = True
        if len(command) <= 5:
            command = bytes([self._axis]) + command
        command = command.ljust(6, b"\0")
        self._serial.write(command.decode("UTF-8"))  # zaber lib doesn't accept bytes

    def close(self):
        self._serial.flush()
        self._serial.close()
