# POINTS — Anchored Summary

**Codec status (2026-10-15):** B1/B2/B3/B4 fixed; 94 tests + 42 subtests pass; golden-corpus glyph bytes unchanged.

## Objective
POINTS (Persistent Ordered Information Naively Transmitted in Series) is a visual encoding scheme that packs structured data (entities, edges with semantics, confidence, polarity) into fixed-width 8192-byte glyphs via Unicode Braille patterns (Point 1: logical structure, Point 2: glyph encoding). Goal: human-verifiable, machine-decodable data that survives screenshot copy-paste.

## Codebase Structure

```
suite/                     # Core engine
  bits.py                  # Raw bit packing (9→8 expansion, chunked)
  braille.py               # Bit pattern ↔ Braille mapping (2×3)
  header.py                # 42-byte glyph header (RS parity fields)
  structure.py             # Data model: Entity, Edge, Graph, LiteralValue
  encode_entities.py       # Entity table encoder
  encode_edges.py          # Edge table encoder
  encode_payload.py        # Full payload encoder
  glyph.py                 # Glyph pack/unpack orchestration
  parity.py                # RS(255,223) + XOR parity (encode, verify, repair)
  agent_tool.py            # decode_glyph, glyph_summary for MCP sub-agents
  delegation.py            # [[NEW]] Label-convention task/result transport
  points_tool.py           # CLI tool
  demo.py                  # Demo pipeline
  tests/                   # Unit tests (94 pass, 42 subtests)
    test_pipeline.py       # Core round-trip, parity, agent_tool
    test_redteam.py        # Adversarial: corruption, boundaries, corpus regression
    test_golden_corpus.py  # 7 reference glyph cross-checks
    test_agent_glyph.py    # Sub-agent glyph integration
    test_multi.py          # Multi-sequence tests
    test_delegation.py     # Label convention protocol tests (14 tests)
    test_codec_gaps.py     # [[NEW]] B1–B4 codec gap regression + byte-stability pins
    bench_glyph.py         # Performance benchmarks

showcase/                  # Sub-agent demos
  subagent_beam.py         # Beam search sub-agent
  subagent_code.py, subagent_fib.py,
  subagent_logic.py, subagent_math.py
  run_showcase.py           # Runner (all 5 pass)

beam_search.py             # Standalone beam search (no POINTS dep)

prior/                     # Spec evolution
  enhancement.md, point1_enhanced.md, point2_enhanced.md
point1.md, point2.md       # Spec docs
```

## Work Completed

### Core System (stable, verified)
- **Glyph encode/decode** — full round-trip pipeline (pack → unpack)
- **RS(255,223) Reed-Solomon parity** — corrects up to 16 byte errors per 223-byte block
- **XOR parity** — lightweight parity option
- **Golden corpus** — 7 reference glyphs for cross-corpus regression
- **Red team testing** — adversarial: bit flips, burst corruption, zero content, max indices, truncated glyphs, bad headers, parity attacks — all pass
- **Codec fixes B1–B4** (2026-10-15) — EntityTable container, properties_literal round-trip, literal edge resolution, no-cid corruption fix
- **94 tests pass** (42 unittest subtests) — up from 74

### MCP Integration
- `suite/agent_tool.py` — `decode_glyph()`, `glyph_summary()` for sub-agent use
- Decoded entities arrive as `EntityTable` — list + `.values()`/label lookup (B1 fixed 2026-10-15)

### Delegation Protocol (new)
- `suite/delegation.py` — transports task instructions + results via entity labels
- Uses label convention: `__param:X=Y`, `__task:X=Y`, `__result:X=Y`
- Sidesteps all three known codec gaps (see below)
- 14 tests, all pass

## Codec Gaps — RESOLVED (2026-10-15)

All four gaps fixed in the single-glyph path (`glyph.py`, `encode_entities.py`, `structure.py`); multi-glyph paths inherit via `glyph_multi.py`'s use of `pack`/`unpack`.

### B1 — `unpack()` entity container (FIXED)
`unpack()["entities"]` is now an `EntityTable`: full list behavior (iteration, int indexing, slicing, equality with plain lists) plus `.values()`, `.keys()`, `.items()`, `.get(key, dflt)`, and `table["Label"]` lookup. The delegation protocol is unaffected (list iteration preserved).

### B2 — `properties_literal` round-trip (FIXED)
Serialized via entity flags bit2 + record extension: `count(1B) + count × (key_len(1B) + key + LiteralValue.as_bytes())`. Plain Python values are coerced (bool before int); empty dict encodes as absent; keys sorted for determinism. Limits: key ≤255 B, ≤255 props per entity.

### B3 — Literal edge targets (FIXED)
`unpack()` resolves literal targets against the edge literal pool (region split derived from entity label extents): `target` = decoded value, `target_raw` = pool address, `target_literal_type` = type name, `target_resolved` = bool. Unresolvable addresses degrade gracefully (`target_resolved=False`).

### B4 — Entities without `canonical_id` (NEW finding, fixed 2026-10-15)
The label block was written only under `if has_cid:`, so entities with `canonical_id=None` produced corrupt glyphs (`BitReader: exhausted` on decode). Labels are now written whenever flags bit0 is set. Pre/post probe: FAIL → CLEAN.

### Byte stability
All 7 golden-corpus glyph hashes are unchanged by the fixes — pinned in `suite/tests/test_codec_gaps.py` (TestPackByteStability).

### Verification record
- 94 tests + 42 subtests green (pytest); per-file suites green; red-team suite green.
- Mutation red-watch: reverting each fix individually fails its targeted tests (B1: 4, B2: 3, B3: 3, B4: 2 failures).
- Consumers audited: `agent_tool.py`, `points_tool.py`, `points_mcp.py`, `showcase/` — no breaks.

## Pending / Future
1. **Streaming decoder** — emit partial graphs before full sequence arrives
2. **Multi-sequence assembly** — stitch glyph sequences into larger graphs
3. ~~Literal edge resolution fix (B3)~~ — DONE 2026-10-15 (codec fixes B1–B4)
4. ~~properties_literal serialization (B2)~~ — DONE 2026-10-15 (codec fixes B1–B4)
5. **MCP server integration** — POINTS as an MCP tool for OpenCode agents
6. **Integration with vexl-language POINTS** — coordinate sub-agent glyph transport across projects

## Critical Constraints
- **NEVER commit/stage/push to git** — POINTS remains untracked LOCAL ONLY
- Working directory: `/var/home/ryan/Documents/projects/POINTS`
