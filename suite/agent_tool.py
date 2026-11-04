"""Agent tool — the function another agent calls to encode/decode POINTS.

Session-key mode (same session):
    char = encode_points(graph)          # returns U+E000, stores payload in session state
    result = decode_points(char)         # resolves from session state

Raw bytes mode (cross-session / file transport):
    glyph = encode_graph_str(graph)      # returns 8192 raw bytes
    result = decode_points(glyph)        # decodes directly

Inspection:
    points_info() -> dict               # current session state summary
    points_clear() -> dict              # wipe session state

Legacy:
    decode_glyph(data) -> dict          # same as decode_points for raw bytes
    glyph_summary(data) -> dict         # fast header-only inspect
"""

from __future__ import annotations
from .glyph import unpack as _unpack

# Re-export all session-key tools
from .points_tool import (
    encode_points,
    decode_points,
    encode_graph_str,
    points_info,
    points_clear,
    POINTS_CHAR,
)


def decode_glyph(data: bytes) -> dict:
    """Decode raw glyph bytes into structured knowledge.

    Args:
        data: Raw 8192-byte glyph payload.

    Returns:
        dict with keys: header, entities, edges, facets, salience,
                        reifications, stats
    """
    return _unpack(data)


def glyph_summary(data: bytes) -> dict:
    """Quick summary of a glyph without full decode.

    Returns header info and counts. Faster than full decode
    for cursory inspection.
    """
    from .header import Header

    if len(data) < 42:
        return {"error": "Glyph too short"}

    header = Header.unpack(data[:42])
    return {
        "magic": header.magic.decode("ascii", errors="replace"),
        "version": header.version,
        "sequence": f"{header.sequence_index + 1}/{header.sequence_total}",
        "entities": header.entity_count,
        "edges": header.edge_count,
        "eib": header.entity_index_bits,
        "facets": header.facet_count,
        "salience_entries": header.salience_entry_count,
        "literal_pool_bytes": header.literal_pool_bytes,
        "graph_id_prefix": f"0x{header.graph_id_prefix:08x}",
        "parity_algo": header.parity_algo_id,
    }
