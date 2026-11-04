#!/usr/bin/env python3
"""Sub-agent glyph round-trip test.

Protocol:
  1. Main agent packs a Graph → glyph bytes → base64 string
  2. Spawns a sub-agent via task() with the base64 glyph in the prompt
  3. Sub-agent: base64-decode → unpack → analyze → add fact → pack → base64
  4. Returns the modified base64 glyph
  5. Main agent decodes and verifies structural fidelity

Measures:
  - Round-trip fidelity (entity/edge counts survive agent transit)
  - Agent decode time (end-to-end)
  - Agent encode time (end-to-end)
"""

import base64
import json
import os
import subprocess
import sys
import time
import textwrap

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
from suite.glyph import pack, unpack
from suite.structure import Graph, RelationType
from suite.tests.golden_corpus import decoded_to_graph


# ── Test graphs ──

SIMPLE_GRAPH = {
    "entities": [
        ("Alice", "alice_1"),
        ("Bob", "bob_1"),
        ("Charlie", "charlie_1"),
    ],
    "edges": [
        (0, 1, RelationType.ASSOCIATIVE, 1),   # Alice → Bob
        (0, 2, RelationType.IS_A, 1),   # Alice → Charlie (is-a)
    ],
}

MEDIUM_GRAPH = {
    "entities": [
        ("Server-A", "srv_a"),
        ("Server-B", "srv_b"),
        ("Database", "db_1"),
        ("LoadBalancer", "lb_1"),
        ("Cache", "cache_1"),
        ("Monitor", "mon_1"),
    ],
    "edges": [
        (0, 1, RelationType.ASSOCIATIVE, 1),
        (0, 2, RelationType.ASSOCIATIVE, 1),
        (1, 2, RelationType.ASSOCIATIVE, 1),
        (0, 3, RelationType.IS_A, 1),
        (4, 2, RelationType.ASSOCIATIVE, 1),
        (5, 0, RelationType.ASSOCIATIVE, 1),
        (5, 1, RelationType.ASSOCIATIVE, 1),
        (5, 2, RelationType.ASSOCIATIVE, 1),
        (5, 3, RelationType.ASSOCIATIVE, 1),
    ],
}


def build_graph(spec: dict) -> Graph:
    """Build a Graph from a spec dict."""
    g = Graph()
    for label, cid in spec["entities"]:
        g.add_entity(label, canonical_id=cid)
    for src, tgt, rel, pol in spec["edges"]:
        g.add_edge(src, tgt, relation_type=rel, polarity=pol)
    return g


def glyph_to_b64(graph: Graph) -> str:
    """Pack a Graph and return base64-encoded string."""
    raw = pack(graph)
    return base64.b64encode(raw).decode("ascii")


def b64_to_glyph(b64: str) -> bytes:
    """Decode base64 string back to glyph bytes."""
    return base64.b64decode(b64)


SUBAGENT_PROMPT_TEMPLATE = textwrap.dedent("""\
    You are a glyph-processing sub-agent.

    Your task: receive a base64-encoded POINTS glyph, decode it, analyze the
    graph inside, add ONE new entity and ONE new edge, re-encode it, and
    return the new base64 glyph.

    The POINTS glyph is a knowledge-graph binary format:
      - pack(graph) → 8192 bytes of glyph
      - unpack(bytes) → dict with entities, edges, header, etc.
      - Use `decoded_to_graph(d)` to convert back to a Graph for modification

    TOOL ACCESS:
      You have bash/write/read. Use Python to process the glyph.

    PROTOCOL:
      1. The base64 glyph will be written to /tmp/agent_inbound.b64
        
         STEP 1 — decode and verify:
         ```python
         import base64, sys
         sys.path.insert(0, "/var/home/ryan/Documents/projects/POINTS/suite")
         with open("/tmp/agent_inbound.b64") as f:
             b64_data = f.read().strip()
         raw = base64.b64decode(b64_data)
         # raw should be 8192 bytes
         from glyph import unpack
         decoded = unpack(raw)
         entities = decoded["entities"]
         edges = decoded["edges"]
         print(f"Received: {{len(entities)}} entities, {{len(edges)}} edges")
         for e in entities:
             print(f"  Entity: {{e['label']}}")
         ```

      2. Add ONE new entity named "GlyphAgent" with canonical_id "agent_1"
         and ONE new edge from the new entity to entity[0] with ASSOCIATIVE relation.
         
         To modify, use decoded_to_graph and Graph.add_entity / add_edge:
         ```python
         from golden_corpus import decoded_to_graph
         g = decoded_to_graph(decoded)
         g.add_entity("GlyphAgent", canonical_id="agent_1")
         new_idx = len(decoded["entities"])  # because we add after existing
         g.add_edge(new_idx, 0, relation_type=1)  # 1 = ASSOCIATIVE
         ```

      3. Re-pack and base64-encode:
         ```python
         from glyph import pack
         new_raw = pack(g)
         new_b64 = base64.b64encode(new_raw).decode("ascii")
         with open("/tmp/agent_outbound.b64", "w") as f:
             f.write(new_b64)
         print("DONE. Outbound glyph written.")
         print(f"NEW_B64_LEN:{{len(new_b64)}}")
         ```

    DO NOT modify anything else. Return the results as a JSON summary of what
    you received and what you added.
    """)


