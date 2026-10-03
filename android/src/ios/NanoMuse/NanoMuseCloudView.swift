import SwiftUI

/// Settings › Providers › nanoMuse Cloud. Signed out: a phone number or an e-mail address, a
/// code, done. Signed in: what is left of the starter allowance, a refresh, the way out.
/// Mirror of the Android `CloudSignInScreen` / `CloudAccountScreen`.
struct NanoMuseCloudView: View {
    @ObservedObject private var store = ProviderConfigStore.shared
    @State private var account: NanoMuseCloudAccount?
    @State private var identifier = ""
    @State private var code = ""
    @State private var codeSent = false
    @State private var busy = false
    @State private var message: String?
    @State private var failed = false
    @State private var confirmSignOut = false
    @State private var relayBase = ""

    private var signedIn: Bool {
        _ = store.instances  // re-evaluate when the provider is removed elsewhere
        return NanoMuseCloud.isSignedIn
    }

    var body: some View {
        Form {
            if signedIn {
                accountSections
                NanoMuseDevicesSection()
            } else {
                signInSections
            }
            if NanoMuseCloud.canOverrideBase, !signedIn {
                relaySection
            }
        }
        .navigationTitle(NanoMuseCloud.label)
        .navigationBarTitleDisplayMode(.inline)
        .task {
            account = NanoMuseCloud.account
            relayBase = NanoMuseCloud.baseURL == NanoMuseCloud.defaultBase ? "" : NanoMuseCloud.baseURL
            if signedIn { await refresh(quiet: true) }
        }
    }

    // MARK: - Signed in

    @ViewBuilder
    private var accountSections: some View {
        Section {
            if let account {
                LabeledContent(AppLocalized("Signed in as"), value: account.hint)
                VStack(alignment: .leading, spacing: 6) {
                    if account.unlimited {
                        // No ceiling on this relay: what was used, nothing to run out of.
                        let used = account.used.formatted()
                        let usedToday = account.usedToday.formatted()
                        Text(AppLocalized("No limit on this account"))
                            .font(.subheadline)
                        Text(AppLocalized("\(used) tokens used so far, \(usedToday) today"))
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    } else {
                        ProgressView(value: account.fraction)
                        let remaining = account.remaining.formatted()
                        let granted = account.granted.formatted()
                        Text(AppLocalized("\(remaining) of \(granted) tokens left"))
                            .font(.subheadline)
                            .foregroundStyle(.secondary)
                        if account.dailyCap > 0 {
                            let usedToday = account.usedToday.formatted()
                            let dailyCap = account.dailyCap.formatted()
                            Text(AppLocalized("Today: \(usedToday) of \(dailyCap)"))
                                .font(.caption)
                                .foregroundStyle(.secondary)
                        }
                    }
                    let checked = account.checkedAt.formatted(.relative(presentation: .named))
                    Text(AppLocalized("Checked \(checked)"))
                        .font(.caption2)
                        .foregroundStyle(.tertiary)
                }
                .padding(.vertical, 4)
            } else {
                Text(AppLocalized("Signed in. Pull the balance with Refresh."))
                    .foregroundStyle(.secondary)
            }
            Button {
                Task { await refresh(quiet: false) }
            } label: {
                Label(AppLocalized("Refresh"), systemImage: "arrow.clockwise")
            }
            .disabled(busy)
        } footer: {
            if let message {
                Text(message).foregroundStyle(failed ? Color.red : Color.secondary)
            }
        }

        if let inst = NanoMuseCloud.instance {
            Section {
                NavigationLink {
                    ProviderInstanceDetailView(instanceId: inst.id)
                } label: {
                    Label(AppLocalized("Provider settings"), systemImage: "slider.horizontal.3")
                }
            } footer: {
                Text(AppLocalized("The relay is an ordinary provider named \"nanoMuse Cloud\": its models can join any model group, and a key of your own can sit next to it."))
            }
        }

        Section {
            Button(role: .destructive) {
                confirmSignOut = true
            } label: {
                Label(AppLocalized("Sign out"), systemImage: "rectangle.portrait.and.arrow.right")
            }
            .disabled(busy)
            .confirmationDialog(
                AppLocalized("Sign out of nanoMuse Cloud?"),
                isPresented: $confirmSignOut,
                titleVisibility: .visible
            ) {
                Button(AppLocalized("Sign out"), role: .destructive) {
                    Task { await signOut() }
                }
            } message: {
                Text(AppLocalized("This phone's key is revoked and the provider is removed. What is left of the allowance stays with the account."))
            }
        } footer: {
            privacyFooter
        }
    }

    // MARK: - Signed out

