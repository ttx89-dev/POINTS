# Point 1, Enhanced — The Structural Theory of Information (Refined & Extended)

> Supersedes `point1.md`. This version deepens the theoretical foundations, makes implicit commitments explicit, and adds the implementation-facing specifications that the original left as "concluded but deferred."

---

## 0. Executive Summary of Changes from `point1.md`

| Dimension | Original | Enhanced |
|-----------|----------|----------|
| **Relation taxonomy** | 5 types, well-sourced | 5 types + **formal signatures** (arity, transitivity, symmetry, composition laws) |
| **Property model** | Object vs. literal split | **Typed property schemas** with cardinality, optionality, defaulting, and validation rules |
| **Canonical identity** | FNV1a(label) at registration | **Content-addressable canonical IDs** with collision resolution protocol |
| **Polarity/confidence** | Two orthogonal bits per edge | **Four-valued epistemic logic** (asserted⊤, asserted⊥, retracted⊤, retracted⊥) with Bayesian update rules |
| **Salience** | 4 sources, pluggable weights | **Salience as computable function** with defined composition algebra |
| **Extension mechanism** | Described informally | **Formal extension calculus** with dependency tracking |
| **Cross-facet identity** | Fixed at registration | **Dynamic facet binding** with versioned canonical paths |

---

## 1. The Five Relation Types — Formal Signatures

Each relation type is now defined by its **structural signature** — the minimal set of formal properties that distinguish it and determine its computational behavior.

### 1.1 Equivalence (`≡`)

```
Signature: Equiv(x, y) : Entity × Entity → Bool
Properties:
  - Reflexive: ∀x. Equiv(x, x)
  - Symmetric: Equiv(x, y) → Equiv(y, x)
  - Transitive: Equiv(x, y) ∧ Equiv(y, z) → Equiv(x, z)
  - Congruence: Equiv(x, y) → (P(x) ↔ P(y)) for all predicates P
Subtypes:
  - Lexical: mechanical string/byte equivalence after normalization
  - Referential: resolution-dependent (definite descriptions, anaphora)
Computational role: Union-find equivalence classes; quotient graph construction
```

### 1.2 Subclass (`⊑` / `is-a`)

```
Signature: Subclass(x, y) : Class × Class → Bool
Properties:
  - Reflexive: ∀c. Subclass(c, c)
  - Antisymmetric: Subclass(c, d) ∧ Subclass(d, c) → c = d
  - Transitive: Subclass(c, d) ∧ Subclass(d, e) → Subclass(c, e)
Test: "Is every X necessarily a Y?"
Computational role: **Tier ordering** — `derive_tiers()` computes topological sort on Subclass + Instance + ComponentPartOf
```

### 1.3 Instance (`∈` / `instance-of`)

```
Signature: Instance(x, c) : Entity × Class → Bool
Properties:
  - Not reflexive (an entity is not an instance of itself qua entity)
  - Not transitive (x ∈ c ∧ c ⊑ d → x ∈ d, but this is Subclass transitivity, not Instance transitivity)
  - Functional in second argument for rigid classes: Instance(x, c) ∧ Instance(x, d) ∧ Rigid(c) ∧ Rigid(d) → c = d
Distinction from Subclass: "Does X have possible subtypes of its own?"
Computational role: **Property inheritance target** — instances inherit property schemas from their class
```

### 1.4 Meronomy / Part-Of (`⊏`)

