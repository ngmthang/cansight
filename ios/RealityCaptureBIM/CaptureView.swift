//
//  CaptureView.swift
//  RealityCaptureBIM
//
//  Minimal capture UI: live camera passthrough with real-time
//  plane/mesh visualization (so the user can see what's been
//  detected and move the camera to fill gaps), start/stop
//  controls, and a running progress count. Does NOT implement a
//  coverage-percentage estimate (V1 spec Section 3's fuller
//  "guided coverage" concept) -- what's here is visual feedback of
//  detected surfaces, not a completeness score.
//
//  STATUS: plane/mesh visualization confirmed working on real
//  hardware (iPad A16, non-LiDAR plane-detection mode) as of this
//  version -- see docs/PROJECT_STATUS.md Section 4/5 for the real-
//  device debugging session that resolved the earlier
//  ARSession.delegate conflict bug. The fill+outline overlay
//  styling in this specific version has NOT yet been re-verified
//  on-device (only the prior solid-color diagnostic version was
//  confirmed) -- expect to fix minor issues if any come up when
//  testing this update.
//

import SwiftUI
import ARKit
import SceneKit
import simd

struct ARPassthroughView: UIViewRepresentable {
    let captureSession: ARCaptureSession

    func makeCoordinator() -> Coordinator {
        Coordinator(captureSession: captureSession)
    }

    func makeUIView(context: Context) -> ARSCNView {
        let view = ARSCNView(frame: .zero)
        view.session = captureSession.session
        view.automaticallyUpdatesLighting = true
        view.delegate = context.coordinator
        return view
    }

    func updateUIView(_ uiView: ARSCNView, context: Context) {}

    /// Renders live visual feedback of whatever ARKit has detected
    /// so far: LiDAR mode gets a wireframe mesh overlay built
    /// directly from ARMeshAnchor geometry (SceneKit, unlike
    /// RealityKit's ARView, has no built-in
    /// ".showSceneUnderstanding" debug option -- that's a
    /// RealityKit-only feature, confirmed the hard way when this
    /// was first tried). Non-LiDAR mode renders each detected
    /// ARPlaneAnchor as a colored overlay.
    ///
    /// This class is also the ONE place that owns
    /// ARSession.delegate (indirectly, by being ARSCNViewDelegate)
    /// -- it forwards every anchor event to ARCaptureSession so its
    /// own tracking (progress counter, point-cloud/plane
    /// extraction) still works. Splitting anchor-handling between
    /// two separate delegates was the original bug here: only one
    /// object can ever be ARSession.delegate, so ARCaptureSession
    /// claiming it directly silently starved ARSCNView of anchor
    /// notifications, and no overlay was ever drawn.
    class Coordinator: NSObject, ARSCNViewDelegate {
        let captureSession: ARCaptureSession

        // Caps how many plane overlays render simultaneously.
        // Detected planes can climb well past what's useful to
        // look at during a long real scan (observed: 13+ over a
        // ~3 minute session and still climbing) -- past a point,
        // more overlays just clutter the screen and add node
        // overhead for no benefit. This ONLY limits the visual
        // overlay: actual capture data still comes from every
        // detected anchor via captureSession.handleAnchorsAdded
        // below, completely unaffected by this cap.
        private var overlaidPlaneAnchors: Set<UUID> = []
        private let maxPlaneOverlays = 30

        // Live duplicate suppression: ARKit's raw plane detector
        // often reports multiple separate, overlapping detections
        // for what is really ONE continuous wall, especially in
        // visually complex/partially-occluded areas (confirmed via
        // real-device testing: a desk/monitor area produced two
        // crossing, overlapping overlay boxes on the same wall).
        // The Python pipeline already merges near-duplicates after
        // the fact (wall_fitting.fit_walls()'s clustering), but the
        // live on-screen overlay showed every raw fragment
        // separately, which reads as clutter/confusion while
        // scanning. This tracks each shown overlay's world-space
        // plane (normal + center) so a genuinely-duplicate new
        // detection can be skipped instead of drawn as a second,
        // overlapping box.
        private struct TrackedPlane {
            let alignment: ARPlaneAnchor.Alignment
            let worldNormal: SIMD3<Float>
            let worldCenter: SIMD3<Float>
        }
        private var trackedPlanesByAnchorID: [UUID: TrackedPlane] = [:]

