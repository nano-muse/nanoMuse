import XCTest
@testable import Minis

/// The words a person reads in the nanoMuse layer follow the project's voice: no dashes
/// (`—`, `–`, `——`) in any of the nine languages, no exclamation marks, and the relay is
/// "nanoMuse Cloud" in every language. Our keys are the ones the Swift files under
/// `NanoMuse/` reference; upstream OpenMinis keys are not ours to rewrite.
///
/// Reads the sources next to this file (Mac only, as all of MinisTests): the catalogue is
/// `../Localizable.xcstrings`, our code is `../NanoMuse/*.swift`.
final class NanoMuseCopyTests: XCTestCase {

    private struct Catalogue {
        /// key -> language -> value
        var values: [String: [String: String]] = [:]
        /// the keys the NanoMuse/ sources reference
        var ours: Set<String> = []
    }

    private static func load() throws -> Catalogue {
        let here = URL(fileURLWithPath: #filePath)
        let root = here.deletingLastPathComponent().deletingLastPathComponent()
        let data = try Data(contentsOf: root.appendingPathComponent("Localizable.xcstrings"))
        guard let top = try JSONSerialization.jsonObject(with: data) as? [String: Any],
              let strings = top["strings"] as? [String: Any] else {
            throw XCTSkip("Localizable.xcstrings is not where the test expects it")
        }
        var cat = Catalogue()
        for (key, entry) in strings {
            var byLang: [String: String] = [:]
            let locs = (entry as? [String: Any])?["localizations"] as? [String: Any] ?? [:]
            for (lang, loc) in locs {
                if let unit = (loc as? [String: Any])?["stringUnit"] as? [String: Any],
                   let value = unit["value"] as? String {
                    byLang[lang] = value
                }
            }
            cat.values[key] = byLang
        }
        let dir = root.appendingPathComponent("NanoMuse")
        let files = try FileManager.default.contentsOfDirectory(atPath: dir.path).filter { $0.hasSuffix(".swift") }
        var blob = ""
        for name in files {
            blob += (try? String(contentsOf: dir.appendingPathComponent(name), encoding: .utf8)) ?? ""
            blob += "\n"
        }
        for key in strings.keys where blob.contains(Self.swiftLiteral(key)) {
            cat.ours.insert(key)
        }
        return cat
    }

    /// The key as it appears in Swift source, quotes included: `"` and `\` escaped, newlines as `\n`.
    private static func swiftLiteral(_ key: String) -> String {
        "\"" + key.replacingOccurrences(of: "\\", with: "\\\\")
            .replacingOccurrences(of: "\"", with: "\\\"")
            .replacingOccurrences(of: "\n", with: "\\n") + "\""
    }

    func testOurKeysAreFound() throws {
        let cat = try Self.load()
        XCTAssertGreaterThan(cat.ours.count, 500, "the NanoMuse/ sources reference hundreds of keys")
        XCTAssertTrue(cat.ours.contains("Before we start, what should I call you?"))
    }

    func testNoDashesInOurCopy() throws {
        let cat = try Self.load()
        var offenders: [String] = []
        for key in cat.ours {
            for (lang, value) in cat.values[key] ?? [:] where value.contains("—") || value.contains("–") {
                offenders.append("[\(lang)] \(value.prefix(80))")
            }
            if key.contains("—") || key.contains("–") { offenders.append("[key] \(key.prefix(80))") }
        }
        XCTAssertTrue(offenders.isEmpty, "dashes in copy a person reads:\n" + offenders.sorted().joined(separator: "\n"))
    }

    func testNoExclamationMarksInOurCopy() throws {
        let cat = try Self.load()
        var offenders: [String] = []
        for key in cat.ours {
            for (lang, value) in cat.values[key] ?? [:] where value.contains("!") || value.contains("！") {
                offenders.append("[\(lang)] \(value.prefix(80))")
            }
        }
        XCTAssertTrue(offenders.isEmpty, "exclamation marks:\n" + offenders.sorted().joined(separator: "\n"))
    }

    func testTheRelayIsNanoMuseCloudInEveryLanguage() throws {
        let cat = try Self.load()
        var offenders: [String] = []
        for key in cat.ours {
            for (lang, value) in cat.values[key] ?? [:] {
                for translated in ["nanoMuse 云", "nanoMuse 雲", "nanoMuse クラウド", "nanoMuse 클라우드"] where value.contains(translated) {
                    offenders.append("[\(lang)] \(value.prefix(80))")
                }
            }
        }
        XCTAssertTrue(offenders.isEmpty, "the relay's name is translated:\n" + offenders.sorted().joined(separator: "\n"))
    }

    /// The Chinese copy uses Android's words: the agent is 智能体 / 智慧體 (never "agent" left in
    /// English, never 代理 where the English says agent: 代理 is the proxy), the relay is 中继 /
    /// 中繼 (not 中转), and "Hands" stays in English.
    func testChineseTermsMatchAndroid() throws {
        let cat = try Self.load()
        var offenders: [String] = []
        let agentWord = try NSRegularExpression(pattern: "(?i)\\bagents?\\b")
        for key in cat.ours {
            for lang in ["zh-Hans", "zh-Hant"] {
                guard let value = cat.values[key]?[lang] else { continue }
                let range = NSRange(value.startIndex..., in: value)
                if agentWord.firstMatch(in: value, range: range) != nil { offenders.append("[\(lang)] agent: \(value.prefix(80))") }
                if value.contains("代理"), key.lowercased().contains("agent") { offenders.append("[\(lang)] 代理: \(value.prefix(80))") }
                if value.contains("中转") || value.contains("中轉") { offenders.append("[\(lang)] 中转: \(value.prefix(80))") }
                if value.contains("双手") || value.contains("雙手") { offenders.append("[\(lang)] 双手: \(value.prefix(80))") }
            }
        }
        XCTAssertTrue(offenders.isEmpty, "Chinese words that differ from Android's:\n" + offenders.sorted().joined(separator: "\n"))
    }
}
