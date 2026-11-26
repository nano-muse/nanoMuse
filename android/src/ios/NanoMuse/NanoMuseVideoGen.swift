//
//  NanoMuseVideoGen.swift
//  nanoMuse
//
//  Short clips through Alibaba Cloud Model Studio's asynchronous video API —
//  Wan 2.2 Flash by default, or whichever Wan or MiniMax model the person
//  picked or typed. The host is either Model Studio itself (the person's own
//  key) or a self-hosted relay whose live menu explicitly advertises video.
//  A first frame is uploaded to Model Studio's free 48-hour
//  temporary storage first (`/api/v1/uploads`), because the video API takes
//  URLs, not inline data; then `POST …/video-synthesis` with
//  `X-DashScope-Async: enable` returns a task, `GET /api/v1/tasks/{id}` is
//  polled every 10 s for up to 12 minutes, and the MP4 is downloaded.
//
//  The families take different bodies: MiniMax wants `media[first_frame]`,
//  `resolution`, `ratio` and `duration`; Wan up to 2.6 wants `img_url`,
//  `resolution`/`size` and — on wan2.6 and 2.5 — a `duration`; Wan 2.7
//  speaks Model Studio's newer protocol, `media[first_frame]` with
//  `resolution` for a picture and `resolution` with `ratio` for words,
//  `duration` 2–15 on both.
//  Wan splits text-to-video and image-to-video into sibling models
//  (`wan2.6-t2v` / `wan2.6-i2v`); whichever the person picked, the sibling
//  is used for the other job.
//
//  Billing is per output second, so callers keep `seconds` at the minimum
//  that reads well (4 for an avatar loop). Android: media/VideoGen.kt.
//

import Foundation
import UIKit

enum NanoMuseVideoGen {
    static let pollSeconds: Double = 10
    static let maxWaitSeconds: Double = 12 * 60

    /// Where a clip is made: a provider instance with a key, and the model.
    struct Endpoint: Equatable, Sendable {
        var instanceId: String
        var label: String
        /// A Model Studio or explicitly media-enabled relay origin, without the API path.
        var host: String
        var apiKey: String
        var model: String
        var studioURL: URL? {
            guard model == NanoMuseRelayMenu.hostedVideo, !NanoMuseRelayMenu.allows(.video, at: host) else { return nil }
            return URL(string: "/app/?video=wizshot", relativeTo: URL(string: host))?.absoluteURL
        }
    }

    struct Failure: LocalizedError, Sendable {
        var message: String
        var errorDescription: String? { message }
    }

    enum Progress: Equatable, Sendable {
        case uploading
        case submitted
        case running(elapsedSeconds: Int)
        case downloading
    }

    // MARK: Pure parts (tested)

    /// Hosts that speak Model Studio's video API.
    static func speaksDashScope(_ baseURL: String) -> Bool {
        let b = baseURL.lowercased()
        return b.contains("aliyuncs.com") || b.contains("dashscope")
    }

    /// The host part of a provider base URL: `/compatible-mode`, `/api/v1` and a trailing `/v1` removed.
    static func host(of baseURL: String) -> String {
        var host = baseURL.trimmingCharacters(in: .whitespacesAndNewlines)
        if let r = host.range(of: "/compatible-mode") { host = String(host[..<r.lowerBound]) }
        if let r = host.range(of: "/api/v1") { host = String(host[..<r.lowerBound]) }
        while host.hasSuffix("/") { host.removeLast() }
        if host.hasSuffix("/v1") { host.removeLast(3) }
        while host.hasSuffix("/") { host.removeLast() }
        return host
    }

    /// The video models Model Studio serves through this API, as of this build; the first is the recommended one.
    static let knownDashScopeModels: [String] = [
        "wan2.2-i2v-flash",
        "wan2.7-i2v", "wan2.7-t2v",
        "MiniMax/MiniMax-H3",
        "wan2.6-i2v", "wan2.6-t2v",
        "wan2.5-i2v-preview", "wan2.5-t2v-preview",
        "wan2.2-i2v-plus", "wan2.2-t2v-plus",
    ]

    /// Names that mean "video" in a provider's model list.
    static func looksLikeVideoModel(_ id: String) -> Bool {
        let s = id.lowercased()
        return s == NanoMuseRelayMenu.hostedVideo || ["t2v", "i2v", "video", "minimax-h", "hailuo", "kling", "veo", "seedance", "sora"].contains { s.contains($0) }
    }

