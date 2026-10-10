//
//  NanoMuseChatModifiers.swift
//  nanoMuse
//
//  Why these exist. `AIChatView.body` is one expression of some sixty chained
//  modifiers (sheets, alerts, listeners). Each link wraps the value so far in
//  another `ModifiedContent`: the body's value grows with every link, the
//  compiler holds the intermediate copies on the stack while the getter builds
//  the chain, and the Swift runtime — asked for the metadata of the finished
//  type the first time the body runs — recurses once per level of nesting.
//  0.1.38 added four links of ours (the composer's fail-safe host, the C9
//  presence hooks) and build 9 overflowed the main thread's stack on an iPad
//  the moment the chat appeared after onboarding, every launch: SIGSEGV in the
//  stack guard, `AIChatView.body.getter` →
//  `__swift_instantiateConcreteTypeFromMangledNameV2` →
//  `swift::Demangle::TypeDecoder::decodeMangledType` (Minis-2026-10-06-005159.ips,
//  symbolised with the dSYM of TestFlight run 9).
//
//  The cure: our links are grouped here into two modifiers, so the chain is
//  as long as 0.1.37's again, and the composer column and the popup layer are
//  boxed in `AnyView`s, so the body's value carries one pointer for the
//  largest subtrees instead of the subtrees themselves. New chat-wide
//  behaviour goes into these modifiers (or a third one), never as another
//  link on `AIChatView.body`; `NanoMuseRound6Tests.testChatBodyStaysSmallAndShallow`
//  keeps the depth in check.
//

import SwiftUI

/// The composer's place in the chat: a row under the message list, inside the safe area —
/// not an overlay of the list (upstream, 0.1.36–0.1.37) and not a safe-area inset of it (the
/// 0.1.38 fail-safe). A plain `VStack` has nothing to go wrong with: the list takes what is
/// left above the column, the keyboard shortens both, and the column is where SwiftUI put it
/// — which the check page (Settings → Appearance → Composer check) can now report in numbers.
/// The list needs no bottom inset for the composer any more (0 is passed to it). The `/` and
/// `@` popup and its tap-outside catcher stay an overlay of the list, so the popup's bottom
/// edge is the column's top edge by layout, as upstream's note wanted.
///
/// The composer that could not be seen in 0.1.36–0.1.39 was not this host's doing: the chat
/// as a whole ran under the shell's bottom bar once the keyboard had come and gone, and the
/// column — wherever it was attached — sat behind the bar. That is fixed where it was, in
/// `NanoMuseHomeView.body` (the bar is a row, not a safe-area inset); this host stays because
/// a row is the simpler of the two layouts and the one the Android app has.
struct NanoMuseComposerHost: ViewModifier {
    /// The column, type-erased: its tree (the cards, the tool strip, the input bar) is the
    /// heaviest part of the chat's body, and a box keeps it out of the body's value and type.
    let stack: AnyView
    /// The popup layer, type-erased for the same reason.
    let popup: AnyView

    func body(content: Content) -> some View {
        VStack(spacing: 0) {
            content
                .overlay(alignment: .bottom) { popup }
            stack
        }
    }
}

/// The chat's listeners of ours, one link of the chain: the Muse header's ••• menu, the
/// composer's expectation when a message goes out or a turn ends, presence (C9 — the
/// "{device} is working…" line under the last remote row, cleared when the reply arrives),
/// and the Action Button's voice prompt (#296).
struct NanoMuseChatHooks: ViewModifier {
    let vm: AIChatViewModel
    /// `vm.isProcessing`, passed as a value so a change re-runs this body and `onChange` sees it.
    let processing: Bool
    let composer: NanoMuseComposerWatch
    let readOnly: Bool
    let perform: (NanoMuseChatAction) -> Void
    /// The composer's voice panel model, and the chat's switch into voice mode (the mic
    /// button's path), for a voice prompt the Action Button asked for.
    let voice: VoiceInputViewModel
    let enterVoice: () -> Void

    func body(content: Content) -> some View {
        content
            .onReceive(NotificationCenter.default.publisher(for: .nanoMuseChatAction)) { note in
                guard let action = NanoMuseChatAction.from(note, for: vm.nmSessionKey) else { return }
                perform(action)
            }
            .onReceive(NanoMuseVoicePrompt.shared.$pending) { _ in
                // A request for this chat, or for the chat that is open when the Muse shell is
                // off (with it on, the shell aims the request at the main chat first). A chat
                // that cannot be typed in cannot be spoken to either; the press is dropped.
                let mine = NanoMuseVoicePrompt.shared.take(for: vm.nmSessionKey, unaddressed: !NanoMuseShellPrefs.shell)
                guard mine, !readOnly else { return }
                NanoMuseVoicePrompt.listen(with: voice, enterVoice: enterVoice)
            }
            .nmOnChange(of: processing) { running in
                // a message went out (any path: the pill, a card's pick, a flow) or a turn ended —
                // the composer must be there a second later
                if !readOnly { composer.expect(running ? "a message went out" : "the turn ended") }
            }
            .onReceive(NanoMusePresence.shared.$revision) { _ in vm.nmApplyPresence() }
            .onReceive(vm.$messages) { _ in vm.nmApplyPresence() }
    }
}
