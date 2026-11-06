import Foundation

extension VoiceProviderResolver {
    /// A System Auto override must not inherit a concrete voice from the group.
    /// Otherwise use the same usable entry that selected the output engine,
    /// never a later member that happens to name a System voice.
    static func systemOutputVoiceId(
        override: String?,
        resolveOutputEntryId: () -> String?
    ) -> String? {
        if isSystemEntry(override) {
            return selectedSystemVoiceId(override)
        }
        return selectedSystemVoiceId(resolveOutputEntryId())
    }
}
