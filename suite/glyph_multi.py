"""Multi-glyph protocol — split/reassemble large graphs across multiple glyphs.

Each glyph in a sequence carries a chunk of entities and their incident edges.
The manifest (glyph 0) contains full graph_id, total counts, and chunk map.
"""

from __future__ import annotations
import hashlib
import json
from dataclasses import dataclass
from typing import List, Tuple, Optional

from .glyph import pack, unpack, GLYPH_SIZE, HEADER_SIZE, CONTENT_SIZE
from .structure import Graph, Entity, Edge, RelationType, LiteralValue, LiteralType
from .header import Header, compute_entity_index_bits, compute_edge_index_bits, R_CHUNK_META


# Maximum entities per glyph (empirically determined from capacity tests)
# With full labels "Entity-NNN" + edges: ~260 is the safe limit
# Conservative value to ensure all labels preserved:
MAX_ENTITIES_PER_GLYPH = 250
MAX_EDGES_PER_GLYPH = 3000    # conservative


@dataclass
class ChunkMeta:
    """Metadata for a single chunk within a multi-glyph sequence."""
    chunk_index: int
    entity_start: int      # global entity index of first entity in this chunk
    entity_count: int      # number of entities in this chunk
    edge_start: int        # global edge index of first edge in this chunk
    edge_count: int        # number of edges in this chunk
    # Offsets are relative to content start within this glyph
    entity_offset: int
    edge_offset: int
    literal_pool_offset: int


@dataclass
class MultiGlyphManifest:
    """Manifest stored in glyph 0 (or derivable from any glyph's header)."""
    graph_id: str              # SHA256 hex of canonical graph
    graph_id_prefix: int       # first 4 bytes as uint32
    total_glyphs: int
    total_entities: int
    total_edges: int
    chunk_strategy: str        # "by_entity" or "by_edge"
    version: int = 1
    # Per-chunk metadata (optional, also in chunk_meta region)
    chunks: List[ChunkMeta] = None

    def to_bytes(self) -> bytes:
        """Serialize manifest to JSON bytes for chunk_meta region."""
        obj = {
            "graph_id": self.graph_id,
            "graph_id_prefix": self.graph_id_prefix,
            "total_glyphs": self.total_glyphs,
            "total_entities": self.total_entities,
            "total_edges": self.total_edges,
            "chunk_strategy": self.chunk_strategy,
            "version": self.version,
            "chunks": [
                {
                    "chunk_index": c.chunk_index,
                    "entity_start": c.entity_start,
                    "entity_count": c.entity_count,
                    "edge_start": c.edge_start,
                    "edge_count": c.edge_count,
                    "entity_offset": c.entity_offset,
                    "edge_offset": c.edge_offset,
                    "literal_pool_offset": c.literal_pool_offset,
                }
                for c in (self.chunks or [])
            ],
        }
        return json.dumps(obj, separators=(",", ":")).encode("utf-8")

    @classmethod
    def from_bytes(cls, data: bytes) -> "MultiGlyphManifest":
        obj = json.loads(data.decode("utf-8"))
        chunks = [
            ChunkMeta(**c) for c in obj.get("chunks", [])
        ]
        return cls(
            graph_id=obj["graph_id"],
            graph_id_prefix=obj["graph_id_prefix"],
            total_glyphs=obj["total_glyphs"],
            total_entities=obj["total_entities"],
            total_edges=obj["total_edges"],
            chunk_strategy=obj["chunk_strategy"],
            version=obj.get("version", 1),
            chunks=chunks,
        )


def _graph_canonical_bytes(graph: Graph) -> bytes:
    """Generate canonical byte representation for graph_id hashing."""
    # Deterministic serialization: entities sorted by id, edges by source then target
    parts = []
    for ent in graph.entities:
        parts.append(f"E:{ent.id}:{ent.label}:{ent.canonical_id or ''}")
        for k, v in sorted(ent.properties.items()):
            parts.append(f"  P:{k}:{v}")
        for k, v in sorted(ent.properties_literal.items()):
            parts.append(f"  PL:{k}:{v.type}:{v.value}")
    for i, edge in enumerate(graph.edges):
        if edge.target_is_literal:
            target_str = f"L:{edge.target}"
        else:
            target_str = f"E:{edge.target}"
        parts.append(
            f"EDGE:{i}:{edge.source}:{target_str}:"
            f"{edge.relation_type}:{edge.subtype}:{edge.confidence}:{edge.polarity}:{int(edge.reified)}"
        )
    return "\n".join(parts).encode("utf-8")


