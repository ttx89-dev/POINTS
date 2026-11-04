"""Golden corpus: 7 reference glyphs for regression and adversarial testing.

Each entry defines a Graph, its packed braille string, and the expected
decoded structure. Tests verify:
  - round-trip: pack(unpack(glyph)) == glyph
  - exact decoded structure (entity/edge counts, specific values)
  - header field consistency

Usage:
    from suite.tests.golden_corpus import CORPUS

    for name, entry in CORPUS.items():
        assert entry["packed"] == pack(entry["graph"])
        decoded = unpack(entry["packed"])
        assert decoded["header"]["entity_count"] == entry["expect"]["entities"]

The 7 entries form a feature progression:
  0. empty_graph    — 0 entities, 0 edges (header-only)
  1. single_entity  — 1 entity, 0 edges
  2. single_edge    — 2 entities, 1 compact edge (IS_A)
  3. multi_edge     — 4 entities, 3 edges (mix of relation types)
  4. with_payload   — entities + literal edges + facets + salience
  5. negated_varied — polarity=0 + non-default confidence
  6. demo_graph     — the Mechanical Watch ontology (backward compat)
"""

from __future__ import annotations
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from suite.structure import (
    Graph, Entity, Edge, LiteralValue, LiteralType,
    RelationType, MeronymySubtype, AssociativeLabel,
    Confidence, SalienceSource,
)
from suite.glyph import pack, unpack
from suite.bits import BitWriter, BitReader

# ── Helper: canonical pack → decode round-trip ──

def _canonical(graph: Graph) -> dict:
    """Return the decoded dict for a graph after pack→unpack.
    
    This is the reference decode. Tests compare against the
    fields in 'expect', not the full decode (which includes
    padding artifacts like zeroed content bytes).
    """
    packed = pack(graph)
    decoded = unpack(packed)
    return {
        "packed": packed,
        "decoded": decoded,
    }


# ── Entry 0: Empty Graph ──────────────────────────────────────────

def _build_empty() -> Graph:
    return Graph()

def _expect_empty() -> dict:
    return {
        "entities": 0,
        "edges": 0,
        "facets": 0,
        "salience_entries": 0,
        "reifications": 0,
        "glyph_size": 8192,  # always 8192 bytes
        "header_version": 1,
    }


# ── Entry 1: Single Entity ────────────────────────────────────────

def _build_single_entity() -> Graph:
    g = Graph()
    g.add_entity("Hydrogen", canonical_id="H")
    return g

def _expect_single_entity() -> dict:
    return {
        "entities": 1,
        "edges": 0,
        "facets": 0,
        "entity_labels": ["Hydrogen"],
    }


# ── Entry 2: Single Edge (compact) ────────────────────────────────

def _build_single_edge() -> Graph:
    g = Graph()
    g.add_entity("Sparrow", canonical_id="passer")
    g.add_entity("Bird", canonical_id="aves")
    g.add_edge(0, 1, relation_type=RelationType.IS_A)
    return g

def _expect_single_edge() -> dict:
    return {
        "entities": 2,
        "edges": 1,
        "entity_labels": ["Sparrow", "Bird"],
        "edge_count": 1,
        "first_edge_relation": int(RelationType.IS_A),
    }


# ── Entry 3: Multi-Edge with Mixed Relation Types ─────────────────

def _build_multi_edge() -> Graph:
    g = Graph()
    g.add_entity("Car", canonical_id="car")
    g.add_entity("Engine", canonical_id="engine")
    g.add_entity("Vehicle", canonical_id="vehicle")
    g.add_entity("Road", canonical_id="road")

    g.add_edge(0, 2, relation_type=RelationType.IS_A)
    g.add_edge(1, 0, relation_type=RelationType.PART_OF,
               subtype=MeronymySubtype.COMPONENT_INTEGRAL)
    g.add_edge(0, 3, relation_type=RelationType.ASSOCIATIVE,
               subtype=AssociativeLabel.USED_FOR)
    return g

def _expect_multi_edge() -> dict:
    return {
        "entities": 4,
        "edges": 3,
        "entity_labels": ["Car", "Engine", "Vehicle", "Road"],
    }


# ── Entry 4: With Payload (facets, salience, literal edges) ───────

def _build_with_payload() -> Graph:
    g = Graph()
    g.add_entity("Paris", canonical_id="paris")
    g.add_entity("France", canonical_id="france")
    g.add_entity("Eiffel Tower", canonical_id="eiffel")
    g.add_entity("Seine", canonical_id="seine")

    # Literal-valued edge
    g.add_edge(0, LiteralValue(LiteralType.STRING, "City of Light"),
               relation_type=RelationType.ASSOCIATIVE,
               subtype=AssociativeLabel.HAS_PROPERTY)
    g.add_edge(0, 1, relation_type=RelationType.PART_OF,
               subtype=MeronymySubtype.PLACE_AREA)
    g.add_edge(2, 0, relation_type=RelationType.PART_OF,
               subtype=MeronymySubtype.COMPONENT_INTEGRAL)
    g.add_edge(3, 0, relation_type=RelationType.PART_OF,
               subtype=MeronymySubtype.PLACE_AREA)

    # Facets
    g.add_facet(0, [1])  # facet_id=0, dim=historical
    g.add_facet(1, [2])  # facet_id=1, dim=geographical

    # Salience
    g.add_salience(0, SalienceSource.EMPIRICAL, 0.95)
    g.add_salience(2, SalienceSource.DESIGNER_INTENDED, 0.80)

    return g

