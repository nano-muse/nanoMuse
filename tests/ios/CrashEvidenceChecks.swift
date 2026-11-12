import Foundation

@main
enum CrashEvidenceChecks {
    static func main() {
        for phase in ["active", "inactive", "background", "unknown"] {
            let label = NanoMuseCrashEvidence.markerType(lastPhase: phase)
            precondition(label.contains("Unconfirmed termination"))
            precondition(!label.contains("SIGKILL") && !label.contains("Jetsam"))
        }
        precondition(NanoMuseCrashEvidence.markerType(lastPhase: "invalid\nphase").contains("unknown"))

        let marker = NanoMuseCrashEvidence(source: .launchMarker)
        precondition(marker.includesPreviousRunArtifacts)
        precondition(marker.unavailableStack.contains("no signal"))

        let begin = Date(timeIntervalSince1970: 1_700_000_000)
        let end = begin.addingTimeInterval(60)
        let delivered = end.addingTimeInterval(86_400)
        let diagnostic = NanoMuseCrashEvidence(source: .metricKit, periodStart: begin, periodEnd: end)
        precondition(!diagnostic.includesPreviousRunArtifacts)
        precondition(!diagnostic.unavailableStack.contains("SIGKILL"))
        let header = diagnostic.header(generatedAt: delivered)
        let formatter = ISO8601DateFormatter()
        precondition(header.contains("Report generated: " + formatter.string(from: delivered)))
        precondition(header.contains("Diagnostic period: " + formatter.string(from: begin)))
        precondition(header.contains(formatter.string(from: end)))
        precondition(header.contains("Incident time: not established"))

        let first = diagnostic.filename(generatedAt: delivered)
        let second = diagnostic.filename(generatedAt: delivered)
        precondition(first != second, "Diagnostics delivered together must not overwrite each other")
        precondition(first.hasPrefix("crash-") && first.hasSuffix(".log"))
        print("Crash evidence checks passed")
    }
}
