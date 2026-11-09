import SwiftUI

struct NanoMuseCodingFile: Identifiable, Equatable {
    var id: String { reference.isEmpty ? path : reference }
    var path: String
    var reference: String
    var additions: Int?
    var deletions: Int?
}

struct NanoMuseCodingItem: Identifiable, Equatable {
    var id: String
    var turnId: String
    var sequence: Int
    var revision: Int
    var role: String
    var kind: String
    var text: String
    var status: String
    var command: String
    var cwd: String
    var exitCode: Int?
    var duration: Double?
    var input: String
    var output: String
    var files: [NanoMuseCodingFile]
    var textTruncated: Bool

    init(_ value: [String: Any]) {
        id = value["id"] as? String ?? ""
        turnId = value["turn_id"] as? String ?? ""
        sequence = (value["sequence"] as? NSNumber)?.intValue ?? 0
        revision = (value["revision"] as? NSNumber)?.intValue ?? 0
        role = value["role"] as? String ?? "system"
        kind = value["kind"] as? String ?? "message"
        text = value["text"] as? String ?? ""
        status = value["status"] as? String ?? "completed"
        textTruncated = value["text_truncated"] as? Bool ?? false
        let cmd = value["command"] as? [String: Any] ?? [:]
        command = cmd["display_command"] as? String ?? ""
        cwd = cmd["cwd"] as? String ?? ""
        exitCode = (cmd["exit_code"] as? NSNumber)?.intValue
        duration = (cmd["duration_ms"] as? NSNumber)?.doubleValue
        input = value["input_preview"] as? String ?? ""
        output = value["output_preview"] as? String ?? ""
        files = (value["files"] as? [[String: Any]] ?? []).map {
            NanoMuseCodingFile(path: $0["path"] as? String ?? "",
                               reference: $0["diff_reference"] as? String ?? "",
                               additions: ($0["additions"] as? NSNumber)?.intValue,
                               deletions: ($0["deletions"] as? NSNumber)?.intValue)
        }
    }

    static func merge(_ old: [Self], _ incoming: [Self]) -> [Self] {
        var result = old
        for item in incoming where !item.id.isEmpty {
            if let index = result.firstIndex(where: { $0.id == item.id }) {
                if item.revision >= result[index].revision { result[index] = item }
            } else { result.append(item) }
        }
        return result
    }

    static func changes(after message: Self, in items: [Self]) -> [Self] {
        guard message.kind == "message", message.role == "assistant", !message.turnId.isEmpty,
              items.last(where: { $0.kind == "message" && $0.role == "assistant" && $0.turnId == message.turnId })?.id == message.id
        else { return [] }
        return items.filter { $0.turnId == message.turnId && !$0.files.isEmpty && $0.status != "failed" }
    }
}

struct NanoMuseCodingTurn: Identifiable {
    var id: String
    var turnId: String
    var items: [NanoMuseCodingItem]
    var messages: [NanoMuseCodingItem] { items.filter { $0.kind == "message" } }
    var tools: [NanoMuseCodingItem] { items.filter { $0.kind != "message" } }
    private var isUser: Bool { items.first?.kind == "message" && items.first?.role == "user" }

    static func group(_ items: [NanoMuseCodingItem]) -> [Self] {
        var result: [Self] = []
        for item in items {
            let user = item.kind == "message" && item.role == "user"
            let changedTurn = result.last.map {
                !item.turnId.isEmpty && !$0.turnId.isEmpty && item.turnId != $0.turnId
            } ?? false
            if result.isEmpty || user || result.last?.isUser == true || changedTurn {
                result.append(Self(id: item.id, turnId: item.turnId, items: [item]))
            } else {
                let index = result.count - 1
                result[index].items.append(item)
                if result[index].turnId.isEmpty { result[index].turnId = item.turnId }
            }
        }
        return result
    }
}

enum NanoMuseCodingDetailTarget: Identifiable {
    case item(NanoMuseCodingItem, runId: String)
    case file(NanoMuseCodingFile, runId: String)

    var id: String {
        switch self {
        case let .item(item, runId): return "item|\(runId)|\(item.id)"
        case let .file(file, runId): return "file|\(runId)|\(file.id)"
        }
    }
}

extension NanoMuseCodingBridge {
    struct HistoryPage {
        var items: [NanoMuseCodingItem]
        var cursor: String?
        var version: String
        var rich: Bool
        var runs: [[String: Any]]
    }

