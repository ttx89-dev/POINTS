#!/usr/bin/env python3
"""Beam-search sub-agent: decodes U+E000, explores multiple paths, encodes best result.

Beam search in simple English:
  - You're at a cave entrance. Many tunnels ahead.
  - Instead of running down EVERY tunnel, you pick the k most promising ones.
  - At each fork, you extend those k paths, score all new options, keep only the top k.
  - Repeat until you reach the goal (or dead-end everywhere).
  - Return the best path found.

Input graph (via U+E000 handle):
  - Entities labeled "start:*" and "goal:*" mark the search endpoints.
  - Entities labeled "node:*" are intermediate states.
  - Edges are transitions (ASSOCIATIVE subtype 1 = PRECEDES/leads-to).
  - Edge confidence = path quality (CERTAIN=best, UNKNOWN=risky).
  - Edge polarity (0=negated) = blocked path, do not traverse.

Output graph:
  - "path:found" entity with chain of visited nodes.
  - "path:cost" as a property.
  - "beam:width" record of the k used.
  - Chain of PRECEDES edges showing the best route.

Usage:
  python -m showcase.subagent_beam "\ue000" [beam_width]
"""

import sys

sys.path.insert(0, "/var/home/ryan/Documents/projects/POINTS")

from suite.points_tool import decode_points, encode_points
from suite.structure import Graph, RelationType, Confidence


# ── Confidence → numeric weight ────────────────────────────────────

CONFIDENCE_WEIGHT = {
    0: 1.0,   # CERTAIN
    1: 0.85,  # LIKELY
    2: 0.6,   # PLAUSIBLE
    3: 0.3,   # UNKNOWN
}


def score_edge(edge: dict) -> float:
    """Return traversal weight from an edge dict.

    Negated edges (polarity=0) return 0.0 → untraversable.
    Otherwise, weight = CONFIDENCE_WEIGHT[confidence_int].
    """
    if edge.get("polarity", 1) == 0:
        return 0.0
    conf_int = edge.get("confidence", 0)  # 0 = CERTAIN
    if not isinstance(conf_int, int) or conf_int < 0 or conf_int > 3:
        conf_int = 0
    return CONFIDENCE_WEIGHT[conf_int]


# ── Beam Search Engine ─────────────────────────────────────────────

def beam_search(
    start_id: int,
    goal_ids: set[int],
    adjacency: dict[int, list[tuple[int, float]]],
    beam_width: int = 3,
    max_depth: int = 50,
) -> list[tuple[list[int], float]]:
    """Run beam search from start_id to any goal_id.

    Args:
        start_id: Entity index to start from.
        goal_ids: Set of entity indices that are valid goals.
        adjacency: {entity_id: [(neighbor_id, weight), ...]}
        beam_width: Number of paths to keep per step (k).
        max_depth: Hard limit on path length.

    Returns:
        List of (path, score) tuples, sorted best-first.
        Path is a list of entity indices [start, ..., goal].
        Score is the product of edge weights (higher = better).
    """
    # Each beam entry: (neg_score, path_set, path_list, last_node)
    # Use negative score so heapq pops best (largest) first.
    # Actually, path score is product of weights (0..1 each).
    # We want HIGHEST product. Use -product for min-heap.
    # score_so_far = product of edge weights traversed so far (higher better)
    # We'll store (-score_so_far, length, path) for deterministic tie-breaking

    # Initialise beam with start node (no edges yet → score=1.0)
    beam: list[tuple[float, int, list[int]]] = [
        (-1.0, 0, [start_id])   # -score, length (tie-break), path
    ]
    # Track visited paths to avoid infinite loops
    # We'll allow re-visiting nodes but not in the same path

    best_complete: list[tuple[float, list[int]]] = []

    for depth in range(max_depth):
        if not beam:
            break

        candidates: list[tuple[float, int, list[int]]] = []

        for neg_score, length, path in beam:
            current = path[-1]

            # If we reached a goal, record it and don't expand further
            if current in goal_ids:
                actual_score = -neg_score
                best_complete.append((actual_score, path))
                continue

            # Expand all neighbors
            for neighbor, weight in adjacency.get(current, []):
                if weight <= 0.0:
                    continue  # blocked or negated
                # Avoid simple loops (don't revisit same node in one path)
                if neighbor in path:
                    continue

                new_path = path + [neighbor]
                new_score = -neg_score * weight  # product of weights
                candidates.append((-new_score, length + 1, new_path))

        if not candidates and not best_complete:
            break

        # Sort candidates by score (highest first), then shortest path
        candidates.sort(key=lambda x: (x[0], -x[1]))  # neg_score asc = score desc, longer paths tie-broken

        # Keep top-k candidates for next iteration
        beam = candidates[:beam_width]

    # If we found complete paths, sort best-first
    if best_complete:
        best_complete.sort(key=lambda x: (-x[0], len(x[1])))
        return best_complete

    # No complete path found — return best partial paths
    return [(path, -neg_score) for neg_score, _, path in beam[:beam_width]]


