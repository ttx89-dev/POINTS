"""42-byte glyph header: pack/unpack.

Per Point 2:
  MAGIC               2B
  VERSION             1B
  SEQUENCE_ID         4B
  SEQUENCE_INDEX      1B
  SEQUENCE_TOTAL      1B
  PARITY_RATIO        1B
  PARITY_ALGO_ID      1B
  ENTITY_COUNT        2B
  ENTITY_INDEX_BITS   1B
  EDGE_COUNT          2B
  CONFIDENCE_BITS     1B
  FACET_COUNT         1B
  SALIENCE_ENTRY_COUNT 2B
  LITERAL_POOL_BYTES  2B
  REGION_OFFSETS     14B (7 regions × 2B)
  GRAPH_ID_PREFIX     4B
  HEADER_CHECKSUM     2B
  ────────────────────
  Total: 42 bytes
"""

from __future__ import annotations
import struct
from dataclasses import dataclass

MAGIC = b"PN"  # "Points Notation"
VERSION = 1

HEADER_SIZE = 42  # bytes (includes graph_id_prefix)
CONTENT_SIZE = 6920  # bytes for content (after 42B header, before parity)

# Region indices for REGION_OFFSETS (relative to content start at byte 42)
R_ENTITIES = 0
R_EDGES = 1
R_SALIENCE = 2
R_FACETS = 3
R_REIFICATION = 4
R_LITERAL_POOL = 5
R_CHUNK_META = 6  # chunk metadata (entity_offset, edge_offset, graph_id_full)
REGION_COUNT = 7


@dataclass
class Header:
    magic: bytes = MAGIC
    version: int = VERSION
    sequence_id: int = 0
    sequence_index: int = 0
    sequence_total: int = 1
    parity_ratio: int = 15
    parity_algo_id: int = 1  # 1 = xor-interleaved
    entity_count: int = 0
    entity_index_bits: int = 0
    edge_count: int = 0
    confidence_bits: int = 2  # 2 bits → 4 levels
    facet_count: int = 0
    salience_entry_count: int = 0
    literal_pool_bytes: int = 0
    graph_id_prefix: int = 0  # first 4 bytes of SHA256(graph_id)
    region_offsets: list[int] = None  # 7 offsets, bytes from content start
    reserved: bytes = b"\x00\x00\x00\x00"
    header_checksum: int = 0

    def __post_init__(self):
        if self.region_offsets is None:
            self.region_offsets = [0] * REGION_COUNT

    def pack(self) -> bytes:
        """Serialize header to 42 bytes."""
        buf = bytearray(42)
        # MAGIC (2 bytes)
        buf[0:2] = self.magic
        # VERSION (1)
        buf[2] = self.version
        # SEQUENCE_ID (4)
        struct.pack_into(">I", buf, 3, self.sequence_id)
        # SEQUENCE_INDEX (1)
        buf[7] = self.sequence_index
        # SEQUENCE_TOTAL (1)
        buf[8] = self.sequence_total
        # PARITY_RATIO (1)
        buf[9] = self.parity_ratio
        # PARITY_ALGO_ID (1)
        buf[10] = self.parity_algo_id
        # ENTITY_COUNT (2)
        struct.pack_into(">H", buf, 11, self.entity_count)
        # ENTITY_INDEX_BITS (1)
        buf[13] = self.entity_index_bits
        # EDGE_COUNT (2)
        struct.pack_into(">H", buf, 14, self.edge_count)
        # CONFIDENCE_BITS (1)
        buf[16] = self.confidence_bits
        # FACET_COUNT (1)
        buf[17] = self.facet_count
        # SALIENCE_ENTRY_COUNT (2)
        struct.pack_into(">H", buf, 18, self.salience_entry_count)
        # LITERAL_POOL_BYTES (2)
        struct.pack_into(">H", buf, 20, self.literal_pool_bytes)
        # REGION_OFFSETS (14 = 7 × 2)
        for i, offset in enumerate(self.region_offsets):
            struct.pack_into(">H", buf, 22 + i * 2, offset)
        # GRAPH_ID_PREFIX (4) — replaces RESERVED
        struct.pack_into(">I", buf, 36, self.graph_id_prefix)
        # HEADER_CHECKSUM (2) — compute after everything else
        cksum = _crc16(buf[:40])
        struct.pack_into(">H", buf, 40, cksum)
        self.header_checksum = cksum
        return bytes(buf)

    @classmethod
    def unpack(cls, data: bytes) -> Header:
        """Parse 42-byte header. CRC check on read."""
        if len(data) < 42:
            raise ValueError(f"Header too short: {len(data)} bytes (need 42)")

        # CRC check
        stored_crc = struct.unpack_from(">H", data, 40)[0]
        computed_crc = _crc16(data[:40])
        if stored_crc != computed_crc:
            raise ValueError(
                f"Header CRC mismatch: stored={stored_crc:#06x} computed={computed_crc:#06x}"
            )

        h = cls(
            magic=data[0:2],
            version=data[2],
            sequence_id=struct.unpack_from(">I", data, 3)[0],
            sequence_index=data[7],
            sequence_total=data[8],
            parity_ratio=data[9],
            parity_algo_id=data[10],
            entity_count=struct.unpack_from(">H", data, 11)[0],
            entity_index_bits=data[13],
            edge_count=struct.unpack_from(">H", data, 14)[0],
            confidence_bits=data[16],
            facet_count=data[17],
            salience_entry_count=struct.unpack_from(">H", data, 18)[0],
            literal_pool_bytes=struct.unpack_from(">H", data, 20)[0],
            graph_id_prefix=struct.unpack_from(">I", data, 36)[0],
            region_offsets=[
                struct.unpack_from(">H", data, 22 + i * 2)[0]
                for i in range(REGION_COUNT)
            ],
            reserved=b"\x00\x00\x00\x00",  # no longer used
            header_checksum=stored_crc,
        )
        return h

    def content_start(self) -> int:
        """Byte offset where content begins (always 42)."""
        return 42


def _crc16(data: bytes) -> int:
    """CRC-16-CCITT (0x1021 polynomial)."""
    crc = 0xFFFF
    for byte in data:
        crc ^= byte << 8
        for _ in range(8):
            if crc & 0x8000:
                crc = (crc << 1) ^ 0x1021
            else:
                crc <<= 1
            crc &= 0xFFFF
    return crc


def compute_entity_index_bits(entity_count: int) -> int:
    """ceil(log2(entity_count)), min 1."""
    if entity_count <= 1:
        return 1
    return (entity_count - 1).bit_length()


def compute_edge_index_bits(edge_count: int) -> int:
    """ceil(log2(edge_count)), min 1."""
    if edge_count <= 1:
        return 1
    return (edge_count - 1).bit_length()