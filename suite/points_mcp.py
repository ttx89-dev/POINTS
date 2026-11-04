"""POINTS MCP Server — agent-callable glyph encode/decode tools.

Protocol:
  1. Main agent builds a graph spec (JSON) and calls `points_encode` or
     `points_encode_raw` to get a handle or raw bytes repr
  2. Handle is `chr(0xE000)` — works within the same MCP server process
  3. Raw bytes repr is `b'...'` — cross-process safe for sub-agents in
     separate processes or sessions
  4. Sub-agent calls `points_decode` with the handle or bytes repr to
     recover the graph dict, does work, and returns results
"""

from __future__ import annotations
import sys
import os

# Ensure POINTS package is importable
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from suite.glyph import pack, unpack
from suite.structure import Graph, RelationType, MeronymySubtype, AssociativeLabel, Confidence, SalienceSource
from suite.points_tool import (
    POINTS_CHAR,
    encode_points as _encode_points,
    decode_points as _decode_points,
    encode_graph_str,
    points_info as _points_info,
    points_clear as _points_clear,
    points_slots as _points_slots,
    DEFAULT_SLOT,
)

# ── Helpers ──────────────────────────────────────────────────────────

def _coerce_struct(item, field_name: str):
    """Return a dict for `item`, parsing it if the transport stringified it.

    Some MCP client transports deliver nested JSON values as strings rather
    than as objects. When that happens to the elements of spec["entities"] or
    spec["edges"], the original code raised

        TypeError: string indices must be integers, not 'str'

    from ``ent["label"]`` — an error that says nothing about the real cause.
    Driven directly over stdio with well-typed JSON the codec is fine, which
    is exactly why this only ever surfaced through a client.

    A dict is returned as-is. A str/bytes holding a JSON object is parsed. A
    bare non-JSON string is wrapped as a label, so the caller's own
    "does not match any entity id/label" error surfaces instead of a type
    error from inside the parser.
    """
    if isinstance(item, dict):
        return item
    if isinstance(item, (bytes, bytearray)):
        item = item.decode("utf-8", "replace")
    if isinstance(item, str):
        text = item.strip()
        if text.startswith("{"):
            import json as _json
            try:
                parsed = _json.loads(text)
            except ValueError:
                return {"label": item}
            if isinstance(parsed, dict):
                return parsed
        return {"label": item}
    raise TypeError(
        f"{field_name} entries must be objects, got {type(item).__name__}")


def _coerce_list(value, field_name: str) -> list:
    """Return a list, parsing it if the transport stringified the whole array."""
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, (bytes, bytearray)):
        value = value.decode("utf-8", "replace")
    if isinstance(value, str):
        import json as _json
        try:
            parsed = _json.loads(value)
        except ValueError:
            return []
        if isinstance(parsed, list):
            return parsed
        if isinstance(parsed, dict):
            return [parsed]
    return []


def _resolve_entity_index(entities: list, ref, field_name: str) -> int:
    """Resolve an entity reference to its index.

    Accepts an int index, or a string matching any entity's
    id, label, or canonical_id. Raises ValueError on failure.
    """
    if isinstance(ref, int):
        if 0 <= ref < len(entities):
            return ref
        raise ValueError(
            f"edge {field_name}={ref} out of range (entities 0..{len(entities)-1})")
    if isinstance(ref, str):
        for i, ent in enumerate(entities):
            if (ent.get("id") == ref or ent.get("label") == ref
                    or ent.get("canonical_id") == ref):
                return i
        raise ValueError(
            f"edge {field_name}='{ref}' does not match any entity id/label")
    raise TypeError(
        f"edge {field_name} must be int or str, got {type(ref).__name__}")


def _coerce_enum(enum_cls, value, field_name: str):
    """Coerce an int or name string to an IntEnum member."""
    if isinstance(value, str):
        key = value.upper()
        if key in enum_cls.__members__:
            return enum_cls[key]
        raise ValueError(
            f"{field_name}='{value}' not in {sorted(enum_cls.__members__)}")
    return enum_cls(value)


