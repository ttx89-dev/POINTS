"""POINTS delegation protocol — task/result transport via entity-label convention.

Uses entity labels as the sole data carrier, sidestepping three known
codec gaps (B1: list-of-dict entities, B2: properties_literal dropped,
B3: literal edge targets unresolved). Labels always survive round-trip.

Convention:
  __param:<key>=<value>   — parameter / configuration
  __task:<key>=<value>    — task instruction or payload
  __result:<key>=<value>  — result returned by sub-agent
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from suite.structure import Graph, Edge, RelationType, Confidence
from suite.glyph import pack, unpack


# ── Data types ──────────────────────────────────────────────────────

@dataclass
class DelegatedTask:
    """A task ready for transport via POINTS glyph."""
    instructions: str = ""
    params: dict[str, str] = field(default_factory=dict)


@dataclass
class DelegatedResult:
    """A result extracted from a POINTS glyph."""
    values: dict[str, str] = field(default_factory=dict)
    raw_entities: list[dict] = field(default_factory=list)
    raw_edges: list[dict] = field(default_factory=list)
    glyph_bytes: bytes | None = None


# ── Constants ───────────────────────────────────────────────────────

PARAM_PREFIX  = "__param:"
TASK_PREFIX   = "__task:"
RESULT_PREFIX = "__result:"
PREFIXES      = (PARAM_PREFIX, TASK_PREFIX, RESULT_PREFIX)

# The canonical name for the main instruction entity
TASK_INSTRUCTION_KEY = "instructions"


# ── Encoding helpers ────────────────────────────────────────────────

def _make_kv_label(prefix: str, key: str, value: str) -> str:
    """Build a label like ``__param:model=gpt4``."""
    return f"{prefix}{key}={value}"


def _parse_kv_label(label: str) -> tuple[str, str, str] | None:
    """Parse a label into (prefix, key, value).

    Returns None if the label does not match the convention.
    """
    for p in PREFIXES:
        if label.startswith(p):
            rest = label[len(p):]
            if "=" in rest:
                eq = rest.index("=")
                key = rest[:eq]
                val = rest[eq + 1:]
                return p, key, val
    return None


# ── Graph construction ──────────────────────────────────────────────

def encode_task_graph(task: DelegatedTask) -> Graph:
    """Build a Graph from a DelegatedTask using label conventions.

    Creates one entity per key-value pair. The ``instructions`` field
    becomes the main entity with label ``__task:instructions=<text>``.
    Parameter entities use ``__param:<key>=<value>``.
    """
    g = Graph()

    # Main instruction entity
    if task.instructions:
        g.add_entity(
            _make_kv_label(TASK_PREFIX, TASK_INSTRUCTION_KEY, task.instructions)
        )

    # Parameter entities
    for k, v in task.params.items():
        g.add_entity(_make_kv_label(PARAM_PREFIX, k, v))

    return g


def encode_result_graph(result: DelegatedResult) -> Graph:
    """Build a Graph from a DelegatedResult using label conventions.

    Each value in ``result.values`` becomes ``__result:<key>=<value>``.
    """
    g = Graph()
    for k, v in result.values.items():
        g.add_entity(_make_kv_label(RESULT_PREFIX, k, v))
    return g


# ── Graph decoding ──────────────────────────────────────────────────

def decode_graph_entities(
    entities: list[dict],
) -> tuple[dict[str, str], dict[str, str], dict[str, str]]:
    """Partition decoded entities by prefix.

    Returns (params, tasks, results) — three dicts of key→value.
    """
    params: dict[str, str] = {}
    tasks: dict[str, str] = {}
    results: dict[str, str] = {}

    for ent in entities:
        label = ent.get("label", "")
        parsed = _parse_kv_label(label)
        if parsed is None:
            continue
        prefix, key, value = parsed
        if prefix == PARAM_PREFIX:
            params[key] = value
        elif prefix == TASK_PREFIX:
            tasks[key] = value
        elif prefix == RESULT_PREFIX:
            results[key] = value

    return params, tasks, results


def extract_task_from_graph(graph: Graph) -> DelegatedTask:
    """Extract a DelegatedTask from an in-memory Graph."""
    task = DelegatedTask()
    for ent in graph.entities:
        parsed = _parse_kv_label(ent.label)
        if parsed is None:
            continue
        prefix, key, value = parsed
        if prefix == TASK_PREFIX:
            if key == TASK_INSTRUCTION_KEY:
                task.instructions = value
        elif prefix == PARAM_PREFIX:
            task.params[key] = value
    return task


def extract_result_from_entities(
    entities: list[dict],
) -> DelegatedResult:
    """Extract a DelegatedResult from decoded entity list."""
    _, _, results = decode_graph_entities(entities)
    return DelegatedResult(values=results)


# ── High-level round-trip protocol ──────────────────────────────────

def pack_task(task: DelegatedTask, **pack_kwargs: Any) -> bytes:
    """Pack a DelegatedTask into POINTS glyph bytes."""
    g = encode_task_graph(task)
    return pack(g, **pack_kwargs)


def unpack_task(glyph: bytes) -> DelegatedTask:
    """Unpack POINTS glyph bytes into a DelegatedTask."""
    decoded = unpack(glyph)
    return extract_result_from_entities(decoded["entities"])


def pack_result(result: DelegatedResult, **pack_kwargs: Any) -> bytes:
    """Pack a DelegatedResult into POINTS glyph bytes."""
    g = encode_result_graph(result)
    return pack(g, **pack_kwargs)


def unpack_result(glyph: bytes) -> DelegatedResult:
    """Unpack POINTS glyph bytes into a DelegatedResult."""
    decoded = unpack(glyph)
    return extract_result_from_entities(decoded["entities"])


# ── Summarise a glyph for agent transport (token-efficient) ─────────

def glyph_summary(glyph: bytes) -> dict:
    """Return a compact summary of what's in a glyph.

    Includes: header fields, entity count, param/task/result keys,
    edge count, parity info.
    """
    decoded = unpack(glyph)
    params, tasks, results = decode_graph_entities(decoded["entities"])

    entity_labels = [
        e.get("label", "?") for e in decoded["entities"]
    ]

    return {
        "entity_count": len(decoded["entities"]),
        "edge_count": len(decoded.get("edges", [])),
        "byte_size": len(glyph),
        "params": params,
        "tasks": tasks,
        "results": results,
        "entity_labels": entity_labels,
        "parity_algo": decoded.get("header", {}).get("parity_algo"),
        "parity_ok": decoded.get("header", {}).get("parity_ok"),
        "errors_corrected": decoded.get("header", {}).get("errors_corrected", 0),
    }
