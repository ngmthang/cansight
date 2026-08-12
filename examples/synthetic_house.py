"""
    End-to-end demo (Phase 3 of the roadmap, run early against
    synthetic data):

      noisy segment "observations" (stand-in for real LiDAR
      wall detections)
            -> wall_fitting.fit_walls()        [clean centerlines]
            -> room_extraction.extract_rooms() [room polygons]
            -> BuildingModel                   [objects + relationships]
            -> export_to_ifc()                 [validated IFC file]

    This is exactly the pipeline in V1 spec Section 5, minus the
    point-cloud steps that need real sensor data (Phase 4). Running
    this against synthetic data now proves the geometry + schema +
    export layers work before any hardware/capture work begins.

    :author: Minh Thang Nguyen
    :version: August 11, 2026
"""

import sys
import os
import random

sys.path.insert(
    0, os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)

from geometry.wall_fitting import fit_walls
from geometry.room_extraction import extract_rooms, room_area
from geometry.height_inference import estimate_floor_and_ceiling
from building_model.schema import BuildingModel
from export.ifc_export import export_to_ifc


def make_noisy_observations(
    true_walls, n_observations=5, noise=0.02, seed=1
):
    random.seed(seed)
    noisy = []
    for a, b in true_walls:
        for _ in range(n_observations):
            jitter = lambda: random.uniform(-noise, noise)
            noisy.append(
                (
                    (a[0] + jitter(), a[1] + jitter()),
                    (b[0] + jitter(), b[1] + jitter()),
                )
            )
    return noisy


def make_noisy_z_samples(true_floor=0.0, true_ceiling=2.4, seed=2):
    """Simulates vertical point-cloud samples along a wall face: dense
    returns at floor/ceiling, sparse clutter in between, a couple of
    genuine outliers -- same scenario height_inference.py is designed for.
    """
    random.seed(seed)
    samples = []
    samples += [
        true_floor + random.uniform(-0.005, 0.005) for _ in range(80)
    ]
    samples += [
        true_ceiling + random.uniform(-0.005, 0.005) for _ in range(80)
    ]
    samples += [
        random.uniform(true_floor + 0.1, true_ceiling - 0.1)
        for _ in range(15)
    ]
    samples += [true_floor - 0.3, true_ceiling + 0.5]  # sensor outliers
    random.shuffle(samples)
    return samples


def main():
    # Ground truth: a two-room house, 8m x 4m split by a dividing wall
    # at x=4
    true_walls = [
        ((0, 0), (4, 0)),
        ((4, 0), (8, 0)),
        ((8, 0), (8, 4)),
        ((8, 4), (4, 4)),
        ((4, 4), (0, 4)),
        ((0, 4), (0, 0)),
        ((4, 0), (4, 4)),  # dividing wall
    ]

    print("=== 1. Simulating noisy multi-frame observations ===")
    noisy_segments = make_noisy_observations(
        true_walls, n_observations=5, noise=0.02
    )
    print(
        f"{len(noisy_segments)} noisy segment observations "
        f"from {len(true_walls)} true walls"
    )

    print(
        "\n=== 2. Wall fitting "
        "(clustering + total-least-squares) ==="
    )
    fitted = fit_walls(noisy_segments)
    print(
        f"Fitted {len(fitted)} clean walls from "
        f"{len(noisy_segments)} noisy observations"
    )
    for w in fitted:
        (x0, y0), (x1, y1) = w.centerline
        print(
            f"  ({x0:.2f},{y0:.2f}) -> ({x1:.2f},{y1:.2f})  "
            f"support={w.support_count}"
        )

    print("\n=== 3. Room extraction (planar graph face traversal) ===")
    wall_segments = [w.centerline for w in fitted]
    rooms = extract_rooms(wall_segments)
    print(f"Extracted {len(rooms)} rooms")
    for r in rooms:
        rounded = [(round(x, 2), round(y, 2)) for x, y in r]
        print(
            f"  area={room_area(r):.2f} m^2, boundary={rounded}"
        )

    print(
        "\n=== 4. Height inference "
        "(floor/ceiling from noisy z samples) ==="
    )
    z_samples = make_noisy_z_samples(true_floor=0.0, true_ceiling=2.4)
    height_est = estimate_floor_and_ceiling(z_samples)
    print(
        f"floor_elevation={height_est.floor_elevation:.3f} m, "
        f"ceiling_elevation={height_est.ceiling_elevation:.3f} m, "
        f"height={height_est.height:.3f} m"
    )
    print(
        f"({height_est.sample_count} samples, "
        f"{height_est.outliers_rejected} outliers rejected)"
    )

    print("\n=== 5. Assembling Building Model (now with 3D) ===")
    bm = BuildingModel(building_id="synthetic_house_01")
    bm.add_level("L1", elevation=height_est.floor_elevation)

    wall_ids = []
    for w in fitted:
        obj = bm.add_wall(
            "L1",
            w.centerline,
            thickness=0.12,
            height=height_est.height,
            confidence=min(1.0, 0.5 + 0.08 * w.support_count),
        )
        wall_ids.append(obj.id)

    for r in rooms:
        bm.add_floor(
            "L1",
            r,
            elevation=height_est.floor_elevation,
            confidence=0.9,
        )
        bm.add_ceiling(
            "L1",
            r,
            elevation=height_est.ceiling_elevation,
            confidence=0.9,
        )
        room = bm.add_room(
            "L1",
            r,
            bounded_by=wall_ids,
            classification="unclassified",
            floor_elevation=height_est.floor_elevation,
            ceiling_elevation=height_est.ceiling_elevation,
            confidence=0.85,
        )
        print(
            f"  room {room.id}: area={room.area():.2f} m^2, "
            f"height={room.height():.2f} m, "
            f"volume={room.volume():.2f} m^3"
        )

    errors = bm.validate()
    print(f"\nValidation errors: {errors if errors else 'none'}")

    print("\n=== 6. Exporting to IFC ===")
    out_path = os.path.join(
        os.path.dirname(__file__), "synthetic_house.ifc"
    )
    warnings = export_to_ifc(bm, out_path)
    print(f"Exported to {out_path}, warnings: {warnings or 'none'}")


if __name__ == "__main__":
    main()