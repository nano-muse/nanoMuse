//
//  NanoMuseUpdateCheck.swift
//  nanoMuse
//
//  The version row in Settings (contract C2): what is installed, what the latest
//  release is, and a link to it when it is newer. The download index on nanomuse.cn
//  answers first; GitHub's latest release is the fallback. Checked at most once a
//  day on its own, or on demand from the row; the answer is kept in UserDefaults so
//  the row has something to show straight away. Never loud: a failed check leaves
//  "latest" empty and the row says only what is installed.
//

import Combine
import Foundation

@MainActor
final class NanoMuseUpdateCheck: ObservableObject {
    static let shared = NanoMuseUpdateCheck()

    nonisolated static let indexURL = "https://nanomuse.cn/dl/index.json"
    nonisolated static let githubURL = "https://api.github.com/repos/nano-muse/nanoMuse/releases/latest"
    nonisolated static let fallbackReleasePage = "https://github.com/nano-muse/nanoMuse/releases/latest"
    /// The download page on nanomuse.cn, where a release found through the index leads (Android's `DOWNLOAD_URL`).
    nonisolated static let downloadPage = "https://nanomuse.cn/dl/"

    private enum Keys {
        static let latest = "nm.update.latest"
        static let page = "nm.update.page"
        static let checkedAt = "nm.update.checked_at"
    }

    private static let ttl: TimeInterval = 24 * 60 * 60

    /// The newest version known, as the servers wrote it (`1.4.0`, `v1.4.0`); nil until a check succeeded.
    @Published private(set) var latest: String?
    /// The release page the servers named for `latest`, when they did.
    @Published private(set) var page: String?
    @Published private(set) var checkedAt: Date?
    @Published private(set) var checking = false

    private init() {
        let d = UserDefaults.standard
        latest = d.string(forKey: Keys.latest)
        page = d.string(forKey: Keys.page)
        let at = d.double(forKey: Keys.checkedAt)
        checkedAt = at > 0 ? Date(timeIntervalSince1970: at) : nil
    }

    // MARK: What the row shows

    /// `CFBundleShortVersionString`, or "0" when the bundle has none.
    nonisolated static var installed: String {
        (Bundle.main.object(forInfoDictionaryKey: "CFBundleShortVersionString") as? String) ?? "0"
    }

    /// `CFBundleVersion`, the build number.
    nonisolated static var build: String {
        (Bundle.main.object(forInfoDictionaryKey: "CFBundleVersion") as? String) ?? ""
    }

    /// "1.4.0 (123)" — what is installed, as the row's first line.
    nonisolated static var installedLine: String {
        build.isEmpty ? installed : "\(installed) (\(build))"
    }

    var installedLine: String { Self.installedLine }

    /// The row's second line (Android `nm_version_*`): "Checking for the latest release…", "1.5.0
    /// is out — tap to update", "Latest 1.4.0 — you have it", or "Could not check. Tap to try again".
    var latestLine: String {
        if checking { return AppLocalized("Checking for the latest release…") }
        guard let latest else { return AppLocalized("Could not check. Tap to try again") }
        let shown = Self.normalize(latest)
        return latestIsNewer
            ? String(format: AppLocalized("%@ is out. Tap to update"), shown)
            : String(format: AppLocalized("Latest %@. You have it"), shown)
    }

    /// Whether `latest` is newer than what is installed.
    var latestIsNewer: Bool {
        guard let latest else { return false }
        return Self.compareVersions(latest, Self.installed) > 0
    }

    /// Where the row goes on a tap: the release page the servers named, or GitHub's latest.
    var releasePage: URL {
        URL(string: page ?? "") ?? URL(string: Self.fallbackReleasePage)!
    }

    // MARK: Checking

    /// A check now, from the row. Returns when it is over; a second call while one runs does nothing.
    func checkNow() async {
        guard !checking else { return }
        checking = true
        defer { checking = false }
        guard let found = await Self.fetchLatest() else { return }
        latest = found.version
        page = found.page
        checkedAt = Date()
        let d = UserDefaults.standard
        d.set(found.version, forKey: Keys.latest)
        d.set(found.page, forKey: Keys.page)
        d.set(Date().timeIntervalSince1970, forKey: Keys.checkedAt)
    }

    /// A check in the background when the last one is older than a day.
    func checkIfStale() {
        if let checkedAt, Date().timeIntervalSince(checkedAt) < Self.ttl { return }
        Task { @MainActor [self] in await checkNow() }
    }

