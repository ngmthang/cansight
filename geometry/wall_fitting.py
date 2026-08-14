"""
    Problem: The reconstruction pipeline observes the SAME physical wall many
    times across different video/LiDAR frames, each observation slightly noisy
    and slightly offset. We need ONE clean wall centerline per physical wall.

    This is a clustering problem: group near-parallel, near-collinear segment
    observations, the fit one clean line through each group.

    Algorithm:
        1. Union-Find (disjoint set) to cluster segments whose angle and
           perpendicular offset are both within tolerance -> O(n^2) pairwise
           compare + near-inverse-Ackermann union/find, fine for the segment
           counts a single-room scan produces (hundreds, not millions).
        2. For each cluster, fit a line via PCA / total-least-squares on all
           endpoint coordinates (robust to noise in both x and y, unlike
           ordinary least-squares regression which assumes error only in y).
        3. Project all endpoints onto the fitted line direction to get the
           wall's extent (min/max projection = the two endpoints of the clean
           centerline).

    @author: Minh Thang Nguyen
    @version: August 8, 2026
"""


from __future__ import annotations
from dataclasses import dataclass
import math


Point = tuple[float, float]
Segment = tuple[Point, Point]


class UnionFind:
    def __init__(self, n: int):
        self.parent = list(range(n))
        self.rank = [0] * n

    def find(self, x: int) -> int:
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]] # path halving
            x = self.parent[x]
        return x

    def union(self, a: int, b: int) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra == rb:
            return
        if self.rank[ra] < self.rank[rb]:
            ra, rb = rb, ra
        self.parent[rb] = ra
        if self.rank[ra] == self.rank[rb]:
            self.rank[ra] += 1


def _segment_angle(seg: Segment) -> float:
    (x0, y0), (x1, y1) = seg
    return math.atan2(y1 - y0, x1 - x0) % math.pi # undirected angle in [0, pi)


def _angle_diff(a: float, b: float) -> float:
    d = abs(a - b) % math.pi
    return min(d, math.pi - d)


def _point_line_distance(p: Point, seg: Segment) -> float:
    """Perpendicular distance from p to the infinite line through seg."""
    (x0, y0), (x1, y1) = seg
    dx, dy = x1 - x0, y1 - y0
    norm = math.hypot(dx, dy)
    if norm < 1e-9:
        return math.hypot(p[0] - x0, p[1] - y0)
    return abs((p[0] - x0) * dy - (p[1] - y0) * dx) / norm


def cluster_wall_observations(
    segments: list[Segment],
    angle_tol_deg: float = 6.0,
    offset_tol: float = 0.08,
) -> list[list[int]]:
    """Group segment indices that likely represent the same physical wall."""
    n = len(segments)
    uf = UnionFind(n)
    angle_tol = math.radians(angle_tol_deg)
    angles = [_segment_angle(s) for s in segments]

    for i in range(n):
        for j in range(i + 1, n):
            if _angle_diff(angles[i], angles[j]) > angle_tol:
                continue
            # perpendicular distance between the two segments' lines,
            # checked both directions since offset isn't symmetric for
            # short vs. long segments
            d1 = _point_line_distance(segments[i][0], segments[j])
            d2 = _point_line_distance(segments[j][0], segments[i])
            if max(d1, d2) <= offset_tol:
                uf.union(i, j)

    groups: dict[int, list[int]] = {}
    for i in range(n):
        root = uf.find(i)
        groups.setdefault(root, []).append(i)
    return list(groups.values())


def fit_line_total_least_squares(points: list[Point]) -> tuple[Point, Point]:
    """
    Total-least-squares line fit via PCA: minimize perpendicular distance
    to all points (not just vertical distance like ordinary regression),
    which matters because wall observation noise isn't axis-aligned.
    Returns (centroid, unit_direction).
    """
    n = len(points)
    cx = sum(p[0] for p in points) / n
    cy = sum(p[1] for p in points) / n

    sxx = sum((p[0] - cx) ** 2 for p in points)
    syy = sum((p[1] - cy) ** 2 for p in points)
    sxy = sum((p[0] - cx) * (p[1] - cy) for p in points)

    # principal eigenvector of the 2x2 covariance matrix [[sxx,sxy],[sxy,syy]]
    theta = 0.5 * math.atan2(2 * sxy, sxx - syy)
    direction = (math.cos(theta), math.sin(theta))
    return (cx, cy), direction


@dataclass
class FittedWall:
    centerline: Segment
    thickness_estimate: float
    support_count: int # how many observations contributed


def fit_walls(
    segments: list[Segment],
    assumed_thickness: float = 0.12,
    angle_tol_deg: float = 6.0,
    offset_tol: float = 0.08,
) -> list[FittedWall]:
    clusters = cluster_wall_observations(
        segments, angle_tol_deg=angle_tol_deg, offset_tol=offset_tol
    )
    results: list[FittedWall] = []

    for cluster in clusters:
        pts: list[Point] = []
        for idx in cluster:
            pts.extend(segments[idx])

        centroid, direction = fit_line_total_least_squares(pts)
        dx, dy = direction

        # project every point onto the fitted line to find the wall's extent
        projections = [((p[0] - centroid[0]) * dx + (p[1] - centroid[1]) * dy) for p in pts]
        t_min, t_max = min(projections), max(projections)

        p_start = (centroid[0] + t_min * dx, centroid[1] + t_min * dy)
        p_end = (centroid[0] + t_max * dx, centroid[1] + t_max * dy)

        results.append(FittedWall(
            centerline=(p_start, p_end),
            thickness_estimate=assumed_thickness,
            support_count=len(cluster),
        ))
    return results