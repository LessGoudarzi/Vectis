"""Power-plant network tracing: given a plant, find its nearest point in
the inferred transmission grid graph (see power/build_grid_topology.py)
and walk outward from there, shortest-path-first, so the frontend can
reveal the result as a gradual wave rather than dumping it all at once.

The graph itself (node adjacency, precomputed from_node_id/to_node_id on
each line) is expensive to build (~4-5 min endpoint self-join) and lives
in power/build_grid_topology.py, run manually against transmission.db -
this module only does the cheap part: load the precomputed graph once at
startup, then trace on demand.

Default trace scope stops at the plant's home NERC subregion (if that
data was available when the topology was built) rather than an arbitrary
distance - this is the electrically meaningful boundary "last
interconnection" is actually asking about, not a number picked to keep
the response size manageable. A numeric max_miles cap still applies
underneath that, since a single subregion can itself be large.

Known caveat, found while validating this against the real data: line
endpoints occasionally cluster across a true synchronous-interconnection
boundary (Eastern/Western/ERCOT) without a real electrical tie there -
161 lines in the current dataset directly connect nodes in different
interconnections, far more than the handful of real DC ties that
actually exist. The subregion-bounded default can still show one of
these as a single boundary-touching line (matching "trace up to the
boundary" for every subregion edge, not just legitimate ones), but never
traverses past it into the neighboring interconnection - that still
requires allow_cross_subregion=True.
"""

import logging
import math
import sqlite3
from dataclasses import dataclass, field
from heapq import heappop, heappush
from pathlib import Path
from typing import Optional

logger = logging.getLogger("uvicorn")

DEFAULT_MAX_MILES = 250.0
ANCHOR_SEARCH_MILES = 2.0


@dataclass
class GridGraph:
    # node_id -> [(line_id, other_node_id, length_miles), ...]
    adjacency: dict[int, list[tuple[int, int, float]]] = field(default_factory=dict)
    node_coord: dict[int, tuple[float, float]] = field(default_factory=dict)  # node_id -> (lon, lat)
    node_subregion: dict[int, Optional[str]] = field(default_factory=dict)

    @property
    def available(self) -> bool:
        return bool(self.adjacency)


