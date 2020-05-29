__all__ = ["ZaberBinary"]

import asyncio
from typing import Dict, Any, List

from yaqd_core import ContinuousHardware
from zaber.serial import BinarySerial, BinaryCommand

from .__version__ import __branch__
from ._serial import SerialDispatcher


class ZaberBinary(ContinuousHardware):
    _kind = "zaber-binary"
    _version = "0.1.0" + f"+{__branch__}" if __branch__ else ""
    traits: List[str] = []
    defaults: Dict[str, Any] = {"baud_rate": 9600}
    serial_dispatchers: Dict[str, SerialDispatcher] = {}

    def __init__(self, name, config, config_filepath):
        self._axis = config["axis"]
        if config["serial_port"] in ZaberBinary.serial_dispatchers:
            self._serial = ZaberBinary.serial_dispatchers[config["serial_port"]]
        else:
            self._serial = SerialDispatcher(BinarySerial(config["serial_port"], config["baud_rate"], timeout=0, inter_char_timeout=0.001))
            ZaberBinary.serial_dispatchers[config["serial_port"]] = self._serial
        self._read_queue = asyncio.Queue()
        self._serial.workers[self._axis] = self._read_queue

        super().__init__(name, config, config_filepath)

        self._tasks.append(self._loop.create_task(self._consume_from_serial()))


    def _set_position(self, position):
        self._serial.write(BinaryCommand(self._axis, 20, round(position)))

    def home(self):
        self._loop.create_task(self._home())

    async def _home(self):
        self._busy = True
        self._serial.write(BinaryCommand(self._axis, 1))
        await self._not_busy_sig.wait()
        self.set_position(self._destination)

    async def update_state(self):
        """Continually monitor and update the current daemon state."""
        # If there is no state to monitor continuously, delete this function
        return
        while True:
            self._serial.write(BinaryCommand(self._axis, 54))
            if self._busy:
                await asyncio.sleep(0.1)
            else:
                await self._busy_sig.wait()

    async def _consume_from_serial(self):
        while True:
            reply = await self._read_queue.get()
            self.logger.debug(reply)
            # Commands which reply with the current position
            if reply.command_number in (20, 18, 23,78,9,11,13,21,1,8,10,12, 60):
                if reply.command_number in (8, 10, 12):
                    self._busy = True
                    self._serial.write(BinaryCommand(self._axis, 54))
                else:
                    self._busy = False
                self._position = reply.data
            elif reply.command_number == 54:
                self._busy = reply.data != 0
            elif reply.command_number == 255:
                self.logger.error(f"Error Code: {reply.data}")



    def direct_serial_write(self, command):
        self._busy = True
        command = bytes(command, "UTF-8")
        if len(command) <= 5:
            command = bytes([self._axis]) + command
        command = command.ljust(6, b'\0')
        self._serial.write(command.decode("UTF-8"))

    def close(self):
        self._serial.flush()
        self._serial.close()
