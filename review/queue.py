"""
    Problem: the correction UI (V1 spec, Section 11) needs to guide the user
    to the LOWEST-confidence objects first, not make them scan the whole
    model. As objects get corrected/approved, the queue needs to update
    without a full re-sort every time.

    This is a textbook priority queue (min-heap on confidence), with lazy
    deletion to handle the "approve/edit an object that's already in the
    heap" case cheaply (O(log n) push, O(log n) amortized pop) instead of
    rebuilding the heap on every correction.

    @author: Minh Thang Nguyen
    @version: August 10, 2026
"""


from __future__ import annotations
import heapq
from dataclasses import dataclass, field


@dataclass(order=True)
class _HeapEntry:
    confidence: float
    object_id: str = field(compare=False)


class ReviewQueue:
    def __init__(self):
        self._heap: list[_HeapEntry] = []
        self._current_confidence: dict[str, float] = {} # latest known confidence per object
        self._resolved: set[str] = set() # approved/deleted -> no longer needs review

    def add_or_update(self, object_id: str, confidence: float) -> None:
        self._current_confidence[object_id] = confidence
        self._resolved.discard(object_id)
        heapq.heappush(self._heap, _HeapEntry(confidence, object_id))

    def resolve(self, object_id: str) -> None:
        """Mark reviewd (approved, or corrected+re-approved). Lazy-deleted
        from the heap: stale entries are skipped when popped."""
        self._resolved.add(object_id)

    def _is_stale(self, entry: _HeapEntry) -> bool:
        if entry.object_id in self._resolved:
            return True
        # stale if a newer confidence value was pushed for this object
        return self._current_confidence.get(entry.object_id) != entry.confidence

    def next_for_review(self) -> str | None:
        """
        Peek the lowest-confidence unresolved object WITHOUT removing it
        from consideration -- an object should keep surfacing until it's
        explicitly resolve()'d, not just because it was looked at once.
        Stale/resolved entries at the top of the heap are discarded
        permanently (that's safe, since a fresher entry or resolution
        already supersedes them), but the current, valid lowest entry is
        left in place.
        """
        while self._heap:
            entry = self._heap[0]
            if self._is_stale(entry):
                heapq.heappop(self._heap)
                continue
            return entry.object_id
        return None

    def peek_batch(self, n: int) -> list[str]:
        """Non-destructive look at the next n items needing review, for the
        'here are your top 5 lowest-confidence objects' UI panel."""
        results: list[str] = []
        heap_copy = list(self._heap)
        heapq.heapify(heap_copy)
        while heap_copy and len(results) < n:
            entry = heapq.heappop(heap_copy)
            if self._is_stale(entry):
                continue
            results.append(entry.object_id)
        return results

    def remaining_count(self) -> int:
        return sum(
            1 for oid, conf in self._current_confidence.items()
            if oid not in self._resolved
        )