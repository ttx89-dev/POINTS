"""Entity table encoding — two-tier, most fields optional.

Per Point 2:
  flags(1B): bit0=has_canonical_id, bit1=has_label
  [canonical_id(8B) if flagged]
  [label_offset(2B) + label_length(1B) if flagged]

Minimum: 1B. Maximum: 12B per entity.
"""

from __future__ import annotations
from .bits import BitWriter, BitReader
from .header import compute_entity_index_bits
from .structure import EntityTable, LiteralValue, LiteralType


def entity_table_size(entity_count: int) -> int:
    """Upper-bound: worst case all 12B each (canonical_id + label)."""
    return entity_count * 12


# NOTE: superseded by the inline entity encoder in glyph._pack_bytes
# (different byte order and feature set). Kept for reference only.
def encode_entity_table(graph, writer: BitWriter) -> tuple[list[bytes], bytes]:
    """Encode entity table. Returns (entity_records, label_pool_bytes).

    Each entity record uses the two-tier format. Labels are pooled
    into a separate byte region (the literal pool handles this in
    practice, but for the standalone entity table we accumulate
    label data here).
    """
    label_pool = bytearray()
    label_offsets = []  # (offset, length) into label_pool

    for ent in graph.entities:
        # Accumulate label
        label_bytes = ent.label.encode("utf-8")
        label_offsets.append((len(label_pool), len(label_bytes)))
        label_pool.extend(label_bytes)

    records = bytearray()
    for i, ent in enumerate(graph.entities):
        has_cid = 1 if ent.canonical_id else 0
        has_label = 1  # always include label for human readability
        flags = (has_cid << 1) | has_label
        records.append(flags)

        if has_cid:
            # canonical_id is stored as first 8 bytes of its FNV1a (for now,
            # we store the string truncated/padded to 8 bytes)
            cid_bytes = ent.canonical_id.encode("utf-8")
            if len(cid_bytes) > 8:
                cid_bytes = cid_bytes[:8]
            elif len(cid_bytes) < 8:
                cid_bytes = cid_bytes.ljust(8, b"\x00")
            records.extend(cid_bytes)

        if has_label:
            offset = label_offsets[i][0]
            length = label_offsets[i][1]
            records.append(offset & 0xFF)
            records.append((offset >> 8) & 0xFF)
            records.append(length & 0xFF)

    return graph.entities, bytes(label_pool)


def _read_literal_value(reader: BitReader) -> LiteralValue:
    """Read one LiteralValue from the bit stream (matches LiteralValue.as_bytes)."""
    t = LiteralType(reader.read(8))
    length = reader.read(8) | (reader.read(8) << 8)
    raw = bytes(reader.read(8) for _ in range(length))
    match t:
        case LiteralType.STRING:
            value = raw.decode("utf-8", errors="replace")
        case LiteralType.INTEGER:
            value = int(raw.decode("ascii", errors="replace"))
        case LiteralType.FLOAT:
            value = float(raw.decode("ascii", errors="replace"))
        case LiteralType.BOOLEAN:
            value = raw == b"1"
    return LiteralValue(t, value)


def decode_entity_table_ex(data: bytes, entity_count: int, eib: int,
                           label_pool: bytes) -> tuple[EntityTable, int]:
    """Decode entity records. Returns (EntityTable, label_pool_size).

    label_pool_size = bytes occupied by the concatenated entity labels;
    the edge literal pool begins right after it in the literal region (B3).

    Record layout (mirrors glyph._pack_bytes):
      flags(1B): bit0=has_label (=1), bit1=has_canonical_id,
                 bit2=has_properties_literal
      [canonical_id(8B)] if bit1
      [label_offset(2B, high byte first) + label_length(1B)] if bit0
      [prop_count(1B) + prop_count * (key_len(1B) + key + LiteralValue)] if bit2
    """
    reader = BitReader(data)
    entities = EntityTable()
    label_pool_size = 0

    for i in range(entity_count):
        flags = reader.read(8)
        has_cid = (flags >> 1) & 1
        has_label = flags & 1
        has_pl = (flags >> 2) & 1

        ent = {"id": i, "canonical_id": None, "label": ""}

        if has_cid:
            cid_bytes = bytearray()
            for _ in range(8):
                cid_bytes.append(reader.read(8))
            ent["canonical_id"] = cid_bytes.rstrip(b"\x00").decode("utf-8", errors="replace")

        if has_label:
            offset = reader.read(16)
            length = reader.read(8)
            label_raw = label_pool[offset:offset + length]
            ent["label"] = label_raw.decode("utf-8", errors="replace")
            label_pool_size = max(label_pool_size, offset + length)

        if has_pl:
            count = reader.read(8)
            props = {}
            for _ in range(count):
                klen = reader.read(8)
                key = bytes(reader.read(8) for _ in range(klen)).decode(
                    "utf-8", errors="replace")
                props[key] = _read_literal_value(reader)
            ent["properties_literal"] = props

        entities.append(ent)

    return entities, label_pool_size


def decode_entity_table(data: bytes, entity_count: int, eib: int,
                        label_pool: bytes) -> EntityTable:
    """Backward-compatible wrapper: rows only (see decode_entity_table_ex)."""
    return decode_entity_table_ex(data, entity_count, eib, label_pool)[0]