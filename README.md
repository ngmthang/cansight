# Cansight

## Reality Capture → Editable Building Model

Cansight is a reality-capture tool for turning a physical interior space into a structured, editable building model.

The project combines **iPhone/iPad AR capture**, **geometry reconstruction**, **human review**, and **CAD/BIM export** into one workflow:

```text
Physical Room
     │
     ▼
 iPhone / iPad
  ARKit Capture
     │
     ▼
 Capture Bundle
     │
     ▼
 Cansight Geometry Pipeline
     │
     ├── Wall Detection
     ├── Room Extraction
     ├── 3D Height Inference
     └── Opening Detection
     │
     ▼
 Building Model
     │
     ▼
 Review & Correction
     │
     ├── Fix uncertain geometry
     └── Draw missing walls
     │
     ▼
 Export
 ┌───┴────────┐
 ▼            ▼
IFC4         DXF
 │             │
 ▼             ├── AutoCAD
Revit/BIM      └── SketchUp
```

Cansight is currently a **working prototype for real interior capture and reconstruction**. It is designed to let you capture a room, reconstruct its basic architectural geometry, review the result, make corrections, and export the model for use in other tools.

---

## What can I do with Cansight today?

The current version supports the following end-to-end workflow:

### 📱 Capture a real room

Use an iPhone or iPad with ARKit to scan an interior space.

Cansight supports:

* **LiDAR devices** — dense spatial capture
* **Non-LiDAR devices** — ARKit plane detection

The capture app provides live visualization of detected surfaces while scanning and saves the result as a Cansight capture bundle.

---

### 🧱 Reconstruct architectural geometry

Cansight processes the captured data to identify:

* walls
* wall segments
* rooms
* floor elevation
* ceiling elevation
* wall height
* doors/openings
* windows/openings

The geometry pipeline is designed to merge noisy observations from multiple frames into a cleaner building representation.

---

### 🔎 Review the reconstruction

Real-world scanning is imperfect.

Furniture, monitors, decorations, and other objects can prevent the device from seeing parts of a wall. ARKit can also detect flat objects that are not actually architectural walls.

Cansight therefore includes a review workflow.

You can:

* inspect the generated model
* review low-confidence geometry
* correct detected elements
* add missing walls
* save corrections to the project

For example, if a sofa blocks part of a wall during capture:

```text
Captured room

┌───────────────┐
│               │
│               │
│     SOFA      │
│   ███████     │
│   ███████     │
└───────────────┘

        ↓

Detected wall

┌───────     ───┐
│               │
│               │

        ↓

Draw Missing Wall

┌───────────────┐
│               │
│               │
│     SOFA      │
│   ███████     │
│   ███████     │
└───────────────┘
```

This human-in-the-loop step is an intentional part of the current workflow.

---

### 💾 Save projects

The web application maintains projects locally using SQLite.

This allows you to:

* create multiple projects
* upload captures
* keep reconstructed models
* reopen projects later
* preserve review/correction state

---

### 📐 Export the result

Cansight currently provides two export formats.

#### IFC4

Export the building model as IFC4 for BIM workflows.

A typical workflow is:

```text
Cansight
   ↓
 IFC4
   ↓
 Revit / IFC-compatible BIM software
```

Cansight does not currently create native `.rvt` files.

#### DXF

Export the floor-plan geometry as DXF.

DXF can be used with:

* AutoCAD
* SketchUp through its DXF import workflow
* other CAD applications supporting DXF

---

# Getting started

There are two ways to try Cansight.

## Option 1 — Try the software without a physical device

If you want to explore the reconstruction pipeline first, use the included Python examples and tests.

### Clone the repository

```bash
git clone https://github.com/ngmthang/cansight.git
cd cansight
```

### Create a Python environment

```bash
python -m venv .venv
```

Activate it:

### macOS / Linux

```bash
source .venv/bin/activate
```

### Windows

```powershell
.venv\Scripts\activate
```

Install the dependencies:

```bash
pip install -r requirements.txt
```

### Run the tests