    @MainActor
    static func history(device: String, agent: String, sessionId: String, cursor: String? = nil) async throws -> HistoryPage {
        var args: [String: Any] = ["agent": agent, "session_id": sessionId, "protocol_version": 2, "limit": 100, "tail": true]
        if let cursor { args["cursor"] = cursor }
        let reply = try await NanoMuseHub.shared.call(to: device, action: "coding.session", args: args, timeout: listTimeout)
        let rich = reply["protocol_version"] as? Int == 2
        let items: [NanoMuseCodingItem]
        if rich {
            items = (reply["timeline"] as? [[String: Any]] ?? []).map(NanoMuseCodingItem.init)
        } else {
            items = (reply["transcript"] as? [[String: Any]] ?? []).enumerated().map {
                NanoMuseCodingItem(["id": "legacy-\($0.offset)", "sequence": $0.offset,
                                   "kind": "message", "role": $0.element["role"] ?? "",
                                   "text": $0.element["text"] ?? ""])
            }
        }
        return HistoryPage(items: items, cursor: reply["next_cursor"] as? String,
                           version: reply["version"] as? String ?? "", rich: rich,
                           runs: reply["runs"] as? [[String: Any]] ?? [])
    }

    @MainActor
    static func sessionPage(device: String, cursor: String? = nil) async throws -> (sessions: [Session], cursor: String?) {
        var args: [String: Any] = ["protocol_version": 2, "limit": 100]
        if let cursor { args["cursor"] = cursor }
        let reply = try await NanoMuseHub.shared.call(to: device, action: "coding.sessions", args: args, timeout: listTimeout)
        return ((reply["sessions"] as? [[String: Any]] ?? []).map(session), reply["next_cursor"] as? String)
    }
}

struct NanoMuseCodingItemRow: View {
    var item: NanoMuseCodingItem
    var onDetail: () -> Void
    var onFile: (NanoMuseCodingFile) -> Void
    @State private var expanded = false

    var body: some View {
        if item.kind == "message" {
            if item.role == "user" {
                HStack {
                    Spacer(minLength: 36)
                    Text(item.text).font(.callout).textSelection(.enabled)
                        .padding(12)
                        .background(NanoMuseTones.action.opacity(0.15), in: RoundedRectangle(cornerRadius: 8))
                }
            } else {
                VStack(alignment: .leading, spacing: 6) {
                    SelectableMarkdownView(markdown: item.text)
                    .fixedSize(horizontal: false, vertical: true)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    if item.textTruncated { Button(AppLocalized("Load more"), action: onDetail).font(.caption) }
                }
            }
        } else {
            VStack(alignment: .leading, spacing: 8) {
                Button { expanded.toggle() } label: {
                    HStack(spacing: 8) {
                        Image(systemName: item.kind == "command" ? "terminal" : item.kind == "file_change" ? "doc.text" : "wrench")
                            .foregroundStyle(NanoMuseTones.action)
                        Text(item.command.isEmpty ? (item.text.isEmpty && !item.files.isEmpty ? AppLocalized("File changes") : item.text) : item.command)
                            .font(.system(.caption, design: .monospaced)).lineLimit(2)
                        Spacer(minLength: 0)
                        if !item.files.isEmpty {
                            VStack(alignment: .trailing, spacing: 2) {
                                let additions = item.files.compactMap(\.additions)
                                let deletions = item.files.compactMap(\.deletions)
                                if additions.count == item.files.count { Text("+\(additions.reduce(0, +))").foregroundStyle(.green) }
                                if deletions.count == item.files.count { Text("-\(deletions.reduce(0, +))").foregroundStyle(.red) }
                            }.font(.system(.caption2, design: .monospaced))
                        }
                        if item.status == "running" { ProgressView().controlSize(.mini) }
                        else { Image(systemName: item.status == "failed" ? "exclamationmark.circle" : "checkmark").foregroundStyle(item.status == "failed" ? Color.red : Color.secondary) }
                        Image(systemName: expanded ? "chevron.down" : "chevron.right").font(.caption2)
                    }
                    .contentShape(Rectangle())
                }.buttonStyle(.plain)
                if expanded {
                    if !item.output.isEmpty {
                        Text(item.output).font(.system(.caption, design: .monospaced))
                            .lineLimit(8).textSelection(.enabled)
                    }
                    Button(action: onDetail) { Label(AppLocalized("Execution details"), systemImage: "arrow.up.right.square") }
                        .font(.caption)
                }
                ForEach(item.files) { file in
                    NanoMuseCodingFileButton(file: file) { onFile(file) }
                }
            }
            .padding(10)
            .background(NanoMuseTones.fill, in: RoundedRectangle(cornerRadius: 8))
        }
    }
}

