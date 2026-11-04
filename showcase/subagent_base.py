#!/usr/bin/env python3
"""Sub-agent base: receives U+E000 handle, decodes, executes, encodes result."""

import sys
import os
import json
sys.path.insert(0, "/var/home/ryan/Documents/projects/POINTS")

from suite.points_tool import decode_points, encode_points
from suite.structure import Graph, RelationType, Confidence

class SubAgent:
    """Base class for glyph-only sub-agents."""
    
    def __init__(self, name: str):
        self.name = name
    
    def execute(self, spec: dict) -> Graph:
        """Override in subclass. Returns result Graph."""
        raise NotImplementedError
    
    def run(self, handle: str) -> str:
        """Entry point: decode handle → execute → encode result → return handle."""
        spec = decode_points(handle)
        
        if "error" in spec:
            print(f"[{self.name}] Decode error: {spec['error']}", file=sys.stderr)
            return encode_points(Graph())
        
        result_graph = self.execute(spec)
        return encode_points(result_graph)

if __name__ == "__main__":
    handle = sys.argv[1] if len(sys.argv) > 1 else "\ue000"
    # Default: echo back
    agent = SubAgent("echo")
    print(agent.run(handle))