#!/usr/bin/env python3
"""beam_search.py — parallel multi-path graph exploration.

BEAM SEARCH IN SIMPLE ENGLISH
─────────────────────────────

Imagine you're in a cave system. There are tunnels everywhere,
and somewhere is a treasure. But every tunnel costs energy.

Option A: Run down ONE tunnel at a time, go as deep as you can,
hit a dead end, come back, try another. That's depth-first search.
Slow, and you might pick the wrong tunnel first.

Option B: Keep a map. At every intersection, pick the k most
promising tunnels and explore ALL of them in parallel. At the
next intersection, again pick the k best. Keep going.

That's beam search. The "k" is the BEAM WIDTH.

  k=1  → greedy. Fast, but you'll miss the treasure if you
         make one wrong turn. (Hill-climbing / greedy search.)

  k=∞  → optimal. You explore everything. Guaranteed to find
         the best path. But you might as well be lost forever
         in a big graph. (Dijkstra / exhaustive.)

  k=3  → pragmatic. You keep 3 irons in the fire. You'll
         probably find the treasure. You'll probably find
         a good path. Not guaranteed optimal, but fast
         enough to be useful.

SCORING
───────

Every edge in the graph has a CONFIDENCE weight:

  0 (CERTAIN)    → 1.0    — guaranteed, take it
  1 (LIKELY)     → 0.85   — probably good
  2 (PLAUSIBLE)  → 0.6    — might work
  3 (UNKNOWN)    → 0.3    — risky

  Polarity = 0 (negated) → 0.0 — blocked, do not enter

A PATH's score = product of all edge weights along it.

Higher score = better path. Simple.

USAGE
─────

Two ways to use this:

1. From Python (preferred):

    from beam_search import beam_search

    graph = {
        0: [(1, 1.0)],      # 0 → 1 (weight 1.0)
        1: [(2, 0.85),       # 1 → 2 (weight 0.85)
            (3, 0.6)],       # 1 → 3 (weight 0.6)
        3: [(2, 1.0)],       # 3 → 2 (weight 1.0)
    }
    results = beam_search(
        start=0,
        goals={2},
        adjacency=graph,
        beam_width=2,
    )
    # Returns [(score, [0, 1, 2]), (score, [0, 1, 3, 2])]
    # sorted best-first

2. From command line:

    python3 beam_search.py
    # Runs the demo above and prints results.

WHAT THE SUB-AGENT DOES
───────────────────────

The sub-agent in this file:

  1. Receives a graph (as a dict — nodes, edges).
  2. Identifies start nodes (label starts with "start:" or "start_").
  3. Identifies goal nodes (label starts with "goal:", "goal_", or "target:").
  4. Builds an adjacency list from edges (skipping negated ones).
  5. Runs beam search to find the best path(s).
  6. Returns the best path, its score, step count, and any alternates.

The sub-agent is POINTS-INDEPENDENT — it works with plain dicts.
"""

import sys


# ── Scoring ──────────────────────────────────────────────────────────

CONFIDENCE_WEIGHT = {
    0: 1.0,   # CERTAIN
    1: 0.85,  # LIKELY
    2: 0.6,   # PLAUSIBLE
    3: 0.3,   # UNKNOWN
}


def score_edge(edge: dict) -> float:
    """Weight of a single edge dict.

    Negated edges (polarity=0) → untraversable (0.0).
    Otherwise → CONFIDENCE_WEIGHT[confidence_int].
    """
    if edge.get("polarity", 1) == 0:
        return 0.0
    ci = edge.get("confidence", 0)  # 0 = CERTAIN
    if not isinstance(ci, int) or ci < 0 or ci > 3:
        ci = 0
    return CONFIDENCE_WEIGHT[ci]


# ── Beam Search Engine ───────────────────────────────────────────────

def beam_search(
    start: int,
    goals: set[int],
    adjacency: dict[int, list[tuple[int, float]]],
    beam_width: int = 3,
    max_depth: int = 50,
) -> list[tuple[float, list[int]]]:
    """Run beam search from start to any goal.

    Parameters
    ----------
    start:
        Node ID to start from.
    goals:
        Set of node IDs that count as success.
    adjacency:
        Graph as {node_id: [(neighbor_id, weight), ...]}.
        Weight should be 0.0–1.0 (higher = better).
    beam_width:
        Number of paths kept per step.
    max_depth:
        Safety limit on path length.

    Returns
    -------
    List of (score, [node_id, ...]) sorted best-first.
    Each path starts at `start` and ends at a goal node
    (or ends at whatever node if no goal was reachable).
    """
    # Beam entries: (neg_score, length, path)
    # neg_score so heapq-style min-sort puts best (largest score) first.
    # length is tie-breaker (shorter paths win on equal score).
    beam: list[tuple[float, int, list[int]]] = [
        (-1.0, 0, [start])
    ]

    complete: list[tuple[float, list[int]]] = []

    for _depth in range(max_depth):
        if not beam:
            break

        candidates: list[tuple[float, int, list[int]]] = []

        for neg_score, length, path in beam:
            current = path[-1]

            # Reached a goal? Record, don't expand.
            if current in goals:
                complete.append((-neg_score, path))
                continue

            # Expand all traversable neighbours
            for neighbour, weight in adjacency.get(current, []):
                if weight <= 0.0:
                    continue          # blocked
                if neighbour in path:
                    continue          # no loops

                new_path = path + [neighbour]
                candidates.append((
                    -(-neg_score * weight),  # negated product
                    length + 1,
                    new_path,
                ))

        if not candidates and not complete:
            break

        # Sort: highest score first (neg_score asc), then shortest path
        candidates.sort(key=lambda x: (x[0], -x[1]))
        beam = candidates[:beam_width]

    if complete:
        complete.sort(key=lambda x: (-x[0], len(x[1])))
        return complete

    # No goal reached — return best partial paths
    return [(-ns, p) for ns, _ln, p in beam[:beam_width]]