struct NanoMuseCodingTurnView: View {
    var turn: NanoMuseCodingTurn
    var onDetail: (NanoMuseCodingItem) -> Void
    var onFile: (NanoMuseCodingFile) -> Void
    @State private var expanded = false

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            if !turn.tools.isEmpty {
                DisclosureGroup(isExpanded: $expanded) {
                    ForEach(turn.tools) { item in
                        NanoMuseCodingItemRow(item: item, onDetail: { onDetail(item) }, onFile: onFile)
                            .padding(.top, 8)
                    }
                } label: {
                    HStack(spacing: 8) {
                        Image(systemName: "wrench")
                        Text(String(format: AppLocalized("%d tool calls"), turn.tools.count))
                            .font(.caption)
                        if turn.tools.contains(where: { $0.status == "running" }) {
                            ProgressView().controlSize(.mini)
                        } else if turn.tools.contains(where: { $0.status == "failed" }) {
                            Image(systemName: "exclamationmark.circle").foregroundStyle(.red)
                        }
                        Spacer(minLength: 4)
                    }
                    .foregroundStyle(.secondary)
                    .padding(.vertical, 8)
                    .contentShape(Rectangle())
                }
                .tint(.secondary)
            }
            ForEach(turn.messages) { item in
                NanoMuseCodingItemRow(item: item, onDetail: { onDetail(item) }, onFile: onFile)
                ForEach(NanoMuseCodingItem.changes(after: item, in: turn.items)) { change in
                    VStack(alignment: .leading, spacing: 8) {
                        Button { onDetail(change) } label: {
                            Label(AppLocalized("File changes"), systemImage: "doc.text")
                                .font(.caption)
                        }.buttonStyle(.plain)
                        ForEach(change.files) { file in
                            NanoMuseCodingFileButton(file: file) { onFile(file) }
                        }
                    }
                    .padding(.vertical, 8)
                }
            }
        }
    }
}

struct NanoMuseCodingFileButton: View {
    var file: NanoMuseCodingFile
    var onOpen: () -> Void

    var body: some View {
        Button(action: onOpen) {
            HStack {
                Image(systemName: "doc.text")
                Text(file.path).font(.caption).lineLimit(2)
                Spacer(minLength: 4)
                NanoMuseCodingFileCounts(file: file)
                Image(systemName: "chevron.right").font(.caption2)
            }
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .disabled(file.reference.isEmpty)
    }
}

struct NanoMuseCodingFileCounts: View {
    var file: NanoMuseCodingFile
    var body: some View {
        HStack(spacing: 8) {
            if let count = file.additions { Text("+\(count)").foregroundStyle(.green) }
            if let count = file.deletions { Text("-\(count)").foregroundStyle(.red) }
        }.font(.system(.caption, design: .monospaced))
    }
}

struct NanoMuseCodingItemDetail: View {
    var computer: HubDevice
    var agent: String
    var sessionId: String
    var runId: String
    var item: NanoMuseCodingItem
    @Environment(\.dismiss) private var dismiss
    @State private var input = ""
    @State private var output = ""
    @State private var cursor: String?
    @State private var error: String?
    @State private var loading = false

