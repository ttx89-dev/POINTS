"""Glyph orchestrator — pack() and unpack().

pack(graph) → 8192 raw bytes
unpack(bytes) → decoded KnowledgeGraph data

Full pipeline through the Point 2 dot-matrix encoding.

Codec fixes (2026-10-15):
  B1 — unpack()["entities"] is now an EntityTable (list + dict conveniences).
  B2 — Entity.properties_literal round-trips (flags bit2 + record extension).
  B3 — Literal edge targets resolve to decoded values ("target_raw" keeps
       the pool address; "target_resolved" reports success).
  B4 — Entities without canonical_id no longer corrupt the glyph (the label
       block is always written when flags bit0 is set).
"""

from __future__ import annotations
import math
from .bits import BitWriter, BitReader
from .header import (Header, HEADER_SIZE, CONTENT_SIZE, compute_entity_index_bits,
                     compute_edge_index_bits)
from .encode_entities import encode_entity_table, decode_entity_table_ex
from .encode_edges import encode_edges, decode_edges
from .encode_payload import (encode_facets, decode_facets,
                             encode_salience, decode_salience,
                             encode_reification, decode_reification)
from .parity import (encode_parity, verify_parity, compute_parity_size,
                     decode_and_repair)

GLYPH_SIZE = 8192  # bytes per glyph
HEADER_SIZE = 42     # bytes for header (includes graph_id_prefix)
CONTENT_SIZE = 6920  # bytes for content (after 42B header, before parity)
PARITY_DEFAULT_RATIO = 15  # %


def _coerce_literal(value) -> "LiteralValue":
    """Coerce a plain Python value to LiteralValue (bool before int)."""
    from .structure import LiteralValue, LiteralType
    if isinstance(value, LiteralValue):
        return value
    if isinstance(value, bool):
        return LiteralValue(LiteralType.BOOLEAN, value)
    if isinstance(value, int):
        return LiteralValue(LiteralType.INTEGER, value)
    if isinstance(value, float):
        return LiteralValue(LiteralType.FLOAT, value)
    return LiteralValue(LiteralType.STRING, str(value))


def _resolve_literal_targets(edges: list, edge_literal_pool: bytes) -> None:
    """B3 fix — resolve literal-edge pool addresses to decoded values, in place.

    Success: target = native value, target_raw = pool address,
             target_literal_type = LiteralType name, target_resolved = True.
    Failure (address outside the pool / corrupt literal bytes): target keeps
    the raw int and target_resolved = False.
    """
    from .structure import LiteralValue
    for e in edges:
        if not e.get("target_is_literal"):
            continue
        addr = e["target"]
        if isinstance(addr, int) and 0 <= addr < len(edge_literal_pool):
            try:
                val, _ = LiteralValue.from_bytes(edge_literal_pool[addr:])
                e["target"] = val.value
                e["target_raw"] = addr
                e["target_literal_type"] = val.type.name.lower()
                e["target_resolved"] = True
                continue
            except (ValueError, IndexError):
                pass
        e["target_resolved"] = False


