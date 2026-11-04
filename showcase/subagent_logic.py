#!/usr/bin/env python3
"""Logic sub-agent: decodes U+E000, reasons, encodes result."""

import sys
sys.path.insert(0, "/var/home/ryan/Documents/projects/POINTS")

from suite.points_tool import decode_points, encode_points
from suite.structure import Graph, Entity, RelationType

class LogicSubAgent:
    def run(self, incoming_handle: str) -> str:
        spec = decode_points(incoming_handle)
        if "error" in spec:
            return encode_points(Graph())
        
        # Extract entities
        entities = spec.get("entities", [])
        premise = next((e for e in entities if "premise" in e["label"]), None)
        query = next((e for e in entities if "query" in e["label"]), None)
        counterexample = next((e for e in entities if "counterexample" in e["label"]), None)
        
        g = Graph()
        
        # Build result graph
        if counterexample:
            ce = g.add_entity(label=counterexample["label"])
            # Counterexample contradicts premise
            if premise:
                p = g.add_entity(label=premise["label"])
                g.add_edge(ce.id, p.id, RelationType.ASSOCIATIVE, subtype=2)  # antonym
        
        # Conclusion entity
        conclusion = g.add_entity(label="conclusion:premise_false_due_to_counterexample")
        if counterexample:
            ce = g.add_entity(label=counterexample["label"])
            g.add_edge(ce.id, conclusion.id, RelationType.ASSOCIATIVE, subtype=5)
        
        return encode_points(g)

if __name__ == "__main__":
    handle = sys.argv[1] if len(sys.argv) > 1 else "\ue000"
    agent = LogicSubAgent()
    print(agent.run(handle))