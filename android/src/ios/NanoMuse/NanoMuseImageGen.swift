//
//  NanoMuseImageGen.swift
//  nanoMuse
//
//  Where the pictures for the face come from. With an Alibaba Cloud Bailian
//  key on this phone (an OpenAI-compatible provider whose base URL is on
//  dashscope / aliyuncs), the face is drawn with that key through Model
//  Studio's native multimodal endpoint — the compatible endpoint answers 404
//  to image models. A self-hosted relay can also be used when its live menu
//  explicitly advertises image generation. Android: avatar/ImageGen.kt.
//

import Foundation
import UIKit

enum NanoMuseImageGen {
    /// A Bailian (DashScope) provider instance on this phone and its key.
    struct OwnKey: Equatable {
        var instanceId: String
        var label: String
        var baseURL: String
        var apiKey: String
        var model: String
    }

    enum Route: Equatable {
        case ownKey(OwnKey)
        case relay
        case unavailable
    }

    struct Failure: LocalizedError {
        var message: String
        var errorDescription: String? { message }
    }
}

/// The sentences for a provider's refusal of a picture or a clip, shared by the image and
/// video generators: the status says what happened, the vendor's own words follow when it sent some.
enum NanoMuseMediaWords {
    static func refused(status: Int, vendorMessage: String?) -> String {
        let head: String
        switch status {
        case 401, 403: head = AppLocalized("The provider refused this key (HTTP %d).")
        case 429: head = AppLocalized("The provider asked to slow down (HTTP %d).")
        case 500...599: head = AppLocalized("The provider did not answer properly (HTTP %d).")
        default: head = AppLocalized("The provider answered HTTP %d.")
        }
        let line = String(format: head, status)
        guard let m = vendorMessage?.trimmingCharacters(in: .whitespacesAndNewlines), !m.isEmpty else { return line }
        return line + " " + String(format: AppLocalized("The provider says: %@"), String(m.prefix(300)))
    }
}

extension NanoMuseImageGen {

    static let defaultsModelKey = "nanomuse.avatar.model"
    static let defaultsInstanceKey = "nanomuse.avatar.instance"
    private static let defaultsPreferRelayKey = "nanomuse.avatar.prefer_relay"
    private static let defaultsRelayModelKey = "nanomuse.avatar.relay_model"

    /// The person chose a relay that advertises pictures (Settings › Models, or the older Image &
    /// video models page). An explicit choice wins over any key on the phone while signed in.
    static var preferRelay: Bool {
        get { UserDefaults.standard.bool(forKey: defaultsPreferRelayKey) }
        set { UserDefaults.standard.set(newValue, forKey: defaultsPreferRelayKey) }
    }

    /// The relay's image model the person picked (0.1.41); nil for the relay's own first choice.
    static var relayModel: String? {
        let s = UserDefaults.standard.string(forKey: defaultsRelayModelKey)?.trimmingCharacters(in: .whitespaces) ?? ""
        return s.isEmpty ? nil : s
    }

    /// Pictures through the configured relay from now on, with `model` when the person picked one.
    @MainActor
    static func useRelay(model: String? = nil) {
        preferRelay = true
        UserDefaults.standard.set(model?.trimmingCharacters(in: .whitespaces) ?? "", forKey: defaultsRelayModelKey)
    }

    /// The relay's image model for the next picture: the one picked, else the first its menu lists.
    @MainActor
    static func relayImageModel() async throws -> String {
        if let model = relayModel, NanoMuseModelSlots.cloudProvider()?.models[.image]?.contains(model) == true { return model }
        return try await NanoMuseRelayMedia.imageModel()
    }
    /// The catalogue's `defaults.image` for Bailian (¥0.18 a picture; the Pro tier draws the
    /// same face for more); the known id only if the catalogue is missing.
    static var recommendedBailianModel: String {
        NanoMuseCatalogue.bundled.first { $0.id == NanoMuseCatalogue.bailian }?.defaults["image"] ?? "qwen-image-3.0"
    }

    /// Follows the proxy setting (Settings → Network) like a chat turn on the same provider.
    private static let sessionSlot = NanoMuseProxy.SessionSlot(requestTimeout: 180, resourceTimeout: 300)
    private static var session: URLSession { sessionSlot.session }

    // MARK: Route (pure part tested)

    static func speaksDashScope(_ baseURL: String) -> Bool {
        let b = baseURL.lowercased()
        return b.contains("aliyuncs.com") || b.contains("dashscope")
    }