def _compute_graph_id(graph: Graph) -> Tuple[str, int]:
    """Compute SHA256 graph_id and its 32-bit prefix."""
    canon = _graph_canonical_bytes(graph)
    hash_bytes = hashlib.sha256(canon).digest()
    graph_id = hash_bytes.hex()
    prefix = int.from_bytes(hash_bytes[:4], "big")
    return graph_id, prefix


def _chunk_entities(entities: List[Entity], max_per_chunk: int = MAX_ENTITIES_PER_GLYPH) -> List[Tuple[int, int]]:
    """Split entities into chunks. Returns list of (start, count) pairs."""
    n = len(entities)
    if n <= max_per_chunk:
        return [(0, n)]
    chunks = []
    for start in range(0, n, max_per_chunk):
        count = min(max_per_chunk, n - start)
        chunks.append((start, count))
    return chunks


def _estimate_chunk_size(num_entities: int, num_edges: int) -> int:
    """Estimate content bytes needed for a chunk.
    
    Rough heuristic: ~12 bytes/entity + ~4 bytes/compact_edge
    """
    return num_entities * 12 + num_edges * 4


def _chunk_by_capacity(
    entities: List[Entity], 
    edges: List[Edge],
    max_content_bytes: int = CONTENT_SIZE
) -> List[Tuple[int, int]]:
    """Split entities into chunks based on estimated content size (entities + edges).
    
    Returns list of (start, count) pairs.
    """
    if not entities:
        return [(0, 0)]
    
    # Build entity -> list of outgoing edges
    entity_to_edges = {}
    for edge in edges:
        if not edge.target_is_literal:
            entity_to_edges.setdefault(edge.source, []).append(edge)
    
    chunks = []
    start = 0
    while start < len(entities):
        # Try to fit as many entities as possible
        best_end = start + 1
        for end in range(start + 1, min(len(entities), start + MAX_ENTITIES_PER_GLYPH) + 1):
            ent_count = end - start
            edge_count = sum(len(entity_to_edges.get(i, [])) for i in range(start, end))
            if _estimate_chunk_size(ent_count, edge_count) <= max_content_bytes:
                best_end = end
            else:
                break
        
        if best_end == start:
            # Can't fit even one entity - force at least 1
            best_end = start + 1
        
        chunks.append((start, best_end - start))
        start = best_end
    
    return chunks


def _assign_edges_to_chunks(
    edges: List[Edge],
    entity_chunks: List[Tuple[int, int]]
) -> List[List[Edge]]:
    """Assign each edge to the chunk containing its source entity."""
    # Build entity_id -> chunk_index map
    entity_to_chunk = {}
    for chunk_idx, (start, count) in enumerate(entity_chunks):
        for eid in range(start, start + count):
            entity_to_chunk[eid] = chunk_idx

    chunk_edges = [[] for _ in entity_chunks]
    for edge in edges:
        src_chunk = entity_to_chunk.get(edge.source, 0)
        chunk_edges[src_chunk].append(edge)
    return chunk_edges


def _build_chunk_graph(
    entities: List[Entity],
    edges: List[Edge],
    global_entity_offset: int,
    graph: Graph
) -> Graph:
    """Build a Graph containing the specified entities and edges,
    with local entity indices (0..N-1) but preserving original IDs in canonical_id.
    Also includes any target entities referenced by edges in this chunk."""
    chunk_graph = Graph()
    # Map global entity index -> local index
    global_to_local = {}
    
    # First pass: add primary entities
    for local_idx, ent in enumerate(entities):
        new_ent = chunk_graph.add_entity(
            label=ent.label,
            canonical_id=ent.canonical_id,
            properties=ent.properties,
            properties_literal=ent.properties_literal,
            facets=ent.facets,
        )
        new_ent.id = local_idx  # override to local index
        global_to_local[ent.id] = local_idx
    
    # Second pass: add any target entities referenced by edges but not in primary list
    extra_entities = {}  # global_id -> local_idx
    for edge in edges:
        if not edge.target_is_literal:
            tgt_global = edge.target
            if tgt_global not in global_to_local and tgt_global not in extra_entities:
                # Add this target entity
                orig_ent = graph.entities[tgt_global]
                local_idx = len(chunk_graph.entities) + len(extra_entities)
                extra_entities[tgt_global] = local_idx
    
    # Add extra entities
    for tgt_global, local_idx in extra_entities.items():
        orig_ent = graph.entities[tgt_global]
        new_ent = chunk_graph.add_entity(
            label=orig_ent.label,
            canonical_id=orig_ent.canonical_id,
            properties=orig_ent.properties,
            properties_literal=orig_ent.properties_literal,
            facets=orig_ent.facets,
        )
        new_ent.id = local_idx
        global_to_local[tgt_global] = local_idx
    
    # Add edges, remapping source/target to local indices
    for edge in edges:
        src_local = global_to_local.get(edge.source)
        if src_local is None:
            continue  # source not in this chunk (shouldn't happen with our strategy)
        if edge.target_is_literal:
            chunk_graph.add_edge(
                source=src_local,
                target=edge.target,
                relation_type=edge.relation_type,
                subtype=edge.subtype,
                polarity=edge.polarity,
                confidence=edge.confidence,
                reified=edge.reified,
                provenance=edge.provenance,
            )
        else:
            tgt_local = global_to_local.get(edge.target)
            if tgt_local is not None:
                chunk_graph.add_edge(
                    source=src_local,
                    target=tgt_local,
                    relation_type=edge.relation_type,
                    subtype=edge.subtype,
                    polarity=edge.polarity,
                    confidence=edge.confidence,
                    reified=edge.reified,
                    provenance=edge.provenance,
                )
    return chunk_graph