    private static func isWan(_ model: String) -> Bool { model.lowercased().hasPrefix("wan") }

    /// Wan 2.7 (`wan2.7-i2v`, `wan2.7-t2v`, their dated snapshots): the newer protocol.
    static func isWan27(_ model: String) -> Bool { model.lowercased().hasPrefix("wan2.7") }

    /// The Wan sibling for the job: `…-i2v…` from a picture, `…-t2v…` from words. Wan 2.2 has no text-to-video Flash: its Plus is
    /// the sibling there. Wan 2.7's dated snapshots differ between the two (`wan2.7-t2v-2026-06-12`, `wan2.7-i2v-2026-04-25`), so
    /// the sibling there is the undated id, which Model Studio keeps current.
    static func model(for model: String, fromImage: Bool) -> String {
        if !isWan(model) { return model }
        if isWan27(model) {
            let kind = fromImage ? "i2v" : "t2v"
            return model.lowercased().contains(kind) ? model : "wan2.7-" + kind
        }
        if fromImage { return model.replacingOccurrences(of: "t2v", with: "i2v") }
        if model.hasPrefix("wan2.2") { return "wan2.2-t2v-plus" }
        return model.replacingOccurrences(of: "i2v", with: "t2v")
    }

    /// Wan 2.2 is priced by resolution (480P is half of 720P) and the avatar's clips are small; the newer Wans start at 720P.
    static func wanResolution(_ model: String) -> String { model.hasPrefix("wan2.2") ? "480P" : "720P" }

    /// Wan 2.2 has a fixed length; 2.5 takes 5 or 10; 2.6 anything from 2 to 15. MiniMax 4–15.
    static func duration(for model: String, seconds: Int) -> Int? {
        if model.hasPrefix("wan2.2") { return nil }
        if model.hasPrefix("wan2.5") { return seconds <= 7 ? 5 : 10 }
        if isWan(model) { return min(max(seconds, 2), 15) }
        return min(max(seconds, 4), 15)
    }

    /// The body of an image-to-video task, as the families want it; `model` is already the sibling for the job.
    static func imageToVideoBody(model: String, ossURL: String, prompt: String, seconds: Int) -> [String: Any] {
        var input: [String: Any] = ["prompt": prompt]
        var parameters: [String: Any] = ["watermark": false]
        if isWan27(model) {
            input["media"] = [["type": "first_frame", "url": ossURL]]
            parameters["resolution"] = "720P"
        } else if isWan(model) {
            input["img_url"] = ossURL
            parameters["resolution"] = wanResolution(model)
        } else {
            input["media"] = [["type": "first_frame", "url": ossURL]]
            parameters["resolution"] = "768P"
        }
        if let d = duration(for: model, seconds: seconds) { parameters["duration"] = d }
        return ["model": model, "input": input, "parameters": parameters]
    }

    /// The body of a text-to-video task. Wan 2.7 has 16:9, 9:16, 1:1, 4:3 and 3:4, so 21:9 becomes 16:9 there.
    static func textToVideoBody(model: String, prompt: String, seconds: Int, ratio: String) -> [String: Any] {
        var parameters: [String: Any] = ["watermark": false]
        if isWan27(model) {
            parameters["resolution"] = "720P"
            parameters["ratio"] = ratio == "21:9" ? "16:9" : ratio
        } else if isWan(model) {
            parameters["size"] = wanSize(ratio)
        } else {
            parameters["resolution"] = "768P"
            parameters["ratio"] = ratio
        }
        if let d = duration(for: model, seconds: seconds) { parameters["duration"] = d }
        return ["model": model, "input": ["prompt": prompt], "parameters": parameters]
    }

    /// Wan text-to-video takes a pixel size instead of a ratio; 720p-class frames for each ratio.
    static func wanSize(_ ratio: String) -> String {
        switch ratio {
        case "16:9": return "1280*720"
        case "9:16": return "720*1280"
        case "4:3": return "960*720"
        case "3:4": return "720*960"
        case "21:9": return "1680*720"
        default: return "960*960"
        }
    }

