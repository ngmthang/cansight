import sys
import os

sys.path.insert(
    0, os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)

from geometry.capture_ingestion import (
    ingest_capture, build_building_model_from_capture,
)

result = ingest_capture(r"C:\Users\nguye\Desktop\cansight\reality-capture-bim\tests\test_bundle")
bm = build_building_model_from_capture(result, "real_test")
print(bm.validate())
print(f"{len(result.fitted_walls)} walls detected")

print(f"floor={result.height_estimate.floor_elevation:.3f} "
      f"ceiling={result.height_estimate.ceiling_elevation:.3f} "
      f"height={result.height_estimate.height:.3f}")

room_count = len([o for o in bm.objects.values() if o.type.value == "room"])
print(f"{room_count} rooms found")

print()
print("=== wall details ===")
for obj in bm.objects.values():
    if obj.type.value == "wall":
        (x0, y0), (x1, y1) = obj.centerline
        length = ((x1-x0)**2 + (y1-y0)**2) ** 0.5
        print(f"  length={length:.2f}m confidence={obj.confidence:.2f}")

print()
print("=== wall endpoints ===")
for obj in bm.objects.values():
    if obj.type.value == "wall":
        (x0, y0), (x1, y1) = obj.centerline
        print(f"  ({x0:.2f},{y0:.2f}) -> ({x1:.2f},{y1:.2f})")