    var body: some View {
        NavigationStack {
            List {
                if !item.command.isEmpty {
                    Section(AppLocalized("Command")) {
                        Text(item.command).font(.system(.callout, design: .monospaced)).textSelection(.enabled)
                        if !item.cwd.isEmpty { Text(item.cwd).font(.caption).foregroundStyle(.secondary) }
                        if let code = item.exitCode { Text(String(format: AppLocalized("Exit code: %d"), code)).font(.caption) }
                        if let duration = item.duration { Text(String(format: "%.2f s", duration / 1000)).font(.caption).foregroundStyle(.secondary) }
                    }
                }
                if !input.isEmpty {
                    Section(AppLocalized("Input")) { Text(input).font(.system(.caption, design: .monospaced)).textSelection(.enabled) }
                }
                Section(AppLocalized("Output")) {
                    Text(output.isEmpty ? AppLocalized("Nothing readable in this session yet.") : output)
                        .font(.system(.caption, design: .monospaced)).textSelection(.enabled)
                    if cursor != nil { Button(AppLocalized("Load more")) { Task { await load(more: true) } }.disabled(loading) }
                }
                if !item.files.isEmpty {
                    Section(AppLocalized("File changes")) {
                        ForEach(item.files) { file in
                            NavigationLink {
                                NanoMuseCodingDiffView(computer: computer, agent: agent, sessionId: sessionId, runId: runId, file: file)
                            } label: {
                                HStack {
                                    Text(file.path).font(.caption).lineLimit(2)
                                    Spacer()
                                    NanoMuseCodingFileCounts(file: file)
                                }
                            }.disabled(file.reference.isEmpty)
                        }
                    }
                }
                if loading { ProgressView() }
                if let error { Text(error).font(.footnote).foregroundStyle(.red) }
            }
            .navigationTitle(AppLocalized("Execution details"))
            .navigationBarTitleDisplayMode(.inline)
            .toolbar { ToolbarItem(placement: .cancellationAction) { Button(AppLocalized("Done")) { dismiss() } } }
            .task { await load(more: false) }
        }.tint(NanoMuseTones.action)
    }

    private func load(more: Bool) async {
        guard !loading else { return }
        loading = true
        defer { loading = false }
        var args: [String: Any] = ["agent": agent, "session_id": sessionId, "item_id": item.id, "run_id": runId]
        if more, let cursor { args["cursor"] = cursor }
        do {
            let reply = try await NanoMuseHub.shared.call(to: computer.id, action: "coding.item", args: args, timeout: NanoMuseCodingBridge.listTimeout)
            input = reply["input"] as? String ?? item.input
            let page = reply["output"] as? [String: Any] ?? [:]
            let text = page["data"] as? String ?? ""
            output = more ? output + text : text
            cursor = page["next_cursor"] as? String
            error = (reply["source_truncated"] as? Bool) == true ? AppLocalized("Recorded output was truncated.") : nil
        } catch { self.error = NanoMuseHubErrors.describe(error) }
    }
}

struct NanoMuseCodingDiffLine: Identifiable {
    var id: Int
    var text: String
    var old: Int?
    var new: Int?
    var isAddition: Bool { text.hasPrefix("+") && !text.hasPrefix("+++") }
    var isDeletion: Bool { text.hasPrefix("-") && !text.hasPrefix("---") }

    static func numberWidth(in lines: [Self]) -> CGFloat {
        let largest = lines.flatMap { [$0.old, $0.new].compactMap { $0 } }.max()
        guard let largest else { return 0 }
        return CGFloat(max(2, String(largest).count)) * 8 + 4
    }

    static func parse(_ diff: String) -> [Self] {
        let regex = try? NSRegularExpression(pattern: #"^@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@"#)
        var old: Int?
        var new: Int?
        return diff.components(separatedBy: "\n").enumerated().map { index, line in
            let range = NSRange(line.startIndex..., in: line)
            if let match = regex?.firstMatch(in: line, range: range),
               let a = Range(match.range(at: 1), in: line), let b = Range(match.range(at: 2), in: line) {
                old = Int(line[a]); new = Int(line[b])
                return Self(id: index, text: line)
            }
            if line.hasPrefix("@@") { old = nil; new = nil }
            if line.hasPrefix("---") || line.hasPrefix("+++") || line.hasPrefix("\\") {
                return Self(id: index, text: line)
            }
            let minus = line.hasPrefix("-")
            let plus = line.hasPrefix("+")
            let row = Self(id: index, text: line, old: plus ? nil : old, new: minus ? nil : new)
            if minus || line.hasPrefix(" "), let count = old { old = count + 1 }
            if plus || line.hasPrefix(" "), let count = new { new = count + 1 }
            return row
        }
    }
}

struct NanoMuseCodingDiffRow: View {
    var line: NanoMuseCodingDiffLine
    var numberWidth: CGFloat
    @Environment(\.colorScheme) private var colorScheme

    private var accent: Color {
        if line.isAddition {
            return colorScheme == .dark
                ? Color(red: 0.44, green: 0.91, blue: 0.63)
                : Color(red: 0.08, green: 0.42, blue: 0.21)
        }
        if line.isDeletion {
            return colorScheme == .dark
                ? Color(red: 1, green: 0.52, blue: 0.52)
                : Color(red: 0.71, green: 0.14, blue: 0.09)
        }
        return .secondary
    }

