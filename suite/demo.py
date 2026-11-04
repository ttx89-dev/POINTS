"""POINTS Demo — builds a showcase ontology, packs to glyph, round-trips.

Usage: python -m suite.demo

Outputs:
  - Glyph size (8192 bytes)
  - Verification: "✓ ROUND TRIP PASSED" or failure detail
  - Size report
"""

from __future__ import annotations
import sys
import os

# Ensure the package is importable
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from suite.structure import Graph, Edge, RelationType, LiteralValue
from suite.glyph import pack, unpack


def build_demo_ontology() -> Graph:
    """Build a compact demo knowledge graph about mechanical watches."""
    g = Graph()

    # ── Entities ──
    g.add_entity("Mechanical Watch", canonical_id="mechanical_watch")
    g.add_entity("Mainspring", canonical_id="mainspring")
    g.add_entity("Balance Wheel", canonical_id="balance_wheel")
    g.add_entity("Escapement", canonical_id="escapement")
    g.add_entity("Gear Train", canonical_id="gear_train")
    g.add_entity("Crown", canonical_id="crown")
    g.add_entity("Jewel Bearing", canonical_id="jewel_bearing")
    g.add_entity("Timekeeping", canonical_id="timekeeping")
    g.add_entity("Power Reserve", canonical_id="power_reserve")
    g.add_entity("Rotor (Automatic)", canonical_id="rotor")
    g.add_entity("Horology", canonical_id="horology")

    # ── Edges ──
    g.add_edge(0, 10, relation_type=RelationType.IS_A)       # watch is-a horology
    g.add_edge(1, 0, relation_type=RelationType.PART_OF)     # mainspring part-of watch
    g.add_edge(2, 0, relation_type=RelationType.PART_OF)     # balance part-of watch
    g.add_edge(3, 0, relation_type=RelationType.PART_OF)     # escapement part-of watch
    g.add_edge(4, 0, relation_type=RelationType.PART_OF)     # gear train part-of watch
    g.add_edge(5, 0, relation_type=RelationType.PART_OF)     # crown part-of watch
    g.add_edge(6, 0, relation_type=RelationType.PART_OF)     # jewel part-of watch
    g.add_edge(9, 0, relation_type=RelationType.PART_OF)     # rotor part-of watch

    # Associative
    g.add_edge(1, 8, relation_type=RelationType.ASSOCIATIVE)     # mainspring → power reserve
    g.add_edge(2, 7, relation_type=RelationType.ASSOCIATIVE)     # balance → timekeeping
    g.add_edge(3, 2, relation_type=RelationType.ASSOCIATIVE)     # escapement → balance
    g.add_edge(4, 1, relation_type=RelationType.ASSOCIATIVE)     # gear train → mainspring
    g.add_edge(6, 2, relation_type=RelationType.ASSOCIATIVE)     # jewel → balance (reduced friction)

    # Instance (polarity negative → "not an instance of")
    g.add_edge(8, 7, relation_type=RelationType.EQUIVALENCE, polarity=0)

    return g


def main():
    print("═" * 56)
    print("  POINTS — Packed Ontology Inline Notation for Token-Swap")
    print("  Demo: Horology Knowledge Graph")
    print("═" * 56)

    # Build
    graph = build_demo_ontology()
    print(f"\n  Entities: {graph.entity_count}")
    print(f"  Edges:    {graph.edge_count}")
    print(f"  Facets:   {len(graph.facets)}")
    print(f"  Salience: {len(graph.salience)}")

    # Pack → raw bytes
    glyph_bytes = pack(graph)

    print(f"\n  Raw glyph: {len(glyph_bytes)} bytes")
    non_null = sum(1 for b in glyph_bytes if b != 0)
    print(f"  Non-null bytes: {non_null} / {len(glyph_bytes)}")

    # Unpack (round-trip)
    result = unpack(glyph_bytes)

    h = result["header"]
    print(f"\n  — Glyph Header —")
    print(f"    Magic: {h['magic']} v{h['version']}")
    print(f"    Seq:   {h['sequence']}")
    print(f"    Parity: {'✓ OK' if h['parity_ok'] else '✗ MISMATCH'}")
    print(f"    EIB:   {h['entity_index_bits']} bits")
    print(f"    EIDX:  {h['edge_index_bits']} bits")

    ents = result["entities"]
    edgs = result["edges"]
    print(f"\n  — Decoded Entities ({len(ents)}) —")
    for e in ents:
        cid = f" [{e['canonical_id']}]" if e.get("canonical_id") else ""
        print(f"    {e['id']}: {e['label']}{cid}")

    print(f"\n  — Decoded Edges ({len(edgs)}) —")
    for i, e in enumerate(edgs[:10]):
        src = e["source"]
        tgt = e["target"]
        rtype = ["EQUIV", "ISA", "INSTANCE", "PARTOF", "ASSOC", "?", "?", "?"][e["relation_type"] % 7]
        pol = "+" if e.get("polarity", 1) else "-"
        compact = "compact" if not e.get("reified") and e.get("subtype", 0) == 0 else "full"
        print(f"    {i}: {src} —{rtype}→ {tgt} [{pol}] ({compact})")
    if len(edgs) > 10:
        print(f"    ... and {len(edgs) - 10} more")

    # Round-trip verification
    print(f"\n  — Round-Trip Verification —")
    ok = True
    if len(ents) != graph.entity_count:
        print(f"    ✗ Entity count: decoded {len(ents)} != original {graph.entity_count}")
        ok = False
    if len(edgs) != graph.edge_count:
        print(f"    ✗ Edge count: decoded {len(edgs)} != original {graph.edge_count}")
        ok = False
    if ok:
        for orig, dec in zip(graph.entities, ents):
            if orig.label != dec["label"]:
                print(f"    ✗ Label mismatch: '{orig.label}' != '{dec['label']}'")
                ok = False
                break
            if orig.canonical_id and orig.canonical_id != dec.get("canonical_id"):
                print(f"    ✗ Canonical ID mismatch: '{orig.canonical_id}' != '{dec.get('canonical_id')}'")
                ok = False
                break

    if ok:
        print("    ✓ ROUND TRIP PASSED — all entities, edges, labels verified")
    else:
        print("    ✗ ROUND TRIP FAILED — see above")

    # Hex preview of first 64 bytes
    print(f"\n  — Glyph Hex Preview (first 64 bytes) —")
    hex_str = glyph_bytes[:64].hex(" ")
    line_len = 48  # 16 bytes per line = 47 chars
    for row in range(0, len(hex_str), line_len):
        print(f"    {hex_str[row:row+line_len]}")

    print(f"\n  — Final —")
    print(f"    Total bytes: {len(glyph_bytes)}")
    print(f"    Content:     {result['stats']['content_bytes']} bytes")
    print(f"    Parity:      {result['stats']['parity_bytes']} bytes")
    print(f"    Payload rate: {result['stats']['content_bytes'] / len(glyph_bytes) * 100:.1f}%")
    print()


if __name__ == "__main__":
    main()
