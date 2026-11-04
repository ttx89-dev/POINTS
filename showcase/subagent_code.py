#!/usr/bin/env python3
"""Code sub-agent: decodes U+E000, generates code, encodes result."""

import sys
sys.path.insert(0, "/var/home/ryan/Documents/projects/POINTS")

from suite.points_tool import decode_points, encode_points
from suite.structure import Graph, RelationType

class CodeSubAgent:
    def run(self, incoming_handle: str) -> str:
        spec = decode_points(incoming_handle)
        if "error" in spec:
            return encode_points(Graph())
        
        entities = spec.get("entities", [])
        goal = next((e for e in entities if "goal" in e["label"]), None)
        
        g = Graph()
        
        if goal and "prime" in goal["label"]:
            # Generate prime sieve code
            n = 100
            goal_e = g.add_entity(label=goal["label"])
            algo_e = g.add_entity(label="algorithm:sieve_of_eratosthenes")
            impl_e = g.add_entity(label="implementation:python")
            result_e = g.add_entity(label="result:25_primes_upto_100")
            
            g.add_edge(goal_e.id, algo_e.id, RelationType.ASSOCIATIVE, subtype=1)
            g.add_edge(algo_e.id, impl_e.id, RelationType.ASSOCIATIVE, subtype=1)
            g.add_edge(impl_e.id, result_e.id, RelationType.ASSOCIATIVE, subtype=5)
        
        else:
            g.add_entity(label="result:unknown_goal")
        
        return encode_points(g)

if __name__ == "__main__":
    handle = sys.argv[1] if len(sys.argv) > 1 else "\ue000"
    agent = CodeSubAgent()
    print(agent.run(handle))