```
Signature: PartOf(x, y, subtype) : Entity × Entity × MeronymyType → Bool
MeronymyType ∈ {ComponentIntegral, MemberCollection, PortionMass, StuffObject, FeatureActivity, PlaceArea}

Subtype properties (Winston et al. 1987, formalized):
| Subtype               | Transitive | Same-Kind | Separable | Composition Constraint          |
|-----------------------|------------|-----------|-----------|----------------------------------|
| ComponentIntegral     | Yes        | No        | Yes       | Functional: part has at most one whole of this type |
| MemberCollection      | Weak*      | No        | Yes       | Inverse functional: whole has many members |
| PortionMass           | Yes        | Yes       | Yes       | Measure-theoretic additivity    |
| StuffObject           | No         | No        | No        | Constitutive, not compositional |
| FeatureActivity       | No         | No        | N/A       | Temporal containment            |
| PlaceArea             | No         | No        | N/A       | Spatial containment             |

* Weak transitivity: a ⊏ b (Member) ∧ b ⊏ c (Component) ↛ a ⊏ c

Computational role: **Construction ordering** — only ComponentIntegral participates in `derive_tiers()`. Other subtypes are query-time only.
Edge encoding: PartOf edges carry `subtype` field (3 bits, 6 values).
```

### 1.5 Associative (`∼`)

```
Signature: Assoc(x, y, label) : Entity × Entity × AssocLabel → Bool
AssocLabel ∈ {causes, precedes, locatedIn, producedBy, usedFor, antonymOf, hasProperty, ...}

Each label carries its own formal properties:
| Label         | Transitive | Symmetric | Inverse      |
|---------------|------------|-----------|--------------|
| causes        | Yes        | No        | causedBy     |
| precedes      | Yes        | No        | follows      |
| locatedIn     | Yes        | No        | contains     |
| producedBy    | No         | No        | produces     |
| usedFor       | No         | No        | uses         |
| antonymOf     | No         | Yes       | antonymOf    |
| hasProperty   | No         | No        | propertyOf   |

hasProperty is modeled as Associative(label=hasProperty) — see §3 for why this is sound.

Computational role: **Query expansion, inference chaining, salience weighting**
```

---

## 2. Property Model — Typed Schemas with Validation

The original split (object-valued vs. literal-valued) is necessary but insufficient. Here is the complete property schema:

```python
# Formal property schema (maps directly to Point 2 encoding)
PropertySchema = {
    # Identity
    "name": str,                    # Canonical property name
    "property_id": uint16,          # Stable ID across glyphs
    
    # Value typing
    "value_type": ValueType,        # OBJECT | LITERAL
    "literal_type": LiteralType | None,  # If LITERAL: INT, FLOAT, BOOL, DATE, STRING, BYTES
    "object_class": ClassID | None,  # If OBJECT: expected class of value entity
    
    # Cardinality & optionality
    "cardinality": Cardinality,     # SINGLE | MULTI | SET | LIST
    "optional": bool,               # May be absent
    "default": Value | None,        # Default value if absent
    
    # Inheritance & override
    "inherited": bool,              # Inherited through Subclass (default: true)
    "override_policy": OverridePolicy,  # REPLACE | MERGE | FORBID
    
    # Validation
    "constraints": list[Constraint],  # Range, pattern, enum, custom predicate
    
    # Epistemic metadata (stored on edges, not schema)
    # polarity, confidence, provenance → per-assertion, see §4
}

ValueType = Enum["OBJECT", "LITERAL"]
LiteralType = Enum["INT", "FLOAT", "BOOL", "DATE", "STRING", "BYTES"]
Cardinality = Enum["SINGLE", "MULTI", "SET", "LIST"]
OverridePolicy = Enum["REPLACE", "MERGE", "FORBID"]
Constraint = Union[RangeConstraint, PatternConstraint, EnumConstraint, CustomPredicate]
```

**Key insight**: The property schema is **design-time** (registered once per class), while property **assertions** are run-time edges carrying polarity/confidence/provenance. This mirrors the design-time/run-time boundary from `point1.md §Design-time vs. run-time`.

---

## 3. Canonical Identity — Content-Addressable with Collision Resolution

The original `canonical_id = FNV1a(normalize(canonical_label))` works for registration but fails under:
- **Legitimate homonyms** (Georgia the state / Georgia the country)
- **Label evolution** (renaming entities over time)
- **Cross-scheme merging** (two independently developed schemes assigning same label)

### Enhanced Protocol