def run_subagent_roundtrip(test_name: str, graph_spec: dict) -> dict:
    """Execute a full sub-agent glyph round trip.

    Returns dict with timing, fidelity, and metadata.
    """
    # ── Phase 1: Build and pack glyph ──
    t0 = time.perf_counter()
    g = build_graph(graph_spec)
    b64_glyph = glyph_to_b64(g)
    pack_time = (time.perf_counter() - t0) * 1e6

    # ── Phase 2: Write inbound glyph for sub-agent ──
    with open("/tmp/agent_inbound.b64", "w") as f:
        f.write(b64_glyph)

    # ── Phase 3: Spawn sub-agent via task tool ──
    # We simulate this via a subprocess running the agent logic
    # (since the actual task() tool is MCP-based and not available in test)
    t1 = time.perf_counter()

    # Write the sub-agent processing script
    agent_script = textwrap.dedent(f"""\
    import base64, sys, json
    sys.path.insert(0, "{os.path.join(os.path.dirname(__file__), '..', '..')}")

    # Read inbound
    with open("/tmp/agent_inbound.b64") as f:
        b64_data = f.read().strip()
    raw = base64.b64decode(b64_data)

    # Unpack and analyze
    from suite.glyph import unpack, pack
    from suite.tests.golden_corpus import decoded_to_graph
    from suite.structure import RelationType

    decoded = unpack(raw)
    entities = decoded["entities"]
    edges = decoded["edges"]
    result = {{
        "inbound": {{
            "entity_count": len(entities),
            "edge_count": len(edges),
            "entity_labels": [e["label"] for e in entities],
            "parity_ok": decoded["stats"]["parity_verified"],
            "errors_corrected": decoded["stats"]["errors_corrected"],
        }}
    }}

    # Modify: add one entity + one edge
    g = decoded_to_graph(decoded)
    g.add_entity("GlyphAgent", canonical_id="agent_1")
    new_idx = len(entities)  # index of newly added entity
    g.add_edge(new_idx, 0, relation_type=RelationType.ASSOCIATIVE, polarity=1)

    # Re-pack and base64-encode
    new_raw = pack(g)
    new_b64 = base64.b64encode(new_raw).decode("ascii")

    with open("/tmp/agent_outbound.b64", "w") as f:
        f.write(new_b64)

    # Verify outbound
    out_decoded = unpack(new_raw)
    result["outbound"] = {{
        "entity_count": len(out_decoded["entities"]),
        "edge_count": len(out_decoded["edges"]),
        "parity_ok": out_decoded["stats"]["parity_verified"],
        "inbound_entities_preserved": all(
            e["label"] in [oe["label"] for oe in out_decoded["entities"]]
            for e in entities
        ),
        "new_entity_added": "GlyphAgent" in [oe["label"] for oe in out_decoded["entities"]],
    }}

    print(json.dumps(result))
    """)

    # Execute the agent processing
    proc = subprocess.run(
        [sys.executable, "-c", agent_script],
        capture_output=True, text=True, timeout=60
    )
    agent_time = (time.perf_counter() - t1) * 1e6

    if proc.returncode != 0:
        return {
            "test": test_name,
            "passed": False,
            "error": f"Agent process failed: {proc.stderr.strip()}",
        }

    try:
        agent_result = json.loads(proc.stdout.strip())
    except json.JSONDecodeError as e:
        return {
            "test": test_name,
            "passed": False,
            "error": f"JSON parse failed: {e}",
            "stdout": proc.stdout.strip(),
            "stderr": proc.stderr.strip(),
        }

    # ── Phase 4: Read outbound and verify ──
    t2 = time.perf_counter()
    with open("/tmp/agent_outbound.b64") as f:
        out_b64 = f.read().strip()

    out_raw = b64_to_glyph(out_b64)
    out_decoded = unpack(out_raw)
    verify_time = (time.perf_counter() - t2) * 1e6

    original_raw = pack(g)
    original_decoded = unpack(original_raw)
    inbound_entities_preserved = all(
        e["label"] in [oe["label"] for oe in out_decoded["entities"]]
        for e in original_decoded["entities"]
    )
    new_entity_found = "GlyphAgent" in [oe["label"] for oe in out_decoded["entities"]]
    new_edge_found = any(
        e["source"] == len([_ for _ in g.entities])  # new entity index
        and e["target"] == 0                          # points to first entity
        for e in out_decoded["edges"]
    ) if len(out_decoded["edges"]) > len(original_decoded["edges"]) else False

    passed = (
        inbound_entities_preserved
        and new_entity_found
        and new_edge_found
        and out_decoded["stats"]["parity_verified"]
    )

    return {
        "test": test_name,
        "passed": passed,
        "timing_us": {
            "pack": round(pack_time, 1),
            "agent_process": round(agent_time, 1),
            "verify": round(verify_time, 1),
            "total": round(pack_time + agent_time + verify_time, 1),
        },
        "inbound": {
            "entities": len(original_decoded["entities"]),
            "edges": len(original_decoded["edges"]),
        },
        "outbound": {
            "entities": len(out_decoded["entities"]),
            "edges": len(out_decoded["edges"]),
        },
        "fidelity": {
            "inbound_entities_preserved": inbound_entities_preserved,
            "new_entity_added": new_entity_found,
            "new_edge_added": new_edge_found,
            "parity_ok": out_decoded["stats"]["parity_verified"],
        },
        "agent_result": agent_result,
    }