```bash
python tests/test_all.py
```

### Run the synthetic example

```bash
python examples/synthetic_house.py
```

The synthetic example demonstrates the reconstruction pipeline without requiring an iPhone/iPad.

---

# Option 2 — Capture a real room

For the full workflow, use the iOS capture application.

The iOS implementation is located under:

```text
ios/
```

The capture application uses Apple's ARKit.

## Supported capture modes

Cansight automatically uses the appropriate mode for the device:

| Device capability          | Capture method             |
| -------------------------- | -------------------------- |
| LiDAR-equipped iPhone/iPad | LiDAR / dense spatial data |
| Non-LiDAR iPhone/iPad      | ARKit plane detection      |

The current non-LiDAR workflow has been tested using a real iPad. The LiDAR pipeline is implemented but should still be considered a validation area on actual LiDAR hardware.

See [`ios/README.md`](ios/README.md) for the device-specific setup instructions.

---

# Capture workflow

Once the iOS capture application is running:

### 1. Start a capture

Point the device at the room you want to reconstruct.

### 2. Move around the room

Slowly move the device so ARKit can observe the walls and other surfaces from different positions.

For best results:

* move slowly
* keep surfaces visible
* avoid covering walls with your body
* capture as much of each wall as possible
* scan from multiple viewpoints

### 3. Watch the live visualization

The application displays ARKit's detected surfaces during capture.

This gives you immediate feedback about what the device is seeing.

### 4. Stop the capture

When you have collected enough observations, stop the session.

### 5. Save the capture bundle

The application saves the captured data as a Cansight bundle.

A bundle contains a manifest plus the captured spatial observations:

```text
capture/
├── manifest.json
└── points.json
```

for LiDAR capture, or:

```text
capture/
├── manifest.json
└── planes.json
```

for non-LiDAR capture.

The manifest tells Cansight which capture pipeline should be used.

---

# Process a capture

The Python side automatically reads the capture bundle and chooses the correct ingestion path.

Conceptually:

```text
capture bundle
      │
      ▼
capture_ingestion
      │
      ├── LiDAR
      │
      └── Non-LiDAR
      │
      ▼
wall fitting
      │
      ▼
room extraction
      │
      ▼
3D inference
      │
      ▼
opening detection
      │
      ▼
BuildingModel
```

You do not need to manually convert a LiDAR capture into the non-LiDAR format or vice versa.

---

# Use the Web App

Cansight includes a local browser-based interface for working with projects.

Start the server:

```bash
python webapp/server.py
```

Then open:

```text
http://127.0.0.1:5000
```

The web interface provides the current user-facing workflow for:

* managing projects
* uploading capture bundles
* viewing reconstructed geometry
* reviewing detected elements
* correcting geometry
* drawing missing walls
* saving project state
* exporting models

The application runs locally; the current version does not require a hosted Cansight account or cloud service.

---

# Review your model

After processing a capture, inspect the reconstructed floor plan and 3D geometry.

Pay particular attention to:

### Walls

Check that:

* walls are in the correct positions
* separate wall fragments have been merged correctly
* furniture has not caused missing wall sections
* non-architectural objects have not been interpreted as walls

### Rooms

Check that:

* room boundaries are closed
* dividing walls are represented correctly
* the generated room polygons match the physical space

### Openings

Check detected:

* doors
* windows
* other wall openings

### Heights

Check the inferred:

* floor elevation
* ceiling elevation
* wall height

The current system is intended as a reconstruction and editing workflow, rather than a guaranteed survey-grade measurement system.

---

# Correct missing geometry

One of the most important current features is the ability to manually add geometry that could not be reliably recovered from the scan.

For example, if furniture blocks a wall:

1. Open the project.
2. Locate the missing section.
3. Select **Draw Missing Wall**.
4. Draw the wall segment.
5. Save the correction.
6. Continue reviewing the model.

This allows a real scan to be converted into a usable building model even when the sensor cannot observe every surface.

---

# Export your model

Once the model has been reviewed, export it for use in another application.

