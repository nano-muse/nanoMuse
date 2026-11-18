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

/// The height of the shell's floating bottom bar over the chat's bottom edge, 0 when the shell
/// is off or the bar is away for the keyboard. `NanoMuseHomeView` sets it over the chat layer;
/// `NanoMuseComposerHost` stands the composer column that much above the bottom, and the
/// message list's content scrolls under the column and the bar alike.
private struct NanoMuseBottomOverlayKey: EnvironmentKey {
    static let defaultValue: CGFloat = 0
}

extension EnvironmentValues {
    var nmBottomOverlay: CGFloat {
        get { self[NanoMuseBottomOverlayKey.self] }
        set { self[NanoMuseBottomOverlayKey.self] = newValue }
    }
}

/// The height of the shell's Muse header over the main chat's top edge (the face row and, while
/// one is up, the star or allowance card), 0 when the shell is off or in a pushed side chat.
/// `NanoMuseHomeView.chatLayer` measures the header and sets it; the chat lets its message list
/// extend under the header (`.ignoresSafeArea(.container, edges: .top)`) and gives the list that
/// much top content inset, so the rows pass under the face and the scrim behind the header
/// (`NanoMuseHeaderScrim`) has rows to fade. 1.0.3 and 1.0.4 laid the list out below the header
/// (a `safeAreaInset` shortens a UIKit view, unlike a SwiftUI `ScrollView`), so the rows stopped
/// at a hard edge under the face and the scrim faded nothing.
private struct NanoMuseTopOverlayKey: EnvironmentKey {
    static let defaultValue: CGFloat = 0
}

extension EnvironmentValues {
    var nmTopOverlay: CGFloat {
        get { self[NanoMuseTopOverlayKey.self] }
        set { self[NanoMuseTopOverlayKey.self] = newValue }
    }
}

/// True for a side chat pushed from the shell: the system navigation bar stays, with the main
/// chat's scrim behind it instead of a bar background (`NavBarStyleModifier` in AIChatView.swift
/// reads it). The main chat has no system bar and draws its scrim behind the Muse header.
private struct NanoMuseSystemBarScrimKey: EnvironmentKey {
    static let defaultValue = false
}

extension EnvironmentValues {
    var nmSystemBarScrim: Bool {
        get { self[NanoMuseSystemBarScrimKey.self] }
        set { self[NanoMuseSystemBarScrimKey.self] = newValue }
    }
}

/// The composer's place in the chat: a layer over the message list's bottom edge, standing
/// `overlay` points above it (the shell's bottom bar), the list as tall as the chat. The rows
/// scroll under the column and under the bar, which is what gives the bar's glass something to
/// blur and lets the last row dissolve instead of ending at a hard edge, as on Android
/// (`NmChatBottomLayout`, #331). The list keeps its content clear of the column with a bottom
/// inset of the column's measured height plus the bar (`columnHeight` is written here and read
/// by the chat for the list and for the scroll buttons). The `/` and `@` popup and its
/// tap-outside catcher stand on the column's top edge by layout, in one `VStack` with it.
///
/// Behind the column, Android's scrolling fade: once the person has scrolled up, a gradient of
/// the canvas colour over the rows passing behind the column and the solid canvas behind the
/// column itself, stopping at the bar so the glass keeps its rows; at the latest message there
/// is nothing behind the column but the list's own inset, and the fade is away.
///
/// 0.1.40 to 1.0.3 had the column as a `VStack` row under a shorter list (the composer that could
/// not be seen in 0.1.36 to 0.1.39 was a safe-area inset on the NavigationStack's ancestor, fixed
/// in `NanoMuseHomeView.body`; the row was the simplest layout that could not fail). That
/// layout left a plain canvas behind the bar, so the glass pill read as a white one. The three
/// layers here are boxed in `AnyView`s to keep this body shallow (NanoMuseRound6Tests).
struct NanoMuseComposerHost: ViewModifier {
    /// The column, type-erased: its tree (the cards, the tool strip, the input bar) is the
    /// heaviest part of the chat's body, and a box keeps it out of the body's value and type.
    let stack: AnyView
    /// The popup layer, type-erased for the same reason.
    let popup: AnyView
    /// The shell's bottom bar under the column (`\.nmBottomOverlay`), 0 without it.
    let overlay: CGFloat
    /// The column's height as laid out, without `overlay`; written on every change.
    @Binding var columnHeight: CGFloat
    /// The person has scrolled up from the latest row: the fade shows.
    let fade: Bool

