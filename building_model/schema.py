"""
    Universal Building Model - core data classes.

    This is the source of truth described in the V1 spec, Section 12/13.
    Every downstream system (geometry pipeline, review UI, IFC export)
    reads and writes this representation - nothing talks to raw point
    clouds expect the geometry pipeline itself.

    @author: Minh Thang Nguyen
    @version: August 8, 2026
"""

from __future__ import annotations
from dataclasses import dataclass, field, asdict
from typing import Optional
from enum import Enum
import json
import uuid


class ObjectType(str, Enum):
    WALL = "wall"
    FLOOR = "floor"
    CEILING = "ceiling"
    DOOR = "door"
    WINDOW = "window"
    ROOM = "room"
    COLUMN = "column"


class RelationType(str, Enum):
    HOSTED_BY = "hosted_by" # door/window -> wall
    BOUNDED_BY = "bounded_by" # room -> wall
    CONTAINS = "contains" # room -> door/window


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


@dataclass
class Provenance:
    source_frames: list[str] = field(default_factory=list)
    detection_method: str = "manual"
    pipeline_version: str = "v1.0.0"


@dataclass
class BuildingObject:
    """Base fields shared by every object in the model."""
    id: str
    type: ObjectType
    level: str
    confidence: float = 1.0
    provenance: Provenance = field(default_factory=Provenance)

    def validate(self) -> list[str]:
        errors = []
        if not (0.0 <= self.confidence <= 1.0):
            errors.append(f"{self.id}: confidence {self.confidence} out of range [0,1]")
        return errors


@dataclass
class Wall(BuildingObject):
    centerline: list[tuple[float, float]] = field(default_factory=list) # 2D [(x0,y0),(x1,y1)]
    thickness: float = 0.10
    height: float = 2.4
    material: Optional[str] = None
    room_side_a: Optional[str] = None
    room_side_b: Optional[str] = None

    def __post_init__(self):
        self.type = ObjectType.WALL

    def length(self) -> float:
        (x0, y0), (x1, y1) = self.centerline
        return ((x1 - x0) ** 2 + (y1 - y0) ** 2) ** 0.5

    def validate(self) -> list[str]:
        errors = super().validate()
        if len(self.centerline) != 2:
            errors.append(f"{self.id}: wall centerline must have exactly 2 points")
        if self.thickness <= 0 or self.height <= 0:
            errors.append(f"{self.id}: thickness/height must be positive")
        return errors


@dataclass
class Opening(BuildingObject):
    """Shared base for Door/Window."""
    host_wall_id: str = ""
    width: float = 0.9
    height: float = 2.1
    sill_height: float = 0.0
    position_on_wall: float = 0.5 # 0..1 fraction along host wall centerline

    def validate(self) -> list[str]:
        errors = super().validate()
        if not self.host_wall_id:
            errors.append(f"{self.id}: opening has no host_wall_id")
        if not (0.0 <= self.position_on_wall <= 1.0):
            errors.append(f"{self.id}: position_on_wall out of range [0,1]")
        return errors


@dataclass
class Door(Opening):
    swing: Optional[str] = None # "left" | "right" | None

    def __post_init__(self):
        self.type = ObjectType.DOOR


@dataclass
class Window(Opening):
    head_height: float = 2.0

    def __post_init__(self):
        self.type = ObjectType.WINDOW
        self.sill_height = self.head_height or 0.9


@dataclass
class Room(BuildingObject):
    boundary: list[tuple[float, float]] = field(default_factory=list)
    classification: str = "other"
    bounded_by: list[str] = field(default_factory=list)
    contains: list[str] = field(default_factory=list)

    def __post_init__(self):
        self.type = ObjectType.ROOM

    def area(self) -> float:
        """Shoelace formula."""
        pts = self.boundary
        n = len(pts)
        if n < 3:
            return 0.0
        s = sum(pts[i][0] * pts[(i + 1) % n][1] - pts[(i + 1) % n][0] * pts[i][1] for i in range(n))
        return abs(s) / 2.0

    def validate(self) -> list[str]:
        errors = super().validate()
        if len(self.boundary) < 3:
            errors.append(f"{self.id}: room boundary needs >= 3 points")
        return errors