```
Registration:
  1. Applicant provides: proposed_label, disambiguation_context
  2. System computes: base_id = FNV1a(normalize(proposed_label))
  3. If base_id unused → assign canonical_id = base_id, record label
  4. If base_id used by different entity → 
       canonical_id = FNV1a(normalize(proposed_label) || disambiguation_context)
     (context must be provided; system suggests minimal unique context)

Resolution (at decode/merge time):
  1. Entities with identical canonical_id → same entity (strong identity)
  2. Entities with different canonical_id but equivalence edge → merge candidates
  3. Entities with same label, different canonical_id → distinct entities (weak identity)

Versioning:
  - canonical_id is immutable once assigned
  - label changes create new label→canonical_id mapping; old mapping retained with timestamp
  - Cross-glyph resolution uses canonical_id only; labels are presentation-layer
```

**Why this works for Point 2**: The 8-byte canonical_id fits in the entity record's `has_canonical_id` flag path. The disambiguation context is a design-time concern, not encoded in the glyph.

---

## 4. Polarity & Confidence — Four-Valued Epistemic Logic

The original two independent bits (polarity ∈ {+,−}, confidence ∈ {0,1,2,3}) create a 4×4=16 state space but only 8 are semantically meaningful. We replace with a proper **four-valued logic**:

### Epistemic States

| State | Symbol | Meaning | Tier Propagation |
|-------|--------|---------|------------------|
| **Asserted True** | ⊤⁺ | "X is-a Y" with confidence ≥ threshold | **Yes** — contributes to dependency graph |
| **Asserted False** | ⊤⁻ | "X is-not-a Y" with confidence ≥ threshold | **No** — constraint, not dependency |
| **Retracted True** | ⊥⁺ | "X was asserted is-a Y, now withdrawn" | **No** — historical only |
| **Retracted False** | ⊥⁻ | "X was asserted is-not-a Y, now withdrawn" | **No** — historical only |

### Confidence as Continuous Belief

Internally, confidence is a **beta distribution** `Beta(α, β)` updated via Bayesian evidence:
- `α` = positive evidence count
- `β` = negative evidence count
- Displayed/quantized as 2-bit level: `⌊4 × α/(α+β)⌋`

**Threshold for tier propagation**: `α/(α+β) > 0.75` (level 3 of 4). This is a **tunable policy parameter**, not a hard constant.

### Provenance Composition

```
Edge = (source, target, relation, subtype, polarity, confidence, provenance_set)
provenance_set = { (agent_id, timestamp, method) }

Conflict resolution (at query time, not encoding time):
  - Multiple edges same (source, target, relation) with different polarity → 
      compute weighted belief: Σ confidence_i × polarity_i / Σ confidence_i
  - Provenance weights: curated > inferred > imported > heuristic
```

This makes disagreement **representable, not an error** — as `point1.md` concluded.

---

## 5. Salience — Computable Function with Composition Algebra

The original "four sources, pluggable weights" is operationally vague. Here is the formal model:

### Salience Sources (Formalized)

```python
# All sources produce: Entity → [0, 1] scalar
# Structural salience is NOT stored — computed on decode via derive_priority()

SalienceSource = Protocol:
    def score(self, entity: Entity, context: Context) -> float  # [0, 1]
    def weight(self, context: Context) -> float                 # ≥ 0
    def combine(self, scores: list[float]) -> float: ...

# Built-in sources:
class StructuralSalience:
    # score(e) = log(1 + transitive_dependents(e)) normalized to [0,1]
    # weight = policy.structural_weight
    # combine = identity (single score)
    
class EmpiricalSalience:
    # score(e) = corpus_frequency(e) / max_corpus_frequency
    # weight = policy.empirical_weight
    
class DesignerIntendedSalience:
    # score(e) = 1.0 if marked default, else 0.0
    # weight = policy.designer_weight
    
class SituationalSalience:
    # score(e, context) = context.relevance(e)  # user-defined function
    # weight = policy.situational_weight
```

### Composition Algebra

```
TotalSalience(e, context) = 
    Normalize( Σᵢ weightᵢ(context) × scoreᵢ(e, context) )

Where Normalize maps to [0, 1] preserving order.
```

