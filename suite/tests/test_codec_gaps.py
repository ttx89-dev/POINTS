"""Codec gap tests — B1/B2/B3/B4 fixes + pack byte-stability pins.

B1: unpack()["entities"] is an EntityTable (list + .values()/label lookup).
B2: Entity.properties_literal round-trips through pack/unpack.
B3: literal edge targets resolve to decoded values ("target_raw" keeps the address).
B4: entities without canonical_id encode/decode without corruption.

The TestPackByteStability hashes were recorded BEFORE the fixes landed;
they prove the fixes did not change the byte layout for graphs that
exercise none of the fixed features.
"""

import hashlib
import sys
import os
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
for _p in (os.path.join(_HERE, ".."), os.path.join(_HERE, "..", "..")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from suite.structure import (Graph, Entity, LiteralValue, LiteralType,
                             RelationType, AssociativeLabel, MeronymySubtype)
from suite.glyph import pack, unpack, _resolve_literal_targets
from suite.tests.golden_corpus import CORPUS


class TestB1EntityTable(unittest.TestCase):
    """unpack() entities are EntityTable — list-compatible + dict conveniences."""

    def _ones(self):
        g = Graph()
        g.add_entity("Dog")
        g.add_entity("Cat")
        return unpack(pack(g))

    def test_entity_table_type(self):
        from suite.structure import EntityTable
        ents = self._ones()["entities"]
        self.assertIsInstance(ents, EntityTable)
        self.assertIsInstance(ents, list)

    def test_values_accessor(self):
        ents = self._ones()["entities"]
        vals = ents.values()
        self.assertEqual(len(vals), 2)
        self.assertEqual(vals[0]["label"], "Dog")

    def test_label_lookup(self):
        ents = self._ones()["entities"]
        self.assertEqual(ents["Cat"]["id"], 1)
        with self.assertRaises(KeyError):
            ents["Horse"]

    def test_get_keys_items(self):
        ents = self._ones()["entities"]
        self.assertEqual(ents.get(1)["label"], "Cat")
        self.assertEqual(ents.get("Dog")["id"], 0)
        self.assertIsNone(ents.get("Nope"))
        self.assertEqual(ents.get("Nope", "dflt"), "dflt")
        self.assertEqual(ents.keys(), [0, 1])
        self.assertEqual(ents.items()[1][0], 1)

    def test_list_semantics_preserved(self):
        ents = self._ones()["entities"]
        self.assertEqual(len(ents), 2)
        self.assertEqual([e["label"] for e in ents], ["Dog", "Cat"])
        row0 = {"id": 0, "canonical_id": "fnv:dog", "label": "Dog"}
        self.assertEqual(ents[0], row0)
        self.assertEqual(ents[0:1], [row0])


class TestB2PropertiesLiteral(unittest.TestCase):
    """properties_literal survives pack→unpack with type fidelity."""

    def test_round_trip_all_types(self):
        g = Graph()
        e = g.add_entity("Widget")
        e.properties_literal["name"] = LiteralValue(LiteralType.STRING, "widget-1")
        e.properties_literal["mass"] = LiteralValue(LiteralType.FLOAT, 1.25)
        e.properties_literal["count"] = LiteralValue(LiteralType.INTEGER, 7)
        e.properties_literal["active"] = LiteralValue(LiteralType.BOOLEAN, True)

        row = unpack(pack(g))["entities"]["Widget"]
        self.assertIn("properties_literal", row)
        got = row["properties_literal"]
        self.assertEqual(got["name"], LiteralValue(LiteralType.STRING, "widget-1"))
        self.assertEqual(got["mass"], LiteralValue(LiteralType.FLOAT, 1.25))
        self.assertEqual(got["count"], LiteralValue(LiteralType.INTEGER, 7))
        self.assertEqual(got["active"], LiteralValue(LiteralType.BOOLEAN, True))

    def test_empty_and_absent(self):
        g = Graph()
        g.add_entity("Plain")
        row = unpack(pack(g))["entities"][0]
        self.assertNotIn("properties_literal", row)

    def test_plain_value_coercion(self):
        g = Graph()
        e = g.add_entity("Coerced")
        e.properties_literal["n"] = 5        # int, not LiteralValue
        e.properties_literal["s"] = "txt"    # str
        e.properties_literal["b"] = False    # bool (must not become INTEGER 0)
        got = unpack(pack(g))["entities"][0]["properties_literal"]
        self.assertEqual(got["n"], LiteralValue(LiteralType.INTEGER, 5))
        self.assertEqual(got["s"], LiteralValue(LiteralType.STRING, "txt"))
        self.assertEqual(got["b"], LiteralValue(LiteralType.BOOLEAN, False))

    def test_order_insensitive_determinism(self):
        g1 = Graph()
        e1 = g1.add_entity("A")
        e1.properties_literal["x"] = LiteralValue(LiteralType.INTEGER, 1)
        e1.properties_literal["y"] = LiteralValue(LiteralType.INTEGER, 2)

        g2 = Graph()
        e2 = g2.add_entity("A")
        e2.properties_literal["y"] = LiteralValue(LiteralType.INTEGER, 2)
        e2.properties_literal["x"] = LiteralValue(LiteralType.INTEGER, 1)

        self.assertEqual(pack(g1), pack(g2))

    def test_unicode_key_and_value(self):
        g = Graph()
        e = g.add_entity("U")
        e.properties_literal["cle"] = LiteralValue(LiteralType.STRING, "valeur-\u00e9")
        got = unpack(pack(g))["entities"][0]["properties_literal"]
        self.assertEqual(got["cle"].value, "valeur-\u00e9")


class TestB3LiteralTargets(unittest.TestCase):
    """Literal edge targets resolve against the edge literal pool."""

    def test_resolution_and_raw(self):
        g = Graph()
        g.add_entity("Paris")
        g.add_entity("France")
        g.add_edge(0, LiteralValue(LiteralType.STRING, "City of Light"),
                   relation_type=RelationType.ASSOCIATIVE,
                   subtype=AssociativeLabel.HAS_PROPERTY)
        g.add_edge(1, LiteralValue(LiteralType.FLOAT, 2.5),
                   relation_type=RelationType.ASSOCIATIVE,
                   subtype=AssociativeLabel.HAS_PROPERTY)

        d = unpack(pack(g))
        lits = [e for e in d["edges"] if e["target_is_literal"]]
        self.assertEqual(len(lits), 2)
        self.assertEqual(lits[0]["target"], "City of Light")
        self.assertEqual(lits[0]["target_raw"], 0)
        self.assertEqual(lits[0]["target_literal_type"], "string")
        self.assertTrue(lits[0]["target_resolved"])
        # second literal sits after the first in the pool
        self.assertEqual(lits[1]["target"], 2.5)
        self.assertGreater(lits[1]["target_raw"], lits[0]["target_raw"])
        self.assertEqual(lits[1]["target_literal_type"], "float")

    def test_all_literal_types(self):
        g = Graph()
        g.add_entity("X")
        g.add_edge(0, LiteralValue(LiteralType.INTEGER, 42),
                   relation_type=RelationType.ASSOCIATIVE)
        g.add_edge(0, LiteralValue(LiteralType.BOOLEAN, True),
                   relation_type=RelationType.ASSOCIATIVE)
        g.add_edge(0, LiteralValue(LiteralType.STRING, ""),
                   relation_type=RelationType.ASSOCIATIVE)

        lits = [e for e in unpack(pack(g))["edges"] if e["target_is_literal"]]
        self.assertEqual(lits[0]["target"], 42)
        self.assertEqual(lits[0]["target_literal_type"], "integer")
        self.assertEqual(lits[1]["target"], True)
        self.assertEqual(lits[1]["target_literal_type"], "boolean")
        self.assertEqual(lits[2]["target"], "")
        self.assertEqual(lits[2]["target_literal_type"], "string")

    def test_entity_edges_unaffected(self):
        g = Graph()
        g.add_entity("A")
        g.add_entity("B")
        g.add_edge(0, 1, relation_type=RelationType.IS_A)
        e = unpack(pack(g))["edges"][0]
        self.assertFalse(e["target_is_literal"])
        self.assertEqual(e["target"], 1)
        self.assertEqual(e["source"], 0)

    def test_unresolvable_address_graceful(self):
        edges = [{"target": 9999, "target_is_literal": True}]
        _resolve_literal_targets(edges, b"\x00\x01\x02")
        self.assertEqual(edges[0]["target"], 9999)
        self.assertFalse(edges[0]["target_resolved"])

    def test_mixed_graph_fidelity(self):
        g = Graph()
        e = g.add_entity("Root")
        e.properties_literal["tag"] = LiteralValue(LiteralType.STRING, "r1")
        g.add_entity("Leaf")
        g.add_edge(0, 1, relation_type=RelationType.PART_OF,
                   subtype=MeronymySubtype.COMPONENT_INTEGRAL)
        g.add_edge(1, LiteralValue(LiteralType.INTEGER, 3),
                   relation_type=RelationType.ASSOCIATIVE)

        d = unpack(pack(g))
        self.assertEqual(d["header"]["entity_count"], 2)
        self.assertEqual(d["entities"][0]["properties_literal"]["tag"].value, "r1")
        lit = [x for x in d["edges"] if x["target_is_literal"]][0]
        self.assertEqual(lit["target"], 3)


class TestB4NoCanonicalId(unittest.TestCase):
    """Entities without canonical_id must not corrupt the glyph stream."""

    def test_entity_without_canonical_id(self):
        g = Graph()
        g.entities.append(Entity(id=0, label="NoCID", canonical_id=None))
        d = unpack(pack(g))
        self.assertEqual(d["header"]["entity_count"], 1)
        self.assertEqual(d["entities"][0]["label"], "NoCID")
        self.assertIsNone(d["entities"][0]["canonical_id"])

    def test_mixed_cid_graph(self):
        g = Graph()
        g.add_entity("With", canonical_id="with")
        g.entities.append(Entity(id=1, label="Without", canonical_id=None))
        g.add_entity("Cat")  # canonical_id "fnv:cat" (within the 8-byte cid cap)
        d = unpack(pack(g))
        self.assertEqual([e["label"] for e in d["entities"]],
                         ["With", "Without", "Cat"])
        self.assertEqual(d["entities"][1]["canonical_id"], None)
        self.assertEqual(d["entities"][2]["canonical_id"], "fnv:cat")


class TestPackByteStability(unittest.TestCase):
    """Pins recorded pre-change: the fixes must not alter bytes for graphs
    that exercise none of the fixed features (all corpus entities have
    canonical_id, no properties_literal, no flags-bit2)."""

    CORPUS_HASHES = {
        "empty_graph": "54151a519b1e95fa4bde7fbcf7b1325084fd24d53db0bb5eb2cd9b14f42af572",
        "single_entity": "c4fe4b2b771fa27bdb1c228dbfee5a51188e9f6f8d9347a9c3473a7b844303b8",
        "single_edge": "eb67b27d29211813034724b8e75481060e5247a12039858cb2294491217f213b",
        "multi_edge": "0c0bb20d9789c0994ca41d7d7ac544210bf13bdff2243f4a6420c04fc1964385",
        "with_payload": "13ef458a3b5aacdc6417410d6696c50653b9edf4576dab1229366fd8d18e6ec2",
        "negated_varied": "586fbb9168ba793172e840b2f2766b1e4c20e37d7f824629d6f2328d0e0484b0",
        "demo_graph": "04d5809b05e36d6d5548e52a312873076bf77df270fbfe948e4a81af7b45b51c",
    }

    def test_corpus_hashes_unchanged(self):
        for name, expect in self.CORPUS_HASHES.items():
            got = hashlib.sha256(pack(CORPUS[name]["graph"])).hexdigest()
            self.assertEqual(got, expect, f"{name} pack bytes changed")

    def test_repeat_pack_deterministic(self):
        for name in CORPUS:
            self.assertEqual(pack(CORPUS[name]["graph"]),
                             pack(CORPUS[name]["graph"]))

    def test_corpus_sizes(self):
        for name in CORPUS:
            self.assertEqual(len(pack(CORPUS[name]["graph"])), 8192)


if __name__ == "__main__":
    unittest.main()
