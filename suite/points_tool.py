"""Session-state and transport tools for POINTS encoding.

encode_points(graph)   → chr(0xE000) — stores state, returns handle
decode_points(data)    → dict — resolves from session handle or raw bytes
encode_graph_str(graph) → bytes — raw 8192-byte glyph for cross-session transport

The session-state approach (chr(0xE000)) lets agents pass a single
Unicode codepoint as a handle without filling context with glyph bytes.

Enhanced with:
- In-memory session state (no file I/O)
- Named slots for multiple concurrent graphs
- Direct context passing for agent↔agent loops
"""

from __future__ import annotations
import json
import os
import threading
from typing import Optional
from .glyph import pack, unpack

# ── Session state: in-memory + file fallback ───────────────────────────
SESSION_FILE = os.path.join(os.path.dirname(__file__), ".points_session")
POINTS_CHAR = chr(0xE000)  # Private Use Area — session key handle

# In-memory session store: {slot_name: glyph_bytes}
# Thread-safe for concurrent agent use
_session_store: dict[str, bytes] = {}
_session_lock = threading.Lock()

# Default slot name
DEFAULT_SLOT = "main"


def encode_points(graph, slot: str = DEFAULT_SLOT) -> str:
    """Store a Graph in session state, return chr(0xE000) handle.

    Args:
        graph: Graph object to encode
        slot: Named slot for multiple concurrent graphs (default: "main")

    Returns:
        chr(0xE000) — single Unicode handle for agent transport
    """
    raw = pack(graph)
    with _session_lock:
        _session_store[slot] = raw
    # Also persist to file for cross-process compatibility
    try:
        with open(SESSION_FILE, "wb") as f:
            f.write(raw)
    except OSError:
        pass
    return POINTS_CHAR


def encode_points_multi(graphs: dict[str, any]) -> str:
    """Store multiple graphs in named slots at once.

    Args:
        graphs: {slot_name: Graph} mapping

    Returns:
        chr(0xE000) — handle for the batch
    """
    with _session_lock:
        for slot, graph in graphs.items():
            _session_store[slot] = pack(graph)
    return POINTS_CHAR


def encode_graph_str(graph) -> bytes:
    """Pack a Graph into raw 8192 bytes (for cross-session / file transport)."""
    return pack(graph)


def decode_points(data: str | bytes, slot: str = DEFAULT_SLOT) -> dict:
    """Decode a POINTS payload from a session handle or raw bytes.

    Resolution order:
      1. If data is bytes → decode as raw glyph
      2. If data is chr(0xE000) and slot exists in memory → load from memory
      3. If data is chr(0xE000) and file exists → load from file
      4. If data is str and looks like bytes repr (b"...") → eval and decode

    Args:
        data: chr(0xE000), raw bytes, or a bytes repr string
        slot: Named slot to load from (default: "main")

    Returns:
        dict with keys: header, entities, edges, facets, salience,
                        reifications, stats
    """
    if isinstance(data, bytes):
        return unpack(data)

    stripped = data.strip()

    # Case 1: session key handle
    if stripped == POINTS_CHAR:
        payload_bytes = _load_session_bytes(slot)
        if payload_bytes is None:
            return {"error": f"No POINTS session state in slot '{slot}'. "
                             "Run encode_points() first."}
        return unpack(payload_bytes)

    # Case 2: raw bytes passed as repr (b"...")
    if stripped.startswith("b'") or stripped.startswith('b"'):
        try:
            payload_bytes = eval(stripped, {"__builtins__": {}}, {})
            if isinstance(payload_bytes, bytes):
                return unpack(payload_bytes)
        except Exception:
            pass

    return {"error": "Cannot decode: expected chr(0xE000), bytes, or b'...' repr"}


def decode_points_multi(slots: list[str] = None) -> dict[str, dict]:
    """Decode multiple slots at once.

    Args:
        slots: List of slot names (default: all in memory)

    Returns:
        {slot_name: decoded_dict}
    """
    with _session_lock:
        target_slots = slots or list(_session_store.keys())
    return {slot: decode_points(POINTS_CHAR, slot) for slot in target_slots if slot in _session_store}


def points_info(slot: str = DEFAULT_SLOT) -> dict:
    """Return info about current session state for a slot."""
    with _session_lock:
        raw = _session_store.get(slot)

    if raw is None:
        # Try file fallback
        if os.path.exists(SESSION_FILE):
            with open(SESSION_FILE, "rb") as f:
                raw = f.read()

    if raw is None:
        return {"status": "empty", "message": f"No POINTS session state in slot '{slot}'"}

    try:
        result = unpack(raw)
        return {
            "status": "loaded",
            "slot": slot,
            "bytes": len(raw),
            "entities": len(result["entities"]),
            "edges": len(result["edges"]),
            "header": result["header"],
            "stats": result["stats"],
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}


def points_info_all() -> dict:
    """Return info for all slots."""
    with _session_lock:
        slots = list(_session_store.keys())
    return {slot: points_info(slot) for slot in slots}


def points_clear(slot: str = DEFAULT_SLOT) -> dict:
    """Wipe current session state for a slot."""
    with _session_lock:
        if slot in _session_store:
            del _session_store[slot]
    # Also clear file if it's the default slot
    if slot == DEFAULT_SLOT and os.path.exists(SESSION_FILE):
        os.remove(SESSION_FILE)
    return {"status": "cleared", "message": f"POINTS session state cleared for slot '{slot}'"}


def points_clear_all() -> dict:
    """Wipe all session state."""
    with _session_lock:
        _session_store.clear()
    if os.path.exists(SESSION_FILE):
        os.remove(SESSION_FILE)
    return {"status": "cleared", "message": "All POINTS session state cleared"}


def points_slots() -> list[str]:
    """List all active slot names."""
    with _session_lock:
        return list(_session_store.keys())


def set_session_glyphs(glyphs: list[bytes], slot: str = DEFAULT_SLOT) -> str:
    """Store a multi-glyph sequence in a named slot.

    Args:
        glyphs: List of 8192-byte glyph payloads
        slot: Named slot for storage

    Returns:
        chr(0xE000) handle for agent transport
    """
    # Store as JSON-encoded list of base64 strings
    import base64
    encoded = [base64.b64encode(g).decode('ascii') for g in glyphs]
    with _session_lock:
        _session_store[f"{slot}__multi"] = json.dumps(encoded).encode('ascii')
    return POINTS_CHAR


def get_session_glyphs(slot: str = DEFAULT_SLOT) -> list[bytes]:
    """Retrieve a multi-glyph sequence from a named slot.

    Args:
        slot: Named slot to retrieve from

    Returns:
        List of 8192-byte glyph payloads
    """
    import base64
    with _session_lock:
        raw = _session_store.get(f"{slot}__multi")
    if raw is None:
        return []
    encoded = json.loads(raw.decode('ascii'))
    return [base64.b64decode(e) for e in encoded]


# ── Internal helpers ──────────────────────────────────────────────────

def _load_session_bytes(slot: str = DEFAULT_SLOT) -> bytes | None:
    """Load glyph bytes from memory, falling back to file."""
    with _session_lock:
        raw = _session_store.get(slot)
    if raw is not None:
        return raw
    # File fallback (only for default slot)
    if slot == DEFAULT_SLOT and os.path.exists(SESSION_FILE):
        with open(SESSION_FILE, "rb") as f:
            return f.read()
    return None
