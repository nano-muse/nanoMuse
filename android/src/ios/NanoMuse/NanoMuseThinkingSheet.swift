// The Muse chat menu uses the existing session thinking controls, including drafts.
import SwiftUI

struct NanoMuseThinkingSheet: View {
    @ObservedObject var vm: AIChatViewModel
    var dismiss: () -> Void
    @ObservedObject private var providers = ProviderConfigStore.shared

    var body: some View {
        if vm.currentModelSupportsReasoning && !vm.availableThinkingLevels.isEmpty {
            ThinkingLevelSheetView(
                currentLevel: vm.currentThinkingLevel,
                availableLevels: vm.availableThinkingLevels,
                onSelect: { level in
                    // Recheck after a model switch while the sheet was open.
                    guard vm.currentModelSupportsReasoning,
                          level == .off || vm.availableThinkingLevels.contains(level) else { return }
                    vm.setThinkingLevel(level)
                    dismiss()
                }
            )
        } else {
            NavigationStack {
                Text(AppLocalized("Thinking is unavailable for this model."))
                    .foregroundStyle(.secondary)
                    .padding()
                    .navigationTitle(AppLocalized("Thinking Intensity"))
                    .navigationBarTitleDisplayMode(.inline)
            }
        }
    }
}
