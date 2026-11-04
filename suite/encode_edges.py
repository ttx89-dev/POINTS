"""Edge table encoding — compact/full duality.

Per Point 2:
  Compact (leading=0):
    source[EIB] + target_kind[1]=0 + target[EIB] + relation_type[3] + polarity[1]
    = 2*EIB + 6 bits, subtype=0, confidence=max, reified=false

  Full (leading=1):
    source[EIB] + target_kind[1] + target[TARGET_BITS] + relation_type[3]
    + subtype[3] + confidence[CB] + polarity[1] + reified[1]
    where TARGET_BITS = max(EIB, 16)
    = EIB + 1 + TARGET_BITS + 3 + 3 + CB + 1 + 1
    = EIB + TARGET_BITS + CB + 10 bits
"""

from __future__ import annotations
import math
from .bits import BitWriter, BitReader
from .header import compute_entity_index_bits, compute_edge_index_bits


def encode_edges(graph, writer: BitWriter,
                 eib: int, cb: int) -> tuple[int, list, bytes]:
    """Encode edge table to the writer. Returns (edge_count, reification_list, literal_pool_bytes)."""
    eib = eib or compute_entity_index_bits(len(graph.entities))
    cb = cb or 2
    target_bits = max(eib, 16)

    literal_pool = bytearray()
    reification_list = []
    edge_count = len(graph.edges)

    for i, edge in enumerate(graph.edges):
        if edge.target_is_literal:
            # Full encoding with literal target
            writer.write(1, 1)  # leading=full
            writer.write(edge.source, eib)
            writer.write(1, 1)  # target_kind=literal
            # Target is a literal pool address — we need to place it first
            # and record the offset. For now, just append and use pool position.
            if isinstance(edge.target, LiteralValue):
                lit_bytes = edge.target.as_bytes()
            else:
                # If already bytes, write as string literal
                if isinstance(edge.target, bytes):
                    lit_bytes = bytes([0, len(edge.target) & 0xFF, (len(edge.target) >> 8) & 0xFF]) + edge.target
                else:
                    lit_bytes = bytes([0, 0, 0])  # empty string
            target_addr = len(literal_pool)
            literal_pool.extend(lit_bytes)
            writer.write(target_addr, target_bits)
            writer.write(edge.relation_type, 3)
            writer.write(edge.subtype, 3)
            writer.write(edge.confidence, cb)
            writer.write(edge.polarity, 1)
            writer.write(1 if edge.reified else 0, 1)
        else:
            # Entity-to-entity: try compact, fall back to full
            can_compact = (
                edge.subtype == 0
                and edge.confidence == 0  # CERTAIN
                and not edge.reified
            )
            if can_compact:
                writer.write(0, 1)  # leading=compact
                writer.write(edge.source, eib)
                writer.write(0, 1)  # target_kind=entity
                writer.write(edge.target, eib)
                writer.write(edge.relation_type, 3)
                writer.write(edge.polarity, 1)
            else:
                writer.write(1, 1)  # leading=full
                writer.write(edge.source, eib)
                writer.write(0, 1)  # target_kind=entity
                writer.write(edge.target, target_bits)
                writer.write(edge.relation_type, 3)
                writer.write(edge.subtype, 3)
                writer.write(edge.confidence, cb)
                writer.write(edge.polarity, 1)
                writer.write(1 if edge.reified else 0, 1)

        if edge.reified:
            # Record the edge → entity mapping
            reification_list.append((i, edge.target if not edge.target_is_literal else 0))

    return edge_count, reification_list, bytes(literal_pool)


def decode_edges(reader: BitReader, edge_count: int, eib: int, cb: int,
                 target_bits: int) -> list[dict]:
    """Decode edges from bit stream. Returns list of edge dicts."""
    edges = []
    for i in range(edge_count):
        leading = reader.read(1)
        if leading == 0:  # compact
            source = reader.read(eib)
            target_kind = reader.read(1)
            target = reader.read(eib)
            relation_type = reader.read(3)
            polarity = reader.read(1)
            edges.append({
                "source": source,
                "target": target,
                "target_is_literal": bool(target_kind),
                "relation_type": relation_type,
                "subtype": 0,
                "confidence": 0,
                "polarity": polarity,
                "reified": False,
                "reified_edge_index": 0,
            })
        else:  # full
            source = reader.read(eib)
            target_kind = reader.read(1)
            target = reader.read(target_bits)
            relation_type = reader.read(3)
            subtype = reader.read(3)
            confidence = reader.read(cb)
            polarity = reader.read(1)
            reified = reader.read(1)
            edges.append({
                "source": source,
                "target": target,
                "target_is_literal": bool(target_kind),
                "relation_type": relation_type,
                "subtype": subtype,
                "confidence": confidence,
                "polarity": polarity,
                "reified": bool(reified),
                "reified_edge_index": 0,
            })
    return edges


# Circular import workaround: import at function call time
from .structure import LiteralValue