        /// True if this plane is close enough (same orientation,
        /// same approximate position along that orientation) to an
        /// already-shown overlay that it's very likely the same
        /// physical wall, not a new one -- same idea as
        /// wall_fitting.py's clustering (angle tolerance + offset
        /// tolerance), just computed directly on raw plane
        /// normals/centers here instead of fitted 2D segments,
        /// since that's all a live ARPlaneAnchor gives us.
        private func isDuplicate(of planeAnchor: ARPlaneAnchor) -> Bool {
            let transform = planeAnchor.transform
            let normal4 = transform * SIMD4<Float>(0, 1, 0, 0)
            let worldNormal = simd_normalize(
                SIMD3<Float>(normal4.x, normal4.y, normal4.z)
            )
            let center4 =
                transform * SIMD4<Float>(planeAnchor.center, 1)
            let worldCenter = SIMD3<Float>(
                center4.x, center4.y, center4.z
            )

            for existing in trackedPlanesByAnchorID.values {
                guard existing.alignment == planeAnchor.alignment
                else { continue }
                // abs(): two nearly-parallel planes can have
                // normals pointing in opposite directions
                // depending on which side ARKit detected first
                let normalDot = abs(
                    simd_dot(existing.worldNormal, worldNormal)
                )
                guard normalDot > 0.94 else { continue }  // ~20deg
                let delta = worldCenter - existing.worldCenter
                let distanceAlongNormal = abs(
                    simd_dot(delta, existing.worldNormal)
                )
                if distanceAlongNormal < 0.2 {  // 20cm coplanar tol
                    return true
                }
            }
            return false
        }

        init(captureSession: ARCaptureSession) {
            self.captureSession = captureSession
        }

        func renderer(
            _ renderer: SCNSceneRenderer,
            didAdd node: SCNNode,
            for anchor: ARAnchor
        ) {
            captureSession.handleAnchorsAdded([anchor])

            if let planeAnchor = anchor as? ARPlaneAnchor {
                guard overlaidPlaneAnchors.count < maxPlaneOverlays
                else { return }
                guard !isDuplicate(of: planeAnchor) else { return }

                overlaidPlaneAnchors.insert(planeAnchor.identifier)
                let transform = planeAnchor.transform
                let normal4 = transform * SIMD4<Float>(0, 1, 0, 0)
                let center4 =
                    transform * SIMD4<Float>(planeAnchor.center, 1)
                trackedPlanesByAnchorID[planeAnchor.identifier] =
                    TrackedPlane(
                        alignment: planeAnchor.alignment,
                        worldNormal: simd_normalize(
                            SIMD3<Float>(
                                normal4.x, normal4.y, normal4.z
                            )
                        ),
                        worldCenter: SIMD3<Float>(
                            center4.x, center4.y, center4.z
                        )
                    )

                node.addChildNode(
                    Self.planeVisualization(for: planeAnchor)
                )
            } else if let meshAnchor = anchor as? ARMeshAnchor {
                node.addChildNode(
                    Self.meshVisualization(for: meshAnchor)
                )
            }
        }

        func renderer(
            _ renderer: SCNSceneRenderer,
            didUpdate node: SCNNode,
            for anchor: ARAnchor
        ) {
            captureSession.handleAnchorsUpdated([anchor])

            if let planeAnchor = anchor as? ARPlaneAnchor,
                let container = node.childNodes.first
            {
                // ARKit refines a plane's extent continuously as it
                // sees more of the surface -- keep the overlay in
                // sync so the user sees detection improve live.
                container.simdPosition = planeAnchor.center
                let width = CGFloat(planeAnchor.planeExtent.width)
                let height = CGFloat(planeAnchor.planeExtent.height)
                let color =
                    planeAnchor.alignment == .vertical
                    ? UIColor.systemBlue : UIColor.systemGreen

                if let fillNode = container.childNode(
                    withName: "fill", recursively: false
                ), let plane = fillNode.geometry as? SCNPlane {
                    plane.width = width
                    plane.height = height
                }
                if let outlineHolder = container.childNode(
                    withName: "outline", recursively: false
                ) {
                    outlineHolder.removeFromParentNode()
                }
                let newOutline = Self.outlineNode(
                    width: width, height: height, color: color
                )
                newOutline.name = "outline"
                container.addChildNode(newOutline)
            } else if let meshAnchor = anchor as? ARMeshAnchor {
                // The mesh's vertex/face count changes shape on
                // every update -- simplest robust approach is to
                // replace the child node's geometry wholesale
                // rather than mutating it in place.
                node.childNodes.forEach { $0.removeFromParentNode() }
                node.addChildNode(
                    Self.meshVisualization(for: meshAnchor)
                )
            }
        }

