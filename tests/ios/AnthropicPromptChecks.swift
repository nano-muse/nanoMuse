import Foundation

/// Runs without the app, SDK, credentials or network. The prefix here is synthetic test data.
@main
struct AnthropicPromptChecks {
    static func main() throws {
        for missing in [nil, "", " ", "\t\n  ", "\u{00a0}"] as [String?] {
            do {
                _ = try NanoMuseAnthropicPrompt.prefix(isOAuth: true, configuredIdentifier: missing)
                preconditionFailure("Missing OAuth configuration should throw")
            } catch NanoMuseAnthropicPrompt.ConfigurationError.missingOAuthPrefix {
                // A request can report this error instead of terminating the process.
            }
        }

        let synthetic = "  Synthetic OAuth identifier used only by this check.\n"
        let configured = try NanoMuseAnthropicPrompt.prefix(isOAuth: true, configuredIdentifier: synthetic)
        precondition(configured == synthetic, "Configured text must be preserved verbatim")

        for absentOrConfigured in [nil, "", " \t\n", synthetic] as [String?] {
            let prefix = try NanoMuseAnthropicPrompt.prefix(isOAuth: false, configuredIdentifier: absentOrConfigured)
            precondition(prefix == nil, "An API-key request must not require or include the OAuth prefix")
        }

        let message = NanoMuseAnthropicPrompt.ConfigurationError.missingOAuthPrefix.localizedDescription
        precondition(!message.isEmpty)
        precondition(!message.contains("ANTHROPIC_OAUTH_IDENTIFIER_PROMPT"))
        print("Anthropic OAuth prompt checks passed")
    }
}
