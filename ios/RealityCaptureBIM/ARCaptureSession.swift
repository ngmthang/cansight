//
//  ARCaptureSession.swift
//  RealityCaptureBIM
//
//  Wraps an ARSession and captures geometry from whichever source
//  the device supports:
//    - LiDAR-equipped devices: dense ARMeshAnchor scene
//      reconstruction (matches Python's "lidar_mesh" bundle format)
//    - Non-LiDAR devices (iPhone 8 and later, any device running
//      iOS 11.3+): ARKit's built-in vertical/horizontal plane
//      detection (matches Python's "arkit_plane_detection" bundle
//      format)
//
//  Per docs/ROOMPLAN_SPIKE.md (Section 6): raw ARKit capture feeds
//  this project's own geometry pipeline, not RoomPlan's CapturedRoom,
//  on either path.
//
//  The non-LiDAR path is explicitly lower-fidelity -- ARKit's plane
//  detector gives a coarse polygon (a handful of boundary points),
//  not a dense mesh -- and geometry/capture_ingestion.py's
//  build_building_model_from_capture() deliberately caps confidence
//  much lower for it. This is intentional, not a bug: see the
//  project discussion on Conceptual vs. Architectural accuracy tiers
//  (V1 spec Section 13).
//
//  REFERENCE / UNVERIFIED: written without access to Xcode or a
//  physical device in this environment. API usage is grounded
//  against Apple's current ARKit documentation and known-working
//  reference implementations, but this file has not been compiled
//  or run. Treat it as a structured starting point, not tested
//  code -- build it in Xcode and fix whatever the compiler/device
//  flags before relying on it.
//

import ARKit
import simd

/// A single captured point in ARKit's world coordinate frame
/// (Y-up, meters) -- matches the "arkit_world_y_up_meters" contract
/// that geometry/capture_ingestion.py expects on the Python side.
struct CapturedPoint {
    let x: Float
    let y: Float
    let z: Float
}

/// A detected plane's boundary polygon, ARKit world space -- matches
/// the non-LiDAR "planes.json" bundle format's per-plane structure.
struct CapturedPlane {
    let alignment: String  // "vertical" | "horizontal"
    let boundaryVertices: [CapturedPoint]
}

enum CaptureMode {
    case lidarMesh
    case planeDetection
}

final class ARCaptureSession: NSObject {

    /// Exposed (not private) so a SwiftUI view can bind an ARSCNView
    /// to this exact session, giving the user a live camera
    /// passthrough while this class captures data from the same
    /// session in the background.
    let session = ARSession()

    private(set) var mode: CaptureMode = .lidarMesh

    private var meshAnchors: [UUID: ARMeshAnchor] = [:]
    private var planeAnchors: [UUID: ARPlaneAnchor] = [:]

    /// Called on the main thread whenever the running count changes
    /// (points for LiDAR mode, detected planes for plane-detection
    /// mode), so a UI can show live capture progress. This exposes
    /// the raw signal; the full coverage-percentage UI described in
    /// V1 spec Section 3 is not implemented here (see ios/README.md).
    var onProgressChanged: ((Int) -> Void)?

    static var supportsLiDAR: Bool {
        ARWorldTrackingConfiguration.supportsSceneReconstruction(.mesh)
    }

    /// Determines and starts the best available capture mode for
    /// this device: LiDAR mesh if supported, plane detection
    /// otherwise. Every iPhone/iPad capable of running ARKit's world
    /// tracking at all (iPhone 6s and later) supports plane
    /// detection, so this should never fail to start on any
    /// ARKit-capable device -- LiDAR is a quality upgrade, not a
    /// hard requirement, on this path.
    func start() {
        let configuration = ARWorldTrackingConfiguration()

        if Self.supportsLiDAR {
            mode = .lidarMesh
            configuration.sceneReconstruction = .mesh
            configuration.environmentTexturing = .none
        } else {
            mode = .planeDetection
            configuration.planeDetection = [.horizontal, .vertical]
            configuration.environmentTexturing = .none
        }

        // Deliberately NOT setting session.delegate here.
        // ARSession.delegate is a single slot -- if this class
        // claimed it, ARSCNView (in CaptureView.swift) would never
        // receive anchor add/update notifications itself, and its
        // renderer(_:didAdd:for:) visualization callbacks would
        // silently never fire (this was a real bug: scanning and
        // the progress counter worked, since those came from this
        // class's own tracking, but the plane/mesh overlays never
        // appeared, since ARSCNView never found out about new
        // anchors at all). Instead, ARPassthroughView.Coordinator
        // owns session.delegate (indirectly, via being
        // ARSCNViewDelegate) and forwards anchor events here via
        // handleAnchorsAdded/Updated/Removed below.
        session.run(configuration)
    }