        func renderer(
            _ renderer: SCNSceneRenderer,
            didRemove node: SCNNode,
            for anchor: ARAnchor
        ) {
            captureSession.handleAnchorsRemoved([anchor])
            if let planeAnchor = anchor as? ARPlaneAnchor {
                overlaidPlaneAnchors.remove(planeAnchor.identifier)
                trackedPlanesByAnchorID.removeValue(
                    forKey: planeAnchor.identifier
                )
            }
        }

        /// Builds a plane overlay as two layered pieces, matching
        /// how real scanning apps (RoomPlan, Polycam, etc.) show
        /// detected surfaces -- a LOW-opacity fill so the real
        /// wall/door/window underneath stays visible, plus a
        /// crisp, fully-opaque border outline so the detected
        /// boundary still reads clearly. A single opaque fill (the
        /// earlier diagnostic version) hides real detail like door
        /// handles or window frames -- not what an actual user
        /// wants to see while scanning.
        private static func planeVisualization(
            for planeAnchor: ARPlaneAnchor
        ) -> SCNNode {
            let width = CGFloat(planeAnchor.planeExtent.width)
            let height = CGFloat(planeAnchor.planeExtent.height)
            // blue = wall (vertical), green = floor/ceiling
            // (horizontal) -- same convention as the web review
            // UI's confidence coloring, so a capture reviewed later
            // in the browser uses a consistent visual language
            let color =
                planeAnchor.alignment == .vertical
                ? UIColor.systemBlue : UIColor.systemGreen

            let container = SCNNode()
            container.simdPosition = planeAnchor.center
            // SCNPlane lies in the local XY plane by default (normal
            // along Z); ARKit's plane anchors define their extent
            // along local X/Z (normal along Y) regardless of whether
            // the anchor represents a vertical or horizontal
            // real-world surface -- the anchor's own transform
            // handles the actual world-space orientation. Standard
            // rotation from Apple's own ARKit plane-visualization
            // sample code.
            container.eulerAngles.x = -.pi / 2

            let fillNode = Self.fillNode(
                width: width, height: height, color: color
            )
            fillNode.name = "fill"
            container.addChildNode(fillNode)

            let outlineNode = Self.outlineNode(
                width: width, height: height, color: color
            )
            outlineNode.name = "outline"
            container.addChildNode(outlineNode)

            return container
        }

        private static func fillNode(
            width: CGFloat, height: CGFloat, color: UIColor
        ) -> SCNNode {
            let plane = SCNPlane(width: width, height: height)
            let material = SCNMaterial()
            // Deliberately translucent -- a "highlight," not a
            // "cover." The first version was fully opaque (0.35+),
            // which hid real surface detail like door handles or
            // window frames. But 0.15 turned out to be too subtle
            // to read as useful feedback at all once compressed
            // through video/screen recording -- 0.25 is the
            // corrected middle ground: still clearly see-through,
            // but visible enough to actually help while scanning.
            material.diffuse.contents = color.withAlphaComponent(0.25)
            material.isDoubleSided = true
            material.lightingModel = .constant
            plane.materials = [material]
            return SCNNode(geometry: plane)
        }

