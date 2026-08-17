"""
Building Model -> DXF export (2D floor plan).

Serves two of the three most-requested CAD/BIM targets with one
exporter: DXF is AutoCAD's native format, and SketchUp has built-in
DXF import support. (Revit is already served by export/ifc_export.py,
since Revit has native IFC import -- no separate exporter needed
there.)

Per V1 spec Section 20 ("CAD Strategy"): the exporter organizes
output into meaningful layers (not just an undifferentiated pile of
lines), matching standard architectural CAD conventions. This is
intentionally 2D-only (a floor plan, not a 3D DXF model) -- matching
the same "geometry-simple for V1" scope as export/ifc_export.py.
"""

from __future__ import annotations
import math, ezdxf

from building_model.schema import (
    BuildingModel,
    Wall,
    Door,
    Window,
    Room,
)

LAYER_WALLS = "WALLS"
LAYER_ROOMS = "ROOMS"
LAYER_DOORS = "DOORS"
LAYER_WINDOWS = "WINDOWS"
LAYER_TEXT = "TEXT"


def _wall_corners(wall: Wall) -> list[tuple[float, float]]:
    """Computes the wall's 2D footprint (a rectangle) from its
    centerline + thickness, by offsetting perpendicular to the wall
    direction on both sides -- same idea as the web review UI's
    rendering, but producing real DXF polyline geometry instead of
    an SVG line."""
    (x0, y0), (x1, y1) = wall.centerline
    dx, dy = x1 - x0, y1 - y0
    length = math.hypot(dx, dy)
    if length < 1e-9:
        return [(x0, y0)] * 4
    ux, uy = dx / length, dy / length
    px, py = -uy, ux # perpendicular unit vector
    half_t = wall.thickness / 2.0

    return [
        (x0 + px * half_t, y0 + py * half_t),
        (x1 + px * half_t, y1 + py * half_t),
        (x1 - px * half_t, y1 - py * half_t),
        (x0 - px * half_t, y0 - py * half_t),
    ]


def _opening_center(
    wall: Wall, position_on_wall: float
) -> tuple[float, float]:
    (x0, y0), (x1, y1) = wall.centerline
    return (
        x0 + position_on_wall * (x1 - x0),
        y0 + position_on_wall * (y1 - y0),
    )


def _opening_rectangle(
    wall: Wall, position_on_wall: float, width: float
) -> list[tuple[float, float]]:
    """A small rectangle spanning the opening's width along the wall,
    at the wall's thickness -- represents where a door/window
    interrupts the wall, drawn on its own layer so it reads clearly
    against the solid wall polygon underneath."""
    (x0, y0), (x1, y1) = wall.centerline
    dx, dy = x1 - x0, y1 - y0
    length = math.hypot(dx, dy)
    if length < 1e-9:
        return []
    ux, uy = dx / length, dy / length
    px, py = -uy, ux
    half_t = wall.thickness / 2.0
    half_w = width / 2.0

    cx, cy = _opening_center(wall, position_on_wall)
    p0 = (cx - ux * half_w, cy - uy * half_w)
    p1 = (cx + ux * half_w, cy + uy * half_w)

    return [
        (p0[0] + px * half_t, p0[1] + py * half_t),
        (p1[0] + px * half_t, p1[1] + py * half_t),
        (p0[0] - px * half_t, p0[1] - py * half_t),
        (p1[0] - px * half_t, p1[1] - py * half_t),
    ]


def export_to_dxf(model: BuildingModel, path: str) -> list[str]:
    """Exports the model to a DXF floor plan. Returns a list of
    warnings (empty = clean) -- same "validate first, refuse to
    export an inconsistent model" policy as export/ifc_export.py."""
    warnings: list[str] = []
    errors = model.validate()
    if errors:
        raise ValueError(
            f"Building Model failed validation, refusing export: "
            f"{errors}"
        )

    doc = ezdxf.new(setup=True)
    doc.units = ezdxf.units.M # meters, matching this project's
    # internal representation throughout (units.py's whole reason
    # for existing is converting at the display boundary, never
    # changing the internal representation)
    msp = doc.modelspace()

    for layer_name, color in [
        (LAYER_WALLS, 7),  # white/black
        (LAYER_ROOMS, 3),  # green
        (LAYER_DOORS, 5),  # blue
        (LAYER_WINDOWS, 4),  # cyan
        (LAYER_TEXT, 2),  # yellow
    ]:
        doc.layers.add(name=layer_name, color=color)

    wall_lookup: dict[str, Wall] = {}

    for obj in model.objects.values():
        if isinstance(obj, Wall):
            wall_lookup[obj.id] = obj
            corners = _wall_corners(obj)
            msp.add_lwpolyline(
                corners, close=True, dxfattribs={"layer": LAYER_WALLS}
            )

        elif isinstance(obj, Room):
            if len(obj.boundary) >= 3:
                msp.add_lwpolyline(
                    obj.boundary,
                    close=True,
                    dxfattribs={"layer": LAYER_ROOMS},
                )
            cx = sum(p[0] for p in obj.boundary) / len(obj.boundary)
            cy = sum(p[1] for p in obj.boundary) / len(obj.boundary)
            label = f"{obj.classification} ({obj.area():.1f} m2)"
            text = msp.add_text(
                label, dxfattribs={"layer": LAYER_TEXT, "height": 0.2}
            )
            text.set_placement((cx, cy))

        elif isinstance(obj, (Door, Window)):
            wall = wall_lookup.get(obj.host_wall_id)
            if wall is None:
                # In practice unreachable given the validate-first
                # policy above (model.validate() already requires
                # every opening's host_wall_id to exist as a Wall
                # object) -- kept as defensive code in case that
                # invariant is ever loosened, same as the analogous
                # branch in export/ifc_export.py.
                warnings.append(
                    f"{obj.id}: host wall not exported, skipping"
                )
                continue
            layer = (
                LAYER_DOORS if isinstance(obj, Door) else LAYER_WINDOWS
            )
            rect = _opening_rectangle(
                wall, obj.position_on_wall, obj.width
            )
            if rect:
                msp.add_lwpolyline(
                    rect, close=True, dxfattribs={"layer": layer}
                )

    doc.saveas(path)
    return warnings
