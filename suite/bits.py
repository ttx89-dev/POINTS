"""Bit-level read/write helpers for the dot-matrix encoding.

Provides BitWriter (accumulate bits → bytes) and BitReader
(consume bits from bytes) used by all encoding stages.
"""

class BitWriter:
    """Accumulate bits and flush to bytes."""
    def __init__(self):
        self._buffer = 0
        self._count = 0
        self._bytes = bytearray()

    def write(self, value: int, bits: int):
        """Append `value` using `bits` bits (MSB-first within each byte)."""
        if bits == 0:
            return
        # Mask to the requested bit width
        value = value & ((1 << bits) - 1)
        # Shift into buffer from the right
        self._buffer = (self._buffer << bits) | value
        self._count += bits
        # Drain complete bytes
        while self._count >= 8:
            self._count -= 8
            self._bytes.append((self._buffer >> self._count) & 0xFF)

    def flush(self) -> bytes:
        """Return accumulated bytes (zero-padded on the last partial byte)."""
        if self._count > 0:
            self._bytes.append((self._buffer << (8 - self._count)) & 0xFF)
        return bytes(self._bytes)

    def tell(self) -> int:
        """Total bits written so far."""
        return len(self._bytes) * 8 + self._count

    def tell_bytes(self) -> int:
        """Bytes consumed so far (counting partial byte as 1)."""
        return len(self._bytes) + (1 if self._count > 0 else 0)


class BitReader:
    """Read bits from a byte sequence."""
    def __init__(self, data: bytes):
        self._data = data
        self._byte_pos = 0
        self._bit_pos = 0  # 0-7, next bit to read within current byte

    def read(self, bits: int) -> int:
        """Read `bits` bits and return as integer (MSB-first)."""
        if bits == 0:
            return 0
        result = 0
        remaining = bits
        while remaining > 0:
            if self._byte_pos >= len(self._data):
                raise ValueError("BitReader: exhausted")
            # Bits available in current byte
            available = 8 - self._bit_pos
            take = min(remaining, available)
            # Extract `take` bits from current byte
            mask = (1 << take) - 1
            shift = available - take
            chunk = (self._data[self._byte_pos] >> shift) & mask
            result = (result << take) | chunk
            remaining -= take
            self._bit_pos += take
            if self._bit_pos >= 8:
                self._bit_pos = 0
                self._byte_pos += 1
        return result

    def skip(self, bits: int):
        """Skip `bits` without returning them."""
        self.read(bits)

    def tell(self) -> int:
        """Total bits consumed so far."""
        return self._byte_pos * 8 + self._bit_pos

    def remaining(self) -> int:
        """Bits remaining in the data."""
        total_bits = len(self._data) * 8
        return total_bits - self.tell()