@dataclass
class Level:
    id: str
    elevation: float = 0.0
    rooms: list[str] = field(default_factory=list)
    walls: list[str] = field(default_factory=list)
    doors: list[str] = field(default_factory=list)
    windows: list[str] = field(default_factory=list)


@dataclass
class Relationship:
    type: RelationType
    from_id: str
    to_id: str


@dataclass
class BuildingModel:
    building_id: str
    model_version: str = "1.0"
    levels: dict[str, Level] = field(default_factory=dict)
    objects: dict[str, BuildingObject] = field(default_factory=dict)
    relationships: list[Relationship] = field(default_factory=list)

    # mutation helpers
    def add_level(self, level_id: str, elevation: float = 0.0) -> Level:
        lvl = Level(id=level_id, elevation=elevation)
        self.levels[level_id] = lvl
        return lvl

    def add_wall(self, level: str, centerline, thickness=0.10, height=2.4, **kw) -> Wall:
        w = Wall(id=new_id("wall"), type=ObjectType.WALL, level=level,
                 centerline=centerline, thickness=thickness, height=height, **kw)
        self.objects[w.id] = w
        self.levels[level].walls.append(w.id)
        return w

    def add_door(self, level: str, host_wall_id: str, **kw) -> Door:
        d = Door(id=new_id("door"), type=ObjectType.DOOR, level=level, host_wall_id=host_wall_id, **kw)
        self.objects[d.id] = d
        self.levels[level].doors.append(d.id)
        self.relationships.append(Relationship(RelationType.HOSTED_BY, d.id, host_wall_id))
        return d

    def add_window(self, level: str, host_wall_id: str, **kw) -> Window:
        w = Window(id=new_id("window"), type=ObjectType.WINDOW, level=level, host_wall_id=host_wall_id, **kw)
        self.objects[w.id] = w
        self.levels[level].windows.append(w.id)
        self.relationships.append(Relationship(RelationType.HOSTED_BY, w.id, host_wall_id))
        return w

    def add_room(self, level: str, boundary, bounded_by: list[str], classification="other", **kw) -> Room:
        r = Room(id=new_id("room"), type=ObjectType.ROOM, level=level, boundary=list(boundary),
                 bounded_by=list(bounded_by), classification=classification, **kw)
        self.objects[r.id] = r
        self.levels[level].rooms.append(r.id)
        for w_id in bounded_by:
            self.relationships.append(Relationship(RelationType.BOUNDED_BY, r.id, w_id))
        return r

    # validation
    def validate(self) -> list[str]:
        """Consistency checks across the whole model, not just per-object."""
        errors: list[str] = []
        for obj in self.objects.values():
            errors.extend(obj.validate())

        # every relationship must reference existing objects
        for rel in self.relationships:
            if rel.from_id not in self.objects:
                errors.append(f"relationship {rel.type}: unknown from_id {rel.from_id}")
            to_ok = rel.to_id in self.objects or rel.to_id in self.levels
            if not to_ok:
                errors.append(f"relationship {rel.type}: unknown to_id {rel.to_id}")

        # opening must host on a wall that exists and belongs to same level
        for obj in self.objects.values():
            if isinstance(obj, Opening):
                wall = self.objects.get(obj.host_wall_id)
                if wall is None:
                    errors.append(f"{obj.id}: host wall {obj.host_wall_id} not found")
                elif wall.level != obj.level:
                    errors.append(f"{obj.id}: host wall on different level than opening")

        # room bounded_by walls must exist
        for obj in self.objects.values():
            if isinstance(obj, Room):
                for w_id in obj.bounded_by:
                    if w_id not in self.objects:
                        errors.append(f"{obj.id}: bounded_by references missing wall {w_id}")

        return errors

    # serialization
    def to_json(self, path: Optional[str] = None) -> str:
        def obj_to_dict(o):
            d = asdict(o)
            d["type"] = o.type.value
            return d

        payload = {
            "building_id": self.building_id,
            "model_version": self.model_version,
            "levels": {k: asdict(v) for k, v in self.levels.items()},
            "objects": {k: obj_to_dict(v) for k, v in self.objects.items()},
            "relationships": [
                {"type": r.type.value, "from": r.from_id, "to": r.to_id} for r in self.relationships
            ],
        }
        text = json.dumps(payload, indent=2)
        if path:
            with open(path, "w") as f:
                f.write(text)
        return text