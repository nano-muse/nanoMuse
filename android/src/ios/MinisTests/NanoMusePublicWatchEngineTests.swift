import Foundation
import XCTest
@testable import Minis

final class NanoMusePublicWatchEngineTests: XCTestCase {
    func testBundledReaderAndLedgerWorkInJavaScriptCore() throws {
        let js = NanoMuseWatchScript()
        var state: [String: Any] = [:]
        var now = 1_800_000_000_000
        func run(_ op: String, _ values: [String: Any] = [:]) throws -> [String: Any] {
            var args = values
            args["state"] = state; args["op"] = op; args["now"] = now
            let out = try XCTUnwrap(js.call("NanoMuseWatch", args))
            XCTAssertNil(out["error"])
            state = try XCTUnwrap(out["state"] as? [String: Any])
            return out
        }
        let initial = try run("view")
        XCTAssertEqual(initial["enabled"] as? Bool, true)
        let added = try run("edit", ["kind": "github_repo", "target": "example/project", "revision": initial["revision"]!])
        let id = try XCTUnwrap((added["due"] as? [[String: String]])?.first?["id"])
        let plan = try XCTUnwrap(js.call("NanoMusePublicRead", ["kind": "github_repo", "target": "example/project",
                                                                "now": now, "responses": []]))
        XCTAssertTrue(((plan["request"] as? [String: String])?["url"] ?? "").hasPrefix("https://api.github.com/"))
        let old = ["key": "old", "text": "Earlier issue", "url": "https://github.com/example/project/issues/1"]
        let new = ["key": "new", "text": "New issue", "url": "https://github.com/example/project/issues/2"]
        let baseline = try run("sample", ["id": id, "items": [old]])
        XCTAssertTrue((baseline["pending"] as? [[String: Any]])?.isEmpty == true)
        now += 5 * 3_600_000
        let changed = try run("sample", ["id": id, "items": [new, old]])
        XCTAssertEqual((changed["pending"] as? [[String: String]])?.map { $0["key"] }, ["new"])
        let consumed = try run("consume", ["keys": ["new"]])
        XCTAssertTrue((consumed["pending"] as? [[String: Any]])?.isEmpty == true)
    }
}
