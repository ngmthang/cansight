# Cansight / Reality Capture -> BIM: Project Status

**Purpose of this document:** paste this as the first message in a
new chat to continue development with full context, without
needing the (very long) conversation history that produced it.

---

## 1. What This Project Is

Personal + organizational tool: capture real interior spaces
(iPhone/iPad camera + LiDAR or plane detection) and turn them into
an editable, structured Building Information Model, exportable to
IFC. Full vision and phased roadmap: see
`V1_Technical_Specification.md` in the repo root.

**Core strategic decision (see `docs/ROOMPLAN_SPIKE.md`):** this
project owns its detection pipeline from raw ARKit data rather than
depending on Apple's RoomPlan API. RoomPlan is kept only as a
future offline accuracy benchmark. This was a deliberate trade:
higher upfront engineering cost, in exchange for platform
independence, architectural control (server-side processing later),
and organizational ability to recalibrate/extend the pipeline using
accumulated real capture data -- something a black-box API can
never offer.

---

## 2. Current Architecture

Capture (iOS, Swift, in ios/RealityCaptureBIM/)
| writes a "bundle": manifest.json + (points.json | planes.json)
v
geometry/capture_ingestion.py -- bundle format contract, dispatch
|
+-- LiDAR path: geometry/plane_detection.py (RANSAC plane seg)
+-- non-LiDAR path: sparse per-plane line fitting
v
geometry/wall_fitting.py -- cluster/merge wall observations
geometry/room_extraction.py -- planar-graph room polygon extraction
geometry/height_inference.py -- floor/ceiling elevation estimate
geometry/opening_detection.py -- door/window gap detection
v
building_model/schema.py -- BuildingModel: source of truth
v
review/queue.py -- confidence-sorted correction queue
review/correction_session.py -- apply human corrections
review/formatting.py -- unit-aware display strings
units.py -- feet/inches <-> meters
v
export/ifc_export.py -- validated IFC4 output
webapp/server.py + static/ -- local browser UI over all of the above


Every algorithm above is original, from-scratch, and unit-tested.
Nothing in this chain calls RoomPlan or any other third-party
detection API.

---

## 3. What's Built and Tested (76/76 passing as of this handoff)

| Area | File(s) | Tests |
|---|---|---|
| Building Model + validation | `building_model/schema.py` | 8 |
| Units (feet/inches display+parsing) | `units.py` | 15 |
| Review/correction backend | `review/*.py` | 13 |
| 3D extension (floor/ceiling/volume, opening containment) | `building_model/schema.py`, `geometry/height_inference.py` | 11 |
| LiDAR capture ingestion (RANSAC) | `geometry/plane_detection.py`, `capture_ingestion.py` | 10 |
| Non-LiDAR capture ingestion (sparse plane fitting) | `capture_ingestion.py` | 9 |
| Web review UI backend (Flask API) | `webapp/server.py` | 10 |

Run everything:
```powershell
cd reality-capture-bim
python tests\test_all.py
python tests\test_units.py
python tests\test_correction_session.py
python tests\test_3d_extension.py
python tests\test_capture_ingestion.py
python tests\test_non_lidar_capture.py
python tests\test_webapp.py
```

Run the web UI locally:
```powershell
python webapp\server.py
```
Then open `http://127.0.0.1:5000`.

---

## 4. Real-World Validation (not just synthetic)

Tested against real captures from an iPad (A16, non-LiDAR --
falls back to ARKit plane-detection mode automatically) via Swift
Playgrounds (no Mac/Xcode available, see `ios/README.md`). This
surfaced two real, non-obvious findings synthetic testing had
missed:

1. **Sparse per-plane line fits have much higher angular noise**
   than dense LiDAR clusters -- `wall_fitting.fit_walls()`'s
   default clustering tolerance (6deg/0.08m) was too tight for
   real non-LiDAR data. Fixed by exposing `angle_tol_deg`/
   `offset_tol` as parameters and using looser values (25deg/
   0.25m) specifically in the non-LiDAR ingestion path.