    struct Found: Sendable, Equatable {
        var version: String
        var page: String?
    }

    /// The download index first, GitHub second. Nil when neither answered usefully.
    private static func fetchLatest() async -> Found? {
        if let json = await fetchJSON(indexURL), let found = parseIndex(json) {
            return found
        }
        if let json = await fetchJSON(githubURL), let found = parseGitHubLatest(json) {
            return found
        }
        return nil
    }

    /// The index as `scripts/release-sync.py` writes it, `{"releases": [{"tag": "v1.0.0", …}, …]}`
    /// newest first (what Android reads): the first release with a tag, leading to the download
    /// page. Older shapes (`ios.version`, `latest`, `version`, with `page` / `url`) still count,
    /// so a changed index does not leave the row saying "Could not check".
    nonisolated static func parseIndex(_ json: [String: Any]) -> Found? {
        if let releases = json["releases"] as? [[String: Any]] {
            for release in releases {
                if let tag = release["tag"] as? String, !normalize(tag).isEmpty {
                    let page = (release["page"] as? String).flatMap { $0.isEmpty ? nil : $0 } ?? downloadPage
                    return Found(version: tag, page: page)
                }
            }
        }
        let ios = json["ios"] as? [String: Any]
        let version = (ios?["version"] as? String) ?? (json["latest"] as? String) ?? (json["version"] as? String)
        guard let version, !normalize(version).isEmpty else { return nil }
        let page = (ios?["page"] as? String) ?? (ios?["url"] as? String) ?? (json["page"] as? String) ?? downloadPage
        return Found(version: version, page: page)
    }

    /// GitHub's release object: `tag_name` and `html_url`.
    nonisolated static func parseGitHubLatest(_ json: [String: Any]) -> Found? {
        guard let tag = json["tag_name"] as? String, !normalize(tag).isEmpty else { return nil }
        return Found(version: tag, page: json["html_url"] as? String)
    }

    private static func fetchJSON(_ address: String) async -> [String: Any]? {
        guard let url = URL(string: address) else { return nil }
        var request = URLRequest(url: url)
        request.timeoutInterval = 10
        request.setValue("application/json", forHTTPHeaderField: "Accept")
        request.setValue("nanoMuse-iOS/\(installed)", forHTTPHeaderField: "User-Agent")
        guard let result = try? await URLSession.shared.data(for: request) else { return nil }
        let (data, response) = result
        guard (200..<300).contains((response as? HTTPURLResponse)?.statusCode ?? 0) else { return nil }
        return (try? JSONSerialization.jsonObject(with: data)) as? [String: Any]
    }

    // MARK: Versions (pure)

    /// "v1.4.0-beta.2" → "1.4.0-beta.2".
    nonisolated static func normalize(_ version: String) -> String {
        var s = version.trimmingCharacters(in: .whitespacesAndNewlines)
        if s.hasPrefix("v") || s.hasPrefix("V") { s.removeFirst() }
        return s
    }

    /// Semver-ish: the dotted numbers compare as numbers (missing parts are 0); a release beats
    /// its pre-release ("1.4.0" > "1.4.0-beta.1"); two pre-releases compare by their labels.
    /// Returns -1, 0 or 1.
    nonisolated static func compareVersions(_ a: String, _ b: String) -> Int {
        let (an, ap) = split(normalize(a))
        let (bn, bp) = split(normalize(b))
        let count = max(an.count, bn.count)
        for i in 0..<count {
            let x = i < an.count ? an[i] : 0
            let y = i < bn.count ? bn[i] : 0
            if x != y { return x < y ? -1 : 1 }
        }
        switch (ap.isEmpty, bp.isEmpty) {
        case (true, true): return 0
        case (true, false): return 1
        case (false, true): return -1
        case (false, false): return ap == bp ? 0 : (ap < bp ? -1 : 1)
        }
    }

    /// "1.4.0-beta.2+7" → ([1, 4, 0], "beta.2"); build metadata after "+" is ignored.
    private nonisolated static func split(_ version: String) -> ([Int], String) {
        let noBuild = version.split(separator: "+", maxSplits: 1).first.map(String.init) ?? version
        let parts = noBuild.split(separator: "-", maxSplits: 1).map(String.init)
        let numbers = (parts.first ?? "").split(separator: ".").map { Int($0.filter(\.isNumber)) ?? 0 }
        return (numbers, parts.count > 1 ? parts[1] : "")
    }
}
