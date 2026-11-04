"""Payload encoding: facets, salience, reification table, literal pool.

Per Point 2:
  Facets: facet_id(1B) + dimension_count(1B) + dimension_ids(1B each)
  Salience: entity_index(EIB) + source_id(2b) + scalar(1B)
  Reification: edge_index(EIB) + entity_index(EIB)  (each padded to bytes)
  Literal pool: raw bytes, TLV-tagged, referenced by edges with target_kind=1
"""

from __future__ import annotations
from .bits import BitWriter, BitReader
from .header import compute_entity_index_bits, compute_edge_index_bits


def encode_facets(graph) -> bytes:
    """Facets are simple byte sequences: id + count + ids."""
    buf = bytearray()
    for facet in graph.facets:
        buf.append(facet.facet_id & 0xFF)
        buf.append(facet.dimension_count & 0xFF)
        for dim_id in facet.dimension_ids:
            buf.append(dim_id & 0xFF)
    return bytes(buf)


def decode_facets(data: bytes, facet_count: int) -> list[dict]:
    """Decode facet records."""
    facets = []
    pos = 0
    for _ in range(facet_count):
        if pos >= len(data):
            break
        fid = data[pos]
        dcount = data[pos + 1]
        dims = list(data[pos + 2:pos + 2 + dcount])
        facets.append({"facet_id": fid, "dimension_count": dcount, "dimension_ids": dims})
        pos += 2 + dcount
    return facets


def encode_salience(graph, eib: int) -> bytes:
    """Salience entries (non-structural only): entity_index + source(2b) + scalar(1B)."""
    writer = BitWriter()
    for entry in graph.salience:
        writer.write(entry.entity_index, eib)
        writer.write(int(entry.source), 2)
        # scalar: 0.0-1.0 → 0-255
        scaled = max(0, min(255, int(entry.scalar * 255)))
        writer.write(scaled, 8)
    return writer.flush()


def decode_salience(data: bytes, count: int, eib: int) -> list[dict]:
    """Decode salience entries."""
    reader = BitReader(data)
    entries = []
    for _ in range(count):
        ei = reader.read(eib)
        src = reader.read(2)
        scalar_raw = reader.read(8)
        entries.append({
            "entity_index": ei,
            "source": src,
            "scalar": scalar_raw / 255.0,
        })
    return entries


def encode_reification(graph, eib: int, edge_index_bits: int) -> bytes:
    """Reification table: edge_index + entity_index."""
    if not graph.reifications:
        return b""
    writer = BitWriter()
    for entry in graph.reifications:
        writer.write(entry.edge_index, edge_index_bits)
        writer.write(entry.entity_index, eib)
    return writer.flush()


def decode_reification(data: bytes, eib: int, eidx_bits: int) -> list[dict]:
    """Decode reification entries."""
    if not data:
        return []
    reader = BitReader(data)
    entries = []
    # We don't know the count from the header directly — infer from data size
    entry_bits = eib + eidx_bits
    if entry_bits == 0:
        return []
    count = (len(data) * 8) // entry_bits
    for _ in range(count):
        ei_edge = reader.read(eidx_bits)
        ei_entity = reader.read(eib)
        entries.append({"edge_index": ei_edge, "entity_index": ei_entity})
    return entries