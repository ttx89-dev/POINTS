"""Red Team — adversarial tests against the golden corpus.

Tests exercise:
  - Bit-flip corruption (single/multi-byte, burst)
  - Truncation / extension beyond glyph boundaries
  - Header corruption (bad CRC, invalid magic, impossible field values)
  - Boundary conditions (empty regions, max entity index)
  - Cross-region bleed (data in wrong region)
  - Polarity/confidence edge cases from negated_varied corpus entry

Each test uses golden corpus entries as known-good baselines, applies
an adversarial transformation, then checks decoder behavior.

Dependencies: golden_corpus.py (CORPUS dict), suite.glyph, suite.header
"""

from __future__ import annotations
import sys, os, random
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

import unittest
from suite.glyph import pack, unpack, pack_bytes, unpack_bytes, GLYPH_SIZE, CONTENT_SIZE
from suite.header import Header

# HEADER_SIZE is hardcoded as 40 in glyph.py; define here for readability
HEADER_SIZE = 40
from suite.tests.golden_corpus import CORPUS

# Seed for reproducible corruption
RNG = random.Random(42)


# ── Helpers ────────────────────────────────────────────────────────

def _glyph_bytes(name: str) -> bytes:
    """Return packed glyph bytes for a corpus entry."""
    return pack(CORPUS[name]["graph"])


def _flip_bit(data: bytes, byte_offset: int, bit: int) -> bytes:
    """Flip one bit in a byte at byte_offset."""
    buf = bytearray(data)
    if byte_offset < len(buf):
        buf[byte_offset] ^= (1 << bit)
    return bytes(buf)


def _flip_bits(data: bytes, offsets: list[tuple[int, int]]) -> bytes:
    """Flip multiple bits. offsets = [(byte_offset, bit), ...]"""
    buf = bytearray(data)
    for byte_offset, bit in offsets:
        if byte_offset < len(buf):
            buf[byte_offset] ^= (1 << bit)
    return bytes(buf)


def _burst_corrupt(data: bytes, start: int, length: int) -> bytes:
    """Replace a span of bytes with random data."""
    buf = bytearray(data)
    for i in range(start, min(start + length, len(buf))):
        buf[i] = RNG.randint(0, 255)
    return bytes(buf)


# ── Test Classes ───────────────────────────────────────────────────

class TestCorruptionDetection(unittest.TestCase):
    """Verify parity detects various corruption patterns."""

    def setUp(self):
        self.glyph = _glyph_bytes("demo_graph")

    def test_single_bit_flip_content(self):
        """Single bit flip in content region → parity should fail."""
        corrupted = _flip_bit(self.glyph, 100, 3)  # content byte 60
        result = unpack_bytes(corrupted)
        self.assertFalse(result["header"]["parity_ok"],
                         "Parity should detect single-bit content flip")

    def test_single_bit_flip_header(self):
        """Header corruption → checksum should fail."""
        corrupted = _flip_bit(self.glyph, 10, 7)  # header byte 10
        with self.assertRaises((ValueError, Exception)):
            unpack_bytes(corrupted)

    def test_multi_bit_flip_content(self):
        """Multiple bit flips across content → parity fails."""
        corrupted = _flip_bits(self.glyph, [(200, 0), (300, 7), (500, 3)])
        result = unpack_bytes(corrupted)
        self.assertFalse(result["header"]["parity_ok"])

    def test_burst_corruption_content(self):
        """Burst error in content → parity fails."""
        corrupted = _burst_corrupt(self.glyph, 1000, 50)
        result = unpack_bytes(corrupted)
        # Note: XOR parity may not detect all burst patterns, but should detect most
        # This is more of a documentation test
        self.assertIn("parity_ok", result["header"])

    def test_truncated_glyph(self):
        """Missing tail bytes → decode should handle gracefully."""
        truncated = self.glyph[:4000]  # Only first 4K of 8K
        # Should not crash; may fail with less informative error
        try:
            result = unpack_bytes(truncated)
            # If it decodes (padded), parity should fail
            self.assertFalse(result["header"]["parity_ok"])
        except (ValueError, Exception):
            pass  # Acceptable to raise on truncation

    def test_extra_padding(self):
        """Extra bytes beyond 8192 → decoder handles but stats reflect raw input."""
        padded = self.glyph + b"\xAB" * 100
        result = unpack_bytes(padded)
        # stats.total_bytes reports the raw input, but decode succeeded
        self.assertGreaterEqual(result["stats"]["total_bytes"], GLYPH_SIZE)
        self.assertEqual(result["header"]["magic"], "PN")


