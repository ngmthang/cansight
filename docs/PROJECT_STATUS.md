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

```
Capture (iOS, Swift, in ios/RealityCaptureBIM/)
   |  writes a "bundle": manifest.json + (points.json | planes.json)
   |  live capture also shows real-time plane/mesh overlays
   |  (confirmed working on real hardware, see Section 4 item 5)
   v
geometry/capture_ingestion.py   -- bundle format contract, dispatch
   |
   +-- LiDAR path: geometry/plane_detection.py (RANSAC plane seg)
   +-- non-LiDAR path: sparse per-plane line fitting
   v
geometry/wall_fitting.py        -- cluster/merge wall observations
geometry/room_extraction.py     -- planar-graph room polygon extraction
geometry/height_inference.py    -- floor/ceiling elevation estimate
geometry/opening_detection.py   -- door/window gap detection
   v
building_model/schema.py        -- BuildingModel: source of truth
   v
review/queue.py                 -- confidence-sorted correction queue
review/correction_session.py    -- apply human corrections
review/formatting.py            -- unit-aware display strings
units.py                        -- feet/inches <-> meters
   v
export/ifc_export.py            -- validated IFC4 output (-> Revit,
                                    via Revit's native IFC import)
export/dxf_export.py             -- DXF floor plan (-> AutoCAD
                                    directly, -> SketchUp via its
                                    built-in DXF import)
webapp/server.py + static/      -- local browser UI over all of the above
webapp/storage.py               -- SQLite persistence (multi-project,
                                    survives restart)
```

Every algorithm above is original, from-scratch, and unit-tested.
Nothing in this chain calls RoomPlan or any other third-party
detection API.

**Export coverage:** all three originally-requested CAD/BIM targets
(AutoCAD, Revit, SketchUp) now have a real path -- two of them
sharing a single DXF exporter rather than three separate efforts.
No native `.rvt`/`.skp` writers exist (those would need the Revit
API in C#/.NET, and SketchUp's own SDK, respectively -- see
`docs/BACKLOG.md` if that level of native integration ever becomes
worth the much larger effort it requires).

---

## 3. What's Built and Tested (110/110 passing as of this handoff)

| Area | File(s) | Tests |
|---|---|---|
| Building Model + validation | `building_model/schema.py` | 8 |
| Units (feet/inches display+parsing) | `units.py` | 15 |
| Review/correction backend | `review/*.py` | 13 |
| 3D extension (floor/ceiling/volume, opening containment) | `building_model/schema.py`, `geometry/height_inference.py` | 11 |
| LiDAR capture ingestion (RANSAC) | `geometry/plane_detection.py`, `capture_ingestion.py` | 10 |
| Non-LiDAR capture ingestion (sparse plane fitting, false-positive filtering) | `capture_ingestion.py` | 11 |
| Web review UI backend + persistence (Flask API, SQLite, bundle upload) | `webapp/server.py`, `webapp/storage.py` | 22 |
| DXF export (AutoCAD/SketchUp) | `export/dxf_export.py` | 8 |
| Real-capture regression, fixture 1 (permanent, not synthetic) | `tests/test_real_capture_regression.py` | 6 |
| Real-capture regression, fixture 2 (desk/monitor scan) | `tests/test_real_capture_regression_2.py` | 6 |

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
python tests\test_dxf_export.py
python tests\test_real_capture_regression.py
python tests\test_real_capture_regression_2.py
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
3. **A separate, unrelated bug found while adding persistence:**
   `geometry/plane_detection.py`'s RANSAC used an internal
   `random.Random(seed=None)` instance that global `random.seed()`
   calls in tests couldn't reach, making a subset of
   `tests/test_capture_ingestion.py` flaky (~1 in 10 runs).
   Fixed by threading an explicit `seed` parameter through
   `extract_wall_candidates()` and `ingest_capture(...,
   ransac_seed=...)`. Worth knowing: production capture calls
   should still leave `ransac_seed=None` (non-determinism doesn't
   matter for real data); only tests need a fixed seed.
4. **ARKit's plane detector has no semantic understanding of what
   it's looking at.** A monitor screen got detected and visualized
   as if it were a wall during a live capture session -- ARKit only
   asks "is this flat and vertical," not "is this actually part of
   a room's structure." Fixed in
   `_ingest_plane_detection_bundle()` by filtering vertical planes
   on their VERTICAL extent (a real wall spans close to full room
   height, however narrow horizontally; a monitor/picture frame is
   short regardless of width). Threshold (0.5m) derived directly
   from real capture data: every genuine wall segment in
   `tests/fixtures/real_ipad_capture_1` spans >= 0.7m vertically;
   the confirmed false positive spanned only 0.267m.
