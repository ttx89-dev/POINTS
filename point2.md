# Point 2, concluded — the dot-matrix mapping framework

How Point 1's structure (entities, five relation types, properties,
facets, salience, polarity/confidence) packs into a hard 65,536-bit
(8,192-byte) budget per glyph, with multi-glyph sequencing as the
overflow path. Same discipline as the bootstrap block: spec fully
locked here, code next.

## Why bit-packed here, byte-aligned everywhere else

Every prior format this session built (bootstrap block, payload codec,
content store) stayed byte-aligned — clarity and debuggability mattered
more than density, because the address space itself was never the
scarce resource. Here the opposite is true: 65,536 bits is a hard wall,
and the Huffman-style instinct from several rounds back — the common
case should cost less — finally has a problem where it's literally
correct, not just analogous. This format is bit-packed by deliberate
necessity, not inconsistency.

## Budget

| Region | Bytes | % |
|---|---|---|
| Header (fixed) | 40 | 0.5% |
| Parity | 1,228 | 15% |
| Content (entity/edge/facet/salience/literal/reification tables) | 6,924 | 84.5% |
| **Total** | **8,192** | **100%** |

> **Edit note (2026-11-05, documentation pass):** the implemented header
> (`suite/header.py`) is **42 bytes** — the 40 field bytes drafted above plus a
> 2-byte CRC16 over `buf[:40]` stored at offsets 40–41 — and the content region
> is **6,920 bytes** (`CONTENT_SIZE = 6920`), leaving **1,230 bytes** of parity
> budget. The drafted figures above (40 / 6,924 / 1,228) predate that fix-up;
> the total is unchanged: 40 + 6,924 + 1,228 = 42 + 6,920 + 1,230 = 8,192.

15% parity matches real QR "Level M." Declared, not hardcoded — see
Parity below.

## Header (fixed, 40 bytes, Layer A — read before anything else)

> *(Implemented as 42 bytes — 40 field bytes + CRC16; see the edit note
> under the Budget table above.)*

| Field | Size | Purpose |
|---|---|---|
| MAGIC | 2B | format identifier |
| VERSION | 1B | |
| SEQUENCE_ID | 4B | which multi-glyph communication this belongs to |
| SEQUENCE_INDEX | 1B | this glyph's position in that sequence |
| SEQUENCE_TOTAL | 1B | how many glyphs the sequence has |
| PARITY_RATIO | 1B | percent, default 15 |
| PARITY_ALGO_ID | 1B | 0=none, 1=xor-interleaved, 2=reed-solomon |
| ENTITY_COUNT | 2B | |
| ENTITY_INDEX_BITS | 1B | declared, = ceil(log2(entity_count)) — self-describing, not recomputed |
| EDGE_COUNT | 2B | |
| CONFIDENCE_BITS | 1B | default 2 (four levels) |
| FACET_COUNT | 1B | |
| SALIENCE_ENTRY_COUNT | 2B | non-structural only, see below |
| LITERAL_POOL_BYTES | 2B | |
| REGION_OFFSETS | 12B | 6 regions × 2B each |
| RESERVED | 4B | headroom, matching every prior format's reserved-space discipline |
| HEADER_CHECKSUM | 2B | crc16, reusing the algorithm already in `payload_codec.py` |

## Entities — two-tier, most fields optional

Not every entity needs to be recognizable from another glyph, and not
every entity needs a human-readable label — an entity that only exists
as the target of a reified edge is meaningful purely through its edges.
Fixed record, flags determine what's actually present:

`flags(1B: bit0=has_canonical_id, bit1=has_label) + [canonical_id(8B) if flagged] + [label_pool_offset(2B)+length(1B) if flagged]`

Minimum: 1 byte. Maximum: 12 bytes. Cross-glyph identity is resolved
entirely at this level — two different glyphs each declaring an entity
with the same `canonical_id` (the same FNV1a-of-canonical-label hash
already fixed in `point1.md`) are recognized as the same entity when a
decoder assembles the full sequence. Edges never need to point outside
their own glyph — this is why that design works, not just why it's
convenient.

## Edges — compact/full duality

The Huffman instinct made concrete: most edges are the boring common
case (asserted, maximally confident, standard subtype, never reified).
Those get the cheap encoding. Anything else pays for what it uses.