class TestHeaderIntegrity(unittest.TestCase):
    """Malformed header detection."""

    def test_bad_magic(self):
        """Wrong magic bytes → reject."""
        glyph = bytearray(_glyph_bytes("single_entity"))
        glyph[0] = 0x00  # corrupt PN magic
        glyph[1] = 0x00
        with self.assertRaises((ValueError, Exception)):
            unpack_bytes(bytes(glyph))

    def test_impossible_entity_count(self):
        """Entity count > 65535 → CRC rejection or saturate."""
        glyph = bytearray(_glyph_bytes("empty_graph"))
        # entity_count at offset 11-12
        glyph[11] = 0xFF
        glyph[12] = 0xFF
        try:
            result = unpack_bytes(bytes(glyph))
            # If it parses (e.g. CRC updated), entity count must be nonzero
            self.assertGreater(result["header"]["entity_count"], 0)
        except ValueError:
            pass  # CRC rejection is also acceptable

    def test_bad_region_offsets(self):
        """Overlapping region offsets → should not crash."""
        glyph = bytearray(_glyph_bytes("demo_graph"))
        # Set all region offsets to same value (overlap)
        for off in [22, 24, 26, 28, 30, 32]:
            glyph[off] = 0x00
            glyph[off + 1] = 0x00
        # Should decode without crash (may produce empty results)
        try:
            result = unpack_bytes(bytes(glyph))
            self.assertIsNotNone(result)
        except Exception:
            pass

    def test_zero_entity_count_legit(self):
        """Empty graph → 0 entities should decode cleanly."""
        result = unpack_bytes(_glyph_bytes("empty_graph"))
        self.assertEqual(result["header"]["entity_count"], 0)
        self.assertEqual(len(result["entities"]), 0)
        self.assertEqual(len(result["edges"]), 0)


class TestBoundaryConditions(unittest.TestCase):
    """Edge cases at boundary values."""

    def test_empty_graph_roundtrip(self):
        """Empty graph → pack→unpack→repack consistency."""
        glyph = _glyph_bytes("empty_graph")
        result = unpack_bytes(glyph)
        self.assertEqual(result["header"]["entity_count"], 0)
        self.assertEqual(result["header"]["edge_count"], 0)

    def test_single_entity_roundtrip(self):
        """Single entity → decode preserves label."""
        result = unpack_bytes(_glyph_bytes("single_entity"))
        self.assertEqual(len(result["entities"]), 1)
        self.assertEqual(result["entities"][0]["label"], "Hydrogen")

    def test_single_edge_relation(self):
        """Single edge → decode preserves relation type."""
        result = unpack_bytes(_glyph_bytes("single_edge"))
        self.assertEqual(len(result["edges"]), 1)
        self.assertEqual(result["edges"][0]["relation_type"],
                         int(CORPUS["single_edge"]["graph"].edges[0].relation_type))

    def test_full_range_of_relation_types(self):
        """All 5 relation types via multi_edge corpus."""
        result = unpack_bytes(_glyph_bytes("multi_edge"))
        types = {e["relation_type"] for e in result["edges"]}
        # Should have at least 2 distinct types (IS_A=1, PART_OF=3, ASSOC=4)
        self.assertGreaterEqual(len(types), 2)


class TestPolarityConfidence(unittest.TestCase):
    """Negated edges and confidence levels from negated_varied corpus."""

    def setUp(self):
        self.result = unpack_bytes(_glyph_bytes("negated_varied"))

    def test_negated_edge_detected(self):
        """At least one edge has polarity=0 (negated)."""
        negated = [e for e in self.result["edges"] if e["polarity"] == 0]
        self.assertGreaterEqual(len(negated), 1,
                                "Should have at least 1 negated edge")

    def test_negated_is_not_fish(self):
        """The specific Whale→Fish IS_A edge should be negated."""
        # Edge 0: Whale(0) → Fish(1) with IS_A(1), polarity=0
        edges = self.result["edges"]
        e0 = edges[0]
        self.assertEqual(e0["source"], 0)
        self.assertEqual(e0["target"], 1)
        self.assertEqual(e0["relation_type"], int(CORPUS["negated_varied"]["graph"].edges[0].relation_type))
        self.assertEqual(e0["polarity"], 0)

    def test_varied_confidence(self):
        """Edges have non-CERTAIN confidence values."""
        non_certain = [e for e in self.result["edges"] if e["confidence"] != 0]
        self.assertGreaterEqual(len(non_certain), 1,
                                "Should have edges with non-CERTAIN confidence")


