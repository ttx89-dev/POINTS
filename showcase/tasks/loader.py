"""YAML task spec → Graph builder."""
from __future__ import annotations
import yaml
from pathlib import Path
from typing import Any
import sys
sys.path.insert(0, "/var/home/ryan/Documents/projects/POINTS")

from suite.structure import Graph, Entity, Edge, RelationType, Confidence

TASKS_DIR = Path("/var/home/ryan/Documents/projects/POINTS/showcase/tasks")

def load_task(name: str) -> dict:
    path = TASKS_DIR / f"{name}.yaml"
    if not path.exists():
        return {}
    with open(path) as f:
        return yaml.safe_load(f)

def build_graph(spec: dict) -> Graph:
    g = Graph()
    entity_map = {}
    
    # Entities
    for ent_spec in spec.get("entities", []):
        e = g.add_entity(
            label=ent_spec["label"],
            canonical_id=ent_spec.get("canonical_id"),
            properties=ent_spec.get("properties", {}),
        )
        entity_map[ent_spec["id"]] = e.id
    
    # Edges
    for edge_spec in spec.get("edges", []):
        src = entity_map[edge_spec["source"]]
        tgt = entity_map[edge_spec["target"]]
        rel = RelationType[edge_spec["relation"]]
        g.add_edge(
            src, tgt, rel,
            subtype=edge_spec.get("subtype", 0),
            confidence=Confidence[edge_spec.get("confidence", "CERTAIN")],
            polarity=edge_spec.get("polarity", 1),
            provenance=edge_spec.get("provenance", "task_spec"),
        )
    
    # Facets
    for facet_spec in spec.get("facets", []):
        ent_id = entity_map[facet_spec["entity"]]
        g.add_facet(ent_id, facet_spec["key"], facet_spec["value"])
    
    # Salience
    for sal_spec in spec.get("salience", []):
        ent_id = entity_map[sal_spec["entity"]]
        g.add_salience(ent_id, sal_spec["source"], sal_spec["weight"])
    
    return g

def all_tasks() -> list[str]:
    return [p.stem for p in TASKS_DIR.glob("*.yaml")]