    private var fill: Color {
        if line.isAddition {
            return colorScheme == .dark
                ? Color(red: 0.13, green: 0.23, blue: 0.16)
                : Color(red: 0.86, green: 0.96, blue: 0.89)
        }
        if line.isDeletion {
            return colorScheme == .dark
                ? Color(red: 0.27, green: 0.13, blue: 0.12)
                : Color(red: 1, green: 0.88, blue: 0.86)
        }
        return .clear
    }

    var body: some View {
        HStack(alignment: .top, spacing: 0) {
            HStack(spacing: 6) {
                if numberWidth > 0 {
                    Text(line.old.map(String.init) ?? "").frame(width: numberWidth, alignment: .trailing)
                    Text(line.new.map(String.init) ?? "").frame(width: numberWidth, alignment: .trailing)
                }
            }
            .foregroundStyle(accent)
            .padding(.leading, 8)
            .padding(.trailing, numberWidth > 0 ? 8 : 0)
            .padding(.vertical, 4)
            .background(colorScheme == .dark ? Color.black.opacity(0.28) : Color.white.opacity(0.35))
            Text(line.text).textSelection(.enabled).fixedSize()
                .padding(.horizontal, 8).padding(.vertical, 4)
        }
        .font(.system(.caption, design: .monospaced))
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(fill)
        .overlay(alignment: .leading) {
            if line.isAddition || line.isDeletion {
                Rectangle().fill(accent).frame(width: 3)
            }
        }
    }
}

struct NanoMuseCodingDiffView: View {
    var computer: HubDevice
    var agent: String
    var sessionId: String
    var runId: String
    var file: NanoMuseCodingFile
    @State private var diff = ""
    @State private var cursor: String?
    @State private var error: String?
    @State private var loading = false
    @State private var initialScrollToken = 0

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack(alignment: .top) {
                Text(file.path).font(.caption).textSelection(.enabled)
                    .frame(maxWidth: .infinity, alignment: .leading)
                NanoMuseCodingFileCounts(file: file)
            }.padding(.horizontal, 12)
            // A single two-axis scroller keeps long recorded lines reachable on the phone.
            ScrollViewReader { proxy in
                ScrollView([.horizontal, .vertical]) {
                    let lines = NanoMuseCodingDiffLine.parse(diff)
                    let numberWidth = NanoMuseCodingDiffLine.numberWidth(in: lines)
                    VStack(alignment: .leading, spacing: 12) {
                        Color.clear.frame(width: 1, height: 1).id("diff-start")
                        VStack(alignment: .leading, spacing: 0) {
                            ForEach(lines) { line in
                                NanoMuseCodingDiffRow(line: line, numberWidth: numberWidth)
                            }
                        }
                        .fixedSize(horizontal: true, vertical: false)
                        if cursor != nil { Button(AppLocalized("Load more")) { Task { await load(more: true) } }.disabled(loading) }
                        if loading { ProgressView() }
                        if let error { Text(error).font(.footnote).foregroundStyle(.red) }
                    }
                    .padding(.horizontal, 12)
                }
                .nmOnChange(of: initialScrollToken) { _ in
                    proxy.scrollTo("diff-start", anchor: .topLeading)
                }
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
        }
        .padding(.top, 12)
        .background(NanoMuseTones.canvas.ignoresSafeArea())
        .navigationTitle(AppLocalized("File changes"))
        .navigationBarTitleDisplayMode(.inline)
        .task { await load(more: false) }
    }

    private func load(more: Bool) async {
        guard !loading else { return }
        loading = true
        defer { loading = false }
        var args: [String: Any] = ["agent": agent, "session_id": sessionId, "run_id": runId, "diff_reference": file.reference]
        if more, let cursor { args["cursor"] = cursor }
        do {
            let reply = try await NanoMuseHub.shared.call(to: computer.id, action: "coding.diff", args: args, timeout: NanoMuseCodingBridge.listTimeout)
            let text = reply["data"] as? String ?? ""
            diff = more ? diff + text : text
            cursor = reply["next_cursor"] as? String
            error = nil
            if !more { initialScrollToken += 1 }
        } catch { self.error = NanoMuseHubErrors.describe(error) }
    }
}
