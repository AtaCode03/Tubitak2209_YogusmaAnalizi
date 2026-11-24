"""USB seri port verisi ve bağlantı durumu."""

from datetime import datetime, timezone
from time import sleep

import serial

from acquisition.protocol import BAUD, LineFramer


def serial_frames(port):
    while True:
        try:
            with serial.Serial(port, BAUD, timeout=1) as device:
                framer = LineFramer()
                while device.is_open:
                    data = device.read(min(device.in_waiting or 1, 96))
                    yield from (('line', datetime.now(timezone.utc), line) for line in framer.feed(data))
                    yield 'idle', datetime.now(timezone.utc), b''
        except (serial.SerialException, OSError):
            yield 'disconnected', datetime.now(timezone.utc), b''
            sleep(2)