# ── Graph-Aware Sub-Agent ────────────────────────────────────────────

def build_adjacency(
    entities: list[dict],
    edges: list[dict],
) -> tuple[int | None, set[int], dict[int, list[tuple[int, float]]]]:
    """Build search graph from POINTS-style entity/edge dicts.

    Returns (start_id, goal_ids, adjacency).
    """
    start_id: int | None = None
    goal_ids: set[int] = set()

    for e in entities:
        eid = e.get("id")
        label = e.get("label", "")
        if label.startswith("start:") or label.startswith("start_"):
            start_id = eid
        if label.startswith("goal:") or label.startswith("goal_") or label.startswith("target:"):
            goal_ids.add(eid)

    if start_id is None and entities:
        start_id = entities[0].get("id", 0)

    adj: dict[int, list[tuple[int, float]]] = {}
    for edge in edges:
        src = edge.get("source")
        tgt = edge.get("target")
        if src is None or tgt is None or not isinstance(tgt, int):
            continue
        weight = score_edge(edge)
        if weight > 0:
            adj.setdefault(src, []).append((tgt, weight))

    return start_id, goal_ids, adj


def run_sub_agent(
    entities: list[dict],
    edges: list[dict],
    beam_width: int = 3,
) -> dict:
    """Run beam search on a POINTS-style graph, return result as a dict.

    Returns
    -------
    {
        "found": True/False,
        "best_path": [entity_labels...],
        "score": float,
        "steps": int,
        "alternates": int,
        "beam_width": int,
    }
    """
    start_id, goal_ids, adjacency = build_adjacency(entities, edges)

    if start_id is None or not adjacency:
        return {"found": False, "reason": "no_traversable_graph"}

    if not goal_ids:
        return {"found": False, "reason": "no_goal_defined"}

    results = beam_search(
        start=start_id,
        goals=goal_ids,
        adjacency=adjacency,
        beam_width=beam_width,
    )

    if not results:
        return {"found": False, "reason": "no_path_to_goal"}

    score, path = results[0]

    # Map node IDs back to labels
    label_map: dict[int, str] = {e["id"]: e.get("label", f"node:{e['id']}")
                                  for e in entities}

    path_labels = [label_map.get(n, f"node:{n}") for n in path]

    return {
        "found": True,
        "best_path": path_labels,
        "score": score,
        "steps": len(path) - 1,
        "alternates": len(results) - 1,
        "beam_width": beam_width,
    }


# ── Demo / CLI ───────────────────────────────────────────────────────

def demo() -> None:
    """Run a self-contained demo of beam search."""
    print("=" * 60)
    print("BEAM SEARCH DEMO")
    print("=" * 60)

    graph = {
        # Path A: 0→1→4 (CERTAIN × CERTAIN = 1.0)  ← best
        # Path B: 0→2→3→4 (LIKELY × PLAUSIBLE × CERTAIN = 0.51)
        # Blocked: 0→4 direct (negated)
        0: [(1, 1.0), (2, 0.85), (4, 0.0)],  # direct is blocked
        1: [(4, 1.0)],
        2: [(3, 0.6)],
        3: [(4, 1.0)],
    }

    entities = [
        {"id": 0, "label": "start:entrance"},
        {"id": 1, "label": "node:shortcut"},
        {"id": 2, "label": "node:detour"},
        {"id": 3, "label": "node:long_way"},
        {"id": 4, "label": "goal:treasure"},
    ]

    edges = [
        {"source": 0, "target": 1, "confidence": 0, "polarity": 1},
        {"source": 1, "target": 4, "confidence": 0, "polarity": 1},
        {"source": 0, "target": 2, "confidence": 1, "polarity": 1},
        {"source": 2, "target": 3, "confidence": 2, "polarity": 1},
        {"source": 3, "target": 4, "confidence": 0, "polarity": 1},
        {"source": 0, "target": 4, "confidence": 0, "polarity": 0},  # negated!
    ]

    result = run_sub_agent(entities, edges, beam_width=3)

    print(f"\nGraph nodes: entrance, shortcut, detour, long_way, treasure")
    print(f"Edges:")
    print(f"  entrance  →  shortcut    (CERTAIN,  1.0)")
    print(f"  shortcut  →  treasure    (CERTAIN,  1.0)")
    print(f"  entrance  →  detour      (LIKELY,   0.85)")
    print(f"  detour    →  long_way    (PLAUSIBLE, 0.6)")
    print(f"  long_way  →  treasure    (CERTAIN,  1.0)")
    print(f"  entrance  →  treasure    (NEGATED — blocked)")
    print(f"\nBeam width: {result['beam_width']}")

    if result["found"]:
        route = " → ".join(
            lbl.split(":", 1)[1] if ":" in lbl else lbl
            for lbl in result["best_path"]
        )
        print(f"\nBest path: {route}")
        print(f"Score:     {result['score']:.4f}")
        print(f"Steps:     {result['steps']}")
        print(f"Alternate paths found: {result['alternates']}")
        print(f"(Path B score: 0.85 × 0.6 × 1.0 = 0.51 — found, but worse)")
    else:
        print(f"FAILED: {result.get('reason', 'unknown')}")

    print("=" * 60)


if __name__ == "__main__":
    demo()