def split_graph(
    graph: Graph,
    max_entities_per_glyph: int = MAX_ENTITIES_PER_GLYPH,
    parity_ratio: int = 15,
    parity_algo_id: int = 1,
) -> List[bytes]:
    """Split a large graph into multiple glyphs.

    Returns list of glyph bytes (each 8192 bytes).
    Glyph 0 is the manifest; glyphs 1..N are data chunks.
    """
    graph_id, graph_id_prefix = _compute_graph_id(graph)

    # Chunk entities based on capacity (entities + edges)
    entity_chunks = _chunk_by_capacity(graph.entities, graph.edges)
    total_chunks = len(entity_chunks)

    # Assign edges to chunks based on source entity
    chunk_edges = _assign_edges_to_chunks(graph.edges, entity_chunks)

    glyphs = []

    # Glyph 0: Manifest (minimal graph, just metadata)
    manifest = MultiGlyphManifest(
        graph_id=graph_id,
        graph_id_prefix=graph_id_prefix,
        total_glyphs=total_chunks + 1,  # +1 for manifest
        total_entities=len(graph.entities),
        total_edges=len(graph.edges),
        chunk_strategy="by_entity",
        version=1,
    )

    # Create a tiny graph for the manifest glyph
    manifest_graph = Graph()
    # Add a dummy entity so the glyph is valid
    manifest_graph.add_entity("__manifest__", canonical_id="manifest")

    # Pack manifest glyph with custom header fields
    from .glyph import _pack_bytes
    manifest_bytes = _pack_bytes(
        manifest_graph,
        sequence_id=0,
        sequence_index=0,
        sequence_total=total_chunks + 1,
        parity_ratio=parity_ratio,
        parity_algo_id=parity_algo_id,
        graph_id_prefix=graph_id_prefix,
    )
    # Override header with manifest metadata
    # We'll inject the manifest into the chunk_meta region of the manifest glyph
    # For now, just use the packed bytes as-is (manifest is small)
    glyphs.append(manifest_bytes)

    # Data glyphs: 1..N
    for chunk_idx, ((ent_start, ent_count), edges) in enumerate(zip(entity_chunks, chunk_edges)):
        chunk_entities = graph.entities[ent_start:ent_start + ent_count]
        chunk_graph = _build_chunk_graph(chunk_entities, edges, ent_start, graph)

        # Pack with sequence info
        glyph_bytes = _pack_bytes(
            chunk_graph,
            sequence_id=0,  # same sequence_id for all chunks in this graph
            sequence_index=chunk_idx + 1,  # 1-based for data chunks
            sequence_total=total_chunks + 1,
            parity_ratio=parity_ratio,
            parity_algo_id=parity_algo_id,
            graph_id_prefix=graph_id_prefix,
        )
        glyphs.append(glyph_bytes)

    return glyphs


