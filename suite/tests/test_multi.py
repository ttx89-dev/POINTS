"""Tests for multi-glyph protocol."""

from __future__ import annotations
import unittest

from suite.glyph_multi import (
    split_graph,
    reassemble,
    verify_multi_glyph,
    _compute_graph_id,
    _chunk_entities,
    _assign_edges_to_chunks,
    _build_chunk_graph,
)
from suite.glyph import pack, unpack
from suite.structure import Graph, RelationType, Confidence, LiteralValue, LiteralType


class TestChunking(unittest.TestCase):
    """Test entity chunking and edge assignment."""

    def test_chunk_entities_small(self):
        """Graph smaller than chunk size stays as one chunk."""
        g = Graph()
        for i in range(10):
            g.add_entity(f"E{i}", canonical_id=f"e{i}")

        chunks = _chunk_entities(g.entities, max_per_chunk=20)
        self.assertEqual(len(chunks), 1)
        self.assertEqual(chunks[0], (0, 10))

    def test_chunk_entities_large(self):
        """Graph larger than chunk size splits correctly."""
        g = Graph()
        for i in range(100):
            g.add_entity(f"E{i}", canonical_id=f"e{i}")

        chunks = _chunk_entities(g.entities, max_per_chunk=30)
        self.assertEqual(len(chunks), 4)
        self.assertEqual(chunks[0], (0, 30))
        self.assertEqual(chunks[1], (30, 30))
        self.assertEqual(chunks[2], (60, 30))
        self.assertEqual(chunks[3], (90, 10))

    def test_assign_edges_to_chunks(self):
        """Edges assigned to chunk containing source entity."""
        g = Graph()
        for i in range(10):
            g.add_entity(f"E{i}", canonical_id=f"e{i}")

        # Chain: 0->1->2->3->4->5->6->7->8->9
        for i in range(9):
            g.add_edge(i, i+1, relation_type=RelationType.ASSOCIATIVE)

        chunks = _chunk_entities(g.entities, max_per_chunk=5)  # (0,5), (5,5)
        chunk_edges = _assign_edges_to_chunks(g.edges, chunks)

        # Chunk 0 (entities 0-4) should have edges 0->1, 1->2, 2->3, 3->4 (4 edges)
        # Plus edge 4->5 where source=4 is in chunk 0, target=5 is in chunk 1
        self.assertEqual(len(chunk_edges[0]), 5)
        # Chunk 1 (entities 5-9) should have edges 5->6, 6->7, 7->8, 8->9 (4 edges)
        self.assertEqual(len(chunk_edges[1]), 4)


class TestChunkGraph(unittest.TestCase):
    """Test building chunk graphs."""

    def test_build_chunk_graph(self):
        """Chunk graph has correct entities and edges."""
        g = Graph()
        for i in range(10):
            g.add_entity(f"E{i}", canonical_id=f"e{i}")
        for i in range(9):
            g.add_edge(i, i+1, relation_type=RelationType.ASSOCIATIVE)

        chunks = _chunk_entities(g.entities, max_per_chunk=5)
        chunk_edges = _assign_edges_to_chunks(g.edges, chunks)

        chunk_entities = g.entities[0:5]
        chunk_graph = _build_chunk_graph(chunk_entities, chunk_edges[0], 0, g)

        # Chunk graph includes primary entities (5) + target entity for edge 4->5 (1 extra)
        self.assertEqual(chunk_graph.entity_count, 6)
        self.assertEqual(chunk_graph.edge_count, 5)  # 0->1, 1->2, 2->3, 3->4, 4->5

        # Check entities preserve canonical_id
        labels = [ent.label for ent in chunk_graph.entities]
        self.assertEqual(labels[:5], ["E0", "E1", "E2", "E3", "E4"])
        self.assertEqual(labels[5], "E5")  # extra target entity


