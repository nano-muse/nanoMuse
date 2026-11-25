//
//  NanoMuseOwnTurns.swift
//  nanoMuse
//
//  A turn answered on the person's own key joins the account's record (docs/cloud.md "The
//  record", relay 0.29): the request as the agent loop made it (every message, the system
//  prompt, the tools) and the answer as the model gave it (text, reasoning, tool calls, usage,
//  why it stopped), one `POST /v1/turns` per model call, the pictures put first as files named
//  by their hash. The key itself and the provider's base URL are never part of it; what is sent
//  is what the chat on the other devices needs to show the same history. Nothing is recorded
//  while signed out, for the relay's own instance (the relay records those itself), or on a
//  relay that keeps no record. Since relay 0.31 a turn also says where it sat: who started it,
//  its number, the call's number within it, the platform (NanoMuseProvenance).
//  Android: io.github.nanomuse.cloud.OwnTurns.
//

import CryptoKit
import Foundation

enum NanoMuseOwnTurns {
    static let blobPrefix = "blob:sha256:"
    /// The relay's ceiling for one turn's JSON (`TURN_MAX_CHARS`); a larger one stays here.
    static let turnMaxChars = 2_000_000
    /// Turns waiting to go up; past this the oldest in line are dropped, not the chat.
    static let queueMax = 32

    /// `provider` as the chat uses it, recording each call when the account wants it.
    @MainActor
    static func wrap(entry: ModelEntry, _ provider: AgentProvider) -> AgentProvider {
        guard let instance = ProviderConfigStore.shared.instance(for: entry.providerInstanceId),
              instance.id != NanoMuseCloud.instance?.id else { return provider }
        let vendor = NanoMuseCatalogue.vendor(for: instance)?.id ?? instance.providerType.rawValue
        return Recording(vendor: vendor, inner: provider)
    }

    /// Whether a turn made now would be recorded: signed in, and the relay keeps a record.
    @MainActor
    static func wants() -> Bool {
        NanoMuseCloud.isSignedIn && (NanoMuseCloud.account?.recordOn ?? false)
    }

    // MARK: The wrapper

    private final class Recording: AgentProvider {
        let vendor: String
        let inner: AgentProvider

        init(vendor: String, inner: AgentProvider) {
            self.vendor = vendor
            self.inner = inner
        }

        var name: String { inner.name }
        var model: LLMModel { inner.model }
        var defaultMaxTokens: Int { inner.defaultMaxTokens }

        func streamAgentMessageClamped(
            messages: [AgentMessage],
            systemPrompt: String?,
            tools: [AgentToolDefinition],
            maxTokens: Int,
            thinkingLevel: ThinkingLevel
        ) async throws -> AsyncThrowingStream<AgentStreamEvent, Error> {
            let upstream = try await inner.streamAgentMessageClamped(
                messages: messages, systemPrompt: systemPrompt, tools: tools, maxTokens: maxTokens, thinkingLevel: thinkingLevel
            )
            guard await NanoMuseOwnTurns.wants() else { return upstream }
            let gathered = Gathered(
                vendor: vendor, model: model.id, messages: messages.filter { $0.dbMessageId?.hasPrefix(NanoMuseOutreachJournal.localPublicPrefix) != true }, systemPrompt: systemPrompt,
                tools: tools, maxTokens: maxTokens, thinkingLevel: thinkingLevel,
                origin: NanoMuseProvenance.current // the chat, the run and the turn this call sits in (relay 0.31)
            )
            return AsyncThrowingStream { continuation in
                let task = Task {
                    do {
                        for try await event in upstream {
                            gathered.take(event)
                            continuation.yield(event)
                        }
                        gathered.ended = Task.isCancelled ? "aborted" : nil
                        continuation.finish()
                    } catch is CancellationError {
                        gathered.ended = "aborted"
                        continuation.finish(throwing: CancellationError())
                    } catch {
                        gathered.ended = "error"
                        gathered.error = String(describing: error)
                        continuation.finish(throwing: error)
                    }
                    Uploader.shared.enqueue(gathered)
                }
                continuation.onTermination = { reason in
                    if case .cancelled = reason { task.cancel() }
                }
            }
        }
    }

    // MARK: What one call was

    private final class Gathered: @unchecked Sendable {
        let id = UUID().uuidString
        let ts = Date()
        let vendor: String
        let model: String
        let messages: [AgentMessage]
        let systemPrompt: String?
        let tools: [AgentToolDefinition]
        let maxTokens: Int
        let thinkingLevel: ThinkingLevel
        /// Where the call sat when it went out, as the agent loop announced it; nil from elsewhere.
        let origin: NanoMuseProvenance.Current?

