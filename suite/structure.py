"""Point 1 data model: Entity, Edge, RelationType, Graph.

Implements the structural theory: five relation types, two-tier
properties (object-valued vs literal-valued), facets, salience,
polarity/confidence, and reification.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Optional


# ── Relation Types ────────────────────────────────────────────────

class RelationType(IntEnum):
    EQUIVALENCE = 0     # two labels, one referent
    IS_A = 1            # subclass-of, genus-differentia
    INSTANCE_OF = 2     # individual belongs to a class
    PART_OF = 3         # meronomy, whole-part
    ASSOCIATIVE = 4     # everything else (causes, precedes, located-in, ...)

# Part-of (meronomy) subtypes per Winston, Chaffin & Herrmann 1987
class MeronymySubtype(IntEnum):
    COMPONENT_INTEGRAL = 0   # pedal-bike
    MEMBER_COLLECTION = 1    # ship-fleet
    PORTION_MASS = 2         # slice-pie
    STUFF_OBJECT = 3         # steel-car
    FEATURE_ACTIVITY = 4     # paying-shopping
    PLACE_AREA = 5           # everglades-florida

# Associative relation labels (typed)
class AssociativeLabel(IntEnum):
    CAUSES = 0          # transitive, asymmetric
    PRECEDES = 1        # transitive, asymmetric
    LOCATED_IN = 2      # transitive
    PRODUCED_BY = 3
    USED_FOR = 4
    ANTONYM_OF = 5      # symmetric, non-transitive
    HAS_PROPERTY = 6    # object-valued property
    OTHER = 7


# ── Salience Sources ──────────────────────────────────────────────

class SalienceSource(IntEnum):
    STRUCTURAL = 0      # derivable from graph (NOT stored explicitly)
    EMPIRICAL = 1       # corpus frequency, etc.
    DESIGNER_INTENDED = 2  # scheme author's defaults
    SITUATIONAL = 3     # context-dependent


# ── Confidence Levels ─────────────────────────────────────────────

class Confidence(IntEnum):
    CERTAIN = 0     # ~1.0
    LIKELY = 1      # ~0.8
    PLAUSIBLE = 2   # ~0.5
    UNKNOWN = 3     # ~0.2


# ── Property Value Types ─────────────────────────────────────────

class LiteralType(IntEnum):
    STRING = 0
    INTEGER = 1
    FLOAT = 2
    BOOLEAN = 3


# ── Data Model ─────────────────────────────────────────────────────

@dataclass
class Entity:
    """A node in the knowledge graph.

    Fields:
        id: Local index within a graph (assigned during construction).
        label: Human-readable name.
        canonical_id: FNV1a(normalize(label)) — stable across glyphs.
        properties: dict of property_name → Entity | LiteralValue.
        properties_literal: dict of property_name → LiteralValue.
        facets: dict of facet_name → facet_value.
    """
    id: int = 0
    label: str = ""
    canonical_id: Optional[str] = None
    properties: dict = field(default_factory=dict)       # object-valued
    properties_literal: dict = field(default_factory=dict)  # literal-valued
    facets: dict = field(default_factory=dict)

    def __hash__(self):
        return hash(self.canonical_id or self.label)


@dataclass
class LiteralValue:
    """A literal (non-entity) value."""
    type: LiteralType
    value: str | int | float | bool

    def as_bytes(self) -> bytes:
        """Serialize to bytes for the literal pool."""
        match self.type:
            case LiteralType.STRING:
                raw = str(self.value).encode("utf-8")
                return bytes([self.type, len(raw) & 0xFF, (len(raw) >> 8) & 0xFF]) + raw
            case LiteralType.INTEGER:
                raw = str(int(self.value)).encode("ascii")
                return bytes([self.type, len(raw) & 0xFF, (len(raw) >> 8) & 0xFF]) + raw
            case LiteralType.FLOAT:
                raw = f"{float(self.value):.10g}".encode("ascii")
                return bytes([self.type, len(raw) & 0xFF, (len(raw) >> 8) & 0xFF]) + raw
            case LiteralType.BOOLEAN:
                raw = b"1" if self.value else b"0"
                return bytes([self.type, 1, 0]) + raw

    @classmethod
    def from_bytes(cls, data: bytes) -> tuple[LiteralValue, int]:
        """Deserialize from bytes. Returns (value, bytes_consumed)."""
        t = LiteralType(data[0])
        length = data[1] | (data[2] << 8)
        raw = data[3:3 + length]
        consumed = 3 + length
        match t:
            case LiteralType.STRING:
                return cls(t, raw.decode("utf-8")), consumed
            case LiteralType.INTEGER:
                return cls(t, int(raw.decode("ascii"))), consumed
            case LiteralType.FLOAT:
                return cls(t, float(raw.decode("ascii"))), consumed
            case LiteralType.BOOLEAN:
                return cls(t, raw == b"1"), consumed


@dataclass
class Edge:
    """A directed relation between two entities, or entity→literal.

    Fields:
        source: source entity index.
        target: target entity index, or literal pool reference.
        target_is_literal: if True, target is a literal pool address.
        relation_type: one of the 5 RelationType values.
        subtype: meronomy subtype or associative label (0 if unused).
        confidence: Confidence level (default CERTAIN).
        polarity: 1 = asserted, 0 = negated (default asserted).
        reified: if True, this edge describes another edge.
        reified_edge_index: which edge this reifies (if reified=True).
        provenance: who/what asserted this fact (optional).
    """
    source: int
    target: int | str | float | bool  # entity index or literal value
    target_is_literal: bool = False
    relation_type: RelationType = RelationType.ASSOCIATIVE
    subtype: int = 0
    confidence: Confidence = Confidence.CERTAIN
    polarity: int = 1  # 1 = asserted, 0 = negated
    reified: bool = False
    reified_edge_index: int = 0
    provenance: str = ""


@dataclass
class SalienceEntry:
    """A non-structural salience record.

    structural salience is NOT stored — it's re-computed from the edge
    table on decode. Only empirical, designer-intended, and situational
    get explicit records.
    """
    entity_index: int
    source: SalienceSource
    scalar: float  # 0.0-1.0


@dataclass
class FacetEntry:
    """A facet dimension-value pair attached to an entity."""
    facet_id: int        # index into the graph's facet registry
    dimension_count: int  # typically 1
    dimension_ids: list[int] = field(default_factory=list)


@dataclass
class ReificationEntry:
    """Maps a reified edge to the entity that represents it."""
    edge_index: int
    entity_index: int


class Graph:
    """Container for all entities and edges.

    Usage:
        g = Graph()
        dog = g.add_entity("dog")
        mammal = g.add_entity("mammal")
        g.add_edge(dog.id, mammal.id, RelationType.IS_A)
    """
    def __init__(self):
        self.entities: list[Entity] = []
        self.edges: list[Edge] = []
        self.facets: list[FacetEntry] = []
        self.salience: list[SalienceEntry] = []
        self.reifications: list[ReificationEntry] = []
        self._entity_map: dict[str, int] = {}  # label → id

    def add_entity(self, label: str, canonical_id: str = None,
                   properties: dict = None, properties_literal: dict = None,
                   facets: dict = None) -> Entity:
        """Add an entity or return existing one with same label."""
        if label in self._entity_map:
            return self.entities[self._entity_map[label]]
        eid = len(self.entities)
        ent = Entity(
            id=eid,
            label=label,
            canonical_id=canonical_id or f"fnv:{label.lower()}",
            properties=properties or {},
            properties_literal=properties_literal or {},
            facets=facets or {},
        )
        self.entities.append(ent)
        self._entity_map[label] = eid
        return ent

    def get_entity(self, label: str) -> Optional[Entity]:
        if label in self._entity_map:
            return self.entities[self._entity_map[label]]
        return None

    def add_edge(self, source: int, target: int | LiteralValue,
                 relation_type: RelationType = RelationType.ASSOCIATIVE,
                 subtype: int = 0,
                 polarity: int = 1,
                 confidence: Confidence = Confidence.CERTAIN,
                 reified: bool = False,
                 provenance: str = "") -> Edge:
        target_is_literal = isinstance(target, LiteralValue)
        edge = Edge(
            source=source,
            target=target if not target_is_literal else None,
            target_is_literal=target_is_literal,
            relation_type=relation_type,
            subtype=subtype,
            polarity=polarity,
            confidence=confidence,
            reified=reified,
            provenance=provenance,
        )
        if target_is_literal:
            edge.target = target  # keep as LiteralValue for now
        eidx = len(self.edges)
        self.edges.append(edge)
        return edge

    def add_salience(self, entity_index: int, source: SalienceSource,
                     scalar: float):
        self.salience.append(SalienceEntry(entity_index, source, scalar))

    def add_facet(self, facet_id: int, dimension_ids: list[int]):
        self.facets.append(FacetEntry(facet_id, len(dimension_ids), dimension_ids))

    def add_reification(self, edge_index: int, entity_index: int):
        self.reifications.append(ReificationEntry(edge_index, entity_index))

    @property
    def entity_count(self) -> int:
        return len(self.entities)

    @property
    def edge_count(self) -> int:
        return len(self.edges)

    def summary(self) -> dict:
        return {
            "entities": self.entity_count,
            "edges": self.edge_count,
            "facets": len(self.facets),
            "salience_entries": len(self.salience),
            "reifications": len(self.reifications),
        }


# ── Decoded Containers ─────────────────────────────────────────────

class EntityTable(list):
    """Decoded entity rows — list-compatible, with dict-like conveniences (B1 fix).

    `unpack()["entities"]` previously returned `list[dict]`; callers that
    expected dict access (`.values()`, label lookup) got AttributeError.
    EntityTable keeps full list behavior (iteration, int indexing, slicing,
    equality with plain lists) and adds:

        table["Label"]        -> row by label (KeyError if absent)
        table.values()        -> copy of the rows list
        table.keys()          -> row ids
        table.items()         -> (id, row) pairs
        table.get(key, dflt)  -> row by int index or str label; default on miss
    """

    def values(self) -> list:
        return list(self)

    def keys(self) -> list:
        return [row.get("id") for row in self]

    def items(self) -> list:
        return [(row.get("id"), row) for row in self]

    def get(self, key, default=None):
        try:
            return self[key]
        except (KeyError, IndexError, TypeError):
            return default

    def __getitem__(self, key):
        if isinstance(key, str):
            for row in self:
                if row.get("label") == key:
                    return row
            raise KeyError(key)
        return list.__getitem__(self, key)