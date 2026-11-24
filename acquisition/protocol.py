"""ESP32 ölçüm satırı ve sınırlı seri tamponu."""

from dataclasses import dataclass

from core.contracts import Measurement
from core.validation import validate_measurement

MAX_LINE_BYTES = 96
BAUD = 115200


@dataclass(frozen=True)
class Packet:
    sequence: int
    uptime_ms: int
    free_heap_bytes: int
    measurement: Measurement


def parse_line(line, timestamp, series_id='ESP32'):
    if not line or len(line) > MAX_LINE_BYTES:
        raise ValueError('Seri satır uzunluğu geçersiz')
    version, sequence, uptime, air, humidity, surface, heap = line.decode('ascii').strip().split(',')
    if version != 'M1':
        raise ValueError('Protokol sürümü geçersiz')
    sequence, uptime, heap = int(sequence), int(uptime), int(heap)
    if any(not 0 <= value <= 0xFFFFFFFF for value in (sequence, uptime, heap)):
        raise ValueError('Sayaç alanı geçersiz')
    measurement = validate_measurement(Measurement(series_id, timestamp, float(air), float(humidity), float(surface)))
    return Packet(sequence, uptime, heap, measurement)


class LineFramer:
    def __init__(self):
        self.buffer = bytearray()
        self.discard = False

    def feed(self, chunk):
        for byte in chunk:
            if byte == 10:
                yield b'' if self.discard else bytes(self.buffer)
                self.buffer.clear()
                self.discard = False
            elif not self.discard:
                if len(self.buffer) == MAX_LINE_BYTES:
                    self.buffer.clear()
                    self.discard = True
                else:
                    self.buffer.append(byte)
