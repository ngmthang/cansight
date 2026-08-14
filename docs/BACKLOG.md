# Backlog

Features that are real, motivated, and worth building -- but
deliberately deferred. Each entry should capture enough context
(why it matters, what triggered it) that picking it up later
doesn't require re-deriving the reasoning from scratch.

---

## Furniture-aware wall detection

**Status:** Deferred. `add_manual_wall()` (review/
correction_session.py) covers the human-correction side of this
problem today; this entry is about the automated-detection side.

**Motivation (from real-device testing, Aug 2026):** Scanning an
actual furnished room (bed, table, etc. against walls) with the
non-LiDAR plane-detection path produced 7 detected wall
fragments with 3 specific gaps -- each gap traced back to a wall
segment that had one well-connected end and one end dangling
0.85-1.07m from anything. The pattern was consistent with
furniture blocking the camera's view of those wall segments
during capture, preventing ARKit's plane detector from ever
seeing a continuous surface there.

This isn't a synthetic edge case -- it's the **realistic common
case**. Real bedrooms have beds against walls. Real living rooms
have sofas against walls. An empty, fully-visible room (which is
all the synthetic test data in this project currently models) is
the unusual case, not the norm.

**What's already handled:** `add_manual_wall()` lets a human
reviewer manually draw in a wall the pipeline missed, with
`detection_method="manual_correction"` provenance and confidence
1.0. This is sufficient as a correction mechanism, but requires a
human to notice the gap and know roughly where the missing wall
should go.

**What's NOT handled yet -- the actual feature to build:**

1. **Furniture detection/classification during capture.**
   RoomPlan already does this (16 furniture/fixture categories,
   per docs/ROOMPLAN_SPIKE.md Section 2) -- worth referencing as
   a design input even though this project doesn't depend on
   RoomPlan for walls. The question: can `plane_detection.py`'s
   RANSAC output, or ARKit's own object-detection capabilities,
   distinguish "this vertical plane is a wall" from "this
   surface is furniture" before wall_fitting.py ever sees it?
2. **Occlusion-aware gap inference.** Given two wall fragments
   with a gap between them, and known Manhattan-world geometry
   (V1 spec Section 4), can the system *suggest* a probable wall
   completion (e.g. "these two fragments are roughly collinear,
   the gap is probably one continuous wall") rather than leaving
   it to a human to notice and draw from scratch? This would be
   a suggested/low-confidence auto-completion, explicitly
   surfaced for human approval -- not a silent guess, consistent
   with this project's established "don't silently guess"
   principle (opening_detection.py's "ambiguous" classification,
   the sill-height validation).
3. **Distinguishing "furniture-shaped gap" from "actually missing
   wall data" from "doorway/opening."** A gap in wall detection
   could mean furniture occlusion, insufficient scan coverage, or
   a real architectural opening (a doorway to another room). These
   need different handling, and conflating them would produce
   wrong results confidently.

**Why deferred rather than built now:** This needs a broader base
of real capture data than one room to design well -- the specific
gap-inference heuristics (item 2) shouldn't be tuned against a
single test scan the way `angle_tol_deg`/`offset_tol` were
recalibrated this session. Worth revisiting once several more real
scans (ideally a mix of furnished/empty, LiDAR/non-LiDAR) are
available to validate against.