// The Muse chat menu uses the existing session thinking controls, including drafts.
import SwiftUI

struct NanoMuseThinkingButton: View {
    @ObservedObject var vm: AIChatViewModel
    @ObservedObject private var providers = ProviderConfigStore.shared

    var body: some View {
        Button {
            NanoMuseChatAction.post(.thinking, session: vm.nmSessionKey)
        } label: {
            Image(systemName: vm.currentThinkingLevel.isEnabled ? "lightbulb.fill" : "lightbulb")
                .font(.system(size: 14, weight: .medium))
                .foregroundStyle(ChatColors.secondaryText)
                .frame(width: 44, height: 44)
                .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .accessibilityLabel(Text(AppLocalized("Thinking Intensity")))
        .accessibilityValue(Text(
            vm.currentModelSupportsReasoning && !vm.availableThinkingLevels.isEmpty
                ? vm.currentThinkingLevel.displayName
                : AppLocalized("Thinking is unavailable for this model.")
        ))
    }
}

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