# ── Sub-Agent ──────────────────────────────────────────────────────

class BeamSubAgent:
    """Beam search sub-agent.

    Decodes a graph describing a search problem, runs beam search,
    encodes the best path found.
    """

    def __init__(self, beam_width: int = 3):
        self.beam_width = beam_width

    def run(self, incoming_handle: str) -> str:
        spec = decode_points(incoming_handle)
        if "error" in spec:
            return encode_points(Graph())

        entities = spec.get("entities", [])
        edges = spec.get("edges", [])

        # ── 1. Identify start, goals, and all nodes ──────────────
        start_id = None
        goal_ids: set[int] = set()
        node_ids: dict[int, dict] = {}  # id → entity dict

        for e in entities:
            eid = e["id"]
            label = e.get("label", "")
            node_ids[eid] = e
            if label.startswith("start:") or label.startswith("start_"):
                start_id = eid
            if label.startswith("goal:") or label.startswith("goal_") or label.startswith("target:"):
                goal_ids.add(eid)

        if start_id is None:
            # Fallback: use first entity
            start_id = entities[0]["id"] if entities else 0

        # ── 2. Build adjacency list ──────────────────────────────
        adjacency: dict[int, list[tuple[int, float]]] = {}
        for edge in edges:
            src = edge.get("source")
            tgt = edge.get("target")
            if src is None or tgt is None or isinstance(tgt, (str, float, bool)):
                continue  # literal-target edges aren't traversable
            tgt = int(tgt)
            rel = edge.get("relation_type", 4)
            weight = score_edge(edge)
            # Only traverse ASSOCIATIVE (4) or PRECEDES (subtype 1) or any edge marked as path
            if rel in (4,) or weight > 0:
                if src not in adjacency:
                    adjacency[src] = []
                adjacency[src].append((tgt, weight))

        # ── 3. Run beam search ───────────────────────────────────
        results = beam_search(
            start_id=start_id,
            goal_ids=goal_ids,
            adjacency=adjacency,
            beam_width=self.beam_width,
            max_depth=50,
        )

        # ── 4. Build result graph ────────────────────────────────
        g = Graph()

        # Record beam width used
        bw_ent = g.add_entity(
            label=f"beam:width_{self.beam_width}",
            properties_literal={"value": str(self.beam_width)},
        )

        if results:
            best_score, best_path = results[0]

            # Route as label string (encoded in label because binary format
            # doesn't store properties dicts — only edges and labels survive)
            hops = [
                node_ids.get(n, {}).get("label", f"node:{n}")
                for n in best_path
            ]
            route_str = "→".join(hops)
            if len(route_str) > 55:
                route_str = route_str[:52] + "…"

            score_str = f"score:{best_score:.4f}"
            steps_str = f"steps:{len(best_path) - 1}"

            path_ent = g.add_entity(label=f"path:found|{score_str}|{steps_str}")

            # Score and beam-width as linked entities (survive binary round-trip)
            score_ent = g.add_entity(label=score_str)
            steps_ent = g.add_entity(label=steps_str)
            g.add_edge(path_ent.id, score_ent.id, RelationType.ASSOCIATIVE, subtype=6)  # HAS_PROPERTY
            g.add_edge(path_ent.id, steps_ent.id, RelationType.ASSOCIATIVE, subtype=6)  # HAS_PROPERTY

            # Runtime route as entity chain (traversable edges)
            prev_ent = None
            for hop_label in hops:
                # Strip 'start:'/'goal:'/'node:' prefixes for clean intermediate nodes
                clean_label = hop_label.replace("start:", "hop:").replace("goal:", "hop:").replace("node:", "hop:")
                cur_ent = g.add_entity(label=clean_label)
                if prev_ent is not None:
                    g.add_edge(
                        prev_ent.id, cur_ent.id,
                        relation_type=RelationType.ASSOCIATIVE,
                        subtype=1,  # PRECEDES
                        confidence=Confidence.CERTAIN,
                    )
                prev_ent = cur_ent

            # Link beam width → path
            g.add_edge(bw_ent.id, path_ent.id, RelationType.ASSOCIATIVE, subtype=0)

            # Number of alternates found
            if len(results) > 1:
                alt_ent = g.add_entity(label=f"alternates:{len(results) - 1}")
                g.add_edge(path_ent.id, alt_ent.id, RelationType.ASSOCIATIVE, subtype=0)

        else:
            # No path found
            g.add_entity(
                label="path:none",
                properties_literal={"reason": "no_path_to_goal", "beam_width": str(self.beam_width)},
            )

        return encode_points(g)


if __name__ == "__main__":
    handle = sys.argv[1] if len(sys.argv) > 1 else "\ue000"
    bw = int(sys.argv[2]) if len(sys.argv) > 2 else 3
    agent = BeamSubAgent(beam_width=bw)
    print(agent.run(handle))
