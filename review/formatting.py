"""
    Human-readable, unit-aware object summaries for the correction UI
    (V1 spec, Section 15-16).

    This is the layer that actually calls into units.py, BuildingModel and
    the geometry pipeline never do that themselves -- see units.py's
    module docstring: the dependency only goes one direction, display
    code -> units.py, never the other way. This module is that "display
    code."

    @author: Minh Thang Nguyen
    @version: August 11, 2026
"""


from __future__ import annotations

from building_model.schema import BuildingObject, Wall, Door, Window, Room
import units


def _pct(confidence: float) -> str:
    return f"{confidence * 100:.0f}%"


def format_wall(wall: Wall, unit_system: str = "us") -> str:
    length = wall.length()
    return (
        f"Wall {wall.id}: {units.format_length(length, unit_system)} long, "
        f"{units.format_length(wall.thickness, unit_system)} thick, "
        f"{units.format_length(wall.height, unit_system)} tall, "
        f"(confidence: {_pct(wall.confidence)})"
    )


def format_door(door: Door, unit_system: str = "us") -> str:
    return (
        f"Door {door.id}: {units.format_length(door.width, unit_system)} wide x "
        f"{units.format_length(door.height, unit_system)} tall, "
        f"host wall {door.host_wall_id} "
        f"(confidence: {_pct(door.confidence)})"
    )


def format_window(window: Window, unit_system: str = "us") -> str:
    return (
        f"Window {window.id}: {units.format_length(window.width, unit_system)} wide x "
        f"{units.format_length(window.height, unit_system)} tall, "
        f"sill {units.format_length(window.sill_height, unit_system)}, "
        f"host wall {window.host_wall_id} "
        f"(confidence: {_pct(window.confidence)})"
    )


def format_room(room: Room, unit_system: str = "us") -> str:
    return (
        f"Room {room.id} ({room.classification}): "
        f"{units.format_area(room.area(), unit_system)} "
        f"(confidence: {_pct(room.confidence)})"
    )


# Order matters only in that Door/Window are unrelated sibling classes
# (both subclass Opening, not each other), so a plain isinstance dance
# is fine here -- so ambiguity between them.
_FORMATTERS = (
    (Wall, format_wall),
    (Door, format_door),
    (Window, format_window),
    (Room, format_room),
)


def format_object(obj: BuildingObject, unit_system: str = "us") -> str:
    for cls, fn in _FORMATTERS:
        if isinstance(obj, cls):
            return fn(obj, unit_system)
    return f"{obj.type.value} {obj.id} (confidence: {_pct(obj.confidence)})"