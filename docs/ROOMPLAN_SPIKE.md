# RoomPlan Build-vs-Buy Spike

**Status:** Desk research complete. Recommendation:
build our own pipeline (already underway in `geometry/`)
using raw ARKit capture, with RoomPlan kept only as an
offline accuracy benchmark -- not a production dependency.
See Section 6 for full reasoning.

**Per V1 spec Section 21:** time-boxed evaluation of whether
Apple's RoomPlan API covers enough of this project's wall/
room/opening detection to justify using it instead of (or
alongside) the custom pipeline already built in `geometry/`.

This project is meant to be a genuinely owned system --
used for real work by an organization, not an Apple-API
wrapper -- so "does RoomPlan work well" is a necessary
question but not sufficient on its own. The deciding
question is narrower: **does depending on RoomPlan help
or hurt building something this project actually owns and
can extend?**

---

## 1. The Question

This repo's `geometry/` package (`wall_fitting.py`,
`room_extraction.py`, `opening_detection.py`,
`height_inference.py`) solves wall clustering, room-polygon
extraction, and door/window detection from scratch, as
explicit DSA problems. Apple ships a framework, RoomPlan,
that claims to solve the same problem end-to-end on-device
for LiDAR-equipped iPhones/iPads.

**Does adopting RoomPlan let us skip (some or all) of the
custom geometry pipeline, or does it fall short in ways that
mean the custom pipeline is still required?**

---

## 2. What RoomPlan Actually Does

RoomPlan is a first-party Apple framework (not a raw ARKit
plane detector) that runs entirely on-device, using the
LiDAR scanner plus two neural networks: one that detects
walls and openings as 2D lines and lifts them into 3D using
estimated wall height, and a second that detects doors and
windows on the 2D wall planes before projecting them into 3D.

It outputs a `CapturedRoom` structure containing:

- **Surfaces**: walls, doors, windows, and openings
  (passages without doors), each with confidence,
  dimensions, and a 3D transform.
- **Objects**: 16 furniture/fixture categories (bed, chair,
  sofa, table, dishwasher, oven, refrigerator, sink, stove,
  bathtub, toilet, washer, dryer, fireplace, stairs,
  storage, television), each with an oriented bounding box.
- A parametric 3D model, exportable as USD/USDZ.

Device support matches this project's own V1 spec target
almost exactly: LiDAR-equipped iPhone Pro and iPad Pro
(2020+) models.

Reported accuracy is "within a few centimeters," which is
in the same range as this project's own V1 accuracy target
(±1-3cm, "Architectural Mode," per the master spec).

As of iOS 17, RoomPlan can run on a custom `ARSession` with
`ARWorldTrackingConfiguration`, which opens the door to
capturing RoomPlan's structured output AND raw ARKit
scene geometry/depth in the same session -- relevant if we
want RoomPlan's walls/openings but still want raw point
data for our own height-inference or confidence pipeline.

---

## 3. Capability Match Against This Repo's Pipeline

| This repo's algorithm | RoomPlan equivalent | Verdict |
|---|---|---|
| `wall_fitting.py` (cluster + fit wall centerlines from noisy multi-frame observations) | Built into the wall-detection neural network; not exposed as a separate step | RoomPlan likely subsumes this for supported room shapes |
| `room_extraction.py` (planar-graph face traversal, T-junction splitting) | RoomPlan outputs individual room "surfaces," not an explicit room-polygon graph; multi-room merging exists via `CapturedRoom` combination but the graph-topology reasoning is internal/opaque | Partial overlap -- our explicit graph gives us T-junction handling and confidence per relationship, which RoomPlan doesn't expose |
| `opening_detection.py` (interval merging for door/window gaps) | Built into the door/window detection network | RoomPlan likely subsumes this |
| `height_inference.py` (robust floor/ceiling elevation from noisy z-samples) | RoomPlan estimates wall height directly, mechanism not published | Unclear whether RoomPlan's robustness to outliers matches our density-threshold approach -- untested |

---

## 4. Real Limitations (Not Just Marketing Gaps)

These are documented constraints, not guesses:

- **Session length cap**: recommended max 5 minutes per
  scan. A large multi-room home may need multiple sessions
  stitched together.
- **Room size cap**: ~30ft x 30ft (9m x 9m) recommended
  maximum per room.
- **Lighting sensitivity**: minimum ~50 lux; dark rooms
  degrade quality noticeably.
- **Known failure modes**: open doors, large mirrors,
  higher-than-standard ceilings, and glossy/dark surfaces
  all cause documented detection problems.