    /// Android's `nmFadeHeight`: how far above the column the canvas fades in.
    static let fadeHeight: CGFloat = 90

    func body(content: Content) -> some View {
        ZStack(alignment: .bottom) {
            content
            fadeLayer
            VStack(spacing: 0) {
                popup
                columnLayer
            }
        }
    }

    private var columnLayer: AnyView {
        AnyView(
            stack
                .onGeometryChange(for: CGFloat.self) { proxy in
                    proxy.size.height
                } action: { height in
                    if abs(height - columnHeight) > 0.5 { columnHeight = height }
                }
                .padding(.bottom, overlay)
        )
    }

    private var fadeLayer: AnyView {
        AnyView(
            NanoMuseComposerVignette(
                composerHeight: min(columnHeight, 62),
                bottomGap: overlay > 0 ? 8 : 0
            )
            .frame(height: Self.fadeHeight + min(columnHeight, 62))
            .padding(.bottom, overlay)
            .opacity(fade ? 1 : 0)
            .animation(.easeInOut(duration: 0.25), value: fade)
            .allowsHitTesting(false)
        )
    }
}

/// Rounded halo behind the floating composer pill, matching Android's `NmComposerVignette`.
/// Follows the capsule contour (`cornerRadius = 26`, `maxWidth = 760`, `horizontalPadding = 16`)
/// instead of painting a full-width opaque rectangular strip across the chat.
private struct NanoMuseComposerVignette: View {
    let composerHeight: CGFloat
    let bottomGap: CGFloat

    private static let spread: CGFloat = NanoMuseComposerHost.fadeHeight
    private static let cornerRadius: CGFloat = 26
    private static let horizontalInset: CGFloat = 16
    private static let maxContentWidth: CGFloat = 760

