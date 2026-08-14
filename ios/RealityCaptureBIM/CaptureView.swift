//
//  CaptureView.swift
//  RealityCaptureBIM
//
//  Minimal capture UI: live camera passthrough (so the user can see
//  what they're scanning), start/stop controls, and a running
//  progress count as a crude coverage signal. This intentionally
//  does NOT implement the full "guided coverage heat map" UI
//  described in V1 spec Section 3 -- that's a real design/
//  engineering task on its own, out of scope for this scaffold.
//  What's here is the minimum needed to actually run a capture
//  session (LiDAR or non-LiDAR, auto-detected) and produce a bundle.
//
//  REFERENCE / UNVERIFIED -- see ARCaptureSession.swift's header.
//

import SwiftUI
import ARKit
import SceneKit

struct ARPassthroughView: UIViewRepresentable {
    let session: ARSession

    func makeUIView(context: Context) -> ARSCNView {
        let view = ARSCNView(frame: .zero)
        view.session = session
        view.automaticallyUpdatesLighting = true
        return view
    }

    func updateUIView(_ uiView: ARSCNView, context: Context) {}
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