def _graph_from_spec(spec: dict) -> Graph:
    """Convert a JSON-serializable graph spec into a structure.Graph object.

    Accepts two equivalent formats — the canonical integer-index format
    and the documented graph model with entity ids and from/to edges:

    Canonical format:
    {
        "entities": [
            {"label": "Alice", "canonical_id": "alice_1"},   # canonical_id optional
            {"label": "Bob"}
        ],
        "edges": [
            {"source": 0, "target": 1, "relation_type": 0,
             "subtype": 0, "polarity": 1, "confidence": 0},   # subtype/polarity/confidence optional
        ],
        "facets": [          # optional
            {"facet_id": 0, "dimension_ids": [1]}
        ],
        "salience": [         # optional
            {"entity_index": 0, "source": 0, "scalar": 0.95}
        ]
    }

    Documented graph model (codec gap closure):
    {
        "entities": [
            {"id": "task-import-resolution", "type": "task",
             "label": "Implement import resolution"},
            {"id": "crate-vexl-driver", "type": "crate",
             "label": "vexl-driver"}
        ],
        "edges": [
            {"from": "task-import-resolution", "to": "crate-vexl-driver",
             "type": "PART_OF", "subtype": 3, "polarity": 1, "confidence": "LIKELY"}
        ]
    }

    Entity keys: label (required); id (becomes canonical_id);
    type/properties (stored as entity properties).
    Edge keys: source/target OR from/to (int index, or entity id/label
    string); relation_type OR type (int or name); confidence int or name.
    Salience: entity_index OR entity (int or id/label).

    RelationType names: EQUIVALENCE, IS_A, INSTANCE_OF, PART_OF, ASSOCIATIVE
    Confidence names: CERTAIN, LIKELY, PLAUSIBLE, UNKNOWN
    Polarity: 1=positive, -1=negative (may normalize during pack/unpack)
    """
    g = Graph()
    entities = [_coerce_struct(e, "entities")
                for e in _coerce_list(spec.get("entities"), "entities")]

    for ent in entities:
        label = ent["label"]
        cid = ent.get("canonical_id") or ent.get("id")
        props = dict(ent.get("properties") or {})
        if ent.get("type"):
            props.setdefault("type", ent["type"])
        g.add_entity(label, canonical_id=cid, properties=props or None)

    for edge in _coerce_list(spec.get("edges"), "edges"):
        edge = _coerce_struct(edge, "edges")
        if "source" in edge and "target" in edge:
            src_ref, tgt_ref = edge["source"], edge["target"]
        elif "from" in edge and "to" in edge:
            src_ref, tgt_ref = edge["from"], edge["to"]
        else:
            raise ValueError(
                "edge must provide source/target or from/to")
        src = _resolve_entity_index(entities, src_ref, "source/from")
        tgt = _resolve_entity_index(entities, tgt_ref, "target/to")
        rel_type = _coerce_enum(
            RelationType,
            edge.get("relation_type", edge.get("type", 0)),
            "relation_type/type")
        subtype = edge.get("subtype", 0)
        polarity = edge.get("polarity", 1)
        confidence = _coerce_enum(
            Confidence, edge.get("confidence", 0), "confidence")
        g.add_edge(src, tgt, relation_type=rel_type,
                   subtype=subtype, polarity=polarity, confidence=confidence)

    for facet in _coerce_list(spec.get("facets"), "facets"):
        facet = _coerce_struct(facet, "facets")
        g.add_facet(facet["facet_id"], facet["dimension_ids"])

    for sal in _coerce_list(spec.get("salience"), "salience"):
        sal = _coerce_struct(sal, "salience")
        if "entity_index" in sal:
            sal_idx = sal["entity_index"]
        elif "entity" in sal:
            sal_idx = _resolve_entity_index(entities, sal["entity"], "entity")
        else:
            raise ValueError("salience must provide entity_index or entity")
        sal_source = _coerce_enum(
            SalienceSource, sal["source"], "salience source")
        g.add_salience(sal_idx, sal_source, sal["scalar"])

    return g


