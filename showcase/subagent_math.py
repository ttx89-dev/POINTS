#!/usr/bin/env python3
"""Math sub-agent: decodes U+E000, computes, encodes result."""

import sys
sys.path.insert(0, "/var/home/ryan/Documents/projects/POINTS")

from suite.points_tool import decode_points, encode_points
from suite.structure import Graph, RelationType

class MathSubAgent:
    def run(self, incoming_handle: str) -> str:
        spec = decode_points(incoming_handle)
        if "error" in spec:
            return encode_points(Graph())
        
        entities = spec.get("entities", [])
        
        # Find operation and value
        op = next((e for e in entities if "operation" in e["label"]), None)
        n_val = next((e for e in entities if e["label"].startswith("n:")), None)
        
        g = Graph()
        
        if op and "sum" in op["label"]:
            # Sum 1..n
            n = int(n_val["label"].split(":")[1]) if n_val else 10
            result = n * (n + 1) // 2
            op_e = g.add_entity(label=f"operation:sum_n={n}")
            res_e = g.add_entity(label=f"result:{result}")
            g.add_edge(op_e.id, res_e.id, RelationType.ASSOCIATIVE, subtype=5)
        
        elif op and "fib" in op["label"]:
            # Fibonacci
            n = int(n_val["label"].split(":")[1]) if n_val else 10
            a, b = 0, 1
            for _ in range(n):
                a, b = b, a + b
            op_e = g.add_entity(label=f"operation:fib_n={n}")
            res_e = g.add_entity(label=f"result:{a}")
            g.add_edge(op_e.id, res_e.id, RelationType.ASSOCIATIVE, subtype=5)
        
        else:
            g.add_entity(label="result:unknown_operation")
        
        return encode_points(g)

if __name__ == "__main__":
    handle = sys.argv[1] if len(sys.argv) > 1 else "\ue000"
    agent = MathSubAgent()
    print(agent.run(handle))