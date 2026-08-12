"""
    Problem: LiDAR/point-cloud data along a wall face gives many z (height)
    samples -- points scattered from floor to ceiling, contaminated by
    furniture, clutter, and sensor noise. We need to robustly recover the
    TRUE floor and ceiling elevation for that wall, ignoring outliers.

    Why not just make min(z) and max(z) of the samples? Because a single
    stray noise point below the true floor (sensor multipath off a
    reflective floor, say) or above the true ceiling (a light fixture, or
    a partial return through a gap) would corrupt the whole wall's
    inferred height using naive min/max.

    Algorithm: 1D histogram binning + density peak detection near each end
    of the observed z-range. The floor and ceiling are large, flat,
    continuous planar surfaces, so LiDAR returns cluster DENSELY right at
    those elevations -- many points hit the floor/ceiling plane, while
    "in between" clutter at any single height is comparatively sparse. We
    bin z-values into fixed-width bins, then walk in from each extreme
    looking for the first bin whose point count exceeds a density
    threshold -- that's the real floor/ceiling plane, not a isolated
    outlier point sitting further out.

    :author: Minh Thang Nguyen
    :version: August 11, 2026
"""

from __future__ import annotations
from dataclasses import dataclass
import math


@dataclass
class HeightEstimate:
    floor_elevation: float
    ceiling_elevation: float
    sample_count: int
    outliers_rejected: int

    @property
    def height(self) -> float:
        return self.ceiling_elevation - self.floor_elevation


def _histogram(
        z_values: list[float], bin_size: float
) -> dict[int, list[float]]:
    bins: dict[int, list[float]] = {}
    for z in z_values:
        b = math.floor(z / bin_size)
        bins.setdefault(b, []).append(z)
    return bins


def estimate_floor_and_ceiling(
        z_samples: list[float],
        # 2cm bins -- fine enough to localize a plan, coarse
        # enough to survive noise
        bin_size: float = 0.02,
        # min points in a bin before it counts as a real
        # surface, not noise
        density_threshold: int = 3,
) -> HeightEstimate:
    """
    Given raw z-coordinate samples from points near/on a wall face,
    robustly find the floor and ceiling elevation for that wall.
    """
    if len(z_samples) < 2:
        raise ValueError(
            "need at least 2 z samples to estimate floor/ceiling"
        )

    bins = _histogram(z_samples, bin_size)
    sorted_bin_ids = sorted(bins.keys())

    # walk up from the bottom until a bin is dense enough
    # to be a real surface
    floor_bin = next((b for b in sorted_bin_ids
                    if len(bins[b]) >= density_threshold), None)
    # walk down from the top similarly
    ceiling_bin = next((b for b in reversed(sorted_bin_ids)
                    if len(bins[b]) >= density_threshold), None)

    if(floor_bin is None or ceiling_bin is None or
        floor_bin > ceiling_bin):
        # data too sparse for any bin to clear the density bar -- fall
        # back to a percentile estimate (still not raw min/max, so a
        # single extreme outlier still can't dominate the result)
        sorted_z = sorted(z_samples)
        n = len(sorted_z)
        floor_elevation = sorted_z[max(0, int(n * 0.02))]
        ceiling_elevation = sorted_z[min(n -1, int(n * 0.98))]
        outliers_rejected = 0
    else:
        # sub-bin-size precision: average the points actually inside
        # the accepted floor/ceiling bin, rather than using the bin's
        # boundary value
        floor_elevation = sum(bins[floor_bin]) / len(bins[floor_bin])
        ceiling_elevation = sum(bins[ceiling_bin]) / len(bins[ceiling_bin])
        # outliers are samples that fell outside the accepted
        # [floor_bin, ceiling_bin] range entirely -- points BETWEEN
        # those bins are legitimate wall-face returns, not outliers
        outliers_rejected = sum(len(bins[b]) for b in sorted_bin_ids
                                if b < floor_bin or b > ceiling_bin)

    return HeightEstimate(
        floor_elevation=floor_elevation,
        ceiling_elevation=ceiling_elevation,
        sample_count=len(z_samples),
        outliers_rejected=outliers_rejected,
    )