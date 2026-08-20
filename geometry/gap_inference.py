"""
Gap inference: suggests probable wall completions for dangling wall
endpoints that don't connect to anything -- the automated-detection
half of the furniture-occlusion problem described in
docs/BACKLOG.md's "Furniture-aware wall detection" entry.
add_manual_wall() (review/correction_session.py) already lets a
human draw in a missing wall; this module instead SUGGESTS where
one might belong, so a human doesn't have to notice the gap and
eyeball its position from scratch.

Deliberately conservative and explicit, per this project's
established "don't silently guess" principle (see
opening_detection.py's "ambiguous" classification, the sill-height
validation in building_model/schema.py): a suggestion is never
auto-applied to a BuildingModel. It's surfaced for a human to
review and explicitly accept (by calling add_manual_wall() with the
suggested centerline) or ignore.

Honest limitation (matches docs/BACKLOG.md item 3, not solved
here): this function can't distinguish "furniture occluded this
wall" from "this gap is a real doorway to another room" -- both
look identical from geometry alone (two collinear wall fragments
with a gap between them). A human reviewing a suggestion needs to
make that call; this module's job is only to notice the gap and
propose *a* plausible completion, not to decide what it means.
"""

from __future__ import annotations
from dataclasses import dataclass
import math

Point2D = tuple[float, float]
Segment = tuple[Point2D, Point2D]


@dataclass
class GapSuggestion:
    wall_a_index: int
    wall_a_endpoint: Point2D
    wall_b_index: int
    wall_b_endpoint: Point2D
    suggested_centerline: Segment
    gap_distance: float
    collinearity_deg: float  # 0 = perfectly collinear, higher = worse


def _direction(segment: Segment) -> tuple[float, float]:
    (x0, y0), (x1, y1) = segment
    dx, dy = x1 - x0, y1 - y0
    length = math.hypot(dx, dy)
    if length < 1e-9:
        return (0.0, 0.0)
    return (dx / length, dy / length)


def _undirected_angle_deg(
    dir_a: tuple[float, float], dir_b: tuple[float, float]
) -> float:
    """Angle between two direction vectors, treating a line and its
    reverse as equivalent (a wall has no inherent 'forward') -- so
    this is always in [0, 90] degrees, unlike a signed angle."""
    dot = abs(dir_a[0] * dir_b[0] + dir_a[1] * dir_b[1])
    dot = max(-1.0, min(1.0, dot))
    return math.degrees(math.acos(dot))


def _endpoints_with_wall_index(walls: list[Segment]):
    for i, (a, b) in enumerate(walls):
        yield i, a
        yield i, b


def _is_dangling(
    wall_index: int,
    endpoint: Point2D,
    walls: list[Segment],
    connect_tol: float,
) -> bool:
    """True if this endpoint has no OTHER wall's endpoint within
    connect_tol -- i.e., ordinary endpoint snapping (the same idea
    room_extraction.py uses) wouldn't already have joined it to
    something."""
    for j, other_endpoint in _endpoints_with_wall_index(walls):
        if j == wall_index:
            continue
        dist = math.hypot(
            endpoint[0] - other_endpoint[0],
            endpoint[1] - other_endpoint[1],
        )
        if dist < connect_tol:
            return False
    return True


def suggest_gap_completions(
    walls: list[Segment],
    min_gap: float = 0.15,
    max_gap: float = 2.5,
    angle_tol_deg: float = 20.0,
) -> list[GapSuggestion]:
    """
    Finds pairs of "dangling" wall endpoints (not connected to
    anything else) that are plausibly fragments of one physical
    wall interrupted by an obstruction, and suggests a bridging
    wall for each. A pair qualifies if:
      - the gap between them is within [min_gap, max_gap] (below
        min_gap, they'd already be connected by ordinary endpoint
        snapping; above max_gap, treat it as too far to guess at --
        deliberately conservative, since a wrong suggestion is
        worse than no suggestion)
      - the gap direction and both walls' own directions are
        mutually collinear within angle_tol_deg (a real corner has
        perpendicular walls, which this correctly excludes)

    Returns suggestions sorted by collinearity (best first). Never
    modifies the input walls or produces anything auto-applied --
    purely advisory, for a human to review via the same workflow as
    add_manual_wall().
    """
    dangling: list[tuple[int, Point2D]] = [
        (i, ep)
        for i, ep in _endpoints_with_wall_index(walls)
        if _is_dangling(i, ep, walls, min_gap)
    ]

    directions = [_direction(w) for w in walls]

    suggestions: list[GapSuggestion] = []

    for idx_a in range(len(dangling)):
        wall_a, ep_a = dangling[idx_a]
        for wall_b, ep_b in dangling[idx_a + 1 :]:
            if wall_a == wall_b:
                continue  # a wall's own two ends -- not a gap

            gap_distance = math.hypot(
                ep_a[0] - ep_b[0], ep_a[1] - ep_b[1]
            )
            if not (min_gap <= gap_distance <= max_gap):
                continue

            gap_dir = _direction((ep_a, ep_b))
            if gap_dir == (0.0, 0.0):
                continue

            angle_a = _undirected_angle_deg(gap_dir, directions[wall_a])
            angle_b = _undirected_angle_deg(gap_dir, directions[wall_b])
            worst_angle = max(angle_a, angle_b)
            if worst_angle > angle_tol_deg:
                continue

            suggestions.append(
                GapSuggestion(
                    wall_a_index=wall_a,
                    wall_a_endpoint=ep_a,
                    wall_b_index=wall_b,
                    wall_b_endpoint=ep_b,
                    suggested_centerline=(ep_a, ep_b),
                    gap_distance=gap_distance,
                    collinearity_deg=worst_angle,
                )
            )

    suggestions.sort(key=lambda s: s.collinearity_deg)

    # Deduplicate: if wall0 and wall7 are truly two fragments of one
    # interrupted wall, BOTH of their endpoint pairings can pass the
    # collinearity check (near-to-near AND far-to-far), producing
    # two overlapping suggestions for what's really one gap
    # (confirmed against real capture data -- see
    # tests/test_gap_inference.py). Keep only the best (most
    # collinear) suggestion touching each endpoint.
    used_endpoints: set[tuple[int, Point2D]] = set()
    deduped: list[GapSuggestion] = []
    for s in suggestions:
        key_a = (s.wall_a_index, s.wall_a_endpoint)
        key_b = (s.wall_b_index, s.wall_b_endpoint)
        if key_a in used_endpoints or key_b in used_endpoints:
            continue
        used_endpoints.add(key_a)
        used_endpoints.add(key_b)
        deduped.append(s)

    return deduped