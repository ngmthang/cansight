"""
    Problem: given a set of wall centerlines (a planar graph — walls are
    edges,
    wall endpoints are vertices), find the enclosed ROOM POLYGONS.

    This is the classic "find faces of a planar straight-line graph"
    problem,
    solved with the standard technique used in computational geometry /
    GIS (same idea used to extract polygons from a planar subdivision):

      1. Build a graph where each undirected wall becomes TWO directed
         half-edges (one per direction).
      2. At each vertex, sort outgoing half-edges by angle.
      3. To trace a face: from a half-edge (u -> v), at v take the NEXT
         half-edge clockwise (or counter-clockwise, consistently) from the
         reverse edge (v -> u). Follow until you return to the start.
      4. Every half-edge belongs to exactly one face this way -> O(E log E)
         total (the log factor is the angle-sort at each vertex).
      5. The outer/unbounded face (the one traced with the "wrong" winding
         order, i.e. negative signed area) is discarded; the rest are rooms.

    This is more robust than trying to detect closed loops by search/DFS
    on the raw graph, because it works even when many walls meet at one
    junction (T-junctions, 4-way intersections) — ordinary cycle-finding
    gets ambiguous there, but half-edge traversal doesn't.

    :author: Minh Thang Nguyen
    :version: August 12, 2026
"""

from __future__ import annotations
import math
from collections import defaultdict

from geometry.wall_fitting import UnionFind

Point = tuple[float, float]
Wall = tuple[Point, Point]  # (id-free) centerline endpoints


def _round_pt(p: Point, precision: int = 4) -> Point:
    """Snap endpoints so shared corners compare equal despite
    float noise."""
    return (round(p[0], precision), round(p[1], precision))


def _snap_nearby_endpoints(
    walls: list[Wall], tol: float = 0.15
) -> list[Wall]:
    """
    Cluster wall endpoints that are merely CLOSE together (not
    exactly equal) into one shared point. This matters for walls
    that came from independently-fit planes (e.g.
    plane_detection.extract_wall_candidates() RANSAC-fitting each
    wall separately) -- two walls that physically meet at a corner
    won't land on the exact same floating-point coordinate the way
    hand-built synthetic segments do, so exact-match snapping
    (_round_pt) alone isn't enough to make the planar graph connect.

    Union-Find over all endpoints, unioning any pair within `tol`,
    then replacing every endpoint with its cluster's centroid --
    same "cluster then average" pattern as wall_fitting.py's
    cluster_wall_observations(), just applied to points instead of
    segments.

    tol defaults to 15cm, calibrated against RANSAC-derived wall
    endpoints in plane_detection.py's test suite (observed corner
    gaps up to ~9cm from independently-fit wall planes). Real
    capture-hardware noise characteristics should be re-validated
    against this default once real scan data is available (see
    docs/ROOMPLAN_SPIKE.md Section 5, item 4).
    """
    endpoints: list[Point] = []
    for a, b in walls:
        endpoints.append(a)
        endpoints.append(b)

    n = len(endpoints)
    uf = UnionFind(n)
    for i in range(n):
        for j in range(i + 1, n):
            dx = endpoints[i][0] - endpoints[j][0]
            dy = endpoints[i][1] - endpoints[j][1]
            if math.hypot(dx, dy) <= tol:
                uf.union(i, j)

    groups: dict[int, list[int]] = {}
    for i in range(n):
        root = uf.find(i)
        groups.setdefault(root, []).append(i)

    representative: dict[int, Point] = {}
    for idxs in groups.values():
        cx = sum(endpoints[i][0] for i in idxs) / len(idxs)
        cy = sum(endpoints[i][1] for i in idxs) / len(idxs)
        for i in idxs:
            representative[i] = (cx, cy)

    new_walls: list[Wall] = []
    for k in range(len(walls)):
        new_walls.append(
            (representative[2 * k], representative[2 * k + 1])
        )
    return new_walls


def _polygon_signed_area(pts: list[Point]) -> float:
    n = len(pts)
    s = sum(
        pts[i][0] * pts[(i + 1) % n][1]
        - pts[(i + 1) % n][0] * pts[i][1]
        for i in range(n)
    )
    return s / 2.0