    /// Model Studio's native endpoint takes qwen-image and wan-image; nothing else.
    static func drawsNatively(_ modelId: String) -> Bool {
        let id = modelId.lowercased()
        return id.hasPrefix("qwen-image") || (id.hasPrefix("wan") && id.contains("-image"))
    }

    /// The host part of a DashScope base URL, with `/compatible-mode` and `/api/v1` removed.
    static func dashScopeHost(_ baseURL: String) -> String {
        var host = baseURL
        if let r = host.range(of: "/compatible-mode") { host = String(host[..<r.lowerBound]) }
        if let r = host.range(of: "/api/v1") { host = String(host[..<r.lowerBound]) }
        while host.hasSuffix("/") { host.removeLast() }
        return host
    }

    /// Bailian instances with a key on this phone, the nanoMuse Cloud instance excluded.
    @MainActor
    static func bailianInstances() -> [ProviderInstance] {
        let cloudId = NanoMuseCloud.instance?.id
        return ProviderConfigStore.shared.instances.filter { inst in
            inst.isEnabled
                && inst.id != cloudId
                && (inst.providerType == .openAI || inst.providerType == .openAIResponses)
                && speaksDashScope(inst.customBaseURL ?? "")
                && !(ProviderKeychainHelper.loadAPIKey(instanceId: inst.id) ?? "").isEmpty
        }
    }

    /// Where the next picture is drawn (0.1.41, the contract's section 3): the person's choice
    /// first; without one, the chat provider's own image model when the chat runs on a key of
    /// their own that draws, then a signed-in relay whose live menu advertises pictures, then
    /// the first key on the phone that draws. A relay never jumps ahead of a provider the
    /// person picked.
    @MainActor
    static func route() -> Route {
        let candidates = bailianInstances()
        guard let resolved = NanoMuseModelSlots.imageValue() else { return .unavailable }
        if resolved.providerId == NanoMuseCloud.instance?.id {
            return NanoMuseCloud.modelsOn ? .relay : .unavailable
        }
        guard let inst = candidates.first(where: { $0.id == resolved.providerId }),
              let key = ProviderKeychainHelper.loadAPIKey(instanceId: inst.id), !key.isEmpty else { return .unavailable }
        let model = resolved.model.isEmpty ? suggestedModel(for: inst) : resolved.model
        return .ownKey(OwnKey(instanceId: inst.id, label: inst.label, baseURL: inst.customBaseURL ?? "", apiKey: key, model: model))
    }

    @MainActor
    static var usesOwnKey: Bool {
        if case .ownKey = route() { return true }
        return false
    }

    /// Image models the instance lists that the native endpoint draws with.
    @MainActor
    static func availableModels(for inst: ProviderInstance) -> [String] {
        var ids = ProviderConfigStore.shared.entries(for: inst.id)
            .map(\.model.id)
            .filter { drawsNatively($0) }
        if !ids.contains(recommendedBailianModel) { ids.append(recommendedBailianModel) }
        return Array(NSOrderedSet(array: ids)) as? [String] ?? ids
    }

    @MainActor
    static func suggestedModel(for inst: ProviderInstance) -> String {
        let listed = ProviderConfigStore.shared.entries(for: inst.id).map(\.model.id)
        if listed.isEmpty || listed.contains(recommendedBailianModel) { return recommendedBailianModel }
        return listed.first { drawsNatively($0) } ?? recommendedBailianModel
    }

    @MainActor
    static func save(instanceId: String, model: String) {
        UserDefaults.standard.set(instanceId, forKey: defaultsInstanceKey)
        UserDefaults.standard.set(model.trimmingCharacters(in: .whitespaces), forKey: defaultsModelKey)
        preferRelay = false // a key was chosen on purpose
    }

    /// Back to the automatic order for pictures (the *Automatic* entry of the picker): no key
    /// and no relay preference stored, so `route()` follows the chat provider, then a relay
    /// that advertises pictures, then the first key that draws.
    @MainActor
    static func clearChoice() {
        for key in [defaultsInstanceKey, defaultsModelKey, defaultsPreferRelayKey, defaultsRelayModelKey] {
            UserDefaults.standard.removeObject(forKey: key)
        }
    }

    /// "Drawn by nanoMuse Cloud" / "Drawn by Bailian · qwen-image-3.0".
    @MainActor
    static func providerLine() -> String {
        switch route() {
        case .relay: return String(format: AppLocalized("Drawn by %@"), NanoMuseCloud.label)
        case .ownKey(let k): return String(format: AppLocalized("Drawn by %@ · %@"), k.label, k.model)
        case .unavailable: return AppLocalized("No image model found on this provider. Type one below, or check again once the key is in.")
        }
    }