5. **A second, independent iOS-side bug, found via screen
   recordings analyzed frame-by-frame:** `ARCaptureSession` and
   `ARSCNView` were both trying to own `ARSession.delegate` (a
   single slot) -- `ARCaptureSession` claiming it directly silently
   starved `ARSCNView` of anchor notifications, so the plane/mesh
   visual overlay never rendered even though capture itself worked
   fine. Fixed by making `ARPassthroughView.Coordinator` (an
   `ARSCNViewDelegate`) the sole delegate, forwarding every anchor
   event to `ARCaptureSession` via `handleAnchorsAdded/Updated/
   Removed`. Confirmed working via a screen recording showing
   correctly-tracked blue/green overlays across a 90+ second real
   scan. Follow-on refinements from further real-device video
   review: fill opacity tuned (0.15 was too subtle to see through
   video compression, 0.25 reads clearly); outline switched from a
   line-primitive (renders at a fixed ~1px regardless of hinted
   width) to real `SCNBox` bar geometry (guaranteed visible
   thickness); a duplicate-overlay suppression pass added, since
   ARKit's raw plane detector often reports multiple overlapping
   detections for one continuous wall in visually complex areas
   (confirmed: a desk/monitor area showed two crossing, overlapping
   boxes) -- the Python pipeline already merges these after the
   fact via `wall_fitting.fit_walls()`, but the live overlay didn't
   apply that same merging until this fix.

**Takeaway for continued development:** keep accumulating real
capture bundles as permanent test fixtures, not just one-off
debugging sessions -- this is no longer just a suggestion: two
fixtures now do exactly this
(`tests/test_real_capture_regression.py` and its counterpart `_2`),
and both proved their worth independently -- reverting the
wall-clustering tolerance to its old default changes each
fixture's wall count differently (8->9 for fixture 1's data, 9->11
for fixture 2's), confirming the regression check generalizes
rather than just happening to catch one specific case. The two
fixtures are also deliberately complementary: fixture 1's data
triggers the false-positive vertical-extent filter (one plane
correctly excluded); fixture 2's data doesn't trigger it at all
(every plane clears the threshold) -- together they confirm the
filter neither under- nor over-triggers on real data, not just on
the one scenario that originally motivated it.
Similarly worth doing: when screen recordings of real device usage
are available, extracting and reviewing actual frames (not just
trusting a written description) repeatedly surfaced real, specific,
fixable problems here that reasoning alone would have missed or
mis-diagnosed.

---

## 5. Known Gaps / Deferred Work

See `docs/BACKLOG.md` for full detail on deferred features
(currently: furniture-aware automated wall detection). Additional
gaps not yet in that file:

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
- **`webapp/storage.py` is single-machine SQLite**, not a shared
  server -- resolves "survive a restart" and "multiple projects"
  but not "multiple people accessing the same project
  concurrently." Fine for the current solo-use scope; would need
  real client-server separation for team use.
- **iOS visualization styling not re-confirmed after the latest
  round of changes.** Plane/mesh overlay rendering itself is
  confirmed working on real hardware (Section 4, item 5), but the
  most recent refinements (fill/outline styling tweaks, duplicate-
  overlay suppression) were verified through careful frame-by-frame
  screen-recording analysis, not a fresh live test on-device after
  the final version. Worth one more real scan to confirm everything
  together looks right in practice, not just in isolated review.

---

## 6. Practical Path Forward (recommended priority order)

Completed since this document was first written: bundle upload
(zip, with zip-slip protection and nested-folder handling),
SQLite-backed persistence (multi-project, survives restart,
correctly distinguishes "human reviewed this" from "confidence
happens to be high" -- see `ReviewQueue.resolved_ids()`'s
docstring for the bug this specifically avoids), DXF export
(AutoCAD directly, SketchUp via its built-in DXF import), TWO
permanent real-capture regression fixtures (up from one), a
false-positive filter for ARKit misidentifying flat objects
(monitors, picture frames) as walls -- validated both ways by the
two fixtures above -- and the iOS plane/mesh visualization overlay
(was broken due to an `ARSession.delegate` conflict, now fixed,
confirmed working, and refined for visual clarity across several
rounds of real-device video review).

If continuing to build toward actual organizational use (per the
original stated goal), in priority order:

1. **One more real scan to confirm the latest iOS visualization
   round together** (Section 5's last bullet) -- everything's been
   verified piecewise across several rounds; worth confirming it
   all reads well together in one fresh test.
2. **Real Xcode/Mac access**, whenever feasible, to validate the
   LiDAR capture path (`ARCaptureSession.swift`'s primary mode) on
   real hardware -- currently completely unverified.
3. **Grow the real-capture regression corpus further** -- now two
   fixtures (`tests/fixtures/real_ipad_capture_1` and `_2`); more
   real captures (ideally covering a wider range of room shapes,
   furniture density, lighting) would catch an even wider range of
   future calibration drift.
4. Everything in `docs/BACKLOG.md` (furniture-aware detection) and
   the "Explicitly NOT implemented" list in `ios/README.md`
   (guided coverage UI, multi-room stitching, upload/networking).
5. If/when multiple people need concurrent access:
   `webapp/storage.py`'s SQLite layer would need to become a real
   client-server backend -- not urgent at current (solo) scale.
6. **Native Revit/SketchUp exporters**, if the IFC/DXF-import paths
   ever prove insufficient -- a much larger, separate undertaking
   (Revit API in C#/.NET; SketchUp's own SDK), not something to
   start casually.

---

## 7. How to Continue

This repo is at `https://github.com/ngmthang/cansight` (folder
`reality-capture-bim/`). Clone/pull, confirm all 110 tests pass
locally, then pick up from Section 6's priority list, or address
whatever specific need prompted returning to this project.