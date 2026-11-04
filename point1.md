# Point 1, concluded — the structural theory of information

Supersedes `ontology.md`, `structure.md`, and `structure1.md`. Self-
contained — reading this alone is sufficient. Not digital; nothing here
mentions glyphs, bits, or the 65536-point spec except in the final bridge
section, which exists only to connect this to Point 2.

## Method

Not proposed from scratch. Library science, formal ontology, and
cognitive linguistics each independently spent the better part of a
century on this question and converged on the same small set of
distinctions. That convergence, across fields not in dialogue with each
other, is the actual evidence this is load-bearing rather than a
well-organized guess. This document reports that convergence, corrects
one internal inconsistency found while verifying it, and adds what a
careful pass surfaced as still missing.

## The five relation types

**1. Equivalence** — two labels, one referent. Two levels: *lexical*
("car"/"automobile" — a synonym map, mechanical) and *referential*
("the president of France in 2020"/"Emmanuel Macron" — a definite
description and a name sharing a referent, requiring resolution, not
mechanical). Both are equivalence edges. **Still unbuilt**: nothing in
the existing code catches either kind — content-addressing only
collapses byte-identical bytes.
| Piece | Origin |
|---|---|
| Five relation types, facets, structural/empirical salience, honest-limits framing | `ontology.md` |
| Meronymy subtypes, typed associative labels, properties, reification, design/runtime split, extension mechanism | `structure.md` (more developed than `structure1.md`, which carried a subset of the same material) |
| Citation correction (paper's actual examples, not substituted ones) | this pass |
| Object-valued vs. literal-valued properties | this pass |
| Canonical-ID fix (was self-contradictory as drafted) | this pass |
| Polarity and confidence, and their composition with provenance | this pass |
| Multi-glyph capacity reconciliation | this pass |
**2. Is-a / subclass-of** — genus-differentia. Test: "is every X
necessarily a Y." `derive_tiers()` computes this correctly, labeled
generically as "depends-on."

**3. Instance-of** — an individual belongs to a class without being a
subtype of it (France is an instance of "country," not a kind of country
the way "island nation" is). Kept structurally distinct in OWL and RDF
Schema (`rdf:type` vs. `rdfs:subClassOf`) for exactly this reason —
collapsing the two implies false things about individuals. Test: "does X
have possible subtypes of its own." Meaningful only once entities carry
properties (§ Properties, below). **Still conflated with is-a** in
`derive_tiers()` — real, specific, unfixed gap.

**4. Part-of (meronomy)** — compositional, whole-part, formally distinct
from is-a. Winston, Chaffin & Herrmann (1987, *Cognitive Science*
11:417–444) identify six subtypes with different formal properties:

| Subtype | Example (the paper's own) | Transitive? | Same-kind? | Separable? |
|---|---|---|---|---|
| Component-integral object | pedal–bike | Yes | No | Yes |
| Member-collection | ship–fleet | Weakly* | No | Yes |
| Portion-mass | slice–pie | Yes | Yes | Yes |
| Stuff-object | steel–car | No | No | No |
| Feature-activity | paying–shopping | No | No | N/A |
| Place-area | Everglades–Florida | No | No | N/A |

\*Mixed-type chains don't compose cleanly — a ship is part of a fleet, a
plank is part of a ship, but a plank is not part of a fleet in the same
sense. The classic failure case for naive mereological transitivity.

What `derive_tiers()` computes is component-integral-object meronomy
with a construction-order constraint — one of six, not the general case,
and the correct one for this project (things are being built
hierarchically). Part-of edges should carry a subtype label; code that
doesn't need the distinction treats all six as "part-of."

**5. Associative** — related, neither hierarchical nor equivalent.
ISO 25964 (thesaurus construction) keeps this as its own bucket because
forcing every real relation into is-a or part-of breaks down fast.
Carries typed labels with their own formal properties — causes
(transitive, asymmetric), precedes (transitive, asymmetric), located-in
(transitive), produced-by, used-for, antonym-of (symmetric, non-
transitive). **Has-property is modeled as an associative relation with a
label**, not a sixth top-level type — checked deliberately during this
pass, not assumed: the alternative (a dedicated Property primitive, the
way OWL treats it) would work too, but folding it into associative-with-
a-label keeps the top-level type count minimal and is consistent with
how every other labeled associative relation already carries its own
distinct formal properties (transitivity, symmetry). Sound as a design
choice, not an oversight.

**Refinement found in this pass — object-valued vs. literal-valued
properties.** Neither prior document distinguishes these, and the
distinction is real: OWL's ObjectProperty/DatatypeProperty split exists
precisely because a property's value is sometimes itself an entity
("color" → RED, which has its own is-a hierarchy — crimson is-a red) and
sometimes a raw, structureless datum (a number, a date, a boolean) that
carries a type but participates in none of the five relations. Treating
"1200" (a car's weight in kg) as an entity that "participates in all
five relation types" is a category error — it's just data. This matters
concretely for Point 2: literal values need only a typed byte slot;
object-valued properties need a full entity reference. Different
encoding cost, and the framework should say so explicitly rather than
treat every property value uniformly.

**Facets** — orthogonal, independent classification axes, read
simultaneously rather than traversed. Ranganathan's Colon Classification
is the canonical case; his five fundamental categories (Personality,
Matter, Energy, Space, Time — PMEST) support the deeper point: **facets
are not primitive** — a facet is a cluster of property dimensions
habitually co-queried together. This resolves cross-facet identity
cleanly: there is one entity with many properties, and facets are just
organized views over that property space, not a separate structure
needing its own reconciliation mechanism.

**Cross-facet identity — corrected mechanism.** structure.md proposed
`canonical_id = FNV1a(all known facet-paths, concatenated)`, then claimed
new facet-paths could be added without the ID changing. Those two claims
contradict each other — hashing a set that grows necessarily changes the
hash. The fix: **the canonical ID is derived once, at first
registration, from the entity's chosen canonical label** —
`canonical_id = FNV1a(normalize(canonical_label))` — a single fixed
string, not a growing set. A separate, genuinely append-only table then
maps `facet_path → canonical_id`. This is stable by construction, reuses
the same FNV1a already built in `content_store.py`, and actually
satisfies the invariant it claims to have. One honest residual: two
distinct entities can want the same label (two "Georgia"s — the US state
and the country) — the canonical label has to be disambiguated enough to
be unique at registration time. That burden falls on whoever registers
first, the same place every other naming judgment call in this framework
has consistently landed.

## Salience

Four sources, same interface (a rankable scalar per entity, per source):
**structural** (transitive dependents — `derive_priority()`, already
built), **empirical** (corpus frequency, prototype centrality,
markedness — not built), **designer-intended** (the scheme author
marking a default — not derivable from graph or corpus, a real design
choice, and the most immediately usable source since this project
controls its own scheme), and **situational** (context-dependent —
"restaurant" matters when hungry, not when hiking). Sources combine via
a pluggable weighting function; sorting by the combined result is
mechanical once the data exists.

## Properties

The main thing `ontology.md` was silent on, and what makes instance-of
and is-a-with-inheritance actually meaningful. `has-property` is
functional (one value per dimension at a time), inherited through is-a
unless overridden, and monotonic (new properties don't remove old ones).
Now split, per the refinement above, into object-valued (participates in
all five relations) and literal-valued (typed data, no further
structure).

## Reification

Any relation edge may be promoted to an entity when it needs its own
properties, needs to participate in further relations, or is itself the
subject of discourse ("this marriage was brief"). Always possible, not
always necessary — simple dependency edges never need it.

## Polarity and confidence — found missing in this pass

Everything above assumes every asserted relation is simply true and
fully believed. Real information isn't always either. Two fields,
cross-cutting all five relation types, attached to every edge with
defaults that cost nothing in the common case:

- **Polarity** — asserted (default) or negated. "X is-a Y" and "X is
  definitely not a Y" are structurally the same edge type and label,
  differing only in this one bit.
- **Confidence** — a degree of belief in the assertion, independent of
  polarity. Orthogonal to salience: something can be highly salient
  (central, important) with low confidence (uncertain), or the reverse.

**Concrete implication for existing code**: `derive_tiers()` should only
follow *asserted* is-a/instance-of/part-of edges when computing
dependency order — a negated relation isn't a construction-order
dependency, it's a constraint, and treating it as one would corrupt the
tier computation. This is a real, specific change existing code needs,
not just a theoretical addition.

## Design-time vs. run-time

The mechanical/grounded distinction from `ontology.md` is a claim about
run-time determinism, not the whole process. Every layer requires
judgment or external data at setup: which facets exist, which
dependencies are honestly real, which salience sources and weights
apply. What the framework guarantees is that once setup is done,
everything downstream — topological sort, ranking, decoding — is fully
deterministic. Same "zero guesswork at read time" property the address
space has always had, now stated precisely for where the boundary
actually sits.

## Closure under extension — the mechanism, not just the claim

A new **relation type** needs: a name, a definition with an inclusion
test, a check for whether it actually reduces to an existing type, a
mechanical-or-grounded classification, and a decision on whether it's
tier-relevant (only `derive_tiers()` needs updating if so — everything
else is unaffected). A new **facet** needs a name, a value domain, and a
disjointness check against existing facets — zero code impact, facets
are additive by construction. A new **salience source** needs a name, a
type, and a combination rule — zero code impact, salience is pluggable
by design. Polarity and confidence needed no new extension category —
they're fixed fields on the existing edge structure, not a new kind of
edge.

## Honest limits

This is the most refined version this pass can produce, converged from
roughly a century of independent cross-field work, corrected once for
an internal contradiction and extended twice for gaps a careful reading
surfaced. That is real evidence of soundness, not a proof of
completeness — no finite, closed scheme can be proven complete over an
open-ended subject, the same limit this project named for the address
space itself. What's claimed is closure under extension: a genuinely
missing seventh relation type, if one is ever found, gets added without
requiring the other six pieces to be redesigned.

## Bridge to Point 2

What the dot matrix has to encode: entities, five relation types between
them (three of which — is-a, instance-of, part-of — participate in tier
ordering, the other two don't), properties split by whether their values
are entities or literals, reification for edges that need to become
entities, facet values, salience per source, and now polarity/confidence
per edge. One thing checked and confirmed rather than added: temporal
validity ("France was a monarchy, not is") doesn't need a third
always-present field alongside polarity and confidence — it's exactly
the kind of case reification already names ("the edge needs properties
of its own — date, location, certainty") — so it's handled by the
existing mechanism, not a new one.

**Valid mapping criteria, corrected**: a mapping is valid iff (1) it's
isomorphic to the logical structure — every entity, relation, property,
facet, and salience value has exactly one representation, and (2)
`unpack` reconstructs the exact structure with zero ambiguity, given (3)
the header stays compatible with what `bootstrap_block.py` already
parses. Criterion (4) in the prior draft was stated as a hard per-glyph
capacity bound, which can directly conflict with criterion (1) — a
logical structure can need more than 65,536 bits to encode losslessly,
and no mapping satisfies both a hard bound and full isomorphism in that
case. The fix isn't lossy compression, it's what this project already
described unprompted several rounds ago: content spans a glyph
*sequence* when one glyph's budget is insufficient, so the real
constraint is total bits across the sequence actually used, not a wall
at 65,536 that silently forces something to be dropped.

**One composition worth stating explicitly**: polarity and confidence,
from this pass, and provenance — who or what asserted a fact, established
several rounds before this document existed — aren't redundant with each
other, and together they're what makes genuinely *conflicting* assertions
coherent rather than a framework failure. Two sources disagreeing (one
asserting Pluto is-a planet, another asserting it is not) isn't a
contradiction the structure needs to resolve — it's two distinct edges,
each carrying its own polarity, confidence, and provenance. Disagreement
is representable, not an error state.

## Lineage

(Not to be confused with provenance above — this table tracks which
document a piece of *this theory* came from, not who asserted a fact
about the world. Reusing "provenance" for both would be exactly the kind
of conflation this document has spent its effort warning against.)

| Piece | Origin |
|---|---|
| Five relation types, facets, structural/empirical salience, honest-limits framing | `ontology.md` |
| Meronymy subtypes, typed associative labels, properties, reification, design/runtime split, extension mechanism | `structure.md` (more developed than `structure1.md`, which carried a subset of the same material) |
| Citation correction (paper's actual examples, not substituted ones) | this pass |
| Object-valued vs. literal-valued properties | this pass |
| Canonical-ID fix (was self-contradictory as drafted) | this pass |
| Polarity and confidence, and their composition with provenance | this pass |
| Multi-glyph capacity reconciliation | this pass |
