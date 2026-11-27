import Foundation

/// Keeps an exit observation distinct from a later system diagnostic or its delivery logs.
struct NanoMuseCrashEvidence {
    enum Source: String {
        case launchMarker = "Launch marker, termination unconfirmed"
        case metricKit = "MetricKit diagnostic"
    }

    let source: Source
    var periodStart: Date? = nil
    var periodEnd: Date? = nil
    var diagnosticBuild: String? = nil

    var includesPreviousRunArtifacts: Bool { source == .launchMarker }

    static func markerType(lastPhase: String) -> String {
        let phase = ["active", "inactive", "background"].contains(lastPhase) ? lastPhase : "unknown"
        return "Unconfirmed termination (last observed phase: \(phase); cause unknown)"
    }

    var unavailableStack: String {
        source == .launchMarker
            ? "(not available from a launch marker; no signal or termination reason was observed)"
            : "(not supplied by MetricKit)"
    }

    func header(generatedAt: Date) -> String {
        let formatter = ISO8601DateFormatter()
        var text = "Source:  \(source.rawValue)\nReport generated: \(formatter.string(from: generatedAt))"
        text += "\nIncident time: not established by this report"
        if let start = periodStart, let end = periodEnd {
            text += "\nDiagnostic period: \(formatter.string(from: start)) to \(formatter.string(from: end))"
        }
        if source == .launchMarker {
            text += "\nA leftover marker does not establish a crash, SIGKILL, watchdog or memory termination."
        } else {
            text += "\nThe diagnostic period is not an exact incident timestamp. Delivery can occur in a later process."
        }
        return text
    }

    func filename(generatedAt: Date, identifier: UUID = UUID()) -> String {
        let formatter = DateFormatter()
        formatter.locale = Locale(identifier: "en_US_POSIX")
        formatter.dateFormat = "yyyyMMdd-HHmmss"
        return "crash-\(formatter.string(from: generatedAt))-\(identifier.uuidString).log"
    }
}