class TestMultiGlyphRoundTrip(unittest.TestCase):
    """Full multi-glyph round-trip tests."""

    def test_chain_1000_entities(self):
        """1000 entities in a chain."""
        g = Graph()
        for i in range(1000):
            g.add_entity(f"Entity-{i:04d}", canonical_id=f"e{i:04d}")
        for i in range(999):
            g.add_edge(i, i+1, relation_type=RelationType.ASSOCIATIVE)

        glyphs = split_graph(g)
        self.assertGreater(len(glyphs), 1)

        verification = verify_multi_glyph(glyphs)
        self.assertTrue(verification["all_parity_ok"])
        self.assertTrue(verification["prefix_consistent"])
        self.assertEqual(verification["missing_chunks"], [])

        reassembled = reassemble(glyphs)
        self.assertEqual(reassembled.entity_count, 1000)
        self.assertEqual(reassembled.edge_count, 999)

    def test_chain_5000_entities(self):
        """5000 entities in a chain."""
        g = Graph()
        for i in range(5000):
            g.add_entity(f"Entity-{i:05d}", canonical_id=f"e{i:05d}")
        for i in range(4999):
            g.add_edge(i, i+1, relation_type=RelationType.ASSOCIATIVE)

        glyphs = split_graph(g)
        self.assertGreater(len(glyphs), 1)

        verification = verify_multi_glyph(glyphs)
        self.assertTrue(verification["all_parity_ok"])
        self.assertTrue(verification["prefix_consistent"])

        reassembled = reassemble(glyphs)
        self.assertEqual(reassembled.entity_count, 5000)
        self.assertEqual(reassembled.edge_count, 4999)

    def test_dense_graph_1000_entities(self):
        """1000 entities with many edges."""
        g = Graph()
        for i in range(1000):
            g.add_entity(f"N{i:04d}", canonical_id=f"n{i:04d}")

        # Each entity connects to next 5 (where available)
        for i in range(1000):
            for j in range(1, 6):
                if i + j < 1000:
                    g.add_edge(i, i+j, relation_type=RelationType.ASSOCIATIVE)

        glyphs = split_graph(g)
        verification = verify_multi_glyph(glyphs)
        self.assertTrue(verification["all_parity_ok"])

        reassembled = reassemble(glyphs)
        self.assertEqual(reassembled.entity_count, 1000)
        # Edge count: each of 1000 entities has ~5 edges = ~5000 edges
        self.assertGreater(reassembled.edge_count, 4000)

    def test_graph_id_consistency(self):
        """All glyphs in sequence share same graph_id_prefix."""
        g = Graph()
        for i in range(100):
            g.add_entity(f"E{i}", canonical_id=f"e{i}")
        for i in range(99):
            g.add_edge(i, i+1, relation_type=RelationType.ASSOCIATIVE)

        glyphs = split_graph(g)

        # Unpack each and check graph_id_prefix
        prefixes = set()
        for glyph in glyphs:
            decoded = unpack(glyph)
            prefixes.add(decoded["header"]["graph_id_prefix"])

        self.assertEqual(len(prefixes), 1)
        expected_prefix = _compute_graph_id(g)[1]
        self.assertEqual(prefixes.pop(), expected_prefix)

    def test_varied_relation_types(self):
        """Graph with all relation types."""
        g = Graph()
        for i in range(50):
            g.add_entity(f"E{i}", canonical_id=f"e{i}")

        # Add edges of different types
        for i in range(49):
            g.add_edge(i, i+1, relation_type=RelationType.IS_A)
        for i in range(0, 48, 2):
            g.add_edge(i, i+2, relation_type=RelationType.PART_OF)
        for i in range(0, 47, 3):
            g.add_edge(i, i+3, relation_type=RelationType.ASSOCIATIVE)
            g.edges[-1].subtype = 0  # ASSOCIATIVE

        glyphs = split_graph(g)
        reassembled = reassemble(glyphs)

        self.assertEqual(reassembled.entity_count, 50)
        self.assertEqual(reassembled.edge_count, g.edge_count)

    def test_confidence_and_polarity(self):
        """Graph with varied confidence and negated edges."""
        g = Graph()
        for i in range(30):
            g.add_entity(f"E{i}", canonical_id=f"e{i}")

        # Some negated edges
        for i in range(10):
            g.add_edge(i, i+1, relation_type=RelationType.ASSOCIATIVE, polarity=0)
        # Some with lower confidence
        for i in range(10, 20):
            g.add_edge(i, i+1, relation_type=RelationType.ASSOCIATIVE,
                       confidence=Confidence.PLAUSIBLE, polarity=1)
        # Normal edges
        for i in range(20, 29):
            g.add_edge(i, i+1, relation_type=RelationType.ASSOCIATIVE)

        glyphs = split_graph(g)
        reassembled = reassemble(glyphs)

        self.assertEqual(reassembled.entity_count, 30)
        self.assertEqual(reassembled.edge_count, 29)

    def test_literal_edges(self):
        """Graph with literal property edges."""
        g = Graph()
        for i in range(20):
            g.add_entity(f"E{i}", canonical_id=f"e{i}")

        # Add some literal edges
        for i in range(10):
            g.add_edge(i, LiteralValue(LiteralType.INTEGER, 42), relation_type=RelationType.ASSOCIATIVE)
        for i in range(10, 19):
            g.add_edge(i, i+1, relation_type=RelationType.ASSOCIATIVE)

        glyphs = split_graph(g)
        reassembled = reassemble(glyphs)

        self.assertEqual(reassembled.entity_count, 20)


class TestGraphId(unittest.TestCase):
    """Test graph ID computation."""

    def test_graph_id_consistency(self):
        """Same graph produces same graph_id."""
        g1 = Graph()
        for i in range(10):
            g1.add_entity(f"E{i}", canonical_id=f"e{i}")
        for i in range(9):
            g1.add_edge(i, i+1, relation_type=RelationType.ASSOCIATIVE)

        g2 = Graph()
        for i in range(10):
            g2.add_entity(f"E{i}", canonical_id=f"e{i}")
        for i in range(9):
            g2.add_edge(i, i+1, relation_type=RelationType.ASSOCIATIVE)

        id1, prefix1 = _compute_graph_id(g1)
        id2, prefix2 = _compute_graph_id(g2)

        self.assertEqual(id1, id2)
        self.assertEqual(prefix1, prefix2)

    def test_graph_id_changes(self):
        """Different graphs produce different graph_ids."""
        g1 = Graph()
        g1.add_entity("A", canonical_id="a")
        g1.add_entity("B", canonical_id="b")
        g1.add_edge(0, 1, relation_type=RelationType.ASSOCIATIVE)

        g2 = Graph()
        g2.add_entity("A", canonical_id="a")
        g2.add_entity("C", canonical_id="c")
        g2.add_edge(0, 1, relation_type=RelationType.ASSOCIATIVE)

        id1, _ = _compute_graph_id(g1)
        id2, _ = _compute_graph_id(g2)

        self.assertNotEqual(id1, id2)


if __name__ == "__main__":
    unittest.main()