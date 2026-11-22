import SwiftUI

/// A single live card in the Feed. Opening it takes the person back to the source goal.
struct NanoMuseDeadlineCard: View {
    var onOpenSession: (String) -> Void
    @ObservedObject private var store = NanoMuseGoalStore.shared
    @ObservedObject private var locks = SessionLockStore.shared

    var body: some View {
        TimelineView(.periodic(from: .now, by: 60)) { tick in
            if !locks.appIsLocked, let card = NanoMuseGoalDeadline.next(
                in: store.goals, at: tick.date, excluding: locks.lockedSessionIds
            ) {
                VStack(alignment: .leading, spacing: 8) {
                    HStack {
                        Label(deadlineLabel(card), systemImage: "calendar")
                            .font(.footnote.weight(.semibold)).foregroundStyle(.secondary)
                        Spacer()
                        Menu {
                            Button(AppLocalized("Show tomorrow")) {
                                store.respond(to: card, with: .snooze(until: NanoMuseGoalDeadline.tomorrow(after: Date())))
                            }
                            Button(AppLocalized("Hide this deadline")) { store.respond(to: card, with: .hide) }
                        } label: {
                            Image(systemName: "ellipsis").frame(width: 32, height: 32)
                        }
                        .accessibilityLabel(Text(AppLocalized("More")))
                    }
                    Text(verbatim: card.goal.title).font(.headline)
                    if let step = card.goal.steps.first(where: { !$0.done }) {
                        Text(String(format: AppLocalized("Next step: %@"), step.text)).font(.subheadline)
                        Button(AppLocalized("Mark step complete")) { store.respond(to: card, with: .completeStep(step.id)) }
                            .font(.footnote.weight(.medium))
                    }
                    Button(AppLocalized("Open goal")) {
                        guard !locks.appIsLocked, let goal = store.goal(id: card.goal.id),
                              !goal.usesProtectedSession(in: locks.lockedSessionIds) else { return }
                        if let session = goal.sessionId {
                            onOpenSession(session)
                        } else {
                            NotificationCenter.default.post(name: .nanoMuseOpenRoom, object: "goals")
                        }
                    }
                    .font(.footnote.weight(.medium))
                }
                .buttonStyle(.borderless)
                .padding(.horizontal, 16).padding(.vertical, 12)
                .background(NanoMuseTones.surface, in: RoundedRectangle(cornerRadius: 16, style: .continuous))
            }
        }
    }

    private func deadlineLabel(_ card: NanoMuseGoalDeadline) -> String {
        if card.daysAway == 0 { return AppLocalized("Due today") }
        if card.daysAway == 1 { return AppLocalized("Due tomorrow") }
        return String(format: AppLocalized("Overdue since %@"), card.due.formatted(date: .abbreviated, time: .omitted))
    }
}

struct NanoMuseDeadlineEditor: View {
    let goal: NanoMuseGoal
    @Environment(\.dismiss) private var dismiss
    @State private var date: Date

    init(goal: NanoMuseGoal) {
        self.goal = goal
        _date = State(initialValue: NanoMuseGoalDeadline.date(goal.due) ?? Date())
    }

    var body: some View {
        NavigationStack {
            Form {
                DatePicker(AppLocalized("Due date"), selection: $date, displayedComponents: .date)
                if goal.due != nil {
                    Button(AppLocalized("Remove due date"), role: .destructive) {
                        NanoMuseGoalStore.shared.setDue(nil, for: goal.id)
                        dismiss()
                    }
                }
            }
            .navigationTitle(AppLocalized("Due date"))
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) { Button(AppLocalized("Cancel")) { dismiss() } }
                ToolbarItem(placement: .confirmationAction) {
                    Button(AppLocalized("Save")) {
                        NanoMuseGoalStore.shared.setDue(NanoMuseGoalDeadline.key(date), for: goal.id)
                        dismiss()
                    }
                }
            }
        }
    }
}