2. **Furniture occlusion is the realistic common case, not an
   edge case.** A real furnished room produced wall fragments with
   genuine gaps (furniture blocking the camera's view of that wall
   segment) that no tolerance tuning can safely bridge. This led
   to `review/correction_session.py`'s `add_manual_wall()` -- a
   human-in-the-loop capability the original spec called for
   (Section 15, "Add missing elements") but that had never been
   implemented until real data proved it necessary. The web UI's
   "Draw Missing Wall" feature is the actual usable interface for
   this.

**Takeaway for continued development:** keep accumulating real
capture bundles as permanent test fixtures, not just one-off
debugging sessions. `tests/test_capture_ingestion.py` and
`tests/test_non_lidar_capture.py` currently only use synthetic
data -- promoting 1-2 real captures (anonymized/simplified as
needed) into permanent regression fixtures would catch future
calibration drift automatically instead of requiring another
live debugging session like the one that found the issues above.

---

## 5. Known Gaps / Deferred Work

See `docs/BACKLOG.md` for full detail on deferred features
(currently: furniture-aware automated wall detection). Additional
gaps not yet in that file:

- **No persistent storage.** `webapp/server.py`'s model/queue
  state is an in-memory global, lost on restart, single-model-
  at-a-time. Fine for solo use; blocks any multi-user or
  multi-project use. V1 spec Section 15 ("Database/storage
  architecture") was never implemented.
- **Bundle loading requires a local filesystem path.** The web UI's
  "Load Bundle" assumes the Flask process can see the bundle
  directory directly. No upload mechanism exists yet -- a real
  blocker the moment the web UI isn't run on the same machine the
  bundle was transferred to.
- **Manhattan-alignment rotation not implemented**
  (`capture_ingestion.py`'s axis conversion does the ARKit-Y-up ->
  model-Z-up relabel only, not rotation to the dominant wall
  direction, per V1 spec Section 4).
- **iOS app only verified via Swift Playgrounds**, not real Xcode
  -- no Mac/Xcode access during this development. LiDAR mode
  (`ARCaptureSession.swift`'s primary path) has never run on real
  hardware; only the non-LiDAR plane-detection fallback has.
- **Non-LiDAR confidence formulas are placeholders**
  (`min(0.6, 0.3 + 0.05*support_count)` for walls) -- reasonable
  defaults, not yet calibrated against a real ground-truth
  evaluation the way V1 spec Section 18 describes.

---

## 6. Practical Path Forward (recommended priority order)

If continuing to build toward actual organizational use (per the
original stated goal), in priority order:

1. **Bundle upload endpoint** in `webapp/server.py` -- accept a
   zipped bundle via HTTP POST instead of requiring a local path.
   Small, high-value, unblocks using the web UI from a different
   machine than the one holding the bundle files.
2. **Swap in-memory `_state` for lightweight persistence** (SQLite
   is proportionate at this scale -- no need for a heavier DB yet).
   Enables multiple buildings/projects to coexist and survive a
   restart.
3. **Grow the real-capture regression corpus** -- formalize 1-2 of
   the real bundles already captured into permanent test fixtures.
4. **Real Xcode/Mac access**, whenever feasible, to validate the
   LiDAR capture path (`ARCaptureSession.swift`'s primary mode) on
   real hardware -- currently completely unverified.
5. Everything in `docs/BACKLOG.md` (furniture-aware detection) and
   the "Explicitly NOT implemented" list in `ios/README.md`
   (guided coverage UI, multi-room stitching, upload/networking).

---

## 7. How to Continue

This repo is at `https://github.com/ngmthang/cansight` (folder
`reality-capture-bim/`). Clone/pull, confirm all 76 tests pass
locally, then pick up from Section 6's priority list, or address
whatever specific need prompted returning to this project.