    /// The person-facing reason from a failed task; the activation message gets a plainer wording.
    static func failureMessage(_ output: [String: Any]) -> String {
        let code = output["code"] as? String ?? ""
        let message = output["message"] as? String ?? ""
        if message.range(of: "not activated", options: .caseInsensitive) != nil {
            return AppLocalized("The video model is not activated on this account. Open the model's card in the Model Studio console and activate it.")
        }
        if !message.isEmpty { return code.isEmpty ? message : "\(code): \(message)" }
        if !code.isEmpty { return code }
        let status = output["task_status"] as? String ?? ""
        return String(format: AppLocalized("The video task ended as %@."), status.isEmpty ? "FAILED" : status)
    }

    /// DashScope puts the message at the top; the nanoMuse relay answers OpenAI-shaped (`error.message`, e.g. the clip allowance). Empty when there is none.
    static func apiMessage(_ data: Data) -> String {
        guard let json = (try? JSONSerialization.jsonObject(with: data)) as? [String: Any] else { return "" }
        var message = json["message"] as? String ?? ""
        if message.isEmpty { message = (json["error"] as? [String: Any])?["message"] as? String ?? "" }
        return message
    }

    /// The API wants 256–5760 px on each side and an aspect within [0.4, 2.5]; a face is square, so
    /// only size matters. The factor to scale a frame by, or nil when it fits as it is.
    static func frameScale(width: CGFloat, height: CGFloat) -> CGFloat? {
        let maxSide: CGFloat = 1024
        let minSide: CGFloat = 256
        let longest = max(width, height)
        let shortest = min(width, height)
        if longest > maxSide { return maxSide / longest }
        if shortest < minSide { return minSide / shortest }
        return nil
    }

    // MARK: HTTP

    /// Follows the proxy setting (Settings → Network) like a chat turn on the same provider.
    private static let sessionSlot = NanoMuseProxy.SessionSlot(requestTimeout: 120, resourceTimeout: 15 * 60)
    private static var session: URLSession { sessionSlot.session }

    private static func request(_ method: String, _ url: URL, key: String?) -> URLRequest {
        var request = URLRequest(url: url)
        request.httpMethod = method
        if let key { request.setValue("Bearer \(key)", forHTTPHeaderField: "Authorization") }
        let version = Bundle.main.infoDictionary?["CFBundleShortVersionString"] as? String ?? "0"
        request.setValue("nanoMuse-iOS/\(version)", forHTTPHeaderField: "User-Agent")
        return request
    }

    private static func send(_ request: URLRequest) async throws -> (Data, Int) {
        let (data, response) = try await session.data(for: request)
        return (data, (response as? HTTPURLResponse)?.statusCode ?? 0)
    }

    /// Whether `model` exists for this key, without making a video: an empty task is submitted and
    /// Model Studio answers 404 "Model not exist" for an unknown name, or accepts the task (which
    /// then fails at once on the missing prompt — nothing is billed). Nil when the host could not be asked.
    static func probe(host: String, apiKey: String, model: String) async -> Bool? {
        guard let url = URL(string: host + "/api/v1/services/aigc/video-generation/video-synthesis") else { return nil }
        var req = request("POST", url, key: apiKey)
        req.setValue("application/json", forHTTPHeaderField: "Content-Type")
        req.setValue("enable", forHTTPHeaderField: "X-DashScope-Async")
        req.httpBody = try? JSONSerialization.data(withJSONObject: ["model": model, "input": [:], "parameters": [:]] as [String: Any])
        do {
            let (data, status) = try await send(req)
            let text = String(data: data, encoding: .utf8) ?? ""
            if (200..<300).contains(status) { return true }
            if status == 404 || text.range(of: "Model not exist", options: .caseInsensitive) != nil { return false }
            if status == 401 || status == 403 { return nil }
            // Accepted the model name but not the empty body: the model is there.
            if status == 400 { return true }
            return nil
        } catch {
            return nil
        }
    }

