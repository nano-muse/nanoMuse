//
//  NanoMuseRelayRefusalCard.swift
//  nanoMuse
//
//  A turn nanoMuse Cloud refused (docs/parity.md, item 35): one plain sentence from
//  `NanoMuseCloud.describe` and the button that fits — *New chat* for a message too large,
//  *Sign in* for a key the relay no longer takes, *Open Settings* for a model that left the
//  menu or an account the relay does not take, *Try again* for the rest (busy, the provider
//  behind the relay, the operator's switches). An allowance refusal has the pinned card with
//  the ways on (NanoMuseAllowanceCard); here it is the sentence, *Try again* and *Ways on*.
//  The relay's own sentence is shown under ours only where it adds something. Shown where the
//  failed turn is, through NanoMuseProviderReachCard. Android: RelayRefusalCard.kt.
//

import SwiftUI

struct NanoMuseRelayRefusalCard: View {
    let refusal: NanoMuseRelayRefusal.Refusal
    var onRetry: (() -> Void)?

    private var sentence: String { NanoMuseCloud.describe(refusal.cloudError) }

    /// The relay's own sentence is worth a line only where ours is general.
    private var relaySays: String? {
        guard !refusal.message.isEmpty, !refusal.message.hasPrefix("HTTP ") else { return nil }
        guard refusal.kind == .disabled || refusal.kind == .other, refusal.message != sentence else { return nil }
        return refusal.message
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack(alignment: .top, spacing: 10) {
                Image(systemName: icon)
                    .font(.system(size: 16, weight: .medium))
                    .foregroundStyle(tint)
                    .padding(.top, 2)
                    .accessibilityHidden(true)
                VStack(alignment: .leading, spacing: 3) {
                    Text(sentence).font(.subheadline.weight(.medium))
                    if let relaySays {
                        Text(String(format: AppLocalized("The relay says: %@"), relaySays))
                            .font(.footnote).foregroundStyle(.secondary)
                    }
                }
            }
            actions
        }
        .padding(14)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(NanoMuseTones.surface, in: RoundedRectangle(cornerRadius: 18, style: .continuous))
        .overlay(RoundedRectangle(cornerRadius: 18, style: .continuous).stroke(NanoMuseTones.hairline, lineWidth: 1))
        .padding(.top, 4)
    }

    private var icon: String {
        switch refusal.kind {
        case .tooLarge: return "arrow.down.right.and.arrow.up.left"
        case .contentRejected: return "hand.raised"
        case .signedOut, .disabled: return "key"
        case .busy: return "hourglass"
        case .servicePaused, .syncPaused, .hubPaused, .allowancePaused: return "pause.circle"
        case .exhausted, .dailyCap: return "gauge"
        case .model, .relayDown, .other: return "cloud"
        }
    }

    private var tint: Color {
        switch refusal.kind {
        case .tooLarge, .contentRejected, .relayDown, .other, .model: return Color(red: 0.88, green: 0.47, blue: 0.17)
        case .signedOut, .disabled: return NanoMuseTones.action
        case .busy, .servicePaused, .syncPaused, .hubPaused, .allowancePaused, .exhausted, .dailyCap: return Color(red: 0.49, green: 0.36, blue: 1.0)
        }
    }

    @ViewBuilder
    private var actions: some View {
        HStack(spacing: 8) {
            switch refusal.kind {
            case .tooLarge:
                primary(AppLocalized("New chat")) { NotificationCenter.default.post(name: .newChatRequested, object: nil) }
            case .contentRejected:
                // the words are the matter: a new chat leaves them behind; *Try again* sends the same ones once more, by choice
                primary(AppLocalized("New chat")) { NotificationCenter.default.post(name: .newChatRequested, object: nil) }
                secondary(AppLocalized("Try again"), onRetry)
            case .signedOut:
                primary(AppLocalized("Sign in")) { openSettings() }
                secondary(AppLocalized("Try again"), onRetry)
            case .disabled, .model:
                primary(AppLocalized("Open Settings")) { openSettings() }
            case .other:
                primary(AppLocalized("Try again")) { onRetry?() }
                secondary(AppLocalized("Open Settings")) { openSettings() }
            case .exhausted, .allowancePaused, .dailyCap:
                primary(AppLocalized("Try again")) { onRetry?() }
                secondary(AppLocalized("Ways on")) { openSettings() }
            case .busy, .servicePaused, .syncPaused, .hubPaused, .relayDown:
                primary(AppLocalized("Try again")) { onRetry?() }
            }
        }
        .padding(.top, 2)
    }

    private func primary(_ label: String, action: @escaping () -> Void) -> some View {
        Button(label, action: action)
            .buttonStyle(.borderedProminent).tint(NanoMuseTones.action).controlSize(.small)
    }

    @ViewBuilder
    private func secondary(_ label: String, _ action: (() -> Void)?) -> some View {
        if let action {
            Button(label, action: action).buttonStyle(.plain).font(.footnote).foregroundStyle(NanoMuseTones.action)
        }
    }

    /// Settings → nanoMuse Cloud is the first row of the nanoMuse settings home.
    private func openSettings() {
        NotificationCenter.default.post(name: .nanoMuseHomeAction, object: "settings")
    }
}
