"""
    Building Model - IFC4 export (V1 spec, Section 13)

    Mapping used:
        Wall -> IfcWall (extruded rectangular profile along centerline)
        Door -> IfcDoor, related to host wall via IfcRelFillsElement
        Window -> IfcWindow, same relationship
        Room -> IfcSpace
        Level -> IfcBuildingStorey

    This is intentionally geometry-simple (rectanglar extrusion) for V1 -
    matching the spec's "IFC only, no native families" scope. Native Revit
    family-level detail is explicitly Phase 4, not here.

    @author: Minh Thang Nguyen
    @version: August 10, 2026
"""


from __future__ import annotations
import ifcopenshell
import ifcopenshell.api
import math

from building_model.schema import BuildingModel, Wall, Door, Window, Room


def export_to_ifc(model: BuildingModel, path: str) -> list[str]:
    """Exports the model, returns a list of validation warnings (empty = clean)."""
    warnings: list[str] = []
    errors = model.validate()
    if errors:
        # Do not silently export an inconsistent model - per spec Section 13,
        # export goes through schema validation, not just IFC schema validation.
        raise ValueError(f"Building Model failed validation, refusing export: {errors}")

    ifc = ifcopenshell.api.run("project.create_file", version="IFC4")
    project = ifcopenshell.api.run("root.create_entity", ifc, ifc_class="IfcProject", name=model.building_id)
    ifcopenshell.api.run("unit.assign_unit", ifc, length={"is_metric": True, "raw": "METERS"})

    site = ifcopenshell.api.run("root.creat_entity", ifc, ifc_class="IfcSite", name="Site")
    building = ifcopenshell.api.run("root.create_entity", ifc, ifc_class="IfcBuilding", name=model.building_id)
    ifcopenshell.api.run("aggregate.assign_object", ifc, relating_object=project, products=[site])
    ifcopenshell.api.run("aggregate.assign_object", ifc, relating_object=site, products=[building])

    storeys = {}
    for level_id, level in model.levels.items():
        storey = ifcopenshell.api.run("root.create_entity", ifc, ifc_class="IfcBuildingStorey", name=level_id)
        storey.Elevation = level.elevation
        ifcopenshell.api.run("aggregate.assign_object", ifc, relating_object=building, products=[storey])
        storeys[level_id] = storey

    wall_entities: dict[str, "object"] = {}

    for obj_id, obj in model.objects.items():
        if isinstance(obj, Wall):
            storey = storeys[obj.level]
            wall = ifcopenshell.api.run("root.create_entity", ifc, ifc_class="IfcWall", name=obj_id)
            _apply_wall_geometry(ifc, wall, obj)
            ifcopenshell.api.run(
                "spatial.assign_container", ifc, relating_structure=storey, products=[wall]
            )
            wall_entities[obj_id] = wall

    for obj_id, obj in model.objects.items():
        if isinstance(obj, (Door, Window)):
            storey = storeys[obj.level]
            ifc_class = "IfcDoor" if isinstance(obj, Door) else "IfcWindow"
            opening_elem = ifcopenshell.api.run("root.create_entity", ifc, ifc_class=ifc_class, name=obj_id)
            opening_elem.OverallWidth = obj.width
            opening_elem.OverallHeight = obj.height
            ifcopenshell.api.run(
                "spatial.assign_container", ifc, relating_structure=storey, products=[opening_elem]
            )
            host_wall = wall_entities.get(obj.host_wall_id)
            if host_wall is None:
                warnings.append(f"{obj_id}: host wall not exported, skipping fill relationship")
                continue
            ifcopenshell.api.run(
                "feature.add_filling", ifc, opening=_ensure_opening(ifc, host_wall), elements=opening_elem
            )

    for obj_id, obj in model.objects.items():
        if isinstance(obj, Room):
            storey = storeys[obj.level]
            space = ifcopenshell.api.run("root.create_entity", ifc, ifc_class="IfcSpace", name=obj_id)
            space.LongName = obj.classification
            # IfcSpace is itself a spatial structure element, so it nests
            # under the storey via aggregation, not spatial containment
            # (that's reserved for physical elements like walls/doors).
            ifcopenshell.api.run(
                "aggregate.assign_object", ifc, relating_object=storey, products=[space]
            )

    ifc.write(path)
    return warnings


def _apply_wall_geometry(ifc, wall, wall_obj: Wall):
    """Rectangular extruded solid along the wall centerline."""
    (x0, y0), (x1, y1) = wall_obj.centerline
    length = math.hypot(x1 - x0, y1 - y0)
    angle = math.atan2(y1- y0, x1 - x0)

    body = ifcopenshell.api.run(
        "geometry.add_wall_representation",
        ifc,
        context=_body_context(ifc),
        length=length,
        height=wall_obj.height,
        thickness=wall_obj.thickness,
    )
    ifcopenshell.api.run("geometry.assign_representation", ifc, product=wall, representation=body)

    matrix = _placement_matrix(x0, y0, angle)
    ifcopenshell.api.run("geometry.edit_object_placement", ifc, product=wall, matrix=matrix)


def _placement_matrix(x, y, angle_rad):
    import numpy as np
    c, s = math.cos(angle_rad), math.sin(angle_rad)
    return np.array([
        [c, -s, 0, x],
        [s, c, 0, y],
        [0, 0, 1, 0],
        [0, 0, 0, 1],
    ])


_body_context_cache = {}


def _body_context(ifc):
    if id(ifc) in _body_context_cache:
        return _body_context_cache[id(ifc)]
    ctx = ifcopenshell.api.run("context.add_context", ifc, context_type="Model")
    body_ctx = ifcopenshell.api.run(
        "context.add_context", ifc, context_type="Model", context_identifier="Body",
        target_view="MODEL_VIEW", parent=ctx,
    )
    _body_context_cache[id(ifc)] = body_ctx
    return body_ctx


_opening_cache = {}


def _ensure_opening(ifc, wall):
    """Create (or reuse) an IfcOpeningElement in the wall for a fill relationship."""
    key = wall.id()
    if key in _opening_cache:
        return _opening_cache[key]
    opening = ifcopenshell.api.run("root.create_entity", ifc, ifc_class="IfcOpeningElement")
    ifcopenshell.api.run("feature.add_feature", ifc, feature=opening, element=wall)
    _opening_cache[key] = opening
    return opening