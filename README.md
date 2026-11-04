# POINTS — Persistent Ordered Information Naively Transmitted in Series

> Verified on the reference machine (2026-11-04):
> `python3 -m pytest suite/tests/ -q` → **94 tests passed, 42 subtests passed
> in 2.37 s**. Four historically found bugs (B1–B4) are protected by
> regression tests that fail if the bug returns.

**POINTS** is a visual knowledge-graph codec. It packs a whole knowledge
graph — entities, typed and tagged edges, facets, salience, epistemic
state — into a **block of exactly 8,192 bytes** (a *glyph*), displayed as
raised-dot Braille patterns so a person, a camera, or a computer can all
read it. Glyphs are self-contained and the format supports multi-glyph
chaining, so graphs larger than one block span a numbered sequence.

Why it is interesting:

- **Fixed size.** The byte budget is a hard constraint, not a heuristic.
- **Damage repair.** Reed–Solomon parity (255,223) corrects up to 16
  damaged symbols per 223-byte block; XOR parity is the cheaper
  detect-only mode. The header says which mode a glyph uses.
- **Human-checkable.** The payload is rendered in visible dot patterns.
- **Epistemic structure is first-class.** Every connection carries its
  own confidence and polarity fields, not `null`s.
- **Measured.** On the reference sweep, at 460 entities in one glyph
  POINTS holds **9.7×** the semantic capacity of compact JSON for the
  same facts. See the ONE paper for the full measurements.

## Repository layout

| Path | Role |
|---|---|
| `suite/` | Codec modules (packing, entity/edge tables, payload, parity, RS codec, glyph rendering, header) |
| `suite/tests/` | The test suite: 94 tests + 42 subtests, incl. the 7-entry golden corpus and a 14-pattern red-team suite |
| `suite/glyph.py`, `suite/glyph_multi.py` | Single- and multi-glyph renderers |
| `suite/rs_codec.py`, `suite/parity.py` | Reed–Solomon and XOR parity |
| `suite/header.py`, `suite/structure.py` | Fixed header (42 bytes) layout; graph structure model |
| `suite/encode_*.py` | Entity, edge, payload encoders |
| `suite/points_tool.py`, `suite/agent_tool.py`, `suite/points_mcp.py` | Integration surfaces (CLI tooling, agent tool, MCP) |
| `suite/delegation.py`, `suite/bits.py`, `suite/demo.py` | Supporting modules |
| `point1.md`, `point2.md`, `anchor.md` | The structural theory ("Point 1"), the dot-matrix mapping framework ("Point 2"), and the anchored project summary |
| `prior/` | Superseded drafts of the theory documents (kept for provenance) |
| `showcase/` | Runnable showcases (`run_showcase.py`, sessions, tasks) |
| `beam_search.py` | Search tooling used during codec development |
| `sample_glyph/` etc. | Examples and artifacts as present |

## Quick start

```bash
python3 -m pytest suite/tests/ -v          # 94 tests + 42 subtests
python3 -m pytest suite/tests/test_redteam.py -v   # 14 damage patterns
python3 suite/demo.py                      # encode a small graph to a glyph
```

## Glyph byte layout (summary)

Each glyph is exactly 8,192 bytes:

1. **Fixed header (42 bytes)** — magic, version, sequence number, parity
   mode/count, entity/edge counts, graph id, region offsets.
2. **Entity table** — each entity: id code, label index, properties.
3. **Edge table** — per edge: source/target, relation code (one of 12),
   meronymy subtype where applicable, confidence tag (0..3), polarity
   (affirmed/denied), optional reification.
4. **Payload regions** — literal properties, facet and salience lists.
5. **Parity** — either XOR (≈15 % of content, detect-only) or RS(255,223)
   blocks (32 parity bytes per block, corrects up to 16 bad symbols each).

The full formal grammar is Appendix "Full O-OIS EBNF Grammar" of the ONE
paper; the structural theory behind the layout is `point1.md` and
`point2.md` in this repository.

## Relationship to the ONE paper

POINTS is one of the three instantiations of the O-OIS grammar studied in
"Maximum Semantic Capacity via the Ontology of Optimal Information
Structure" (2026). The golden corpus here — an empty graph, a single
entity, a single edge, a 4-entity multi-edge graph, a payload graph, a
denied/uncertain graph, and the six-entity "mechanical watch" — is the
reference set used by the paper's Table on semantic capacity.

## License

MIT — see [`LICENSE`](LICENSE).
