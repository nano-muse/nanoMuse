import XCTest
@testable import Minis

@MainActor
final class NanoMuseSystemOutputVoiceTests: XCTestCase {
    private var system: String { VoiceProviderResolver.systemEntryId }
    private let voice = "com.apple.voice.compact.zh-CN.Tingting"

    func testSystemAutoOverrideDoesNotReadTheConfiguredGroup() {
        for selection in [system, system + "/system-tts"] {
            let result = VoiceProviderResolver.systemOutputVoiceId(override: selection) {
                XCTFail("A System override must not consult an inactive group")
                return self.system + "/" + self.voice
            }
            XCTAssertNil(result, "Auto must leave the language-specific preference in control")
        }
    }

    func testAutoAsTheResolvedGroupMemberKeepsLanguagePreferences() {
        // A persistent group may contain [Auto, Tingting]. The output engine
        // resolved Auto, so the later concrete voice must not replace it.
        XCTAssertNil(VoiceProviderResolver.systemOutputVoiceId(override: nil) {
            self.system + "/system-tts"
        })
    }

    func testExplicitConcreteSystemVoiceWinsOverTheGroup() {
        XCTAssertEqual(
            VoiceProviderResolver.systemOutputVoiceId(override: system + "/" + voice) {
                XCTFail("A concrete System override must not consult the group")
                return self.system + "/system-tts"
            },
            voice
        )
    }

    func testConcreteVoiceOfTheResolvedGroupMemberIsKept() {
        XCTAssertEqual(
            VoiceProviderResolver.systemOutputVoiceId(override: nil) {
                self.system + "/" + self.voice
            },
            voice
        )
    }

    func testCloudOutputDoesNotPickASystemVoice() {
        for selection in [nil, "cloud-provider/speech-model"] as [String?] {
            XCTAssertNil(VoiceProviderResolver.systemOutputVoiceId(override: selection) {
                "cloud-provider/speech-model"
            })
        }
    }

    func testUnavailableOverrideUsesTheActualFallback() {
        XCTAssertEqual(
            VoiceProviderResolver.systemOutputVoiceId(override: "removed-provider/model") {
                self.system + "/" + self.voice
            },
            voice
        )
    }

    func testNoOutputEntryKeepsLanguagePreferences() {
        XCTAssertNil(VoiceProviderResolver.systemOutputVoiceId(override: nil) { nil })
    }
}