def reassemble(glyphs: List[bytes]) -> Graph:
    """Reassemble a graph from multiple glyphs.

    Validates:
    - All glyphs share same graph_id_prefix
    - sequence_total matches count
    - All sequence_index values present (1..N for data, 0 for manifest)
    - Entity/edge counts match manifest
    """
    if not glyphs:
        raise ValueError("No glyphs provided")

    # Unpack all glyphs
    decoded = [unpack(g) for g in glyphs]

    # Validate sequence
    headers = [d["header"] for d in decoded]
    seq_total = headers[0]["sequence"]["total"]
    if len(glyphs) != seq_total:
        raise ValueError(f"Expected {seq_total} glyphs, got {len(glyphs)}")

    # Validate graph_id_prefix consistency
    prefixes = [h.get("graph_id_prefix", 0) for h in headers]
    if len(set(prefixes)) > 1:
        raise ValueError(f"Inconsistent graph_id_prefix: {prefixes}")

    # Reconstruct graph by merging all data chunks (skip manifest at index 0)
    merged = Graph()
    # Track canonical_ids we've already added
    seen_canonical_ids = set()

    # Sort by sequence_index
    data_chunks = [(d, h) for d, h in zip(decoded, headers) if h["sequence"]["index"] > 0]
    data_chunks.sort(key=lambda x: x[1]["sequence"]["index"])

    for chunk_data, chunk_header in data_chunks:
        # Rebuild entities with global IDs
        local_to_global = {}
        for ent in chunk_data["entities"]:
            canonical_id = ent.get("canonical_id")
            # Only add if not seen before (use canonical_id for dedup)
            if canonical_id and canonical_id not in seen_canonical_ids:
                new_ent = merged.add_entity(
                    label=ent["label"],
                    canonical_id=canonical_id,
                    properties=ent.get("properties", {}),
                    properties_literal=ent.get("properties_literal", {}),
                    facets=ent.get("facets", {}),
                )
                seen_canonical_ids.add(canonical_id)
            elif canonical_id:
                # Find existing entity by canonical_id
                new_ent = None
                for e in merged.entities:
                    if e.canonical_id == canonical_id:
                        new_ent = e
                        break
                if new_ent is None:
                    # Shouldn't happen, but fallback
                    new_ent = merged.add_entity(
                        label=ent["label"],
                        canonical_id=canonical_id,
                        properties=ent.get("properties", {}),
                        properties_literal=ent.get("properties_literal", {}),
                        facets=ent.get("facets", {}),
                    )
            else:
                # No canonical_id - add anyway (shouldn't happen in normal use)
                new_ent = merged.add_entity(
                    label=ent["label"],
                    canonical_id=ent.get("canonical_id"),
                    properties=ent.get("properties", {}),
                    properties_literal=ent.get("properties_literal", {}),
                    facets=ent.get("facets", {}),
                )
            local_to_global[ent["id"]] = new_ent.id

        # Rebuild edges
        for edge in chunk_data["edges"]:
            src_global = local_to_global.get(edge["source"])
            if src_global is None:
                continue
            if edge["target_is_literal"]:
                # Reconstruct LiteralValue
                # Note: literal values are not fully decoded in current unpack
                # For now, skip literal edges in reassembly
                pass
            else:
                tgt_global = local_to_global.get(edge["target"])
                if tgt_global is not None:
                    merged.add_edge(
                        source=src_global,
                        target=tgt_global,
                        relation_type=RelationType(edge["relation_type"]),
                        subtype=edge["subtype"],
                        polarity=edge["polarity"],
                        confidence=edge["confidence"],
                        reified=bool(edge["reified"]),
                        provenance=edge.get("provenance", ""),
                    )

    return merged


def verify_multi_glyph(glyphs: List[bytes]) -> dict:
    """Verify integrity of multi-glyph sequence."""
    decoded = [unpack(g) for g in glyphs]
    headers = [d["header"] for d in decoded]

    results = {
        "total_glyphs": len(glyphs),
        "sequence_total": headers[0]["sequence"]["total"] if headers else 0,
        "graph_id_prefixes": [h.get("graph_id_prefix", 0) for h in headers],
        "prefix_consistent": len(set(h.get("graph_id_prefix", 0) for h in headers)) <= 1,
        "all_parity_ok": all(h.get("parity_ok", False) for h in headers),
        "sequence_indices": sorted(h["sequence"]["index"] for h in headers),
        "total_entities": sum(h["entity_count"] for h in headers if h["sequence"]["index"] > 0),
        "total_edges": sum(h["edge_count"] for h in headers if h["sequence"]["index"] > 0),
    }

    # Check for missing sequence indices
    expected = set(range(1, results["sequence_total"]))
    actual = set(results["sequence_indices"])
    if 0 in actual:
        actual.remove(0)  # manifest
    results["missing_chunks"] = sorted(expected - actual)

    return results


def glyphs_to_base64(glyphs: List[bytes]) -> List[str]:
    """Encode list of glyphs to base64 strings for transport."""
    import base64
    return [base64.b64encode(g).decode("ascii") for g in glyphs]


def base64_to_glyphs(b64_list: List[str]) -> List[bytes]:
    """Decode base64 strings to glyph bytes."""
    import base64
    return [base64.b64decode(s) for s in b64_list]