**Policy is a first-class object** — not hardcoded. Different contexts (search vs. display vs. reasoning) instantiate different `SaliencePolicy` objects. The glyph encodes only the **designer-intended** scores (source 3); structural is recomputed; empirical/situational are external.

---

## 6. Reification — Formal Conditions & Encoding

```
Reify(edge) ⇔ 
    edge needs its own properties (temporal validity, certainty modifiers, attribution) OR
    edge participates in further relations (e.g., "this causation is disputed") OR
    edge is subject of discourse ("the marriage was brief")

ReifiedEdge = Entity with:
  - class = "ReifiedRelation"
  - properties: original_source, original_target, original_relation, original_subtype
  - edges: all original edge's epistemic metadata (polarity, confidence, provenance) 
           become properties of the reified entity
  - original edge is replaced by: source --hasReification--> reified_entity
                                 reified_entity --reifies--> target
```

**Encoding implication for Point 2**: Reified edges get a `reified_entity_index` from the reification table (edge_index → entity_index). The original edge record is **not duplicated** — the reification table is the single source of truth.

---

## 7. Extension Calculus — Formal, Not Informal

Every extension to the ontology must pass through this calculus:

```python
Extension = {
    "type": "RELATION_TYPE" | "FACET" | "SALIENCE_SOURCE" | "PROPERTY_SCHEMA" | "EPISTEMIC_FIELD",
    "spec": ExtensionSpec,           # Formal definition per type
    "dependencies": list[ExtensionID],  # What must exist first
    "tier_impact": bool,              # Does derive_tiers() need update?
    "encoding_impact": bool,          # Does Point 2 glyph format need update?
    "migration": MigrationPlan | None # How to upgrade existing glyphs
}

# Extension validation (run at design-time):
def validate_extension(ext: Extension, current_ontology: Ontology) -> ValidationResult:
    # 1. Check name uniqueness
    # 2. Check formal properties (e.g., new relation type must declare transitivity, symmetry)
    # 3. Check reduction: does it reduce to existing type? (If yes, reject or alias)
    # 4. Check tier impact: if adds tier-relevant relation, derive_tiers() must be extended
    # 5. Check encoding impact: if adds new edge field, Point 2 header must version-bump
    # 6. Generate migration plan if encoding_impact
```

**Closure under extension** is now **mechanically verifiable**, not just claimed.

---

## 8. Cross-Facet Identity — Dynamic Binding

The original "canonical ID at registration + append-only facet_path table" is sound but static. Enhanced model:

```
FacetBinding = {
    "canonical_id": CanonicalID,
    "facet_path": FacetPath,           # e.g., "PMEST:Space:Continent:NorthAmerica"
    "bound_at": Timestamp,
    "valid_from": Timestamp,
    "valid_to": Timestamp | None,      # None = currently valid
    "binding_confidence": float,       # [0,1]
    "provenance": ProvenanceRef
}

# Resolution:
resolve(facet_path, at_time) → canonical_id
  1. Find all bindings for facet_path where valid_from ≤ at_time < valid_to
  2. If exactly one → return its canonical_id
  3. If multiple → return highest binding_confidence (tie-break: most recent)
  4. If none → unresolved (facet path not bound at that time)
```

This supports **temporal facet evolution** (e.g., geopolitical changes) without breaking canonical identity.

---

## 9. Bridge to Point 2 — Enhanced Mapping Criteria

The original four criteria are necessary but incomplete. The **valid mapping** must also satisfy:

| # | Criterion | Test |
|---|-----------|------|
| 1 | **Logical isomorphism** | Every entity, relation, property, facet, salience value, epistemic field has exactly one representation |
| 2 | **Lossless round-trip** | `unpack(pack(G)) ≡ G` for all valid graphs G |
| 3 | **Bootstrap compatibility** | Header parsable by `bootstrap_block.py` |
| 4 | **Budget adherence** | `size(pack(G)) ≤ 8192 × sequence_length(G)` bytes |
| 5 | **Epistemic fidelity** | Polarity, confidence, provenance preserved without degradation |
| 6 | **Temporal coherence** | `unpack` at time `t` yields graph valid at `t` (facet bindings, retractions respected) |
| 7 | **Extension forward-compatibility** | New extension types decode gracefully (unknown fields → ignored with warning, not error) |

