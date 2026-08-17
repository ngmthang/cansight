# iOS Capture App — Reference Scaffold

**Status: partially verified.** Confirmed to compile and run on a
real device (iPad A16, plane-detection mode, via Swift
Playgrounds) as of this update. LiDAR mode remains unverified --
no LiDAR-equipped device has run this yet. Treat the
plane-detection path as "builds and runs," not "accuracy
validated" -- a real bundle from a real scan still needs to be
run through the Python pipeline end-to-end to check that, which
hasn't happened yet either.

## What's here

- `ARCaptureSession.swift` — configures an `ARSession` and
  auto-detects the best capture mode for the device:
  - **LiDAR mode** (iPhone/iPad Pro 2020+): dense
    `ARMeshAnchor` scene reconstruction.
  - **Plane-detection mode** (any ARKit device, iPhone 8 and
    later): ARKit's built-in vertical/horizontal plane
    detector, no LiDAR required.
- `BundleWriter.swift` — writes whichever mode's data to disk
  in the exact format `geometry/capture_ingestion.py` expects
  (`manifest.json` + `points.json` for LiDAR mode,
  `manifest.json` + `planes.json` for plane-detection mode).
- `CaptureView.swift` — SwiftUI capture screen: live camera
  passthrough with real-time detected-surface visualization
  (ARKit's built-in mesh overlay in LiDAR mode; colored
  `ARPlaneAnchor` overlays in plane-detection mode), mode
  indicator, start/stop, save-bundle button, running progress
  count.

## Why raw ARKit capture, not RoomPlan

Per `docs/ROOMPLAN_SPIKE.md`: this project's own geometry
pipeline (`geometry/plane_detection.py`, `wall_fitting.py`,
`room_extraction.py`, `height_inference.py`) is the production
detector, not Apple's `CapturedRoom`. RoomPlan is kept aside as
an offline accuracy benchmark only. That's why this scaffold
targets raw `ARMeshAnchor`/`ARPlaneAnchor` data, not the
RoomPlan API.

## The two capture modes, and why the split exists

| | LiDAR mode | Plane-detection mode |
|---|---|---|
| Devices | iPhone/iPad Pro 2020+ | Any ARKit device back to iPhone 8 |
| Data source | Dense mesh, thousands of points | Sparse polygon, ~4-8 points per wall |
| Accuracy tier (V1 spec Section 13) | Architectural, ±1-3cm | Conceptual, ±5-10cm or worse |
| Python confidence formula | `min(1.0, 0.5 + 0.08*support)` | capped at `min(0.6, 0.3 + 0.05*support)` |

The confidence gap is intentional and enforced on the Python
side (`geometry/capture_ingestion.py`'s
`build_building_model_from_capture()`), not something the iOS
app needs to manage — this file just tags which mode a bundle
came from (`capture_method` in the manifest), and Python applies
the appropriate confidence formula. Every non-LiDAR capture
should land near the top of `review/queue.py`'s confidence-
sorted queue automatically, flagged for heavier human
verification rather than silently treated as LiDAR-quality data.

## Setting this up in Xcode (if/when Mac access is available)

1. Create a new iOS App project in Xcode (SwiftUI lifecycle).
2. Add these three Swift files to the project.
3. Set your app's entry point to show `CaptureView()`.
4. **Required:** add `NSCameraUsageDescription` to `Info.plist`
   (any AR app needs this, or it crashes on launch with no
   useful error message) — something like: "This app uses the
   camera and, where available, the LiDAR scanner to capture
   room geometry."
5. **Device requirement:** any device running iOS 11.3+ with
   ARKit world-tracking support (iPhone 6s / iPhone SE and
   later) can run plane-detection mode; LiDAR mode additionally
   requires an iPhone/iPad Pro (2020+). The simulator does not
   support ARKit scene reconstruction or reliable plane
   detection — this must be tested on physical devices, ideally
   at least one of each capability tier.
6. Build and run on-device. `ARCaptureSession.start()` picks the
   mode automatically — no manual switch needed. Point the
   camera at real walls; the session accumulates data as
   anchors update.
7. Tap "Save Bundle," then "Export" to share the bundle's
   `manifest.json` + `points.json`/`planes.json` via the system
   share sheet (AirDrop to a Mac, save to Files, etc.).

## Setting this up in Swift Playgrounds (no Mac required)

If you don't have Mac/Xcode access, Swift Playgrounds on iPad
can build and run this without one. This has NOT been verified
against a live Playgrounds instance — the steps below are
accurate as of how App Playgrounds work generally, but the
in-app settings UI wording may differ slightly by version.