    /// A clip that starts from `image`. Returns the MP4 bytes.
    static func imageToVideo(
        _ ep: Endpoint,
        image: UIImage,
        prompt: String,
        seconds: Int = 4,
        onProgress: @escaping @Sendable (Progress) -> Void = { _ in }
    ) async throws -> Data {
        if let url = ep.studioURL { throw Failure(message: url.absoluteString) }
        onProgress(.uploading)
        let model = Self.model(for: ep.model, fromImage: true)
        guard let png = fitFrame(image).pngData() else { throw Failure(message: AppLocalized("The picture could not be encoded.")) }
        var uploadEndpoint = ep
        uploadEndpoint.model = model
        let ossURL = try await uploadTemp(uploadEndpoint, bytes: png, name: "first-frame.png", mime: "image/png")
        let task = try await createTask(ep, body: imageToVideoBody(model: model, ossURL: ossURL, prompt: prompt, seconds: seconds), ossInput: true)
        onProgress(.submitted)
        let url = try await poll(ep, taskId: task, onProgress: onProgress)
        onProgress(.downloading)
        return try await download(url)
    }

    /// A clip from words alone. `ratio` is one of 16:9, 9:16, 1:1, 4:3, 3:4, 21:9.
    static func textToVideo(
        _ ep: Endpoint,
        prompt: String,
        seconds: Int = 4,
        ratio: String = "1:1",
        onProgress: @escaping @Sendable (Progress) -> Void = { _ in }
    ) async throws -> Data {
        if let url = ep.studioURL { throw Failure(message: url.absoluteString) }
        let model = Self.model(for: ep.model, fromImage: false)
        let task = try await createTask(ep, body: textToVideoBody(model: model, prompt: prompt, seconds: seconds, ratio: ratio), ossInput: false)
        onProgress(.submitted)
        let url = try await poll(ep, taskId: task, onProgress: onProgress)
        onProgress(.downloading)
        return try await download(url)
    }

    // MARK: The protocol

    /// Model Studio's temporary storage: a signed OSS policy, then a multipart POST. Returns the `oss://` URL.
    static func uploadTemp(_ ep: Endpoint, bytes: Data, name: String, mime: String) async throws -> String {
        let modelQuery = ep.model.addingPercentEncoding(withAllowedCharacters: .urlQueryAllowed) ?? ep.model
        guard let policyURL = URL(string: ep.host + "/api/v1/uploads?action=getPolicy&model=" + modelQuery) else {
            throw Failure(message: AppLocalized("The provider's address is not valid."))
        }
        let (policyData, policyStatus) = try await send(request("GET", policyURL, key: ep.apiKey))
        guard (200..<300).contains(policyStatus) else {
            throw Failure(message: NanoMuseMediaWords.refused(status: policyStatus, vendorMessage: apiMessage(policyData)))
        }
        guard let policyJSON = (try? JSONSerialization.jsonObject(with: policyData)) as? [String: Any],
              let policy = policyJSON["data"] as? [String: Any],
              let uploadDir = policy["upload_dir"] as? String,
              let uploadHost = policy["upload_host"] as? String,
              let accessKey = policy["oss_access_key_id"] as? String,
              let signature = policy["signature"] as? String,
              let policyText = policy["policy"] as? String,
              let formURL = URL(string: uploadHost) else {
            throw Failure(message: AppLocalized("The provider's reply could not be read."))
        }
        let key = uploadDir + "/" + name
        let boundary = "nanomuse-" + UUID().uuidString
        var form = Data()
        func field(_ fieldName: String, _ value: String) {
            form.append(Data("--\(boundary)\r\n".utf8))
            form.append(Data("Content-Disposition: form-data; name=\"\(fieldName)\"\r\n\r\n".utf8))
            form.append(Data(value.utf8))
            form.append(Data("\r\n".utf8))
        }
        field("OSSAccessKeyId", accessKey)
        field("Signature", signature)
        field("policy", policyText)
        field("x-oss-object-acl", policy["x_oss_object_acl"] as? String ?? "private")
        field("x-oss-forbid-overwrite", policy["x_oss_forbid_overwrite"] as? String ?? "true")
        field("key", key)
        form.append(Data("--\(boundary)\r\n".utf8))
        form.append(Data("Content-Disposition: form-data; name=\"file\"; filename=\"\(name)\"\r\n".utf8))
        form.append(Data("Content-Type: \(mime)\r\n\r\n".utf8))
        form.append(bytes)
        form.append(Data("\r\n--\(boundary)--\r\n".utf8))
        var upload = request("POST", formURL, key: nil)
        upload.setValue("multipart/form-data; boundary=\(boundary)", forHTTPHeaderField: "Content-Type")
        upload.httpBody = form
        let (_, uploadStatus) = try await send(upload)
        guard (200..<300).contains(uploadStatus) else { throw Failure(message: String(format: AppLocalized("The picture could not be uploaded (HTTP %d)."), uploadStatus)) }
        return "oss://" + key
    }

