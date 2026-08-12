<<<<<<< HEAD
# Reality Capture → BIM: V1 Foundation

This is Phase 0–2 of the build roadmap: the Building Model, the core
geometry algorithms, and the IFC export — all provable and testable
**without any real sensor data**. Phase 3 (real ARKit capture) plugs
into this foundation later without changing any of it.

## What's here and why it's built in this order

building_model/schema.py     Phase 0  Source-of-truth data model (Wall,
                                       Door, Window, Room, Level,
                                       relationships, validation)
geometry/wall_fitting.py     Phase 1  Cluster noisy multi-frame wall
                                       observations into one clean
                                       centerline per physical wall
                                       (union-find clustering +
                                       total-least-squares line fit)
geometry/room_extraction.py  Phase 1  Extract room polygons from a wall
                                       graph (planar-graph half-edge
                                       face traversal), including
                                       T-junction splitting
geometry/opening_detection.py Phase 1 Merge noisy door/window gap
                                       observations (interval merging)
review/queue.py              Phase 2  Confidence-sorted correction
                                       queue backend (min-heap, lazy
                                       deletion)
export/ifc_export.py         Phase 0  Building Model -> validated IFC4
examples/synthetic_house.py  Phase 3  Full pipeline demo on synthetic
                                       noisy data, no hardware needed
tests/test_all.py                     Regression suite for all of the
                                       above

Why this order: none of Phase 0–2 needs a phone, a scan, or any ML
model. It's pure, deterministic, fully testable code — which means we
can find and fix real bugs (and we did, see below) before spending any
effort on the much harder, much less controllable problem of real
sensor data. Phase 3's synthetic pipeline proves the whole chain works
together before Phase 4 (real capture) is even started.

## Running it

pip install ifcopenshell --break-system-packages   # only external dependency
python3 tests/test_all.py                          # 8/8 should pass
python3 examples/synthetic_house.py                # full pipeline demo

The demo prints each pipeline stage and writes `synthetic_house.ifc`
which you can open in any IFC viewer (e.g. web-ifc, BIMcollab, or
Blender's BlenderBIM addon) to see the actual geometry.

## Bugs this process already caught (worth knowing about)

Building the synthetic pipeline immediately surfaced two real
correctness bugs that would have been much harder to find later
against messy real sensor data:

1. **T-junction vertices didn't match.** A dividing wall's endpoint
   met another wall in its *middle*, not at a shared endpoint. The
   fix (`_split_at_t_junctions`) originally cut the host wall at the
   *projected* point on its line — but under real-world noise that
   projected point differs from the neighboring wall's actual endpoint
   by the noise offset, so the two "shared" vertices never matched
   after rounding, and the room extraction silently returned zero
   rooms. Fixed by cutting at the actual neighboring endpoint instead
   of its projection.
2. **Review queue could permanently lose track of an unresolved
   item.** `next_for_review()` was popping from the heap even when the
   object hadn't been resolved yet, so an unfixed low-confidence object
   could disappear from the queue forever after being looked at once.
   Fixed so only `resolve()` removes something from consideration.

Both are exactly the kind of subtle-but-serious bugs the V1 spec's
"build incrementally, test each layer" philosophy (Master Plan §33) is
meant to catch early.

## Next steps (in order)

1. **Extend room classification** — the room extraction gives geometry;
   add the object-detection-based classifier (kitchen/bedroom/etc.)
   described in spec §8. Needs a labeled image dataset — can start
   with a small hand-labeled set.
2. **Wire opening_detection into the Building Model** — currently
   standalone; connect `classify_openings()` output to
   `BuildingModel.add_door`/`add_window` calls, the way
   `synthetic_house.py` already does for walls/rooms.
3. **3D extension** — everything above is 2D (floor-plan-plane). Add
   floor/ceiling elevation and wall height inference from vertical
   point-cloud extent (spec §5, the depth-estimation → point-cloud
   steps this repo doesn't touch yet).
4. **RoomPlan spike** (spec §21) — time-boxed 1-2 week evaluation of
   whether Apple's RoomPlan API covers a meaningful fraction of the
   wall/room detection this repo currently does with synthetic
   input, before committing engineering time to a from-scratch
   point-cloud pipeline.
5. **Real capture ingestion** — once 3 and 4 are resolved, build the
   iOS capture app and the server-side point-cloud fusion step that
   feeds real segment observations into `wall_fitting.fit_walls()`
   instead of the synthetic generator in `examples/synthetic_house.py`.

Everything in this repo is designed so that step 5 only needs to
produce `list[Segment]` (pairs of 2D points) — the exact same input
`fit_walls()` already consumes from synthetic data. That's the whole
point of building it in this order: the interface between "real
sensor data" and "clean architecture" was locked down and tested
before any sensor code exists.
=======
# cansight
>>>>>>> 420866c426715b864eb162b0799d3c51c12a70d2