    @ViewBuilder
    private var signInSections: some View {
        Section {
            Text(AppLocalized("Sign in with a phone number or an e-mail address and start right away with a starter allowance — no key of your own needed. A provider of your own can be added at any time."))
                .font(.subheadline)
                .foregroundStyle(.secondary)
        }

        Section {
            TextField(AppLocalized("Phone number or e-mail"), text: $identifier)
                .keyboardType(.emailAddress)
                .textContentType(.username)
                .textInputAutocapitalization(.never)
                .autocorrectionDisabled()
                .disabled(busy || codeSent)
            if codeSent {
                TextField(AppLocalized("Verification code"), text: $code)
                    .keyboardType(.numberPad)
                    .textContentType(.oneTimeCode)
                    .disabled(busy)
            }
        } footer: {
            if let message {
                Text(message).foregroundStyle(failed ? Color.red : Color.secondary)
            }
        }

        Section {
            if codeSent {
                Button {
                    Task { await signIn() }
                } label: {
                    HStack {
                        Text(AppLocalized("Sign in"))
                        if busy { Spacer(); ProgressView() }
                    }
                }
                .disabled(busy || code.trimmingCharacters(in: .whitespaces).isEmpty)
                Button(AppLocalized("Use another number or address")) {
                    codeSent = false
                    code = ""
                    message = nil
                }
                .disabled(busy)
            } else {
                Button {
                    Task { await sendCode() }
                } label: {
                    HStack {
                        Text(AppLocalized("Send code"))
                        if busy { Spacer(); ProgressView() }
                    }
                }
                .disabled(busy || identifier.trimmingCharacters(in: .whitespaces).isEmpty)
            }
        } footer: {
            privacyFooter
        }
    }

    private var privacyFooter: some View {
        VStack(alignment: .leading, spacing: 4) {
            Text(AppLocalized("The relay keeps a hashed identifier and token counts. Messages are passed to the model and not stored."))
            Link(AppLocalized("How nanoMuse Cloud works"), destination: URL(string: "https://github.com/nano-muse/nanoMuse/blob/main/docs/cloud.md")!)
        }
    }

    // MARK: - Relay

    private var relaySection: some View {
        Section {
            TextField(NanoMuseCloud.defaultBase, text: $relayBase)
                .keyboardType(.URL)
                .textInputAutocapitalization(.never)
                .autocorrectionDisabled()
                .onSubmit { NanoMuseCloud.setBaseURL(relayBase) }
                .onChange(of: relayBase) { newValue in NanoMuseCloud.setBaseURL(newValue) }
        } header: {
            Text(AppLocalized("Relay server"))
        } footer: {
            Text(AppLocalized("Another relay to sign in against, for example one running on a laptop on the same Wi-Fi. Empty means the default."))
        }
    }

    // MARK: - Actions

    private func sendCode() async {
        busy = true
        failed = false
        defer { busy = false }
        do {
            try await NanoMuseCloud.requestCode(identifier: identifier)
            codeSent = true
            message = AppLocalized("Code sent. Enter it below.")
        } catch {
            failed = true
            message = NanoMuseCloud.describe(error)
        }
    }

    private func signIn() async {
        busy = true
        failed = false
        defer { busy = false }
        do {
            account = try await NanoMuseCloud.verify(identifier: identifier, code: code)
            message = nil
            code = ""
            codeSent = false
        } catch {
            failed = true
            message = NanoMuseCloud.describe(error)
        }
    }

    private func refresh(quiet: Bool) async {
        busy = true
        defer { busy = false }
        do {
            account = try await NanoMuseCloud.refresh()
            if !quiet {
                failed = false
                message = nil
            }
        } catch {
            if !quiet {
                failed = true
                message = NanoMuseCloud.describe(error)
            }
        }
    }

    private func signOut() async {
        busy = true
        defer { busy = false }
        await NanoMuseCloud.signOut()
        account = nil
        message = nil
        failed = false
    }
}

/// The row in the providers list that leads to `NanoMuseCloudView`.
struct NanoMuseCloudRow: View {
    @ObservedObject private var store = ProviderConfigStore.shared

    var body: some View {
        _ = store.instances
        let account = NanoMuseCloud.isSignedIn ? NanoMuseCloud.account : nil
        return HStack(spacing: 12) {
            Image(systemName: "cloud.fill")
                .font(.title3)
                .foregroundStyle(Color.accentColor)
                .frame(width: 28)
            VStack(alignment: .leading, spacing: 2) {
                Text(NanoMuseCloud.label)
                if let account {
                    let hint = account.hint
                    let left = account.fraction.formatted(.percent.precision(.fractionLength(0)))
                    Text(AppLocalized("\(hint) · \(left) of the allowance left"))
                        .font(.caption)
                        .foregroundStyle(.secondary)
                } else if NanoMuseCloud.isSignedIn {
                    Text(AppLocalized("Signed in"))
                        .font(.caption)
                        .foregroundStyle(.secondary)
                } else {
                    Text(AppLocalized("Phone or e-mail sign-in, no key needed"))
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
            }
        }
    }
}