    // MARK: Drawing

    @MainActor
    static func generate(prompt: String) async throws -> UIImage {
        switch route() {
        case .relay:
            let model = try await relayImageModel()
            return try await NanoMuseRelayMedia.generate(prompt: prompt, model: model)
        case .ownKey(let k):
            var parameters: [String: Any] = ["size": "1024*1024", "watermark": false]
            if k.model.hasPrefix("qwen-image") { parameters["prompt_extend"] = false }
            return try await callDashScope(k, model: k.model, content: [["text": prompt]], parameters: parameters, what: "generation")
        case .unavailable:
            throw Failure(message: AppLocalized("No image model found on this provider. Type one below, or check again once the key is in."))
        }
    }

    @MainActor
    static func edit(_ image: UIImage, prompt: String) async throws -> UIImage {
        switch route() {
        case .relay:
            let model = try await relayImageModel()
            return try await NanoMuseRelayMedia.edit(image, prompt: prompt, model: model)
        case .ownKey(let k):
            // qwen-image-3.x, wan-image and qwen-image-edit-* take a picture themselves; an
            // older text-only qwen-image is posed by qwen-image-edit-max on the same key.
            let threeX = k.model.hasPrefix("qwen-image-3") || k.model.hasPrefix("wan")
            let model = (threeX || k.model.contains("edit")) ? k.model : "qwen-image-edit-max"
            let parameters: [String: Any] = threeX
                ? ["size": "1024*1024", "prompt_extend": false, "watermark": false]
                : ["n": 1, "watermark": false]
            guard let png = NanoMuseFaceStore.square(image, side: 768).pngData() else {
                throw Failure(message: AppLocalized("The picture could not be encoded."))
            }
            let content: [[String: Any]] = [
                ["image": "data:image/png;base64," + png.base64EncodedString()],
                ["text": prompt],
            ]
            return try await callDashScope(k, model: model, content: content, parameters: parameters, what: "edit")
        case .unavailable:
            throw Failure(message: AppLocalized("No image model found on this provider. Type one below, or check again once the key is in."))
        }
    }

    /// One call to `multimodal-generation/generation`; the first image of the reply.
    private static func callDashScope(_ k: OwnKey, model: String, content: [[String: Any]], parameters: [String: Any], what: String) async throws -> UIImage {
        let host = dashScopeHost(k.baseURL)
        guard let url = URL(string: host + "/api/v1/services/aigc/multimodal-generation/generation") else {
            throw Failure(message: AppLocalized("The provider's address is not valid."))
        }
        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.setValue("Bearer \(k.apiKey)", forHTTPHeaderField: "Authorization")
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        let body: [String: Any] = [
            "model": model,
            "input": ["messages": [["role": "user", "content": content]]],
            "parameters": parameters,
        ]
        request.httpBody = try JSONSerialization.data(withJSONObject: body)
        let (data, response) = try await session.data(for: request)
        let status = (response as? HTTPURLResponse)?.statusCode ?? 0
        let json = (try? JSONSerialization.jsonObject(with: data)) as? [String: Any]
        guard (200..<300).contains(status) else {
            let msg = (json?["message"] as? String).flatMap { $0.isEmpty ? nil : $0 }
            throw Failure(message: NanoMuseMediaWords.refused(status: status, vendorMessage: msg))
        }
        guard let json else { throw Failure(message: AppLocalized("The provider's reply could not be read.")) }
        let choice = ((json["output"] as? [String: Any])?["choices"] as? [[String: Any]])?.first
        let parts = ((choice?["message"] as? [String: Any])?["content"] as? [[String: Any]]) ?? []
        guard let imageURLString = parts.compactMap({ $0["image"] as? String }).first(where: { !$0.isEmpty }),
              let imageURL = URL(string: imageURLString) else {
            throw Failure(message: (json["message"] as? String).flatMap { $0.isEmpty ? nil : $0 } ?? AppLocalized("The provider sent no picture."))
        }
        let (bytes, imageResponse) = try await session.data(from: imageURL)
        let imageStatus = (imageResponse as? HTTPURLResponse)?.statusCode ?? 0
        guard (200..<300).contains(imageStatus) else { throw Failure(message: String(format: AppLocalized("The picture could not be downloaded (HTTP %d)."), imageStatus)) }
        guard let image = UIImage(data: bytes) else { throw Failure(message: AppLocalized("The picture could not be decoded.")) }
        return image
    }
}