        /// A rectangular border built from four thin SCNBox bars,
        /// not a line-primitive outline. The earlier line-loop
        /// version (SCNGeometryElement with .line primitiveType)
        /// rendered far too thin to actually see once compressed
        /// through video/screen recording -- SceneKit line
        /// primitives typically render at a fixed ~1px width
        /// regardless of any hinted width, which isn't reliably
        /// visible. Real geometry (a thin box per edge) has actual
        /// physical thickness, so it stays visible and looks the
        /// same regardless of device/renderer quirks around line
        /// rendering.
        private static func outlineNode(
            width: CGFloat, height: CGFloat, color: UIColor
        ) -> SCNNode {
            let container = SCNNode()
            let barThickness: CGFloat = 0.025  // ~2.5cm, visible
            // but not heavy at typical room scale

            let material = SCNMaterial()
            material.diffuse.contents = color
            material.lightingModel = .constant

            let horizontalBar = SCNBox(
                width: width,
                height: barThickness,
                length: 0.001,
                chamferRadius: 0
            )
            horizontalBar.materials = [material]

            let topNode = SCNNode(geometry: horizontalBar)
            topNode.position = SCNVector3(0, Float(height / 2), 0)
            container.addChildNode(topNode)

            let bottomNode = SCNNode(geometry: horizontalBar)
            bottomNode.position = SCNVector3(0, Float(-height / 2), 0)
            container.addChildNode(bottomNode)

            let verticalBar = SCNBox(
                width: barThickness,
                height: height,
                length: 0.001,
                chamferRadius: 0
            )
            verticalBar.materials = [material]

            let leftNode = SCNNode(geometry: verticalBar)
            leftNode.position = SCNVector3(Float(-width / 2), 0, 0)
            container.addChildNode(leftNode)

            let rightNode = SCNNode(geometry: verticalBar)
            rightNode.position = SCNVector3(Float(width / 2), 0, 0)
            container.addChildNode(rightNode)

            return container
        }

        /// Builds a wireframe SCNGeometry directly from an
        /// ARMeshAnchor's raw vertex/face buffers. This is the
        /// standard ARKit-to-SceneKit bridging pattern: ARKit's
        /// ARGeometrySource/ARGeometryElement are Metal-buffer-backed
        /// and map directly onto SCNGeometrySource/SCNGeometryElement
        /// with matching parameters, so no manual vertex copying is
        /// needed (unlike ARCaptureSession.swift's point-cloud
        /// extraction, which DOES need to walk vertices one at a
        /// time -- here we hand the whole buffer to SceneKit as-is).
        private static func meshVisualization(
            for meshAnchor: ARMeshAnchor
        ) -> SCNNode {
            let geometry = meshAnchor.geometry

            let vertexSource = SCNGeometrySource(
                buffer: geometry.vertices.buffer,
                vertexFormat: geometry.vertices.format,
                semantic: .vertex,
                vertexCount: geometry.vertices.count,
                dataOffset: geometry.vertices.offset,
                dataStride: geometry.vertices.stride
            )

            let faces = geometry.faces
            let facesData = Data(
                bytes: faces.buffer.contents(),
                count: faces.buffer.length
            )
            let element = SCNGeometryElement(
                data: facesData,
                primitiveType: .triangles,
                primitiveCount: faces.count,
                bytesPerIndex: faces.bytesPerIndex
            )

            let scnGeometry = SCNGeometry(
                sources: [vertexSource], elements: [element]
            )
            let material = SCNMaterial()
            material.fillMode = .lines  // wireframe, not solid fill
            material.diffuse.contents = UIColor.cyan
            material.isDoubleSided = true
            material.lightingModel = .constant  // same unlit fix as
            // planeVisualization -- see that comment for why
            scnGeometry.materials = [material]

            return SCNNode(geometry: scnGeometry)
        }
    }
}

struct CaptureView: View {
    @StateObject private var viewModel = CaptureViewModel()

