//
//  BundleWriter.swift
//  RealityCaptureBIM
//
//  Writes a capture bundle to disk in whichever format the Python
//  side's geometry/capture_ingestion.py expects for the given
//  capture mode:
//
//      LiDAR mode:
//        <bundle_dir>/manifest.json  (capture_method: "lidar_mesh")
//        <bundle_dir>/points.json
//
//      Non-LiDAR mode:
//        <bundle_dir>/manifest.json
//            (capture_method: "arkit_plane_detection")
//        <bundle_dir>/planes.json
//
//  Field names, the coordinate_frame string, and JSON structure
//  here must stay byte-for-byte in sync with
//  capture_ingestion.py's load_bundle() / load_plane_bundle() --
//  this is the actual interface contract between the iOS app and
//  the server-side pipeline. If either side changes field names
//  independently, ingestion breaks silently (a confusing KeyError,
//  not a helpful error) until someone notices.
//
//  REFERENCE / UNVERIFIED -- see ARCaptureSession.swift's header.
//

import Foundation

struct BundleManifest: Codable {
    let session_id: String
    let device_model: String
    let capture_timestamp: String
    let coordinate_frame: String
    let capture_method: String
    let point_count: Int
    let plane_count: Int
}

struct SerializablePlane: Codable {
    let alignment: String
    let boundary_vertices: [[Double]]
}

enum BundleWriter {

    /// LiDAR mode: writes manifest.json + points.json, matching
    /// capture_ingestion.py's load_bundle() contract exactly.
    static func writePointCloudBundle(
        points: [CapturedPoint],
        sessionID: String,
        deviceModel: String,
        captureTimestamp: String,
        to directory: URL
    ) throws {
        try FileManager.default.createDirectory(
            at: directory,
            withIntermediateDirectories: true
        )

        let manifest = BundleManifest(
            session_id: sessionID,
            device_model: deviceModel,
            capture_timestamp: captureTimestamp,
            coordinate_frame: "arkit_world_y_up_meters",
            capture_method: "lidar_mesh",
            point_count: points.count,
            plane_count: 0
        )
        try writeManifest(manifest, to: directory)

        // points.json is a flat JSON array of [x, y, z] triples --
        // NOT an array of objects -- matching how
        // capture_ingestion.py's load_bundle() parses it:
        // `[(p[0], p[1], p[2]) for p in raw_points]`.
        let pointsArray: [[Double]] = points.map {
            [Double($0.x), Double($0.y), Double($0.z)]
        }
        let pointsData = try JSONEncoder().encode(pointsArray)
        try pointsData.write(
            to: directory.appendingPathComponent("points.json")
        )
    }

    /// Non-LiDAR mode: writes manifest.json + planes.json, matching
    /// capture_ingestion.py's load_plane_bundle() contract exactly.
    static func writePlaneBundle(
        planes: [CapturedPlane],
        sessionID: String,
        deviceModel: String,
        captureTimestamp: String,
        to directory: URL
    ) throws {
        try FileManager.default.createDirectory(
            at: directory,
            withIntermediateDirectories: true
        )

        let manifest = BundleManifest(
            session_id: sessionID,
            device_model: deviceModel,
            capture_timestamp: captureTimestamp,
            coordinate_frame: "arkit_world_y_up_meters",
            capture_method: "arkit_plane_detection",
            point_count: 0,
            plane_count: planes.count
        )
        try writeManifest(manifest, to: directory)

        let serializablePlanes = planes.map { plane in
            SerializablePlane(
                alignment: plane.alignment,
                boundary_vertices: plane.boundaryVertices.map {
                    [Double($0.x), Double($0.y), Double($0.z)]
                }
            )
        }
        let planesData = try JSONEncoder().encode(serializablePlanes)
        try planesData.write(
            to: directory.appendingPathComponent("planes.json")
        )
    }

    private static func writeManifest(
        _ manifest: BundleManifest, to directory: URL
    ) throws {
        let manifestData = try JSONEncoder().encode(manifest)
        try manifestData.write(
            to: directory.appendingPathComponent("manifest.json")
        )
    }
}