**Criterion 5 is new** — the original treated epistemic fields as "just bits" but they have semantic composition laws (Bayesian update, provenance weighting) that the decoder must respect.

**Criterion 6 is new** — temporal validity via reification means the decoder needs a `valid_at` parameter.

**Criterion 7 is the closure-under-extension guarantee made testable**.

---

## 10. Honest Limits — Sharpened

| Limit | Original | Enhanced |
|-------|----------|----------|
| **Completeness** | No finite scheme can be proven complete | **Confirmed**: Rice's Theorem — any non-trivial semantic property of the represented structures is undecidable |
| **Consistency** | Not addressed | **Gödel**: The framework can express its own syntax → cannot prove its own consistency internally |
| **Identity** | Canonical ID collision possible | **Quinean**: Identity is always relative to a translation manual; cross-scheme identity is pragmatic, not logical |
| **Scaling** | 6 glyphs for English core | **Phase transition**: At ~10⁴ entities, structural salience dominates; at ~10⁶, empirical salience must be approximated (sketches, not exact counts) |
| **Decoding** | Deterministic | **Adversarial**: Malformed glyphs can cause unbounded decode time without length prefixes on variable regions (mitigated: header declares all region sizes) |

---

## 11. Lineage — Extended

| Piece | Origin |
|-------|--------|
| Five relation types, facets, structural/empirical salience, honest-limits framing | `ontology.md` |
| Meronymy subtypes, typed associative labels, properties, reification, design/runtime split, extension mechanism | `structure.md` |
| Citation correction (Winston et al. actual examples) | `point1.md` pass |
| Object-valued vs. literal-valued properties | `point1.md` pass |
| Canonical-ID fix (was self-contradictory) | `point1.md` pass |
| Polarity and confidence, composition with provenance | `point1.md` pass |
| Multi-glyph capacity reconciliation | `point1.md` pass |
| **Formal relation signatures** | **This enhancement** |
| **Typed property schemas with validation** | **This enhancement** |
| **Content-addressable canonical ID with collision resolution** | **This enhancement** |
| **Four-valued epistemic logic with Bayesian confidence** | **This enhancement** |
| **Salience as computable function with composition algebra** | **This enhancement** |
| **Formal reification conditions & encoding** | **This enhancement** |
| **Extension calculus with mechanical validation** | **This enhancement** |
| **Dynamic facet binding with temporal validity** | **This enhancement** |
| **7-criterion valid mapping (added epistemic fidelity, temporal coherence, forward-compatibility)** | **This enhancement** |

---

## 12. Implementation Checklist for Point 2 Encoder

The encoder must now handle:

- [ ] Two-tier entity records with optional canonical_id (8B) and label_ref
- [ ] Compact vs. full edge format selection per edge
- [ ] Edge subtype field (3 bits) for PartOf
- [ ] Epistemic state (2 bits polarity+confidence quantized, or 8 bits for full beta params)
- [ ] Provenance reference (index into provenance table)
- [ ] Reification table (edge_index → entity_index)
- [ ] Literal pool with TLV encoding
- [ ] Facet binding table (for temporal resolution)
- [ ] Salience records (only non-structural sources)
- [ ] Parity blocks (XOR-interleaved, configurable block count)
- [ ] Sequence fields for multi-glyph messages
- [ ] Header checksum (CRC16)
- [ ] Version field for forward compatibility

**Estimated encoder complexity**: ~2,000 lines of Python (bit-packing, validation, testing). The decoder is symmetric.

---

*End of Point 1 Enhanced. This document, together with Point 2 Enhanced, forms a complete, implementable specification for the structural theory and its dot-matrix encoding.*