def _pack_bytes(graph, sequence_id: int = 0, sequence_index: int = 0,
                sequence_total: int = 1, parity_ratio: int = PARITY_DEFAULT_RATIO,
                parity_algo_id: int = 1, graph_id_prefix: int = 0) -> bytes:
    """Pack a Graph into raw 8192 glyph bytes."""
    eib = compute_entity_index_bits(graph.entity_count)
    cb = 2  # confidence bits (fixed for now)

    # ── Stage 1: Encode all regions to bit streams ──
    # Entities: records + label_pool
    entity_records_bytes = bytearray()
    label_pool = bytearray()

    for ent in graph.entities:
        has_cid = 1 if ent.canonical_id else 0
        has_pl = 1 if ent.properties_literal else 0
        flags = (has_pl << 2) | (has_cid << 1) | 1  # bit0: label always present
        entity_records_bytes.append(flags)

        if has_cid:
            cid_bytes = ent.canonical_id.encode("utf-8")
            if len(cid_bytes) > 8:
                cid_bytes = cid_bytes[:8]
            elif len(cid_bytes) < 8:
                cid_bytes = cid_bytes.ljust(8, b"\x00")
            entity_records_bytes.extend(cid_bytes)

        # B4 fix: the label block is written whenever bit0 is set. It was
        # previously nested under `if has_cid:`, so entities without a
        # canonical_id produced corrupt glyphs (BitReader exhaustion).
        label_bytes = ent.label.encode("utf-8")
        offset = len(label_pool)
        entity_records_bytes.append((offset >> 8) & 0xFF)  # high byte (MSB-first)
        entity_records_bytes.append(offset & 0xFF)           # low byte
        entity_records_bytes.append(len(label_bytes) & 0xFF)
        label_pool.extend(label_bytes)

        if has_pl:
            # B2 fix: serialize literal-valued properties (previously dropped).
            # Layout: count(1B) + count * (key_len(1B) + key + LiteralValue)
            items = sorted(ent.properties_literal.items())
            entity_records_bytes.append(len(items) & 0xFF)
            for key, lit in items:
                key_bytes = str(key).encode("utf-8")
                entity_records_bytes.append(len(key_bytes) & 0xFF)
                entity_records_bytes.extend(key_bytes)
                entity_records_bytes.extend(_coerce_literal(lit).as_bytes())

    entity_table_bytes = bytes(entity_records_bytes)

    # Edges
    edge_writer = BitWriter()
    target_bits = max(eib, 16)
    literal_pool = bytearray()

    for i, edge in enumerate(graph.edges):
        if edge.target_is_literal:
            edge_writer.write(1, 1)  # full
            edge_writer.write(edge.source, eib)
            edge_writer.write(1, 1)  # target_kind=literal
            from .structure import LiteralValue
            if isinstance(edge.target, LiteralValue):
                lit_bytes = edge.target.as_bytes()
            else:
                s = str(edge.target).encode("utf-8")
                lit_bytes = bytes([0, len(s) & 0xFF, (len(s) >> 8) & 0xFF]) + s
            target_addr = len(literal_pool)
            literal_pool.extend(lit_bytes)
            edge_writer.write(target_addr, target_bits)
            edge_writer.write(edge.relation_type, 3)
            edge_writer.write(edge.subtype, 3)
            edge_writer.write(edge.confidence, cb)
            edge_writer.write(edge.polarity, 1)
            edge_writer.write(1 if edge.reified else 0, 1)
        else:
            can_compact = (edge.subtype == 0 and edge.confidence == 0 and not edge.reified)
            if can_compact:
                edge_writer.write(0, 1)  # compact
                edge_writer.write(edge.source, eib)
                edge_writer.write(0, 1)  # target_kind=entity
                edge_writer.write(edge.target, eib)
                edge_writer.write(edge.relation_type, 3)
                edge_writer.write(edge.polarity, 1)
            else:
                edge_writer.write(1, 1)  # full
                edge_writer.write(edge.source, eib)
                edge_writer.write(0, 1)
                edge_writer.write(edge.target, target_bits)
                edge_writer.write(edge.relation_type, 3)
                edge_writer.write(edge.subtype, 3)
                edge_writer.write(edge.confidence, cb)
                edge_writer.write(edge.polarity, 1)
                edge_writer.write(1 if edge.reified else 0, 1)

    edge_table_bytes = edge_writer.flush()

    # Facets
    facet_bytes = encode_facets(graph)

    # Salience
    salience_bytes = encode_salience(graph, eib)

    # Reification
    edge_index_bits = compute_edge_index_bits(graph.edge_count)
    reification_bytes = encode_reification(graph, eib, edge_index_bits)

    # ── Stage 2: Assemble content block (up to CONTENT_SIZE bytes) ──
    # Order: entities + edges + salience + facets + reification + literal_pool
    # Offsets are relative to content start (byte HEADER_SIZE)
    content = bytearray()
    offset_entities = 0
    content.extend(entity_table_bytes)
    offset_edges = len(content)
    content.extend(edge_table_bytes)
    offset_salience = len(content)
    content.extend(salience_bytes)
    offset_facets = len(content)
    content.extend(facet_bytes)
    offset_reification = len(content)
    content.extend(reification_bytes)
    offset_literal_pool = len(content)
    content.extend(label_pool)   # entity labels first
    content.extend(literal_pool)  # then property literals

    # Pad or truncate to CONTENT_SIZE
    if len(content) > CONTENT_SIZE:
        content = content[:CONTENT_SIZE]
    elif len(content) < CONTENT_SIZE:
        content.extend(b"\x00" * (CONTENT_SIZE - len(content)))

    content = bytes(content)

    # ── Stage 3: Parity ──
    parity_size = compute_parity_size(CONTENT_SIZE, parity_ratio)
    parity_block = encode_parity(content, parity_algo_id, parity_ratio)

    # Trim/pad parity to expected size
    if len(parity_block) > parity_size:
        parity_block = parity_block[:parity_size]
    elif len(parity_block) < parity_size:
        parity_block = parity_block.ljust(parity_size, b"\x00")

    # ── Stage 4: Build header ──
    header = Header(
        sequence_id=sequence_id,
        sequence_index=sequence_index,
        sequence_total=sequence_total,
        parity_ratio=parity_ratio,
        parity_algo_id=parity_algo_id,
        entity_count=graph.entity_count,
        entity_index_bits=eib,
        edge_count=graph.edge_count,
        confidence_bits=cb,
        facet_count=len(graph.facets),
        salience_entry_count=len(graph.salience),
        literal_pool_bytes=len(literal_pool) + len(label_pool),
        graph_id_prefix=graph_id_prefix,
        region_offsets=[
            offset_entities,
            offset_edges,
            offset_salience,
            offset_facets,
            offset_reification,
            offset_literal_pool,
            0,  # R_CHUNK_META - not used in single glyph
        ],
    )

    # ── Stage 5: Assemble full glyph ──
    glyph_bytes = header.pack() + content + parity_block

    # Pad or trim to exactly GLYPH_SIZE
    if len(glyph_bytes) < GLYPH_SIZE:
        glyph_bytes = glyph_bytes.ljust(GLYPH_SIZE, b"\x00")
    elif len(glyph_bytes) > GLYPH_SIZE:
        glyph_bytes = glyph_bytes[:GLYPH_SIZE]

    assert len(glyph_bytes) == GLYPH_SIZE, f"Glyph size {len(glyph_bytes)} != 8192"

    return glyph_bytes


