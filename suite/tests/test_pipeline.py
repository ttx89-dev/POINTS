"""Round-trip tests for POINTS encode/decode pipeline."""

import sys
import os
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from suite.structure import Graph, Edge, RelationType, LiteralValue
from suite.glyph import pack, unpack
from suite.header import Header, compute_entity_index_bits, compute_edge_index_bits
from suite.bits import BitWriter, BitReader
from suite.parity import (encode_parity, verify_parity,
                          decode_and_repair, compute_parity_size,
                          RS_N_PARITY, RS_N_DATA)
from suite.agent_tool import decode_glyph, glyph_summary


class TestBits(unittest.TestCase):
    """Bit-level read/write primitives."""

    def test_write_read_cycle(self):
        w = BitWriter()
        w.write(0b10101, 5)
        w.write(0b111, 3)
        w.write(0xDEAD, 16)
        data = w.flush()
        self.assertEqual(len(data), 3)  # 5+3+16 = 24 bits = 3 bytes

        r = BitReader(data)
        self.assertEqual(r.read(5), 0b10101)
        self.assertEqual(r.read(3), 0b111)
        self.assertEqual(r.read(16), 0xDEAD)

    def test_aligned_bytes(self):
        w = BitWriter()
        for i in range(4):
            w.write(i, 8)
        data = w.flush()
        self.assertEqual(data, bytes([0, 1, 2, 3]))

        r = BitReader(data)
        for i in range(4):
            self.assertEqual(r.read(8), i)

    def test_empty_write(self):
        w = BitWriter()
        data = w.flush()
        self.assertEqual(data, b"")

    def test_single_bit(self):
        w = BitWriter()
        w.write(1, 1)
        w.write(0, 1)
        w.write(1, 1)
        data = w.flush()
        self.assertEqual(data[0] >> 5, 0b101)  # MSB-first: 101xxxxx


class TestHeader(unittest.TestCase):
    """42-byte header pack/unpack."""

    def setUp(self):
        self.header = Header(
            sequence_id=42,
            sequence_index=0,
            sequence_total=1,
            parity_ratio=15,
            parity_algo_id=1,
            entity_count=11,
            entity_index_bits=4,
            edge_count=14,
            confidence_bits=2,
            facet_count=0,
            salience_entry_count=0,
            literal_pool_bytes=256,
            graph_id_prefix=0x12345678,
            region_offsets=[0, 100, 300, 400, 500, 600, 0],
        )

    def test_pack_unpack(self):
        packed = self.header.pack()
        self.assertEqual(len(packed), 42)
        unpacked = Header.unpack(packed)
        self.assertEqual(unpacked.sequence_id, 42)
        self.assertEqual(unpacked.entity_count, 11)
        self.assertEqual(unpacked.edge_count, 14)
        self.assertEqual(unpacked.magic, b"PN")
        self.assertEqual(unpacked.graph_id_prefix, 0x12345678)


class TestXorParity(unittest.TestCase):
    """XOR-interleaved parity."""

    def test_round_trip(self):
        content = b"Hello, POINTS! This is test content for parity verification."
        parity = encode_parity(content, algo_id=1)
        self.assertTrue(verify_parity(content, parity, algo_id=1))
        self.assertGreater(len(parity), 0)
        self.assertLessEqual(len(parity), len(content))

    def test_detects_corruption(self):
        content = b"Test content for corruption detection."
        parity = encode_parity(content, algo_id=1)
        corrupted = bytearray(content)
        if corrupted:
            corrupted[0] ^= 0xFF
        self.assertFalse(verify_parity(bytes(corrupted), parity, algo_id=1))