**Compact — entity-to-entity only** (`source[ENTITY_INDEX_BITS] + target_kind[1]=0 + target[ENTITY_INDEX_BITS] + relation_type[3] + polarity[1]`) — subtype defaults to 0, confidence defaults to maximum, reified defaults to false.

**Full — required whenever the target is a literal, and available for anything else that needs a non-default field** — `source[ENTITY_INDEX_BITS] + target_kind[1] + target[TARGET_BITS] + relation_type[3] + subtype[3] + confidence[CONFIDENCE_BITS] + polarity[1] + reified[1]`, where `TARGET_BITS = max(ENTITY_INDEX_BITS, 16)`.

This split isn't arbitrary — it's forced by an honest constraint. The
literal pool can hold up to 65,535 bytes (`LITERAL_POOL_BYTES` is a 2-byte
field), so any edge whose target is a literal needs a field wide enough
to address that whole pool, not just wide enough for the entity count.
Rather than reserving that extra width on *every* edge whether it's used
or not, only literal-targeting edges (and any other edge that genuinely
needs a non-default field) pay for the wider format. Object-valued edges
— the majority in practice — stay in compact format because they only
ever need to address the entity table, never the literal pool.

A leading bit on each edge declares which format follows.

Reified edges get their `reified_entity_index` from a **separate small
reification table** (edge_index → entity_index pairs), not from an
always-reserved field in every edge record — reification is rare, and
paying its cost only where it's used, rather than on every edge whether
used or not, is the same indirection-for-the-rare-case pattern
`content_store.py` already uses for offsets.

## Facets, salience, literal pool

**Facets**: `facet_id(1B) + dimension_count(1B) + dimension_ids(1B each)` — small, rarely more than a handful per glyph.

**Salience — one real economy found here**: structural salience is
*already fully derivable* from the edge table by re-running
`derive_priority()` on decode. Storing it explicitly would be storing a
value the decoder can compute for free. Only empirical,
designer-intended, and situational salience — the three sources
Point 1 established as *not* graph-derivable — get explicit records:
`entity_index + source_id(2b) + scalar(1B)`.

**Literal pool**: raw bytes for literal-valued properties (numbers,
dates, short strings), TLV-tagged, referenced by edges whose
`target_kind=1`.

## Parity

`xor-interleaved-blocks` is the concrete default: split content into N
blocks, XOR them together into one parity block, same principle as
RAID-5 — real, simple, and (unlike Reed-Solomon) something I can
actually implement and test correctly in this sandbox rather than
asserting it works. It recovers any single lost block, not more.
Reed-Solomon (real per-symbol resilience, the actual QR-grade guarantee)
needs Galois-field arithmetic — genuine, well-established math, but
exactly the kind of thing worth its own carefully tested round rather
than rushing into an already-large one, especially since Julia execution
still can't be verified in this sandbox and GF(256) arithmetic is not
where a first untested implementation should live. `PARITY_ALGO_ID`
exists specifically so this upgrades later without touching anything
else — same closure-under-extension property as every checksum choice
this session has made.

## The number, verified not guessed

A first pass assuming every field is always fully present and every
entity needs full cross-glyph identity blows the budget by roughly
**6.6×** for a ~2,000-entity, ~5,000-edge generative core — entities
alone cost 22,000 bytes against a 6,924-byte budget. Applying the real
optimizations above (two-tier entities, compact/full edges, dropping
redundant structural salience) brings total content to **~41,500
bytes**, computed, not estimated by feel. That's **6 glyphs**, not the
1–2 loosely projected several rounds back — an honest correction, not a
failure. The earlier estimate priced *concepts*; it didn't price the
*relationships between them*, which Point 1's structure correctly
insists need explicit representation. Six glyphs for a working
generative core of English is still a small, bounded, genuinely
striking number — it just isn't one.

## What's concluded vs. deferred

Concluded: the full record layout for every region, the budget
allocation, the two-tier entity economy, the compact/full edge economy,
the structural-salience elimination, the multi-glyph sequencing fields,
and a real, verified byte count for a realistic-scale case.

Deferred, named rather than skipped: Reed-Solomon parity (needs its own
tested round), and all of `pack_glyph()`/`unpack_glyph()` — this
document is the spec, the same relationship `bootstrap_block.py`'s spec
table had to its code before either language was written.