    func stop() {
        session.pause()
    }

    // MARK: - Anchor event handling (forwarded from
    // ARPassthroughView.Coordinator, not from ARSessionDelegate --
    // see the comment in start() for why)

    func handleAnchorsAdded(_ anchors: [ARAnchor]) {
        updateAnchors(anchors)
    }

    func handleAnchorsUpdated(_ anchors: [ARAnchor]) {
        updateAnchors(anchors)
    }

    func handleAnchorsRemoved(_ anchors: [ARAnchor]) {
        for anchor in anchors {
            if let meshAnchor = anchor as? ARMeshAnchor {
                meshAnchors.removeValue(forKey: meshAnchor.identifier)
            } else if let planeAnchor = anchor as? ARPlaneAnchor {
                planeAnchors.removeValue(forKey: planeAnchor.identifier)
            }
        }
    }

    private func updateAnchors(_ anchors: [ARAnchor]) {
        var changed = false
        for anchor in anchors {
            if mode == .lidarMesh, let meshAnchor = anchor as? ARMeshAnchor {
                meshAnchors[meshAnchor.identifier] = meshAnchor
                changed = true
            } else if mode == .planeDetection,
                let planeAnchor = anchor as? ARPlaneAnchor
            {
                planeAnchors[planeAnchor.identifier] = planeAnchor
                changed = true
            }
        }
        if changed {
            let count = currentProgressCount()
            DispatchQueue.main.async { [weak self] in
                self?.onProgressChanged?(count)
            }
        }
    }

    private func currentProgressCount() -> Int {
        switch mode {
        case .lidarMesh:
            return meshAnchors.values.reduce(0) {
                $0 + $1.geometry.vertices.count
            }
        case .planeDetection:
            return planeAnchors.count
        }
    }

    // MARK: - LiDAR mesh extraction

    /// Extracts the full accumulated point cloud in ARKit world
    /// space (LiDAR mode only), transforming every mesh anchor's
    /// local-space vertices by that anchor's world transform. Call
    /// once, at the end of a capture session -- not cheap enough to
    /// run every frame.
    func extractWorldSpacePointCloud() -> [CapturedPoint] {
        var points: [CapturedPoint] = []

        for meshAnchor in meshAnchors.values {
            let vertexSource = meshAnchor.geometry.vertices
            let transform = meshAnchor.transform

            for i in 0..<vertexSource.count {
                let localVertex = vertexSource.vertex(at: UInt32(i))
                let localPoint = SIMD4<Float>(localVertex, 1)
                let worldPoint = transform * localPoint
                points.append(
                    CapturedPoint(
                        x: worldPoint.x,
                        y: worldPoint.y,
                        z: worldPoint.z
                    )
                )
            }
        }

        return points
    }

    // MARK: - Plane detection extraction (non-LiDAR)

    /// Extracts every detected plane's boundary polygon in ARKit
    /// world space (plane-detection mode only), transforming each
    /// plane's local-space boundary vertices by its anchor's world
    /// transform. Matches geometry/capture_ingestion.py's expected
    /// "planes.json" structure exactly.
    func extractDetectedPlanes() -> [CapturedPlane] {
        var planes: [CapturedPlane] = []

        for planeAnchor in planeAnchors.values {
            let boundary = planeAnchor.geometry.boundaryVertices
            let transform = planeAnchor.transform

            let worldVertices = boundary.map { local -> CapturedPoint in
                let localPoint = SIMD4<Float>(local, 1)
                let worldPoint = transform * localPoint
                return CapturedPoint(
                    x: worldPoint.x,
                    y: worldPoint.y,
                    z: worldPoint.z
                )
            }

            let alignment =
                planeAnchor.alignment == .vertical
                ? "vertical" : "horizontal"

            planes.append(
                CapturedPlane(
                    alignment: alignment,
                    boundaryVertices: worldVertices
                )
            )
        }

        return planes
    }
}

/// Apple's documented pattern for reading a vertex out of an
/// ARGeometrySource's raw MTLBuffer -- ARGeometrySource doesn't
/// expose vertices as a plain Swift array, only as a strided buffer.
extension ARGeometrySource {
    func vertex(at index: UInt32) -> SIMD3<Float> {
        assert(
            format == MTLVertexFormat.float3,
            "Expected three floats (twelve bytes) per vertex."
        )
        let vertexPointer = buffer.contents().advanced(
            by: offset + (stride * Int(index))
        )
        return vertexPointer.assumingMemoryBound(
            to: SIMD3<Float>.self
        ).pointee
    }
}