class TestRSParity(unittest.TestCase):
    """Reed-Solomon (255,223) parity."""

    def test_round_trip(self):
        content = b"Hello POINTS RS! This tests Reed-Solomon parity encoding."
        parity = encode_parity(content, algo_id=2)
        self.assertEqual(len(parity), compute_parity_size(len(content), algo_id=2))
        self.assertTrue(verify_parity(content, parity, algo_id=2))
        fixed, n = decode_and_repair(content, parity, algo_id=2)
        self.assertEqual(fixed, content)
        self.assertEqual(n, 0)

    def test_empty_content(self):
        parity = encode_parity(b"", algo_id=2)
        self.assertEqual(len(parity), 0)
        self.assertTrue(verify_parity(b"", parity, algo_id=2))
        fixed, n = decode_and_repair(b"", parity, algo_id=2)
        self.assertEqual(fixed, b"")
        self.assertEqual(n, 0)

    def test_short_content_single_block(self):
        content = b"Under 223 bytes"
        parity = encode_parity(content, algo_id=2)
        self.assertEqual(len(parity), RS_N_PARITY)  # one block of parity
        self.assertTrue(verify_parity(content, parity, algo_id=2))
        fixed, n = decode_and_repair(content, parity, algo_id=2)
        self.assertEqual(fixed, content)

    def test_exact_block_boundary(self):
        content = bytes(range(RS_N_PARITY * 5))  # Multiple of block size
        parity = encode_parity(content, algo_id=2)
        self.assertTrue(verify_parity(content, parity, algo_id=2))
        fixed, n = decode_and_repair(content, parity, algo_id=2)
        self.assertEqual(fixed, content)

    def test_corrects_errors_up_to_16_per_block(self):
        """Inject 5 errs/block across 6 blocks (well within 16/block limit)."""
        content = bytes(i % 256 for i in range(RS_N_DATA * 6))
        parity = encode_parity(content, algo_id=2)
        corrupted = bytearray(content)
        for block in range(6):
            for j in range(5):  # 5 errs per block
                idx = block * RS_N_DATA + j * 11  # spaced out
                corrupted[idx] ^= 0xFF
        self.assertFalse(verify_parity(bytes(corrupted), parity, algo_id=2))
        fixed, n = decode_and_repair(bytes(corrupted), parity, algo_id=2)
        self.assertEqual(fixed, content)
        self.assertGreater(n, 0)

    def test_detect_when_beyond_correction(self):
        """20 errors in one block — beyond RS(255,223) 16-symbol limit."""
        content = bytes(range(RS_N_DATA))  # 1 block, 223 bytes
        parity = encode_parity(content, algo_id=2)
        corrupted = bytearray(content)
        for i in range(20):
            corrupted[i] ^= 0xFF
        with self.assertRaises(ValueError):
            decode_and_repair(bytes(corrupted), parity, algo_id=2)

    def test_full_content_size(self):
        """Full 6924B content (what the glyph uses)."""
        content = bytes(i % 256 for i in range(6924))
        parity = encode_parity(content, algo_id=2)
        self.assertEqual(len(parity), 1024)  # ceil(6924/223) * 32
        self.assertTrue(verify_parity(content, parity, algo_id=2))
        fixed, n = decode_and_repair(content, parity, algo_id=2)
        self.assertEqual(fixed, content)


class TestDemoRoundTrip(unittest.TestCase):
    """Full pipeline with the demo ontology."""

    def build_graph(self):
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

    def test_round_trip_xor(self):
        original = self.build_graph()
        braille = pack(original, parity_algo_id=1)
        result = unpack(braille)
        self.assertEqual(len(result["entities"]), original.entity_count)
        self.assertEqual(len(result["edges"]), original.edge_count)
        for orig_ent, dec_ent in zip(original.entities, result["entities"]):
            self.assertEqual(orig_ent.label, dec_ent["label"])
        self.assertEqual(result["header"]["parity_algo"], 1)
        self.assertTrue(result["header"]["parity_ok"])

    def test_round_trip_rs(self):
        original = self.build_graph()
        braille = pack(original, parity_algo_id=2)
        result = unpack(braille)
        self.assertEqual(len(result["entities"]), original.entity_count)
        self.assertEqual(len(result["edges"]), original.edge_count)
        for orig_ent, dec_ent in zip(original.entities, result["entities"]):
            self.assertEqual(orig_ent.label, dec_ent["label"])
        self.assertEqual(result["header"]["parity_algo"], 2)
        self.assertTrue(result["header"]["parity_ok"])
        self.assertEqual(result["header"]["errors_corrected"], 0)

    def test_round_trip_rs_with_correction(self):
        """RS mode survives 30 byte errors."""
        original = self.build_graph()
        braille = pack(original, parity_algo_id=2)
        # Corrupt bytes in the content region
        import random
        random.seed(123)
        glyph = bytearray(braille)
        for _ in range(30):
            glyph[40 + random.randint(0, 6923)] ^= random.randint(1, 255)
        result = unpack(bytes(glyph))
        self.assertEqual(len(result["entities"]), original.entity_count)
        self.assertEqual(len(result["edges"]), original.edge_count)
        for orig_ent, dec_ent in zip(original.entities, result["entities"]):
            self.assertEqual(orig_ent.label, dec_ent["label"])
        self.assertGreater(result["header"]["errors_corrected"], 0)

    def test_agent_tool(self):
        original = self.build_graph()
        braille = pack(original)
        result = decode_glyph(braille)
        self.assertIn("header", result)
        self.assertIn("entities", result)
        self.assertIn("edges", result)

    def test_glyph_summary(self):
        original = self.build_graph()
        braille = pack(original)
        summary = glyph_summary(braille)
        self.assertEqual(summary["entities"], 6)
        self.assertEqual(summary["edges"], 6)


if __name__ == "__main__":
    unittest.main(verbosity=2)