        var text = ""
        var reasoning = ""
        var toolCalls: [(id: String, name: String, args: [String: Any])] = []
        var usage: LLMUsage?
        var finish: String?
        var ended: String?
        var error: String?

        init(vendor: String, model: String, messages: [AgentMessage], systemPrompt: String?, tools: [AgentToolDefinition], maxTokens: Int, thinkingLevel: ThinkingLevel, origin: NanoMuseProvenance.Current? = nil) {
            self.vendor = vendor
            self.model = model
            self.messages = messages
            self.systemPrompt = systemPrompt
            self.tools = tools
            self.maxTokens = maxTokens
            self.thinkingLevel = thinkingLevel
            self.origin = origin
        }

        func take(_ event: AgentStreamEvent) {
            switch event {
            case .textDelta(let t): text += t
            case .thinkingDelta(let t): reasoning += t
            case .reasoningContent(let whole): reasoning = whole
            case .toolCallComplete(let id, let name, let args, _): toolCalls.append((id, name, args))
            case .usage(let u): usage = u
            case .done(let reason): finish = Self.finishReason(reason)
            case .contentBlockStart, .toolInputDelta, .reasoningEcho: break
            }
        }

        private static func finishReason(_ reason: AgentStopReason) -> String {
            switch reason {
            case .endTurn: return "stop"
            case .toolUse: return "tool_calls"
            case .maxTokens: return "length"
            default: return String(describing: reason)
            }
        }
    }

    // MARK: Up to the relay, one at a time

    private final class Uploader: @unchecked Sendable {
        static let shared = Uploader()
        private let lock = NSLock()
        private var queue: [Gathered] = []
        private var running = false

        func enqueue(_ g: Gathered) {
            lock.lock()
            queue.append(g)
            if queue.count > NanoMuseOwnTurns.queueMax { queue.removeFirst(queue.count - NanoMuseOwnTurns.queueMax) }
            let start = !running
            running = true
            lock.unlock()
            if start { Task.detached(priority: .utility) { await self.drain() } }
        }

        private func next() -> Gathered? {
            lock.lock()
            defer { lock.unlock() }
            if queue.isEmpty {
                running = false
                return nil
            }
            return queue.removeFirst()
        }

        private func drain() async {
            while let g = next() {
                do {
                    try await upload(g)
                } catch {
                    AppLogger(category: "NanoMuseOwnTurns").warning("a turn did not reach the record: \(NanoMuseCloud.describe(error))")
                }
            }
        }

        private func upload(_ g: Gathered) async throws {
            var files: [String: (mime: String, data: Data)] = [:]
            var rows: [[String: Any]] = []
            if let system = g.systemPrompt, !system.isEmpty { rows.append(["role": "system", "content": system]) }
            for m in g.messages { rows.append(contentsOf: NanoMuseOwnTurns.rows(m, files: &files)) }
            var response: [String: Any] = ["role": "assistant", "content": g.text]
            if !g.reasoning.isEmpty { response["reasoning_content"] = g.reasoning }
            if !g.toolCalls.isEmpty {
                response["tool_calls"] = g.toolCalls.map { call -> [String: Any] in
                    let args = (try? JSONSerialization.data(withJSONObject: call.args)).flatMap { String(data: $0, encoding: .utf8) } ?? "{}"
                    return ["id": call.id, "type": "function", "function": ["name": call.name, "arguments": args]]
                }
            }
            if let finish = g.finish { response["finish_reason"] = finish }
            var turn: [String: Any] = [
                "id": g.id,
                "ts": g.ts.timeIntervalSince1970,
                "provider": g.vendor,
                "model": g.model,
                "conversation": NanoMuseOwnTurns.conversationKey(g.messages),
                "messages": rows,
                "params": ["max_tokens": g.maxTokens, "thinking": g.thinkingLevel.rawValue],
                "response": ["message": response],
                "status": g.ended == nil ? "ok" : "partial",
            ]
            if !g.tools.isEmpty { turn["tools"] = NanoMuseOwnTurns.toolsJSON(g.tools) }
            if let u = g.usage {
                var usage: [String: Any] = ["prompt_tokens": u.inputTokens, "completion_tokens": u.outputTokens]
                if let cached = u.cacheReadInputTokens { usage["cached_tokens"] = cached }
                var r = turn["response"] as? [String: Any] ?? [:]
                r["usage"] = usage
                turn["response"] = r
            }
            if let ended = g.ended { turn["ended"] = ended }
            if let error = g.error { turn["error"] = String(error.prefix(500)) }
            // where the call sat: run, turn, step and platform (relay 0.31); from elsewhere, counted from the request alone
            (g.origin?.fields ?? NanoMuseProvenance.Fields(run: NanoMuseProvenance.runPerson, turn: NanoMuseProvenance.turnOf(g.messages), step: NanoMuseProvenance.stepOf(g.messages))).into(&turn)
            let encoded = try JSONSerialization.data(withJSONObject: turn)
            guard encoded.count <= NanoMuseOwnTurns.turnMaxChars else {
                AppLogger(category: "NanoMuseOwnTurns").warning("a turn of \(encoded.count) bytes is past the relay's ceiling; it stays on this phone")
                return
            }
            for (sha, file) in files {
                if try await NanoMuseRelayMedia.hasBlob(sha) { continue }
                try await NanoMuseRelayMedia.putBlob(sha, mime: file.mime, data: file.data)
            }
            try await NanoMuseRelayMedia.postTurn(turn)
            NanoMuseProvenance.noteOwnTurn(session: g.origin?.sessionId, id: g.id) // the events about this turn name it
        }
    }

