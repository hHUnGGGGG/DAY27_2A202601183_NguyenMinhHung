"""Dataset & Column Level Lineage Graph Engine.

Provides:
- Transitive downstream asset traversal using BFS
- Transitive column-level lineage tracking
- dbt manifest parser with dependency extraction
- OpenLineage-compatible facet/event generator
"""
from __future__ import annotations

import json
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def load_graph(path: str | Path) -> dict[str, list[str]]:
    with open(path, "r", encoding="utf-8") as f:
        payload = json.load(f)
    return payload.get("dataset_lineage", payload)


def load_full_lineage(path: str | Path) -> dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def get_downstream_assets(graph: dict[str, list[str]], start: str) -> list[str]:
    """Return transitive downstream assets in BFS order, excluding start node."""
    seen = {start}
    q: deque[str] = deque([start])
    out: list[str] = []
    while q:
        node = q.popleft()
        for child in graph.get(node, []):
            if child not in seen:
                seen.add(child)
                out.append(child)
                q.append(child)
    return out


def get_column_downstream(
    column_graph: dict[str, list[str]], start_column: str
) -> list[str]:
    """Return transitive downstream columns in BFS order, excluding start column."""
    seen = {start_column}
    q: deque[str] = deque([start_column])
    out: list[str] = []
    while q:
        node = q.popleft()
        for child in column_graph.get(node, []):
            if child not in seen:
                seen.add(child)
                out.append(child)
                q.append(child)
    return out


def extract_dbt_dataset_graph(manifest_path: str | Path) -> dict[str, list[str]]:
    """Parse dbt manifest.json to extract node-to-children dependency graph."""
    path = Path(manifest_path)
    if not path.exists():
        return {}
    with open(path, "r", encoding="utf-8") as f:
        manifest = json.load(f)
    graph: dict[str, list[str]] = {}
    child_map = manifest.get("child_map", {})
    for parent, children in child_map.items():
        graph[parent] = list(children)
    return graph


def create_openlineage_event(
    job_name: str,
    inputs: list[str],
    outputs: list[str],
    event_type: str = "COMPLETE",
    namespace: str = "data_reliability_lab",
) -> dict[str, Any]:
    """Generate OpenLineage 1.0 standard run event."""
    now_iso = datetime.now(timezone.utc).isoformat()
    return {
        "eventType": event_type,
        "eventTime": now_iso,
        "job": {
            "namespace": namespace,
            "name": job_name,
        },
        "inputs": [{"namespace": namespace, "name": inp} for inp in inputs],
        "outputs": [{"namespace": namespace, "name": out} for out in outputs],
        "producer": "https://github.com/vlearn/data-reliability-lab",
    }