- **No IFC/BIM export**: RoomPlan exports USD/USDZ only.
  Getting to IFC (this project's V1 export target) would
  still require a translation layer -- RoomPlan does not
  remove the need for `export/ifc_export.py` or an
  equivalent.
- **No confidence-sorted review queue semantics**: RoomPlan
  gives per-surface confidence values, but nothing like
  this project's `review/queue.py` + `correction_session.py`
  workflow for turning low-confidence detections into a
  guided human-correction flow. That layer is 100% still
  needed regardless of which detector produces the raw
  surfaces.
- **Straight walls / Manhattan-ish assumption**: consistent
  with this repo's own V1 assumption (spec Section 4), so
  not a new constraint, but confirms neither approach
  currently handles curved or heavily non-orthogonal walls.
- **On-device only, real-time**: RoomPlan scanning happens
  live during capture, not as a batch/server-side job. This
  is a genuinely different architecture than this project's
  planned "capture bundle upload -> async server-side
  reconstruction" pipeline (V1 spec Section 14). Adopting
  RoomPlan would shift wall/room detection from server-side
  to on-device, which has real implications for where
  compute cost lives and how corrections get merged back in.

---

## 5. What's NOT Answered Yet (needs hands-on testing)

This is desk research, not a hands-on trial. These are
now benchmark-tooling questions, not production-dependency
questions, given the Section 6 recommendation:

1. **How our own pipeline's accuracy compares to
   RoomPlan's on the same physical rooms.** Needs a
   physical LiDAR device: scan the same 3-5 rooms with
   both RoomPlan and this project's raw-ARKit capture
   path, run both through the same ground-truth evaluation
   (V1 spec Section 18), and compare wall/room/opening
   error directly. This is the actual point of keeping
   RoomPlan around at all.
2. **Whether raw ARKit Scene Reconstruction + depth +
   pose (the input this project's pipeline needs) is
   accessible without going through RoomPlan's higher-level
   API.** Should be straightforward -- ARKit's Scene
   Reconstruction and depth APIs are independent of
   RoomPlan -- but needs confirming against current ARKit
   docs when the capture app work starts.
3. **Whether `height_inference.py`'s outlier-rejection
   approach actually helps on real (not synthetic) noisy
   z-samples**, compared to whatever RoomPlan's wall-height
   estimation does internally. Only testable with real
   scan data.
4. **Multi-room stitching in our own `room_extraction.py`
   on real, not synthetic, wall data** -- the T-junction
   splitting logic is verified against synthetic noise
   (see `tests/test_all.py`), but real sensor noise may
   have different characteristics worth re-tuning
   `wall_fitting.py`'s `angle_tol_deg`/`offset_tol` and
   `room_extraction.py`'s T-junction `tol` against.

---

## 6. Recommendation (Revised)

**Do not depend on RoomPlan's `CapturedRoom` as the
production data source. Use raw ARKit capture (depth,
pose, mesh) as the input, and run this repo's own
geometry pipeline as the production detector. Use RoomPlan
only as an offline accuracy benchmark, not a runtime
dependency.**

This reverses the initial draft recommendation in this
document. Reasoning for the reversal:

- **Ownership.** `CapturedRoom` is Apple's black box --
  two neural networks whose internals aren't published,
  aren't debuggable, and can't be improved or adapted by
  this project. Every algorithm in `geometry/`
  (`wall_fitting.py`'s union-find clustering,
  `room_extraction.py`'s planar-graph face traversal,
  `height_inference.py`'s density-threshold outlier
  rejection) is fully understood, tested, and owned by
  this project. That's not a nice-to-have -- it's the
  difference between a real product and an Apple-API
  wrapper with a UI on top.
- **Platform independence.** RoomPlan is iOS/LiDAR-only,
  permanently. If this project ever wants Android ToF
  sensors, professional scanner point clouds (V1 spec
  Section 5.4), or photogrammetry from ordinary photos
  (Section 5.1), an own-pipeline approach extends there
  naturally -- a RoomPlan-dependent one does not, since
  `CapturedRoom` has no equivalent on any other platform.
- **Architecture control.** RoomPlan forces real-time,
  on-device processing. This project's planned architecture
  (V1 spec Section 14: capture bundle upload -> async
  server-side reconstruction) needs raw sensor data, not a
  pre-baked on-device result, to keep compute, confidence
  scoring, and correction-queue logic server-side and
  centrally improvable. Depending on RoomPlan's on-device
  result would lock the whole pipeline's intelligence
  inside Apple's runtime, unable to improve without an
  App Store update.
- **Organizational control.** For real use by an
  organization, being able to retrain, tune, recalibrate,
  or extend the detection pipeline based on this
  project's own accumulated scan data (V1 spec Section 19,
  "Dataset Strategy") matters. RoomPlan gives no path to
  that -- its models are Apple's, tuned on Apple's data,
  frozen at whatever Apple ships in a given iOS version.

**What RoomPlan is still genuinely useful for:**

1. **A benchmark, not a dependency.** Scan the same rooms
   with both RoomPlan and this project's raw-ARKit pipeline,
   compare wall/room/opening accuracy against the same
   ground truth (V1 spec Section 18). This tells us
   objectively how good our own algorithms are and where
   they need work, without coupling production code to
   Apple's API.
2. **A fast internal prototyping tool** during early
   development -- e.g. quickly checking "does this room
   layout look plausible" while the raw-ARKit capture path
   is still being built, without it ever touching the
   production Building Model.
3. **A reference for capture UX.** RoomPlan's guided-scan
   coverage UI (live wall-coverage feedback, minimum scan
   requirements) is a good design reference for this
   project's own capture app (V1 spec Section 3), even
   though the underlying detection stays independent.

**Concrete next step, revised:** the capture-app work
(V1 spec Section 3 / Phase 4) should target raw ARKit
Scene Reconstruction + depth + pose capture directly --
the same input shape `examples/synthetic_house.py` already
simulates with `make_noisy_observations()` and
`make_noisy_z_samples()`. RoomPlan is set aside as an
optional benchmarking tool, run separately, never imported
into the production pipeline.

---

## References

- Apple Machine Learning Research, "3D Parametric Room
  Representation with RoomPlan":
  https://machinelearning.apple.com/research/roomplan
- Apple Developer, WWDC23 "Explore enhancements to
  RoomPlan": https://developer.apple.com/videos/play/wwdc2023/10192/
- it-jim, "Apple RoomPlan API Integration for Innovative
  AR Apps": https://www.it-jim.com/blog/apple-roomplan-api/
- Scan Manifold, "Apple RoomPlan for Contractors 2026":
  https://www.scanmanifold.com/blog-posts/roomplan-scan-contractors
- itechcraft, "Your 101 Guide to Using Apple RoomPlan API":
  https://itechcraft.com/blog/your-101-guide-to-using-apple-roomplan-api-for-your-next-app/