def _haversine_miles(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
    """Same formula as ingest_power_grid.py's line-length calculation,
    duplicated rather than imported - matches this codebase's existing
    convention for small geo helpers (see _mercator_to_lonlat, copied
    independently in power/app.py, backend/ingest_power_grid.py, and
    power/build_grid_topology.py)."""
    r_miles = 3958.7613
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 2 * r_miles * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def load_grid_graph(sqlite_db_path: Path, line_length_miles: dict[int, float]) -> GridGraph:
    """Read the topology power/build_grid_topology.py precomputed. Returns
    an empty (unavailable) graph, rather than raising, if that script
    hasn't been run yet against this database - the API endpoint using
    this reports "not available" instead of the process failing to start.

    line_length_miles comes from the caller's already-loaded DuckDB
    power_grid table (ingest_power_grid.py computes it from geometry at
    load time) rather than SQLite - transmission_lines itself has no
    length_miles column, only from_node_id/to_node_id.
    """
    graph = GridGraph()
    if not sqlite_db_path.exists():
        logger.warning(f"No SQLite source at {sqlite_db_path}; network tracing unavailable.")
        return graph

    conn = sqlite3.connect(str(sqlite_db_path))
    conn.row_factory = sqlite3.Row
    try:
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(transmission_lines)")}
        if "from_node_id" not in columns or "to_node_id" not in columns:
            logger.warning(
                "transmission_lines has no from_node_id/to_node_id — "
                "run power/build_grid_topology.py to enable network tracing."
            )
            return graph

        for row in conn.execute(
            "SELECT id, from_node_id, to_node_id FROM transmission_lines "
            "WHERE from_node_id IS NOT NULL AND to_node_id IS NOT NULL"
        ):
            miles = line_length_miles.get(row["id"], 0.0)
            graph.adjacency.setdefault(row["from_node_id"], []).append((row["id"], row["to_node_id"], miles))
            graph.adjacency.setdefault(row["to_node_id"], []).append((row["id"], row["from_node_id"], miles))

        for row in conn.execute("SELECT node_id, lat, lon, subregion_name FROM grid_nodes"):
            graph.node_coord[row["node_id"]] = (row["lon"], row["lat"])
            graph.node_subregion[row["node_id"]] = row["subregion_name"]
    finally:
        conn.close()

    logger.info(f"Loaded grid graph: {len(graph.node_coord)} nodes, {sum(len(v) for v in graph.adjacency.values()) // 2} edges")
    return graph


def find_anchor_node(graph: GridGraph, plant_lon: float, plant_lat: float, max_miles: float = ANCHOR_SEARCH_MILES) -> Optional[int]:
    """Nearest graph node to a plant's coordinates, within max_miles.
    Linear scan over ~70K nodes — a few tens of milliseconds, run once
    per trace request, not worth indexing for this volume."""
    best_node, best_dist = None, max_miles
    for node_id, (lon, lat) in graph.node_coord.items():
        dist = _haversine_miles(plant_lon, plant_lat, lon, lat)
        if dist <= best_dist:
            best_node, best_dist = node_id, dist
    return best_node


def trace_from_node(
    graph: GridGraph,
    start_node: int,
    max_miles: float = DEFAULT_MAX_MILES,
    allow_cross_subregion: bool = False,
) -> dict:
    """Dijkstra outward from start_node. Returns every reachable line with
    its shortest cumulative distance from the origin and hop count, plus
    why the trace stopped where it did.

    When subregion-bounded, lines that cross out of the home subregion are
    still included (the trace reaches the boundary, not one hop short of
    it) but traversal doesn't continue past them into the next subregion.
    """
    home_subregion = graph.node_subregion.get(start_node)
    subregion_bounded = home_subregion is not None and not allow_cross_subregion

    best_dist: dict[int, float] = {start_node: 0.0}
    visited_lines: dict[int, tuple[float, int]] = {}  # line_id -> (distance_from_origin, hop_count)
    hop_count: dict[int, int] = {start_node: 0}
    heap = [(0.0, start_node)]
    hit_max_miles = False
    hit_subregion_boundary = False

    while heap:
        dist, node = heappop(heap)
        if dist > best_dist.get(node, math.inf):
            continue
        for line_id, neighbor, length_miles in graph.adjacency.get(node, []):
            new_dist = dist + length_miles
            if new_dist > max_miles:
                hit_max_miles = True
                continue
            neighbor_subregion = graph.node_subregion.get(neighbor)
            crosses_boundary = (
                subregion_bounded and neighbor_subregion is not None and neighbor_subregion != home_subregion
            )
            # A line whose far end crosses into another subregion still
            # gets included — it's the line that visibly reaches the drawn
            # boundary — but traversal doesn't continue past it into the
            # neighboring subregion. Without this, the trace stopped one
            # hop short of the boundary it's supposedly bounded by.
            if line_id not in visited_lines or new_dist < visited_lines[line_id][0]:
                visited_lines[line_id] = (new_dist, hop_count.get(node, 0) + 1)
            if crosses_boundary:
                hit_subregion_boundary = True
                continue
            if new_dist < best_dist.get(neighbor, math.inf):
                best_dist[neighbor] = new_dist
                hop_count[neighbor] = hop_count.get(node, 0) + 1
                heappush(heap, (new_dist, neighbor))

    if hit_subregion_boundary:
        stopped_reason = "subregion_boundary"
    elif hit_max_miles:
        stopped_reason = "max_miles"
    else:
        stopped_reason = "component_exhausted"

    return {
        "status": "ok",
        "home_subregion": home_subregion,
        "stopped_reason": stopped_reason,
        "lines": [
            {"line_id": line_id, "distance_from_origin_miles": round(dist, 2), "hop_count": hops}
            for line_id, (dist, hops) in visited_lines.items()
        ],
    }