# ── FastMCP Server ──────────────────────────────────────────────────

from mcp.server.fastmcp import FastMCP

mcp = FastMCP(
    "POINTS",
    instructions="POINTS visual-encoding glyph — encode/decode knowledge graphs as compact 8192-byte glyphs"
)

@mcp.tool()
def points_encode(graph_spec: dict, slot: str = DEFAULT_SLOT) -> str:
    """Encode a graph spec into POINTS glyph and store in session.

    Returns chr(0xE000) handle for same-process agent transport.
    The sub-agent calls points_decode(handle) to recover the graph.

    Args:
        graph_spec: Graph specification dict with entities and edges
        slot: Named slot for concurrent graphs (default: "main")
    """
    g = _graph_from_spec(graph_spec)
    return _encode_points(g, slot=slot)

@mcp.tool()
def points_encode_raw(graph_spec: dict) -> str:
    """Encode a graph spec and return raw bytes repr for cross-process transport.

    Returns a b'...' string that can be embedded in agent prompts and
    decoded by points_decode() in any process/session.

    Args:
        graph_spec: Graph specification dict with entities and edges
    """
    g = _graph_from_spec(graph_spec)
    raw = encode_graph_str(g)
    return repr(raw)

@mcp.tool()
def points_decode(handle: str, slot: str = DEFAULT_SLOT) -> dict:
    """Decode a POINTS glyph from session handle or raw bytes repr.

    Accepts:
      - chr(0xE000) — resolves from in-memory session (same-process)
      - b'...' repr string — raw bytes cross-process transport
      - base64 string — naive base64-encoded glyph bytes

    Returns dict with: header, entities, edges, facets, salience, stats
    """
    # Try base64 decode if handle doesn't look like session or bytes repr
    if not handle.startswith("b'") and not handle.startswith('b"') and handle.strip() != POINTS_CHAR:
        try:
            import base64
            raw = base64.b64decode(handle)
            return unpack(raw)
        except Exception:
            pass

    result = _decode_points(handle, slot=slot)
    if isinstance(result, dict) and "error" in result:
        return result
    # Normalize decoded output for JSON serialization
    return _serialize_decoded(result)

@mcp.tool()
def points_encode_graph_str(graph_spec: dict, slot: str = DEFAULT_SLOT) -> str:
    """Encode a graph spec and return both the session handle and base64 bytes.

    Returns a JSON string with keys:
      - handle: chr(0xE000) for same-process agent transport
      - b64: base64-encoded glyph bytes for cross-process transport
      - slots: list of active slots after encoding

    This is the recommended all-in-one encoding tool for agent workflows.
    """
    import base64
    import json as _json
    g = _graph_from_spec(graph_spec)
    handle = _encode_points(g, slot=slot)
    raw = encode_graph_str(g)
    b64 = base64.b64encode(raw).decode("ascii")
    return _json.dumps({
        "handle": handle,
        "b64": b64,
        "bytes_length": len(raw),
        "slots": _points_slots(),
    })

@mcp.tool()
def points_encode_b64(graph_spec: dict) -> str:
    """Encode a graph spec and return base64-encoded glyph bytes only.

    Simpler than points_encode_raw for cross-process transport.
    Use with points_decode() which auto-detects base64 input.
    """
    import base64
    g = _graph_from_spec(graph_spec)
    raw = encode_graph_str(g)
    return base64.b64encode(raw).decode("ascii")

