"""
    Ties BuildingModel + ReviewQueue + units.py together into the backend
    for the confidence-sorted correction workflow (V1 spec, Section 11 &
    16). This is the module a correction-UI frontend would actually call:
    it never touches raw geometry algorithms, only the assembled model.

    Design principle carried over from opening_detection.classify_openings'
    "don't guess" fix: a human correction is treated as ground truth. Once
    a person types a value in, confidence goes to 1.0 and the object drops
    out of the review queue -- there's no "the AI still thinks it's 80%
    sure" lingering after a human has looked at it and confirmed/fixed it.

    @author: Minh Thang Nguyen
    @version: August 11, 2026
"""


from __future__ import annotations
from dataclasses import dataclass
from typing import Optional

from building_model.schema import BuildingModel, Wall, Room, Opening
from review.queue import ReviewQueue
from review.formatting import format_object
import units


def build_review_queue(model: BuildingModel) -> ReviewQueue:
    """Populate a ReviewQueue from every object's current confidence."""
    queue = ReviewQueue()
    for obj_id, obj in model.objects.items():
        queue.add_or_update(obj_id, obj.confidence)
    return queue


@dataclass
class ReviewItem:
    object_id: str
    display_text: str
    remaining_count: int


def next_review_item(
        model: BuildingModel, queue: ReviewQueue, unit_system: str = "us"
) -> Optional[ReviewItem]:
    """The next lowest-confidence object still needing review, or None
    if the queue is empty -- what that 'review panel' UI would poll."""
    obj_id = queue.next_for_review()
    if obj_id is None:
        return None
    obj = model.objects.get(obj_id)
    return ReviewItem(
        object_id=obj_id,
        display_text=format_object(obj, unit_system),
        remaining_count=queue.remaining_count(),
    )


def approve(model: BuildingModel, queue: ReviewQueue, object_id: str) -> None:
    """User confirm the AI-detected value is correct as-is."""
    obj = model.objects.get(object_id)
    obj.confidence = 1.0
    queue.resolve(object_id)


def _parse_value(value_text: str, unit_system: str) -> float:
    if unit_system == "us":
        return units.parse_feet_inches(value_text)
    if unit_system == "metric":
        return float(value_text)
    raise ValueError(f"Unknown unit_system: {unit_system!r}")


def correct_wall_dimension(
        model: BuildingModel,
        queue: ReviewQueue,
        wall_id: str,
        field: str,
        value_text: str,
        unit_system: str = "us",
) -> None:
    """
    Apply a human correction to a wall's thickness/height, parsing the
    user's typed value (e.g. "6\"" or "8' 0\"" in US mode, or a plain
    number of meters in metric mode).
    """
    wall = model.objects.get(wall_id)
    if not isinstance(wall, Wall):
        raise ValueError(f"{wall_id!r} is not a Wall")
    if field not in ("thickness", "height"):
        raise ValueError(f"correctable wall fields are 'thickness/height', got {field!r}")

    meters = _parse_value(value_text, unit_system)
    setattr(wall, field, meters)
    wall.confidence = 1.0
    queue.resolve(wall_id)


def correct_opening_dimension(
        model: BuildingModel,
        queue: ReviewQueue,
        opening_id: str,
        field: str,
        value_text: str,
        unit_system: str = "us",
) -> None:
    """Same as correct_wall_dimension, but for Door/Window width, height,
    or sill_height."""
    obj = model.objects.get(opening_id)
    if not isinstance(obj, Opening):
        raise ValueError(f"{opening_id!r} is not a Door/Window")
    if field not in ("width", "height", "sill_height"):
        raise ValueError(
            f"correctable opening fields are 'width'/'height'/'sill_height', got {field!r}"
        )

    meters = _parse_value(value_text, unit_system)
    setattr(obj, field, meters)
    obj.confidence = 1.0
    queue.resolve(opening_id)


def reclassify_room(
        model: BuildingModel, queue: ReviewQueue, room_id: str, classification: str
) -> None:
    """User corrects the AI's room-type guess (e.g. 'unclassified' -> 'kitchen')."""
    room = model.objects.get(room_id)
    if not isinstance(room, Room):
        raise ValueError(f"{room_id!r} is not a Room")
    room.classification = classification
    room.confidence = 1.0
    queue.resolve(room_id)