    // MARK: Shapes

    /// The OpenAI-style rows for one agent message: the message itself (text, pictures as
    /// files, tool calls) and one `tool` row per tool result it carries.
    private static func rows(_ m: AgentMessage, files: inout [String: (mime: String, data: Data)]) -> [[String: Any]] {
        var parts: [[String: Any]] = []
        var calls: [[String: Any]] = []
        var toolRows: [[String: Any]] = []
        for part in m.parts {
            switch part {
            case .text(let t):
                parts.append(["type": "text", "text": t])
            case .imageData(let data, let mime, _):
                parts.append(imagePart(file(data, mime: mime, into: &files)))
            case .toolUse(let id, let name, let input):
                let args = (try? JSONSerialization.data(withJSONObject: input)).flatMap { String(data: $0, encoding: .utf8) } ?? "{}"
                calls.append(["id": id, "type": "function", "function": ["name": name, "arguments": args]])
            case .toolResult(let id, let name, let content, let isError, let imageData, let imageMime, _, _):
                var row: [String: Any] = ["role": "tool", "tool_call_id": id, "name": name]
                if let imageData {
                    row["content"] = [["type": "text", "text": content], imagePart(file(imageData, mime: imageMime ?? "image/png", into: &files))]
                } else {
                    row["content"] = content
                }
                if isError { row["is_error"] = true }
                toolRows.append(row)
            }
        }
        var out: [[String: Any]] = []
        if !parts.isEmpty || !calls.isEmpty || toolRows.isEmpty {
            var row: [String: Any] = ["role": m.role.rawValue]
            if parts.isEmpty {
                row["content"] = ""
            } else if parts.count == 1, let text = parts[0]["text"] as? String {
                row["content"] = text
            } else {
                row["content"] = parts
            }
            if let reasoning = m.reasoningContent, !reasoning.isEmpty { row["reasoning_content"] = reasoning }
            if !calls.isEmpty { row["tool_calls"] = calls }
            out.append(row)
        }
        out.append(contentsOf: toolRows)
        return out
    }

    private static func imagePart(_ ref: String) -> [String: Any] {
        ["type": "image_url", "image_url": ["url": ref]]
    }

    private static func file(_ data: Data, mime: String, into files: inout [String: (mime: String, data: Data)]) -> String {
        let sha = sha256(data)
        if files[sha] == nil { files[sha] = (mime.isEmpty ? "image/png" : mime, data) }
        return blobPrefix + sha
    }

    private static func toolsJSON(_ tools: [AgentToolDefinition]) -> [[String: Any]] {
        tools.map { tool in
            var properties: [String: Any] = [:]
            for (name, param) in tool.parameters {
                var prop: [String: Any] = ["type": param.type.rawValue, "description": param.description]
                if let values = param.enumValues { prop["enum"] = values }
                properties[name] = prop
            }
            return [
                "type": "function",
                "function": [
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": ["type": "object", "properties": properties, "required": tool.required] as [String: Any],
                ] as [String: Any],
            ]
        }
    }

    /// The conversation's id as the Cloud requests name it (`X-NanoMuse-Conversation`): the
    /// prompt cache key, `minis-` and the first 32 hex of the SHA-256 of the first user text.
    static func conversationKey(_ messages: [AgentMessage]) -> String {
        for m in messages where m.role == .user {
            for part in m.parts {
                if case .text(let t) = part, !t.isEmpty {
                    return "minis-" + String(sha256(Data(t.utf8)).prefix(32))
                }
            }
        }
        return "minis-" + String(sha256(Data("minis-empty-conversation".utf8)).prefix(32))
    }

    static func sha256(_ data: Data) -> String {
        SHA256.hash(data: data).map { String(format: "%02x", $0) }.joined()
    }
}