    var body: some View {
        Canvas { context, size in
            guard size.width > 0, size.height > 0, composerHeight > 0 else { return }
            let bg = ChatColors.background
            let clear = bg.opacity(0)
            let spread = min(Self.spread, size.height)
            let barH = max(0, size.height - spread)
            let gap = min(bottomGap, barH)

            let pillWidth = max(0, min(size.width, Self.maxContentWidth) - Self.horizontalInset * 2)
            let padH = (size.width - pillWidth) / 2
            let innerLeft = padH
            let innerRight = size.width - padH
            let innerTop = spread
            let innerBottom = max(innerTop, size.height - gap)
            let innerW = max(0, innerRight - innerLeft)
            let innerH = max(0, innerBottom - innerTop)
            let r = min(Self.cornerRadius, min(innerW, innerH) / 2)
            let outerR = r + spread

            let cxL = innerLeft + r
            let cxR = innerRight - r
            let cyT = innerTop + r
            let cyB = innerBottom - r

            context.drawLayer { layer in
                if cxR > cxL && innerBottom > innerTop {
                    layer.fill(
                        Path(CGRect(x: cxL, y: innerTop, width: cxR - cxL, height: innerBottom - innerTop)),
                        with: .color(bg)
                    )
                }
                if cyB > cyT && innerRight > innerLeft {
                    layer.fill(
                        Path(CGRect(x: innerLeft, y: cyT, width: innerRight - innerLeft, height: cyB - cyT)),
                        with: .color(bg)
                    )
                }

                let topH = cyT - (cyT - outerR) - r
                if topH > 0 && cxR > cxL {
                    let rect = CGRect(x: cxL, y: cyT - outerR, width: cxR - cxL, height: topH)
                    layer.fill(
                        Path(rect),
                        with: .linearGradient(
                            Gradient(colors: [bg, clear]),
                            startPoint: CGPoint(x: cxL, y: cyT - r),
                            endPoint: CGPoint(x: cxL, y: cyT - outerR)
                        )
                    )
                }

                let botStart = cyB + r
                let botH = size.height - botStart
                if botH > 0 && cxR > cxL {
                    let rect = CGRect(x: cxL, y: botStart, width: cxR - cxL, height: botH)
                    layer.fill(
                        Path(rect),
                        with: .linearGradient(
                            Gradient(colors: [bg, clear]),
                            startPoint: CGPoint(x: cxL, y: botStart),
                            endPoint: CGPoint(x: cxL, y: cyB + outerR)
                        )
                    )
                }

                let leftEnd = cxL - r
                let leftStart = max(0, cxL - outerR)
                if leftEnd > leftStart && cyB > cyT {
                    let rect = CGRect(x: leftStart, y: cyT, width: leftEnd - leftStart, height: cyB - cyT)
                    layer.fill(
                        Path(rect),
                        with: .linearGradient(
                            Gradient(colors: [bg, clear]),
                            startPoint: CGPoint(x: leftEnd, y: cyT),
                            endPoint: CGPoint(x: cxL - outerR, y: cyT)
                        )
                    )
                }

                let rightStart = cxR + r
                let rightEnd = min(size.width, cxR + outerR)
                if rightEnd > rightStart && cyB > cyT {
                    let rect = CGRect(x: rightStart, y: cyT, width: rightEnd - rightStart, height: cyB - cyT)
                    layer.fill(
                        Path(rect),
                        with: .linearGradient(
                            Gradient(colors: [bg, clear]),
                            startPoint: CGPoint(x: rightStart, y: cyT),
                            endPoint: CGPoint(x: cxR + outerR, y: cyT)
                        )
                    )
                }

                if outerR > 0 {
                    let innerStop = min(1, max(0, r / outerR))
                    let radial = Gradient(stops: [
                        .init(color: bg, location: 0),
                        .init(color: bg, location: innerStop),
                        .init(color: clear, location: 1),
                    ])
                    let corners: [(CGPoint, CGRect)] = [
                        (
                            CGPoint(x: cxL, y: cyT),
                            CGRect(x: max(0, cxL - outerR), y: max(0, cyT - outerR), width: cxL - max(0, cxL - outerR), height: cyT - max(0, cyT - outerR))
                        ),
                        (
                            CGPoint(x: cxR, y: cyT),
                            CGRect(x: cxR, y: max(0, cyT - outerR), width: min(size.width, cxR + outerR) - cxR, height: cyT - max(0, cyT - outerR))
                        ),
                        (
                            CGPoint(x: cxL, y: cyB),
                            CGRect(x: max(0, cxL - outerR), y: cyB, width: cxL - max(0, cxL - outerR), height: size.height - cyB)
                        ),
                        (
                            CGPoint(x: cxR, y: cyB),
                            CGRect(x: cxR, y: cyB, width: min(size.width, cxR + outerR) - cxR, height: size.height - cyB)
                        ),
                    ]
                    for (center, clipRect) in corners where clipRect.width > 0 && clipRect.height > 0 {
                        var sub = layer
                        sub.clip(to: Path(clipRect))
                        sub.fill(
                            Path(clipRect),
                            with: .radialGradient(radial, center: center, startRadius: 0, endRadius: outerR)
                        )
                    }
                }

                if gap > 0 {
                    let fadeStart = min(0.95, max(0, (innerBottom - spread * 0.35) / size.height))
                    var mask = layer
                    mask.blendMode = .destinationIn
                    mask.fill(
                        Path(CGRect(origin: .zero, size: size)),
                        with: .linearGradient(
                            Gradient(stops: [
                                .init(color: .white, location: 0),
                                .init(color: .white, location: fadeStart),
                                .init(color: .white.opacity(0), location: 1),
                            ]),
                            startPoint: CGPoint(x: 0, y: 0),
                            endPoint: CGPoint(x: 0, y: size.height)
                        )
                    )
                }
            }
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
    @State private var showThinking = false

    func body(content: Content) -> some View {
        content
            .onReceive(NotificationCenter.default.publisher(for: .nanoMuseChatAction)) { note in
                guard let action = NanoMuseChatAction.from(note, for: vm.nmSessionKey) else { return }
                if action == .thinking {
                    if !readOnly { showThinking = true }
                } else {
                    perform(action)
                }
            }
            .sheet(isPresented: $showThinking) {
                NanoMuseThinkingSheet(vm: vm) { showThinking = false }
                    .presentationDetents([.medium])
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