def pack(graph, **kwargs) -> bytes:
    """Pack a Graph into raw 8192 glyph bytes.

    Returns bytes for transport via session state, files, or agents.
    """
    return _pack_bytes(graph, **kwargs)


# Backward-compatible aliases
pack_bytes = pack


def unpack(data: bytes) -> dict:
    """Unpack raw 8192 glyph bytes into structured dict.

    entities is an EntityTable (list-compatible; supports .values(), label
    lookup). Literal edges carry the decoded value in "target" plus
    "target_raw" / "target_literal_type" / "target_resolved" (B1/B3 fixes).
    """
    if len(data) != GLYPH_SIZE:
        if len(data) < HEADER_SIZE:
            raise ValueError(f"Glyph too short: {len(data)} bytes (need {HEADER_SIZE}+)")
        if len(data) < GLYPH_SIZE:
            data = data.ljust(GLYPH_SIZE, b"\x00")

    # Parse header
    header = Header.unpack(data[:HEADER_SIZE])
    content = data[HEADER_SIZE:HEADER_SIZE + CONTENT_SIZE]

    # ── Parity: detect corruption & repair (RS) ──
    parity_start = HEADER_SIZE + CONTENT_SIZE
    parity_size = compute_parity_size(CONTENT_SIZE, header.parity_ratio,
                                      algo_id=header.parity_algo_id)
    parity_block = data[parity_start:parity_start + parity_size]

    # Run decode_and_repair (no-op for XOR, correction for RS)
    corrected_content, errors_corrected = decode_and_repair(
        content, parity_block, header.parity_algo_id)
    content = corrected_content

    parity_ok = verify_parity(content, parity_block,
                              header.parity_algo_id,
                              ratio=header.parity_ratio)

    # ── Decode regions from content ──
    offsets = header.region_offsets
    eib = header.entity_index_bits
    cb = header.confidence_bits

    # Entities
    if header.entity_count > 0:
        ent_end = offsets[1] if offsets[1] > 0 else len(content)
        ent_data = content[offsets[0]:ent_end]
    else:
        ent_data = b""

    # Label pool is embedded in literal_pool region
    literal_pool_start = offsets[5]
    literal_pool_data = content[literal_pool_start:] if literal_pool_start < len(content) else b""

    entities, label_pool_size = decode_entity_table_ex(
        ent_data, header.entity_count, eib, literal_pool_data)

    # Edges
    if header.edge_count > 0:
        edge_end = offsets[2] if offsets[2] > offsets[1] else len(content)
        edge_data = content[offsets[1]:edge_end]
        edge_reader = BitReader(edge_data)
        target_bits = max(eib, 16)
        edges = decode_edges(edge_reader, header.edge_count, eib, cb, target_bits)

        # B3 fix: resolve literal-edge targets. Literal region layout:
        # [label pool][edge literal pool]; the split point is the label-pool
        # size derived from entity label extents. If the header's literal
        # bounds are inconsistent (corrupt glyph), resolution degrades
        # gracefully and edges carry target_resolved=False.
        region = b""
        if (header.literal_pool_bytes > 0
                and literal_pool_start + header.literal_pool_bytes <= len(content)):
            region = content[literal_pool_start:literal_pool_start + header.literal_pool_bytes]
        _resolve_literal_targets(edges, region[label_pool_size:])
    else:
        edges = []

    # Facets
    if header.facet_count > 0:
        facet_end = offsets[4] if offsets[4] > offsets[3] else len(content)
        facet_data = content[offsets[3]:facet_end]
        facets = decode_facets(facet_data, header.facet_count)
    else:
        facets = []

    # Salience
    if header.salience_entry_count > 0:
        sal_end = offsets[3] if offsets[3] > offsets[2] else len(content)
        sal_data = content[offsets[2]:sal_end]
        salience = decode_salience(sal_data, header.salience_entry_count, eib)
    else:
        salience = []

    # Reification
    if offsets[4] > 0 and offsets[5] > offsets[4]:
        reif_data = content[offsets[4]:offsets[5]]
    else:
        reif_data = b""
    edge_index_bits = compute_edge_index_bits(header.edge_count)
    reifications = decode_reification(reif_data, eib, edge_index_bits)

    return {
        "header": {
            "magic": header.magic.decode("ascii", errors="replace"),
            "version": header.version,
            "sequence": {
                "id": header.sequence_id,
                "index": header.sequence_index,
                "total": header.sequence_total,
            },
            "entity_count": header.entity_count,
            "edge_count": header.edge_count,
            "entity_index_bits": eib,
            "edge_index_bits": edge_index_bits,
            "confidence_bits": cb,
            "facet_count": header.facet_count,
            "salience_entry_count": header.salience_entry_count,
            "literal_pool_bytes": header.literal_pool_bytes,
            "graph_id_prefix": header.graph_id_prefix,
            "parity_algo": header.parity_algo_id,
            "parity_ok": parity_ok,
            "errors_corrected": errors_corrected,
        },
        "entities": entities,
        "edges": edges,
        "facets": facets,
        "salience": salience,
        "reifications": reifications,
        "stats": {
            "total_bytes": len(data),
            "content_bytes": len(content),
            "parity_bytes": len(parity_block),
            "parity_verified": parity_ok,
            "errors_corrected": errors_corrected,
        },
    }


# Backward-compatible alias
unpack_bytes = unpack