1. Open Swift Playgrounds, tap **New Playground → App** (not
   the plain "Playground" option — App produces a real,
   runnable SwiftUI app).
2. Add the three source files above as new file tabs (tap **+**
   in the file browser), pasting each one in unchanged.
3. Replace the template's `@main` entry-point file with:

```swift
   import SwiftUI

   @main
   struct RealityCaptureBIMApp: App {
       var body: some Scene {
           WindowGroup {
               CaptureView()
           }
       }
   }
```

   Delete the template's now-unused placeholder `ContentView`.
4. Find the project's settings/info panel (usually via tapping
   the project name, or a settings icon near the file browser)
   and set the **camera usage description** — App Playgrounds
   handle this instead of a hand-edited `Info.plist`.
5. Run. `ARCaptureSession.start()` auto-detects LiDAR support
   and picks the right mode — on a non-Pro iPad (no LiDAR),
   this correctly falls back to plane-detection mode
   automatically, no manual switch needed.
6. Tap "Save Bundle," then the **Export** button (added
   specifically for this workflow) to share the bundle's files
   via the system share sheet — AirDrop, Files, email, whatever
   gets them to wherever you'll run the Python pipeline. This
   avoids depending on whether Playgrounds' sandboxed Documents
   directory happens to be Files-app-browsable in a given
   context.
7. On the Python side, reassemble the shared files into a
   folder matching the bundle structure (`manifest.json` +
   `points.json` or `planes.json` in the same directory), then
   run `ingest_capture("/path/to/that/folder")` as normal.

To hand a completed bundle to the Python pipeline either way:

```python
from geometry.capture_ingestion import (
    ingest_capture, build_building_model_from_capture,
)
result = ingest_capture("/path/to/pulled/bundle")
bm = build_building_model_from_capture(result, "my_building")
```

`ingest_capture()` reads `manifest.json`'s `capture_method`
field and automatically routes to the right pipeline (RANSAC
plane segmentation for LiDAR bundles, direct line-fitting for
plane-detection bundles) — no manual branching needed on the
Python side either.

## Explicitly NOT implemented here (scope boundaries)

- **Real-time detected-surface visualization.** `ARPassthroughView`
  now shows what's been detected while scanning: LiDAR mode uses
  ARKit's built-in mesh overlay (`ARSCNDebugOptions
  .showSceneUnderstanding`); non-LiDAR mode renders each detected
  `ARPlaneAnchor` as a colored overlay (blue = wall, green =
  floor/ceiling), updated live as ARKit refines its detection.
  This is NOT a coverage-percentage/completeness score -- it shows
  what's been found, not how much of the room is left to scan.
  V1 spec Section 3's fuller "guided coverage" concept (a
  heat map, minimum-scan-quality enforcement) is still unbuilt.
- **Bundle upload / networking.** `BundleWriter` writes to local
  device storage only. Getting bundles from the device to a
  server (V1 spec Section 14's "capture bundle upload -> async
  server-side reconstruction" architecture) is unbuilt.
- **Multi-room / multi-level capture UX.** One continuous
  `ARSession` per bundle; no in-app flow for "now scan the next
  room" or stitching multiple sessions together.
- **Plane-detection mode's floor/ceiling accuracy has not been
  validated against real hardware.** `height_inference.py`'s
  density-threshold algorithm was designed for hundreds of
  LiDAR samples; feeding it a handful of plane-boundary z-values
  (with `density_threshold=2`, loosened from the LiDAR path's
  default of 3) is a reasonable fallback but genuinely untested
  against real non-LiDAR capture noise. This is exactly the kind
  of thing `docs/ROOMPLAN_SPIKE.md`'s "needs hands-on testing"
  section already flags for real-device validation.
- **Manhattan-alignment rotation** (V1 spec Section 4). The
  Python-side axis conversion (`capture_ingestion.py`) does the
  ARKit-Y-up → model-Z-up relabel only, not the rotation to
  align with the building's dominant wall direction.

## Testing without a device

There isn't one for the Swift code specifically. The thing that
*is* fully tested is everything downstream of the bundle format:
`tests/test_capture_ingestion.py` (LiDAR path) and
`tests/test_non_lidar_capture.py` (plane-detection path) cover
the full pipeline against synthetic data shaped like what each
capture mode would realistically produce, including a direct
test that non-LiDAR confidence values stay capped below LiDAR
ones on comparable data. Getting a real device of each type to
write one real bundle and successfully running it through
`ingest_capture()` is the actual integration test this scaffold
still needs.