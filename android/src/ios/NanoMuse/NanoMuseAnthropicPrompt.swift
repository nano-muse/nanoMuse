import Foundation

/// OAuth needs a configured identifier prefix; ordinary API-key requests do not.
enum NanoMuseAnthropicPrompt {
    enum ConfigurationError: LocalizedError {
        case missingOAuthPrefix

        var errorDescription: String? {
            NSLocalizedString(
                "Claude sign-in is unavailable in this version. Choose another model or use an API key.",
                comment: "An unavailable Claude sign-in must not interrupt other model choices."
            )
        }
    }

    /// Validation trims only to detect missing text. A configured prefix is sent unchanged.
    static func prefix(isOAuth: Bool, configuredIdentifier: String?) throws -> String? {
        guard isOAuth else { return nil }
        guard let configuredIdentifier,
              !configuredIdentifier.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else {
            throw ConfigurationError.missingOAuthPrefix
        }
        return configuredIdentifier
    }
}