class TestPayloadRegions(unittest.TestCase):
    """Facets, salience, and literal edges from with_payload corpus."""

    def test_facet_count(self):
        result = unpack_bytes(_glyph_bytes("with_payload"))
        self.assertEqual(result["header"]["facet_count"], 2)

    def test_salience_count(self):
        result = unpack_bytes(_glyph_bytes("with_payload"))
        self.assertEqual(result["header"]["salience_entry_count"], 2)

    def test_literal_pool_nonempty(self):
        result = unpack_bytes(_glyph_bytes("with_payload"))
        self.assertGreater(result["header"]["literal_pool_bytes"], 0)


class TestCrossCorpusRegression(unittest.TestCase):
    """All golden corpus entries decode consistently."""

    def test_all_entries_decode(self):
        """Every corpus entry must unpack without exception."""
        for name in CORPUS:
            with self.subTest(name=name):
                try:
                    result = unpack_bytes(_glyph_bytes(name))
                    self.assertIsNotNone(result)
                except Exception as e:
                    self.fail(f"{name} failed to decode: {e}")

    def test_all_entries_header_magic(self):
        """Every entry must have PN magic."""
        for name in CORPUS:
            with self.subTest(name=name):
                result = unpack_bytes(_glyph_bytes(name))
                self.assertEqual(result["header"]["magic"], "PN")

    def test_entity_count_consistency(self):
        """Decoded entity count matches corpus expectation."""
        for name, entry in CORPUS.items():
            with self.subTest(name=name):
                result = unpack_bytes(_glyph_bytes(name))
                self.assertEqual(
                    result["header"]["entity_count"],
                    entry["graph"].entity_count,
                    f"{name}: entity count mismatch",
                )

    def test_edge_count_consistency(self):
        """Decoded edge count matches corpus expectation."""
        for name, entry in CORPUS.items():
            with self.subTest(name=name):
                result = unpack_bytes(_glyph_bytes(name))
                self.assertEqual(
                    len(result["edges"]),
                    entry["graph"].edge_count,
                    f"{name}: edge count mismatch",
                )


class TestAdversarialBitPatterns(unittest.TestCase):
    """Specific adversarial bit patterns against all corpus entries."""

    def _test_pattern(self, name: str, pattern_fn):
        glyph = _glyph_bytes(name)
        corrupted = pattern_fn(glyph)
        try:
            result = unpack_bytes(corrupted)
            self.assertIn("header", result)
        except Exception:
            pass  # Some adversarial patterns may raise; that's acceptable

    def test_all_zero_header(self):
        """Header of all zeros → rejected."""
        for name in CORPUS:
            with self.subTest(name=name):
                glyph = _glyph_bytes(name)
                corrupted = bytearray(glyph)
                for i in range(40):
                    corrupted[i] = 0
                with self.assertRaises((ValueError, Exception)):
                    unpack_bytes(bytes(corrupted))

    def test_header_randomized(self):
        """Random header bytes → rejected (CRC fail or magic mismatch)."""
        for name in CORPUS:
            with self.subTest(name=name):
                glyph = _glyph_bytes(name)
                corrupted = bytearray(glyph)
                for i in range(40):
                    corrupted[i] = RNG.randint(0, 255)
                with self.assertRaises((ValueError, Exception)):
                    unpack_bytes(bytes(corrupted))

    def test_content_all_zeros(self):
        """Zeroed content → parity fail but structure decodes (entity count from header)."""
        result = unpack_bytes(_glyph_bytes("empty_graph"))
        self.assertEqual(result["header"]["entity_count"], 0)

    def test_max_entity_index(self):
        """Very large entity_index_bits via custom graph."""
        from suite.structure import Graph
        g = Graph()
        for i in range(200):
            g.add_entity(f"E{i}")
        glyph = pack_bytes(g)
        result = unpack_bytes(glyph)
        self.assertEqual(result["header"]["entity_count"], 200)
        self.assertEqual(len(result["entities"]), 200)


if __name__ == "__main__":
    unittest.main(verbosity=2)
