"""
    Problem: sensor data gives us many short "no wall material detected here"
    intervals along a wall's length (from occlusion gaps, actual openings,
    and noise). We need to merge these into candidate door/window openings.

    This is the classic MERGE INTERVALS problem, with a twist: after merging,
    we filter by width to distinguish real opening (0.6m - 3.0m, doors/
    windows) from noise (tiny gaps) and from missing-wall-segment scan holes
    (very large gaps, which are a reconstruction failure, not an opening).

    Algorithm: sort by start position, sweep once, merge overlapping/adjacent
    intervals within a tolerance gap. O(n log n) from the sort, O(n) sweep.

    @author: Minh Thang Nguyen
    @version: August 9, 2026
"""


from __future__ import annotations
from dataclasses import dataclass


@dataclass
class GapObservation:
    start: float # position along wall, meters from wall start
    end: float
    confidence: float = 1.0 # how sure the detector is this is a real gap


@dataclass
class CandidateOpening:
    start: float
    end: float
    confidence: float
    likely_type: str # "door" | "window" | "noise" | "reconstruction_gap"

    @property
    def width(self) -> float:
        return self.end - self.start


def merge_gaps(
    gaps: list[GapObservation],
    merge_tolerance: float = 0.05,
) -> list[GapObservation]:
    """Merge overlapping or near-adjacent gap observations into one."""
    if not gaps:
        return []
    ordered = sorted(gaps, key=lambda g: g.start)
    merged = [ordered[0]]

    for g in ordered[1:]:
        last = merged[-1]
        if g.start <= last.end + merge_tolerance:
            # overlap or close enough to be the same physical opening
            new_end = max(last.end, g.end)
            # confidence of merged gap: weighted by span covered (wider
            # agreement across observations => higher confidence_
            combined_conf = max(last.confidence, g.confidence)
            merged[-1] = GapObservation(last.start, new_end, combined_conf)
        else:
            merged.append(g)

    return merged


def classify_openings(
    merged_gaps: list[GapObservation],
    door_range: tuple[float, float] = (0.6, 1.2),
    window_range: tuple[float, float] = (0.4, 3.0),
    sill_hint_low: bool = True,
) -> list[CandidateOpening]:
    """
    Width-based classification. In a full pipeline this would also use
    the RGB detector's door/window classification per Master plan §5;
    width is the geometry-only fallback / sanity check.

    Widths that don't clearly fall in a known range are NOT guessed at
    -- they're labeled "ambiguous" with reduced confidence so the
    review queue (review/queue.py) surfaces them for a human to decide,
    rather than silently asserting a type that might be wrong. A wrong
    door/window guess baked into the Building Model with high implied
    confidence is worse than an honest "unsure" that gets reviewed.
    """
    results = []
    for g in merged_gaps:
        width = g.end - g.start
        confidence = g.confidence

        if width < 0.15:
            likely_type = "noise"
        elif width > 3.0:
            likely_type = "reconstruction_gap"
        elif door_range[0] <= width <= door_range[1]:
            likely_type = "door"
        elif window_range[0] <= width <= window_range[1]:
            likely_type = "window"
        else:
            likely_type = "ambiguous"
            confidence = min(confidence, 0.5)  # cap confidence so it surfaces in the review queue
        results.append(CandidateOpening(g.start, g.end, confidence, likely_type))
    return results