## IFC

Use IFC when your destination is a BIM workflow.

```text
Cansight → IFC4 → Revit / IFC software
```

## DXF

Use DXF when you want a CAD/floor-plan representation.

```text
Cansight → DXF → AutoCAD
                 ↘ SketchUp
```

The current project deliberately uses standard interchange formats rather than attempting to maintain proprietary native writers for every target application.

---

# What makes Cansight different?

Cansight is not simply a viewer for ARKit data.

The project owns the processing pipeline between the sensor and the final building model.

```text
ARKit data
    ↓
Cansight geometry algorithms
    ↓
BuildingModel
    ↓
Human review
    ↓
Interchange formats
```

The core building representation is independent from the iOS capture layer.

This means the same building-model and geometry pipeline can process different capture sources as long as they produce the expected Cansight capture data.

Cansight also intentionally keeps human correction in the workflow rather than assuming that automated reconstruction will always be correct.

---

# Current capabilities at a glance

| Capability                      | Available |
| ------------------------------- | :-------: |
| iPhone/iPad ARKit capture       |     ✅     |
| LiDAR capture pipeline          |     ✅     |
| Non-LiDAR plane capture         |     ✅     |
| Live capture visualization      |     ✅     |
| Wall reconstruction             |     ✅     |
| Room extraction                 |     ✅     |
| 3D floor/ceiling inference      |     ✅     |
| Opening detection               |     ✅     |
| Confidence/review workflow      |     ✅     |
| Manual wall creation            |     ✅     |
| Browser-based review UI         |     ✅     |
| Local project persistence       |     ✅     |
| IFC4 export                     |     ✅     |
| DXF export                      |     ✅     |
| Synthetic end-to-end example    |     ✅     |
| Real-capture regression testing |     ✅     |

---

# Important limitations

Cansight is an active prototype and should currently be treated accordingly.

The system does **not** yet guarantee:

* survey-grade measurements
* complete recovery of furniture-obscured walls
* automatic reconstruction of every room in a building
* reliable multi-room stitching
* multi-floor building reconstruction
* native `.rvt` Revit output
* native `.skp` SketchUp output
* cloud collaboration

For the detailed engineering status, known limitations, and development roadmap, see:

* [`docs/PROJECT_STATUS.md`](docs/PROJECT_STATUS.md)
* [`docs/BACKLOG.md`](docs/BACKLOG.md)

Those documents are intended for project/development context; this README is intended to explain how to use Cansight.

---

# Project structure

```text
cansight/
│
├── ios/                  # iPhone/iPad AR capture
│
├── geometry/             # Capture ingestion and reconstruction
│   ├── capture_ingestion.py
│   ├── plane_detection.py
│   ├── wall_fitting.py
│   ├── room_extraction.py
│   ├── height_inference.py
│   └── opening_detection.py
│
├── building_model/       # Structured building representation
│
├── review/               # Review and correction workflow
│
├── export/               # IFC and DXF exporters
│
├── webapp/               # Local browser application
│
├── examples/             # Example workflows
│
├── tests/                # Automated and real-capture tests
│
└── docs/                 # Detailed project documentation
```

---

# Documentation

If you are a **user**, start here:

**This README** → understand the product and run the current workflow.

If you are **setting up the iOS capture app**:

→ [`ios/README.md`](ios/README.md)

If you are **developing Cansight**:

→ [`docs/PROJECT_STATUS.md`](docs/PROJECT_STATUS.md)

If you want to understand **future/deferred work**:

→ [`docs/BACKLOG.md`](docs/BACKLOG.md)

If you want to understand the **RoomPlan evaluation and architectural decision**:

→ [`docs/ROOMPLAN_SPIKE.md`](docs/ROOMPLAN_SPIKE.md)

---

# In one sentence

**Cansight lets you capture a real room with an iPhone/iPad, reconstruct it into an editable building model, review and correct the result, and export that model to standard BIM/CAD formats.**

---

## License

MIT License. See [`LICENSE`](LICENSE).
