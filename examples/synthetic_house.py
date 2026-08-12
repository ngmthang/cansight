"""
    End-to-end demo (Phase 3 of the roadmap, run early against synthetic data):

        noisy segment "observations" (stand-in for real LiDAR wall detections)
            -> wall_fitting.fit_walls() [clean centerlines]
            -> room_extraction.extract_rooms() [room polygons]
            -> BuildingModel [semantic objects + relationships]
            -> export_to_ifc() [validated IFC file]

    This is exactly the pipeline in V1 spec Section 5, minus the point-cloud
    steps that need real sensor data (Phase 4). Running this against
    synthetic data now proves the geometry + schema + export layers work
    before any hardware/capture work begins.

    @author: Minh Thang Nguyen
    @version: August 10, 2026
"""


import sys
import os
import random

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from geometry.wall_fitting import fit_walls
from geometry.room_extraction import extract_rooms, room_area
from building_model.schema import BuildingModel
from export.ifc_export import export_to_ifc


def make_noisy_observations(true_walls, n_observations=5, noise=0.02, seed=1):
    random.seed(seed)
    noisy = []
    for (a, b) in true_walls:
        for _ in range(n_observations):
            jiiter = lambda: random.uniform(-noise, noise)
            noisy.append((
                (a[0], jiiter(), a[1] + jiiter()),
                (b[0], jiiter(), b[1] + jiiter()),
            ))
    return noisy


def main():
    # Ground truth: a two-room house, 8m x 4m split by a dividing wall at x=4
    true_walls = [
        ((0, 0), (4, 0)), ((4, 0), (8, 0)),
        ((8, 0), (8, 4)),
        ((8, 4), (4, 4)), ((4, 4), (0, 4)),
        ((0, 4), (0, 0)),
        ((4, 0), (4, 4)), # dividing wall
    ]

    print("=== 1. Simulation noisy multi-frame observations ===")
    noisy_segments = make_noisy_observations(true_walls, n_observations=5, noise=0.02)
    print(f"{len(noisy_segments)} noisy segment observations from {len(true_walls)} true walls")

    print("\n=== 2. Wall fitting (clustering + total-least_squares) ===")
    fitted = fit_walls(noisy_segments)
    print(f"Fitted {len(fitted)} clean walls from {len(noisy_segments)} noisy observations")
    for w in fitted:
        (x0, y0), (x1, y1) = w.centerline
        print(f" ({x0:.2f},{y0:.2f}) -> ({x1:.2f},{y1:.2f}) support={w.support_count}")

    print("\n=== 3. Room extraction (planar graph face traversal) ===")
    wall_segments = [w.centerline for w in fitted]
    rooms = extract_rooms(wall_segments)
    print(f"Extracted {len(rooms)} rooms")
    for r in rooms:
        print(f" area={room_area(r):.2f} m^2, boundary={[(round(x,2),round(y,2)) for x,y in r]}")

    print("\n=== 4. Assembling Building Model ===")
    bm = BuildingModel(building_id="synthetic_house_01")
    bm.add_level("L1")

    wall_ids = []
    for w in fitted:
        obj = bm.add_wall("L1", w.centerline, thickness=0.12, height=2.4,
                          confidence=min(1.0, 0.5 + 0.08 * w.support_count))
        wall_ids.append(obj.id)

    for i, r in enumerate(rooms):
        bm.add_room("L1", r, bounded_by=wall_ids, classification="unclassified",
                    confidence=0.85)

    errors = bm.validate()
    print(f"Validation errors: {errors if errors else 'none'}")

    print("\n=== 5. Export to IFC ===")
    out_path = os.path.join(os.path.dirname(__file__), "synthetic_house.ifc")
    warnings = export_to_ifc(bm, out_path)
    print(f"Exported to {out_path}, warnings: {warnings or 'none'}")


if __name__ == "__main__":
    main()