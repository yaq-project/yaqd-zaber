import asyncio
import re

from yaqd_core import logging

logger = logging.getLogger("serial")


class SerialDispatcher:
    def __init__(self, port):
        self.port = port
        self.workers = {}
        self.write_queue = asyncio.Queue()
        self.loop = asyncio.get_event_loop()
        self.tasks = [
            self.loop.create_task(self.do_writes()),
            self.loop.create_task(self.read_dispatch()),
        ]

    def write(self, data):
        self.write_queue.put_nowait(data)

    async def do_writes(self):
        while True:
            data = await self.write_queue.get()
            logger.debug(f"write pop {data}")
            self.port.write(data)
            self.write_queue.task_done()
            await asyncio.sleep(0.01)

    async def read_dispatch(self):
        count = 0
        while True:
            logger.debug(count)
            count += 1
            try:
                if self.port.can_read():
                    reply = self.port.read()
                else:
                    if self.port._ser.in_waiting:
                        logger.debug(self.port._ser.in_waiting)
                    raise TimeoutError
            except TimeoutError:
                await asyncio.sleep(0.01)
            except exception as e:
                logger.error(e)
                await asyncio.sleep(0.01)
            else:
                logger.debug(reply)
                if reply.device_number in self.workers:
                    self.workers[reply.device_number].put_nowait(reply)
                else:
                    logger.error(f"Unexpected device: {reply.device_number}")
                    self.port._ser.reset_input_buffer()
                await asyncio.sleep(0)

    def flush(self):
        self.port.flush()

    def close(self):
        self.loop.create_task(self._close())

    async def _close(self):
        for task in self.tasks:
            task.cancel()