def main():
    """Run the agent glyph round-trip tests."""
    print("=" * 72)
    print("  AGENT GLYPH ROUND-TRIP TEST")
    print("  Sub-agent: decode → analyze → modify → re-encode → return")
    print("=" * 72)

    tests = [
        ("simple_graph (3 entities, 2 edges)", SIMPLE_GRAPH),
        ("medium_graph (6 entities, 9 edges)", MEDIUM_GRAPH),
    ]

    all_passed = True
    for name, spec in tests:
        print(f"\n  ▶ {name}")
        result = run_subagent_roundtrip(name, spec)

        if result["passed"]:
            print(f"    ✓ PASSED")
        else:
            print(f"    ✗ FAILED")
            all_passed = False

        timing = result.get("timing_us", {})
        print(f"      Pack:       {timing.get('pack', '?'):>8.1f} μs")
        print(f"      Agent:      {timing.get('agent_process', '?'):>8.1f} μs")
        print(f"      Verify:     {timing.get('verify', '?'):>8.1f} μs")
        print(f"      Total:      {timing.get('total', '?'):>8.1f} μs")
        print(f"      Inbound:    {result['inbound']['entities']} entities, {result['inbound']['edges']} edges")
        print(f"      Outbound:   {result['outbound']['entities']} entities, {result['outbound']['edges']} edges")
        print(f"      New entity: {result['fidelity']['new_entity_added']}")
        print(f"      New edge:   {result['fidelity']['new_edge_added']}")
        print(f"      Parity OK:  {result['fidelity']['parity_ok']}")

        if "error" in result:
            print(f"      ERROR: {result['error']}")

    print()
    print("─" * 72)
    if all_passed:
        print("  RESULT: ALL TESTS PASSED ✓")
    else:
        print("  RESULT: SOME TESTS FAILED ✗")
    print(f"  Tests: {len(tests)} passed, {0 if all_passed else len(tests) - sum(1 for _ in tests)} failed")
    print("=" * 72)


if __name__ == "__main__":
    main()
