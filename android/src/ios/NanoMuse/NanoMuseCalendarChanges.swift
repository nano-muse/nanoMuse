import Foundation

/// Only opaque event identities and busy intervals are needed to compare two reads.
enum NanoMuseCalendarChanges {
    struct Slot: Codable, Equatable, Sendable {
        let key: String
        let start: Date
        let end: Date
    }

    struct Snapshot: Codable, Sendable {
        let read: Date
        let through: Date
        let slots: [Slot]
    }

    enum Change: Equatable, Sendable {
        case moved(from: Slot, to: Slot)
        case conflict(Slot, Slot)

        var slots: [Slot] {
            switch self {
            case .moved(let before, let after): return [before, after]
            case .conflict(let a, let b): return [a, b]
            }
        }
    }

    static func next(previous: Snapshot?, current: Snapshot) -> Change? {
        guard let old = previous, old.read <= current.read,
              current.read.timeIntervalSince(old.read) <= 36 * 3600 else { return nil }
        let horizon = min(old.through, current.read.addingTimeInterval(24 * 3600))
        // A newly visible event beyond the previous query's horizon is not a calendar edit.
        let slots = current.slots.filter { $0.end > current.read && $0.start < horizon && $0.end > $0.start }
            .sorted { ($0.start, $0.key) < ($1.start, $1.key) }
        let prior = Dictionary(grouping: old.slots, by: \.key)
        func unique(_ slot: Slot) -> Slot? {
            let matches = prior[slot.key]
            return matches?.count == 1 ? matches?.first : nil
        }
        for (i, first) in slots.enumerated() {
            for other in slots.dropFirst(i + 1) {
                if other.start >= first.end { break }
                guard first.key != other.key, min(first.end, other.end) > current.read else { continue }
                if let a = unique(first), let b = unique(other), a.start < b.end, b.start < a.end { continue }
                return .conflict(first, other)
            }
        }
        for slot in slots where slot.start > current.read {
            guard let before = unique(slot), abs(slot.start.timeIntervalSince(before.start)) >= 15 * 60 else { continue }
            return .moved(from: before, to: slot)
        }
        return nil
    }
}
