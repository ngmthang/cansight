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
    let session: ARSession

    func makeCoordinator() -> Coordinator {
        Coordinator()
    }

    func makeUIView(context: Context) -> ARSCNView {
        let view = ARSCNView(frame: .zero)
        view.session = session
        view.automaticallyUpdatesLighting = true
        view.delegate = context.coordinator

        if ARCaptureSession.supportsLiDAR {
            // Apple's built-in mesh visualization -- draws the
            // detected scene geometry directly as an overlay. No
            // custom rendering code needed for LiDAR mode.
            view.debugOptions = [.showSceneUnderstanding]
        }

        return view
    }

    func updateUIView(_ uiView: ARSCNView, context: Context) {}

    /// Handles live plane visualization for non-LiDAR
    /// (plane-detection) mode. LiDAR mode uses
    /// ARSCNDebugOptions.showSceneUnderstanding instead (set in
    /// makeUIView), which needs no custom rendering.
    class Coordinator: NSObject, ARSCNViewDelegate {
        func renderer(
            _ renderer: SCNSceneRenderer,
            didAdd node: SCNNode,
            for anchor: ARAnchor
        ) {
            guard let planeAnchor = anchor as? ARPlaneAnchor else {
                return
            }
            node.addChildNode(
                Self.planeVisualization(for: planeAnchor)
            )
        }

        func renderer(
            _ renderer: SCNSceneRenderer,
            didUpdate node: SCNNode,
            for anchor: ARAnchor
        ) {
            guard let planeAnchor = anchor as? ARPlaneAnchor,
                let planeNode = node.childNodes.first,
                let plane = planeNode.geometry as? SCNPlane
            else { return }

            // ARKit refines a plane's extent continuously as it
            // sees more of the surface -- keep the overlay in sync
            // so the user sees detection improve live, not just a
            // one-shot guess.
            plane.width = CGFloat(planeAnchor.extent.x)
            plane.height = CGFloat(planeAnchor.extent.z)
            planeNode.simdPosition = planeAnchor.center
        }

        private static func planeVisualization(
            for planeAnchor: ARPlaneAnchor
        ) -> SCNNode {
            let plane = SCNPlane(
                width: CGFloat(planeAnchor.extent.x),
                height: CGFloat(planeAnchor.extent.z)
            )
            let material = SCNMaterial()
            // blue = wall (vertical), green = floor/ceiling
            // (horizontal) -- same color convention as the web
            // review UI's confidence coloring, so a user who later
            // reviews the same capture in the browser sees a
            // consistent visual language
            material.diffuse.contents =
                planeAnchor.alignment == .vertical
                ? UIColor.systemBlue.withAlphaComponent(0.35)
                : UIColor.systemGreen.withAlphaComponent(0.35)
            material.isDoubleSided = true
            plane.materials = [material]

            let planeNode = SCNNode(geometry: plane)
            planeNode.simdPosition = planeAnchor.center
            // SCNPlane lies in the local XY plane by default (normal
            // along Z); ARKit's plane anchors define their extent
            // along local X/Z (normal along Y) regardless of whether
            // the anchor represents a vertical or horizontal
            // real-world surface -- the anchor's own transform
            // handles the actual world-space orientation. Standard
            // rotation from Apple's own ARKit plane-visualization
            // sample code.
            planeNode.eulerAngles.x = -.pi / 2
            return planeNode
        }
    }
}

struct CaptureView: View {
    @StateObject private var viewModel = CaptureViewModel()

    var body: some View {
        ZStack(alignment: .bottom) {
            ARPassthroughView(session: viewModel.captureSession.session)
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