    private static func createTask(_ ep: Endpoint, body: [String: Any], ossInput: Bool) async throws -> String {
        guard let url = URL(string: ep.host + "/api/v1/services/aigc/video-generation/video-synthesis") else {
            throw Failure(message: AppLocalized("The provider's address is not valid."))
        }
        var req = request("POST", url, key: ep.apiKey)
        req.setValue("application/json", forHTTPHeaderField: "Content-Type")
        req.setValue("enable", forHTTPHeaderField: "X-DashScope-Async")
        if ossInput { req.setValue("enable", forHTTPHeaderField: "X-DashScope-OssResourceResolve") }
        req.httpBody = try JSONSerialization.data(withJSONObject: body)
        let (data, status) = try await send(req)
        guard (200..<300).contains(status) else { throw Failure(message: NanoMuseMediaWords.refused(status: status, vendorMessage: apiMessage(data))) }
        guard let json = (try? JSONSerialization.jsonObject(with: data)) as? [String: Any] else {
            throw Failure(message: AppLocalized("The provider's reply could not be read."))
        }
        if let taskId = (json["output"] as? [String: Any])?["task_id"] as? String, !taskId.isEmpty { return taskId }
        let message = json["message"] as? String ?? ""
        throw Failure(message: message.isEmpty ? AppLocalized("The provider did not start the video task.") : message)
    }

    private static func poll(_ ep: Endpoint, taskId: String, onProgress: @escaping @Sendable (Progress) -> Void) async throws -> String {
        guard let url = URL(string: ep.host + "/api/v1/tasks/" + taskId) else { throw Failure(message: AppLocalized("The provider's address is not valid.")) }
        let started = Date()
        while true {
            try await Task.sleep(nanoseconds: UInt64(pollSeconds * 1_000_000_000))
            try Task.checkCancellation()
            let (data, status) = try await send(request("GET", url, key: ep.apiKey))
            guard (200..<300).contains(status) else { throw Failure(message: NanoMuseMediaWords.refused(status: status, vendorMessage: apiMessage(data))) }
            guard let json = (try? JSONSerialization.jsonObject(with: data)) as? [String: Any] else {
                throw Failure(message: AppLocalized("The provider's reply could not be read."))
            }
            let out = json["output"] as? [String: Any] ?? [:]
            switch out["task_status"] as? String ?? "" {
            case "SUCCEEDED":
                if let videoURL = out["video_url"] as? String, !videoURL.isEmpty { return videoURL }
                throw Failure(message: AppLocalized("The provider sent no video."))
            case "FAILED", "CANCELED", "UNKNOWN":
                throw Failure(message: failureMessage(out))
            default:
                break
            }
            let elapsed = Int(Date().timeIntervalSince(started))
            onProgress(.running(elapsedSeconds: elapsed))
            if Double(elapsed) > maxWaitSeconds { throw Failure(message: String(format: AppLocalized("The video took longer than %d minutes."), elapsed / 60)) }
        }
    }

    private static func download(_ urlString: String) async throws -> Data {
        guard let url = URL(string: urlString) else { throw Failure(message: AppLocalized("The provider sent no video.")) }
        let (data, status) = try await send(request("GET", url, key: nil))
        guard (200..<300).contains(status) else { throw Failure(message: String(format: AppLocalized("The video could not be downloaded (HTTP %d)."), status)) }
        guard !data.isEmpty else { throw Failure(message: AppLocalized("The provider sent no video.")) }
        return data
    }

    private static func fitFrame(_ image: UIImage) -> UIImage {
        let w = image.size.width * image.scale
        let h = image.size.height * image.scale
        guard w > 0, h > 0, let scale = frameScale(width: w, height: h) else { return image }
        let target = CGSize(width: max((w * scale).rounded(), 256), height: max((h * scale).rounded(), 256))
        let format = UIGraphicsImageRendererFormat()
        format.scale = 1
        format.opaque = false
        return UIGraphicsImageRenderer(size: target, format: format).image { _ in
            image.draw(in: CGRect(origin: .zero, size: target))
        }
    }
}
