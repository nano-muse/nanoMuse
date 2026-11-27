//
//  NanoMuseApprovalGrantTarget.swift
//  nanoMuse
//
//  The complete, versioned capability named by a cross-device approval event.
//

import Foundation

struct NanoMuseApprovalGrantTarget: Hashable, Sendable {
    let tool: String
    let resource: String
    let action: String

    init?(wire: Any?) {
        guard let value = wire as? [String: Any],
              (value["version"] as? Int) == 1,
              let tool = value["tool"] as? String,
              let resource = value["resource"] as? String,
              let action = value["action"] as? String,
              !tool.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty,
              tool.utf8.count <= 200,
              resource.utf8.count <= 4_096,
              Self.isSHA256(action)
        else { return nil }
        self.tool = tool.trimmingCharacters(in: .whitespacesAndNewlines)
        self.resource = resource
        self.action = action
    }

    /// Length prefixes make every component unambiguous without truncating it.
    var identity: String {
        "v1:\(Self.component(tool))|\(Self.component(resource))|\(Self.component(action))"
    }

    private static func component(_ value: String) -> String {
        "\(value.utf8.count):\(value)"
    }

    private static func isSHA256(_ value: String) -> Bool {
        guard value.utf8.count == 71, value.hasPrefix("sha256:") else { return false }
        return value.dropFirst(7).unicodeScalars.allSatisfy { scalar in
            (48...57).contains(scalar.value) || (97...102).contains(scalar.value)
        }
    }
}

struct NanoMuseApprovalSessionGrants {
    struct Key: Hashable {
        let sessionId: String
        let deviceId: String
        let risk: String
        let target: String
    }

    private var values: Set<Key> = []

    func allows(_ key: Key) -> Bool {
        values.contains(key)
    }

    mutating func insert(_ key: Key) {
        values.insert(key)
    }

    mutating func reset(for sessionId: String) {
        values = values.filter { $0.sessionId != sessionId }
    }

    mutating func resetAll() {
        values.removeAll()
    }
}

func nanoMuseCanRememberApproval(
    target: NanoMuseApprovalGrantTarget?,
    wireRisk: String,
    scheduled: Bool
) -> Bool {
    guard target != nil, !scheduled else { return false }
    return !["money", "payment", "pay"].contains(wireRisk.lowercased())
}