@mcp.tool()
def points_decode_b64(b64_data: str) -> dict:
    """Decode base64-encoded POINTS glyph bytes.

    Explicit base64 decoder. Same as points_decode() with b64 input,
    but clearer intent.
    """
    import base64
    try:
        raw = base64.b64decode(b64_data)
        result = unpack(raw)
        return _serialize_decoded(result)
    except Exception as e:
        return {"error": f"Failed to decode base64 glyph: {e}"}

@mcp.tool()
def points_info(slot: str = DEFAULT_SLOT) -> dict:
    """Return info about current session state for a slot.

    Returns entity/edge counts, header info, and status.
    """
    return _points_info(slot=slot)

@mcp.tool()
def points_slots() -> list[str]:
    """List all active session slot names."""
    return _points_slots()

@mcp.tool()
def points_clear(slot: str = DEFAULT_SLOT) -> dict:
    """Clear session state for a slot."""
    return _points_clear(slot=slot)

@mcp.tool()
def points_clear_all() -> dict:
    """Clear all session state."""
    from suite.points_tool import points_clear_all as _clear_all
    return _clear_all()

@mcp.tool()
def points_graph_from_json(spec: dict) -> dict:
    """Convert a JSON graph spec to a decoded POINTS glyph (round-trip).

    Useful for testing: takes a spec, encodes it, decodes it, and returns
    the decoded result so you can verify the glyph was built correctly.

    Args:
        spec: Graph specification dict

    Returns dict with: header, entities, edges, facets, salience, stats
    """
    g = _graph_from_spec(spec)
    raw = encode_graph_str(g)
    result = unpack(raw)
    return _serialize_decoded(result)


def _serialize_decoded(decoded: dict) -> dict:
    """Ensure decoded dict values are JSON-serializable.

    Converts enum ints, handles edge cases.
    """
    result = {}
    for key, value in decoded.items():
        if key == "header":
            result[key] = dict(value)
        elif key == "entities":
            result[key] = [
                {k: v for k, v in e.items() if k != "raw_label"}
                for e in value
            ]
        elif key == "edges":
            result[key] = [
                {
                    "source": e["source"],
                    "target": e["target"],
                    "relation_type": int(e["relation_type"]),
                    "subtype": int(e.get("subtype", 0)),
                    "polarity": int(e.get("polarity", 1)),
                    "confidence": int(e.get("confidence", 0)),
                }
                for e in value
            ]
        elif key == "stats":
            result[key] = dict(value)
        else:
            result[key] = value
    return result

# ── CLI helpers (standalone, no FastMCP needed) ──────────────────────

import json as _json
import base64 as _b64


def _cli_encode(spec_json: str, slot: str = DEFAULT_SLOT) -> None:
    """Encode from CLI: points_mcp.py encode '{"entities":...}' [slot]"""
    spec = _json.loads(spec_json)
    g = _graph_from_spec(spec)
    handle = _encode_points(g, slot=slot)
    raw = encode_graph_str(g)
    print(_json.dumps({
        "handle": handle,
        "b64": _b64.b64encode(raw).decode("ascii"),
    }))


def _cli_decode(data: str, slot: str = DEFAULT_SLOT) -> None:
    """Decode from CLI: points_mcp.py decode '<handle|bytes|b64>' [slot]"""
    result = _decode_points(data, slot=slot)
    print(_json.dumps(_serialize_decoded(result)))


# ── Main entry ──────────────────────────────────────────────────────
if __name__ == "__main__":
    if len(sys.argv) > 1:
        cmd = sys.argv[1]
        if cmd == "encode" and len(sys.argv) > 2:
            _cli_encode(sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else DEFAULT_SLOT)
        elif cmd == "decode" and len(sys.argv) > 2:
            _cli_decode(sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else DEFAULT_SLOT)
        elif cmd == "serve":
            mcp.run(transport="stdio")
        else:
            print(f"Usage: python -m suite.points_mcp [serve|encode|decode] ...", file=sys.stderr)
            sys.exit(1)
    else:
        # Default: run MCP server (for OpenCode registration with no args)
        mcp.run(transport="stdio")
