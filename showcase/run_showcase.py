#!/usr/bin/env python3
"""Showcase runner: loads YAML tasks, builds graphs, demonstrates full POINTS pipeline."""

import sys
import os
import yaml
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from suite.structure import Graph, Entity, Edge, RelationType, FacetEntry, SalienceEntry, SalienceSource, Confidence
from suite.glyph import pack_bytes, unpack_bytes, pack, unpack
from suite.points_tool import encode_points, decode_points, points_info, points_clear

TASK_DIR = os.path.join(os.path.dirname(__file__), "tasks")

def load_task_yaml(path: str) -> dict:
    with open(path) as f:
        return yaml.safe_load(f)

def build_graph(task: dict) -> Graph:
    g = Graph()
    entity_ids = {}
    
    # Entities
    for e in task.get("entities", []):
        ent = g.add_entity(label=e["label"])
        entity_ids[e["id"]] = ent.id
        if "properties" in e:
            for k, v in e["properties"].items():
                ent.properties[k] = str(v)
    
    # Edges
    for ed in task.get("edges", []):
        src = entity_ids[ed["source"]]
        tgt = entity_ids[ed["target"]]
        rel = getattr(RelationType, ed["relation"])
        sub = ed.get("subtype", 0)
        g.add_edge(src, tgt, rel, subtype=sub)
    
    # Facets - simple: facet_id=0, dimension_ids=[1] etc.
    for i, f in enumerate(task.get("facets", [])):
        g.add_facet(facet_id=i, dimension_ids=[i + 1])
    
    # Salience
    for s in task.get("salience", []):
        ent_id = entity_ids[s["entity"]]
        src = getattr(SalienceSource, s["source"].upper())
        g.add_salience(ent_id, src, s["weight"])
    
    return g

def demo_task(task_file: str):
    print(f"\n{'='*60}")
    print(f"TASK: {task_file}")
    print(f"{'='*60}")
    
    task = load_task_yaml(os.path.join(TASK_DIR, task_file))
    g = build_graph(task)
    
    print(f"Entities: {g.entity_count}, Edges: {g.edge_count}")
    print(f"Facets: {len(g.facets)}, Salience: {len(g.salience)}")
    
    # 1. Raw bytes round-trip
    raw = pack_bytes(g)
    decoded = unpack_bytes(raw)
    print(f"\n1. RAW BYTES: {len(raw)}B → entities={len(decoded['entities'])}, edges={len(decoded['edges'])}")
    assert decoded['header']['entity_count'] == g.entity_count
    assert decoded['header']['edge_count'] == g.edge_count
    print("   ✓ Round-trip verified")
    
    # 2. Session-key transport
    handle = encode_points(g)
    print(f"\n2. SESSION KEY: {handle!r} (U+{ord(handle):04X})")
    info = points_info()
    print(f"   Session: {info['status']}, bytes={info.get('bytes')}, entities={info['entities']}")
    
    # 3. Decode via handle
    decoded2 = decode_points(handle)
    print(f"3. DECODE VIA HANDLE: entities={len(decoded2['entities'])}, edges={len(decoded2['edges'])}")
    assert decoded2['header']['entity_count'] == g.entity_count
    print("   ✓ Handle decode verified")
    
    # 4. Braille fallback (legacy)
    braille = pack(g)
    decoded3 = unpack(braille)
    print(f"\n4. BRAILLE FALLBACK: {len(braille)} chars → entities={len(decoded3['entities'])}")
    assert decoded3['header']['entity_count'] == g.entity_count
    print("   ✓ Braille decode verified")
    
    # 5. Clear session
    points_clear()
    print("\n5. SESSION CLEARED")
    
    # Summary
    print(f"\n   Entities decoded:")
    for e in decoded['entities']:
        print(f"     - [{e['id']}] {e['label']} ({e['canonical_id']})")
    print(f"   Edges decoded:")
    for ed in decoded['edges']:
        print(f"     - {ed['source']} → {ed['target']} [{ed['relation_type']}]")
    return True


def demo_beam_search():
    """Run the beam search sub-agent on a small graph and show the result."""
    print(f"\n{'='*60}")
    print(f"SUB-AGENT: beam_search")
    print(f"{'='*60}")

    from showcase.subagent_beam import BeamSubAgent

    # Build a graph with competing paths and a blocked edge
    g = Graph()
    s = g.add_entity("start:gate")
    f = g.add_entity("node:fast_route")
    c = g.add_entity("node:certain_route")
    d = g.add_entity("node:detour")
    z = g.add_entity("goal:treasure")

    # Path A: gate → fast_route → certain_route → treasure (3 hops, all CERTAIN = 1.0)
    g.add_edge(s.id, f.id, RelationType.ASSOCIATIVE, 1, confidence=Confidence.CERTAIN)
    g.add_edge(f.id, c.id, RelationType.ASSOCIATIVE, 1, confidence=Confidence.CERTAIN)
    g.add_edge(c.id, z.id, RelationType.ASSOCIATIVE, 1, confidence=Confidence.CERTAIN)

    # Path B: gate → detour → treasure (2 hops, but PLAUSIBLE = 0.6 × 0.6 = 0.36)
    g.add_edge(s.id, d.id, RelationType.ASSOCIATIVE, 1, confidence=Confidence.PLAUSIBLE)
    g.add_edge(d.id, z.id, RelationType.ASSOCIATIVE, 1, confidence=Confidence.PLAUSIBLE)

    # Blocked: gate → treasure direct (negated, impassable)
    g.add_edge(s.id, z.id, RelationType.ASSOCIATIVE, 1, confidence=Confidence.CERTAIN, polarity=0)

    print(f"Graph: {g.entity_count} entities, {g.edge_count} edges")
    print(f"  Path A: gate→fast→certain→treasure (CERTAIN → score 1.0)")
    print(f"  Path B: gate→detour→treasure (PLAUSIBLE → score 0.36)")
    print(f"  Blocked: gate→treasure direct (negated)")

    # Run beam search (beam width = 2)
    handle = encode_points(g)
    agent = BeamSubAgent(beam_width=2)
    result = agent.run(handle)
    decoded = decode_points(result)

    path_label = decoded["entities"][1]["label"]
    print(f"\n  Best path: {path_label}")

    # Trace the hops
    hops = []
    for e in decoded["entities"]:
        lbl = e["label"]
        if lbl.startswith("hop:"):
            hops.append(lbl.replace("hop:", ""))
    if hops:
        print(f"  Route: {' → '.join(hops)}")
    else:
        print(f"  Route: [no hops — binary round-trip strips metadata]")

    print(f"  Beam width: 2")

    points_clear()
    return True


def main():
    print("POINTS SHOWCASE — Full Pipeline Demo")
    print("=" * 60)
    
    task_files = sorted(f for f in os.listdir(TASK_DIR) if f.endswith(".yaml"))
    print(f"Found {len(task_files)} task(s): {task_files}")
    
    all_ok = True
    for tf in task_files:
        try:
            demo_task(tf)
        except Exception as e:
            print(f"\n✗ FAILED: {tf} — {e}")
            import traceback
            traceback.print_exc()
            all_ok = False
    
    print("\n" + "=" * 60)
    if all_ok:
        print("ALL TASKS PASSED ✓")
    else:
        print("SOME TASKS FAILED ✗")
    demo_beam_search()

    print("=" * 60)
    return 0 if all_ok else 1

if __name__ == "__main__":
    sys.exit(main())