def _expect_with_payload() -> dict:
    return {
        "entities": 4,
        "edges": 4,
        "facets": 2,
        "salience_entries": 2,
        "entity_labels": ["Paris", "France", "Eiffel Tower", "Seine"],
    }


# ── Entry 5: Negated Edges + Varied Confidence ────────────────────

def _build_negated_varied() -> Graph:
    g = Graph()
    g.add_entity("Whale", canonical_id="whale")
    g.add_entity("Fish", canonical_id="fish")
    g.add_entity("Mammal", canonical_id="mammal")
    g.add_entity("Ocean", canonical_id="ocean")

    # IS_A with polarity=0 (negated — whale is NOT a fish)
    g.add_edge(0, 1, relation_type=RelationType.IS_A,
               polarity=0, confidence=Confidence.CERTAIN)
    # IS_A with assertion
    g.add_edge(0, 2, relation_type=RelationType.IS_A,
               polarity=1, confidence=Confidence.CERTAIN)
    # LOCATED_IN with LIKELY confidence
    g.add_edge(0, 3, relation_type=RelationType.ASSOCIATIVE,
               subtype=AssociativeLabel.LOCATED_IN,
               polarity=1, confidence=Confidence.LIKELY)
    # Full encoding edge (non-compact due to non-zero subtype + non-CERTAIN confidence)
    g.add_edge(3, LiteralValue(LiteralType.STRING, "Pacific"),
               relation_type=RelationType.ASSOCIATIVE,
               subtype=AssociativeLabel.HAS_PROPERTY,
               confidence=Confidence.PLAUSIBLE)

    return g

def _expect_negated_varied() -> dict:
    return {
        "entities": 4,
        "edges": 4,
        "entity_labels": ["Whale", "Fish", "Mammal", "Ocean"],
    }


# ── Entry 6: Demo Graph (Mechanical Watch, backward compat) ───────

def _build_demo() -> Graph:
    g = Graph()
    g.add_entity("Mechanical Watch", canonical_id="watch")
    g.add_entity("Mainspring", canonical_id="mainspring")
    g.add_entity("Balance Wheel", canonical_id="balance")
    g.add_entity("Horology", canonical_id="horology")
    g.add_entity("Escapement", canonical_id="escapement")
    g.add_entity("Power Reserve", canonical_id="power")

    g.add_edge(0, 3, relation_type=RelationType.IS_A)
    g.add_edge(1, 0, relation_type=RelationType.PART_OF)
    g.add_edge(2, 0, relation_type=RelationType.PART_OF)
    g.add_edge(4, 0, relation_type=RelationType.PART_OF)
    g.add_edge(5, 1, relation_type=RelationType.ASSOCIATIVE)
    g.add_edge(2, 5, relation_type=RelationType.ASSOCIATIVE, polarity=0)
    return g

def _expect_demo() -> dict:
    return {
        "entities": 6,
        "edges": 6,
        "entity_labels": [
            "Mechanical Watch", "Mainspring", "Balance Wheel",
            "Horology", "Escapement", "Power Reserve",
        ],
    }


# ── Corpus Assembly ───────────────────────────────────────────────

def _populate() -> dict:
    """Build all 7 corpus entries, computing canonical decodes."""
    builders = [
        ("empty_graph", _build_empty, _expect_empty),
        ("single_entity", _build_single_entity, _expect_single_entity),
        ("single_edge", _build_single_edge, _expect_single_edge),
        ("multi_edge", _build_multi_edge, _expect_multi_edge),
        ("with_payload", _build_with_payload, _expect_with_payload),
        ("negated_varied", _build_negated_varied, _expect_negated_varied),
        ("demo_graph", _build_demo, _expect_demo),
    ]

    corpus = {}
    for name, build_fn, expect_fn in builders:
        graph = build_fn()
        entry = _canonical(graph)
        entry["graph"] = graph
        entry["expect"] = expect_fn()
        corpus[name] = entry
    return corpus


# Compute corpus once at import time
CORPUS = _populate()


def list_corpus() -> list[str]:
    """Return entry names."""
    return list(CORPUS.keys())


def get_entry(name: str) -> dict:
    """Return a single corpus entry by name."""
    return CORPUS[name]


def round_trip_check(name: str) -> bool:
    """Verify pack(unpack(pack(graph))) == pack(graph) for one entry."""
    entry = CORPUS[name]
    packed = entry["packed"]
    decoded = unpack(packed)
    repacked = pack(decoded_to_graph(decoded))
    return packed == repacked


def decoded_to_graph(decoded: dict) -> Graph:
    """Convert a decoded dict back to a Graph for re-packing.
    
    This preserves the structural shape (entity/edge counts, labels)
    but may not reconstruct all fields perfectly (e.g., canonical_id
    padding, subtype defaults).
    """
    g = Graph()
    for ent in decoded.get("entities", []):
        g.add_entity(ent["label"])
    for edge in decoded.get("edges", []):
        g.add_edge(
            edge["source"],
            edge["target"],
            relation_type=edge["relation_type"],
            subtype=edge.get("subtype", 0),
            polarity=edge.get("polarity", 1),
            confidence=edge.get("confidence", 0),
        )
    for facet in decoded.get("facets", []):
        g.add_facet(facet["facet_id"], facet["dimension_ids"])
    for sal in decoded.get("salience", []):
        g.add_salience(sal["entity_index"], sal["source"], sal["scalar"])
    return g
