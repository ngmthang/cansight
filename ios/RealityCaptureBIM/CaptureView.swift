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
//  REFERENCE / UNVERIFIED -- see ARCaptureSession.swift's header.
//

import SwiftUI
import ARKit
import SceneKit

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
                let planeNode = node.childNodes.first,
                let plane = planeNode.geometry as? SCNPlane
            {
                // planeExtent is the modern (iOS 16+) replacement
                // for the deprecated .extent SIMD3<Float>.
                plane.width = CGFloat(planeAnchor.planeExtent.width)
                plane.height = CGFloat(planeAnchor.planeExtent.height)
                planeNode.simdPosition = planeAnchor.center
            } else if let meshAnchor = anchor as? ARMeshAnchor {
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
        }

        private static func planeVisualization(
            for planeAnchor: ARPlaneAnchor
        ) -> SCNNode {
            let plane = SCNPlane(
                width: CGFloat(planeAnchor.planeExtent.width),
                height: CGFloat(planeAnchor.planeExtent.height)
            )
            let material = SCNMaterial()
            material.diffuse.contents =
                planeAnchor.alignment == .vertical
                ? UIColor.systemBlue.withAlphaComponent(0.35)
                : UIColor.systemGreen.withAlphaComponent(0.35)
            material.isDoubleSided = true
            // Unlit: renders at the exact set color regardless of
            // ARKit's estimated ambient lighting. Without this, a
            // semi-transparent overlay can render nearly invisible
            // under realistic (dim/uneven) room lighting -- a known
            // AR debug-overlay pitfall, and the actual fix Apple's
            // own plane-visualization sample code uses.
            material.lightingModel = .constant
            plane.materials = [material]

            let planeNode = SCNNode(geometry: plane)
            planeNode.simdPosition = planeAnchor.center
            planeNode.eulerAngles.x = -.pi / 2
            return planeNode
        }

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