    var body: some View {
        ZStack(alignment: .bottom) {
            ARPassthroughView(captureSession: viewModel.captureSession)
                .ignoresSafeArea()

            VStack(spacing: 12) {
                Text(viewModel.modeLabel)
                    .font(.caption)
                    .foregroundColor(.white)
                    .padding(.horizontal, 8)
                    .padding(.vertical, 4)
                    .background(Color.black.opacity(0.6))
                    .cornerRadius(6)

                Text(viewModel.progressLabel)
                    .foregroundColor(.white)
                    .padding(8)
                    .background(Color.black.opacity(0.6))
                    .cornerRadius(8)

                // Honest scanning-technique tip, not a promise of
                // better detection -- flat, textureless surfaces
                // (a plain painted ceiling especially) are a real,
                // known hard case for camera-based plane detection
                // in general, not something app code can fix
                // outright. This is genuine, achievable guidance,
                // not a claim that it solves ceiling detection.
                if viewModel.isCapturing {
                    Text(
                        "Tip: move slowly, get close to corners "
                            + "and fixtures for better detection"
                    )
                    .font(.caption2)
                    .foregroundColor(.white.opacity(0.85))
                    .padding(.horizontal, 8)
                    .padding(.vertical, 4)
                    .background(Color.black.opacity(0.5))
                    .cornerRadius(6)
                }

                HStack(spacing: 16) {
                    Button(viewModel.isCapturing ? "Stop" : "Start") {
                        viewModel.toggleCapture()
                    }
                    .buttonStyle(.borderedProminent)

                    Button("Save Bundle") {
                        viewModel.saveBundle()
                    }
                    .buttonStyle(.bordered)
                    .disabled(viewModel.progressCount == 0)

                    // System share sheet is the most reliable way to
                    // get files off an App Playground -- avoids
                    // depending on whether the sandboxed Documents
                    // directory happens to be Files-app-browsable in
                    // a given Playgrounds context.
                    if !viewModel.bundleFileURLs.isEmpty {
                        ShareLink(
                            items: viewModel.bundleFileURLs
                        ) {
                            Label("Export", systemImage: "square.and.arrow.up")
                        }
                        .buttonStyle(.bordered)
                    }
                }
            }
            .padding(.bottom, 32)
        }
        .alert(item: $viewModel.saveResult) { result in
            Alert(
                title: Text(result.title),
                message: Text(result.message),
                dismissButton: .default(Text("OK"))
            )
        }
    }
}

@MainActor
final class CaptureViewModel: ObservableObject {
    let captureSession = ARCaptureSession()

    @Published var progressCount: Int = 0
    @Published var isCapturing: Bool = false
    @Published var saveResult: SaveResult?
    @Published var bundleFileURLs: [URL] = []

    var modeLabel: String {
        switch captureSession.mode {
        case .lidarMesh:
            return "LiDAR mode (high accuracy)"
        case .planeDetection:
            return "Plane-detection mode (lower accuracy -- "
                + "no LiDAR on this device)"
        }
    }

    var progressLabel: String {
        switch captureSession.mode {
        case .lidarMesh:
            return "\(progressCount) points captured"
        case .planeDetection:
            return "\(progressCount) planes detected"
        }
    }

    init() {
        captureSession.onProgressChanged = { [weak self] count in
            self?.progressCount = count
        }
    }

    func toggleCapture() {
        if isCapturing {
            captureSession.stop()
        } else {
            captureSession.start()
        }
        isCapturing.toggle()
    }

    func saveBundle() {
        let sessionID = UUID().uuidString
        let timestamp = ISO8601DateFormatter().string(from: Date())
        let deviceModel = UIDevice.current.model

        let documentsURL = FileManager.default.urls(
            for: .documentDirectory, in: .userDomainMask
        )[0]
        let bundleURL = documentsURL
            .appendingPathComponent("capture_bundles")
            .appendingPathComponent(sessionID)

        do {
            switch captureSession.mode {
            case .lidarMesh:
                let points = captureSession.extractWorldSpacePointCloud()
                try BundleWriter.writePointCloudBundle(
                    points: points,
                    sessionID: sessionID,
                    deviceModel: deviceModel,
                    captureTimestamp: timestamp,
                    to: bundleURL
                )
                bundleFileURLs = [
                    bundleURL.appendingPathComponent("manifest.json"),
                    bundleURL.appendingPathComponent("points.json"),
                ]
                saveResult = SaveResult(
                    title: "Saved",
                    message: "\(points.count) points written to "
                        + bundleURL.lastPathComponent
                )
            case .planeDetection:
                let planes = captureSession.extractDetectedPlanes()
                try BundleWriter.writePlaneBundle(
                    planes: planes,
                    sessionID: sessionID,
                    deviceModel: deviceModel,
                    captureTimestamp: timestamp,
                    to: bundleURL
                )
                bundleFileURLs = [
                    bundleURL.appendingPathComponent("manifest.json"),
                    bundleURL.appendingPathComponent("planes.json"),
                ]
                saveResult = SaveResult(
                    title: "Saved (lower accuracy)",
                    message: "\(planes.count) planes written to "
                        + bundleURL.lastPathComponent
                        + " -- no LiDAR on this device, expect "
                        + "this capture to need more review"
                )
            }
        } catch {
            saveResult = SaveResult(
                title: "Save Failed",
                message: error.localizedDescription
            )
        }
    }
}

struct SaveResult: Identifiable {
    let id = UUID()
    let title: String
    let message: String
}