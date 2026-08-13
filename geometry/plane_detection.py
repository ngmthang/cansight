"""
    Problem: turn a raw 3D point cloud (simulating a fused LiDAR/ARKit
    mesh) into wall-candidate line segments in the 2D floor plan, plus
    per-plane z-samples for height inference. This is the "point cloud ->
    plan detection -> 2D wall candidates" step from V1 spec Section 5,
    which nothing in this repo implemented yet -- wall_fitting.fit_walls()
    has always assumed segment observation already exist as input.

    Algorithm: sequential RANSAC plane segmentation.
        1. Repeatedly: randomly sample 3 points, fit the plane through them,
           count how many of the remaining points lie within a distance
           tolerance of that plane (inliers). Keep the best plan found
           over many random trials -- classic RANSAC, robust to the point
           cloud being mostly noise/clutter relative to any one surface.
        2. Remove that plane's inlier points from the working set and
           repeat until too few points remain to reliably fit another
           plane, or a max plane count is reached. This "peel off the best
           plane, repeat" strategy is what makes it SEQUENTIAL RANSAC,
           since single-shot RANSAC only finds one plane.
        3. Classify each found plane by its normal: near-vertical normal
           (normal's z-component close to 0) means the plane's surface is
           roughly vertical -- a wall candidate. Near-horizontal normal
           (|z-component| close to 1) means floor/ceiling, not walls --
           those are filtered out here since height_inference.py handles
           floor/ceiling directly from z-samples, not from plane fitting.
        4. For each wall-candidate plane, project its inlier points onto
           the plane's dominant horizontal direction to get a 2D line
           segment (min/max projection = segment endpoints), and collect
           the inliers' z-values as height_inference.py-ready z-samples.

    Same "fit robustly, ignore outliers via inlier counting" idea as
    wall_fitting.py's clustering and height_inference.py's density
    thresholding -- just extended to full 3D since raw point-cloud data
    has no pre-existing structure to cluster by angle/offset the raw 2D
    segment observations do.

    :author: Minh Thang Nguyen
    :version: August 12, 2026
"""

from __future__ import annotations
from dataclasses import dataclass
import random, math


Point3D = tuple[float, float, float]
Vector3D = tuple[float, float, float]


@dataclass
class DetectedPlane:
    inliers: list[Point3D]
    normal: Vector3D
    centroid: Point3D

    @property
    def is_wall(self) -> bool:
        # near-vertical surface: the plane's normal is roughly
        # horizontal (small z-component), meaning the surface itself
        # stands up vertically -- that's a wall, not a floor/ceiling
        return abs(self.normal[2]) < 0.3


@dataclass
class WallCandidate:
    segment: tuple[tuple[float, float], tuple[float, float]]
    z_samples: list[float]
    inlier_count: int


def _subtract(a: Point3D, b: Point3D) -> Vector3D:
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _cross(a: Vector3D, b: Vector3D) -> Vector3D:
    return (
        a[1] * b[2] - a[2] * b[1],
        a[2] * b[0] - a[0] * b[2],
        a[0] * b[1] - a[1] * b[0],
    )


def _normalize(v: Vector3D) -> Vector3D | None:
    n = math.sqrt(v[0] ** 2 + v[1] ** 2 + v[2] ** 2)
    if n < 1e-9:
        return None
    return (v[0] / n, v[1] / n, v[2] / n)


def _dot(a: Vector3D, b: Vector3D) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _fit_plane(
        p1: Point3D, p2: Point3D, p3: Point3D
) -> tuple[Vector3D, float] | None:
    """Returns (unit_normal, d) for plane normal . x = d, or None if
    the three points are collinear/degenerate."""
    normal = _cross(_subtract(p2, p1), _subtract(p3, p1))
    unit_normal = _normalize(normal)
    if unit_normal is None:
        return None
    d = _dot(unit_normal, p1)
    return unit_normal, d


def _point_plane_distance(
        p: Point3D, normal: Vector3D, d: float
) -> float:
    return abs(_dot(normal, p) - d)


def ransac_plane_segmentation(
        points: list[Point3D],
        distance_threshold: float = 0.03,
        min_inliers: int = 20,
        max_planes: int = 20,
        iterations_per_plane: int = 300,
        seed: int | None = None,
) -> list[DetectedPlane]:
    """Sequential RANSAC: repeatedly find the best-supported plane in
    the remaining points, remove its inliers, repeat."""
    rng = random.Random(seed)
    remaining = list(points)
    planes: list[DetectedPlane] = []

    while(
        len(remaining) >= max(min_inliers, 3)
        and len(planes) < max_planes
    ):
        best_inlier_idx: list[int] = []
        best_plane: tuple[Vector3D, float] | None = None

        for _ in range(iterations_per_plane):
            sample_idx = rng.sample(range(len(remaining)), 3)
            p1, p2, p3 = (remaining[i] for i in sample_idx)
            fit = _fit_plane(p1, p2, p3)
            if fit is None:
                continue
            normal, d = fit
            inlier_idx = [
                i for i, p in enumerate(remaining)
                if _point_plane_distance(p, normal, d)
                <= distance_threshold
            ]
            if len(inlier_idx) > len(best_inlier_idx):
                best_inlier_idx = inlier_idx
                best_plane = (normal, d)

        if best_plane is None or len(best_inlier_idx) < min_inliers:
            break # nothing left worth calling a surface

        normal, d = best_plane
        inliers = [remaining[i] for i in best_inlier_idx]
        cx = sum(p[0] for p in inliers) / len(inliers)
        cy = sum(p[1] for p in inliers) / len(inliers)
        cz = sum(p[2] for p in inliers) / len(inliers)

        planes.append(
            DetectedPlane(inliers=inliers, normal=normal,centroid=(cx, cy, cz))
        )

        keep_set = set(best_inlier_idx)
        remaining = [
            p for i, p in enumerate(remaining) if i not in keep_set
        ]

    return planes


def extract_wall_candidates(
        points: list[Point3D],
        distance_threshold: float = 0.03,
        min_inliers: int = 20,
) -> list[WallCandidate]:
    """
    Full pipeline: RANSAC-segment the point cloud into planes, keep
    only the near-vertical (wall) ones, and project each onto its
    dominant horizontal direction to get a 2D segment plus z-samples
    ready for height_inference.estimate_floor_and_ceiling().
    """
    planes = ransac_plane_segmentation(
        points,
        distance_threshold = distance_threshold,
        min_inliers = min_inliers,
    )

    candidates: list[WallCandidate] = []
    for plane in planes:
        if not plane.is_wall:
            continue

        # horizontal direction along the wall's face: perpendicular
        # to the plane's normal, projected onto the XY plane
        nx, ny, _ = plane.normal
        along = _normalize((-ny, nx, 0.0))
        if along is None:
            continue # degenerate (shouldn't happen for a real wall)

        cx, cy, _ = plane.centroid
        projections = [
            (p[0] - cx) * along[0] + (p[1] - cy) * along[1]
            for p in plane.inliers
        ]
        t_min, t_max = min(projections), max(projections)
        p_start = (cx + t_min * along[0], cy + t_min * along[1])
        p_end = (cx + t_max * along[0], cy + t_max * along[1])

        candidates.append(
            WallCandidate(
                segment=(p_start, p_end),
                z_samples=[p[2] for p in plane.inliers],
                inlier_count=len(plane.inliers)
            )
        )

    return candidates