def _split_at_t_junctions(
    walls: list[Wall], tol: float = 0.02
) -> list[Wall]:
    """
    A wall graph isn't just a set of segments meeting at endpoints -- a
    dividing wall very commonly meets another wall at a T-junction, i.e.
    its endpoint lands in the MIDDLE of the other wall, not at one of
    that wall's endpoints. The half-edge face-tracing algorithm needs a
    true planar graph (edges only touch at shared vertices), so every
    wall must first be split wherever another wall's endpoint lies on
    its interior.

    Approach: for each wall, collect every other wall's endpoint that
    lies within `tol` of this wall's line and within its extent, then
    cut the wall into sub-segments at those points (sorted by position
    along the wall).
    """

    def project_param(p: Point, a: Point, b: Point) -> float | None:
        ax, ay = a
        bx, by = b
        dx, dy = bx - ax, by - ay
        length_sq = dx * dx + dy * dy
        if length_sq < 1e-12:
            return None
        t = ((p[0] - ax) * dx + (p[1] - ay) * dy) / length_sq
        if t <= 1e-6 or t >= 1 - 1e-6:
            # at/beyond the endpoints -> not a T-junction,
            # handled by normal adjacency
            return None
        # perpendicular distance check
        proj = (ax + t * dx, ay + t * dy)
        if math.hypot(p[0] - proj[0], p[1] - proj[1]) > tol:
            return None
        return t

    all_endpoints = []
    for a, b in walls:
        all_endpoints.append(a)
        all_endpoints.append(b)

    new_walls: list[Wall] = []
    for a, b in walls:
        # map param t -> the ACTUAL neighboring endpoint (not its
        # projection),
        # so the new vertex exactly coincides with that wall's own
        # endpoint
        # coordinate -- otherwise the two "shared" points differ by the
        # perpendicular noise offset and never match after rounding.
        cuts: dict[float, Point] = {}
        for p in all_endpoints:
            if p == a or p == b:
                continue
            t = project_param(p, a, b)
            if t is not None:
                cuts[round(t, 6)] = p
        if not cuts:
            new_walls.append((a, b))
            continue

        ordered = sorted(cuts.items())
        chain_points = [a] + [pt for _, pt in ordered] + [b]
        for p0, p1 in zip(chain_points, chain_points[1:]):
            new_walls.append((p0, p1))
    return new_walls


def extract_rooms(walls: list[Wall]) -> list[list[Point]]:
    """
    Returns a list of room polygons (each a list of (x,y) points,
    counter-clockwise, closed implicitly).
    """
    walls = _snap_nearby_endpoints(walls)
    walls = _split_at_t_junctions(walls)

    # 1. snap + build adjacency: vertex -> list of neighbor vertices
    edges = [(_round_pt(a), _round_pt(b)) for a, b in walls]
    adjacency: dict[Point, list[Point]] = defaultdict(list)
    for a, b in edges:
        if a == b:
            continue
        adjacency[a].append(b)
        adjacency[b].append(a)

    # 2. at each vertex, order neighbors by angle (needed for "next
    # half-edge" step)
    def angle_from(v: Point, to: Point) -> float:
        return math.atan2(to[1] - v[1], to[0] - v[0])

    sorted_neighbors: dict[Point, list[Point]] = {}
    for v, nbrs in adjacency.items():
        sorted_neighbors[v] = sorted(
            set(nbrs), key=lambda n: angle_from(v, n)
        )

    # 3. half-edge traversal
    visited_half_edges: set[tuple[Point, Point]] = set()
    faces: list[list[Point]] = []

    def next_half_edge(u: Point, v: Point) -> Point:
        """Given we arrived at v via u->v, pick the next vertex
        w such that v->w is the next edge clockwise from v->u
        (standard face-tracing rule).
        """
        nbrs = sorted_neighbors[v]
        incoming_angle = angle_from(v, u)
        # find nbrs sorted position of u, then step to the next one
        # (wrap around)
        # this yields the tightest clockwise turn, which traces faces
        # correctly
        angles = [(angle_from(v, n), n) for n in nbrs]
        angles.sort()
        idx = next(i for i, (ang, n) in enumerate(angles) if n == u)
        return angles[(idx - 1) % len(angles)][
            1
        ]  # step counter-clockwise in angle list = clockwise turn

    for a, b in edges:
        for start_u, start_v in [(a, b), (b, a)]:
            if (start_u, start_v) in visited_half_edges:
                continue
            face: list[Point] = [start_u]
            u, v = start_u, start_v
            while True:
                visited_half_edges.add((u, v))
                face.append(v)
                w = next_half_edge(u, v)
                u, v = v, w
                if (u, v) == (start_u, start_v):
                    break
                if len(face) > 4 * len(edges) + 10:
                    # safety valve against malformed input
                    # (dangling walls etc.)
                    break
            faces.append(face[:-1])  # drop repeated closing vertex

    # 4. keep only faces with positive signed area (CCW, bounded) —
    #    the outer boundary traces CW (negative area) and is discarded
    rooms = []
    for f in faces:
        if len(f) < 3:
            continue
        area = _polygon_signed_area(f)
        if area > 1e-6:  # positive = CCW = bounded interior face
            rooms.append(f)

    return rooms


def room_area(polygon: list[Point]) -> float:
    return abs(_polygon_signed_area(polygon))