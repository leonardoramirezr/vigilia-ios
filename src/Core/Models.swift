import Foundation

struct AlarmSettings: Codable, Equatable {
    var isEnabled = false
    var hour = 7
    var minute = 0
    /// Calendar weekdays: 1 = Sunday … 7 = Saturday.
    var weekdays: Set<Int> = Set(1...7)
}

/// One weekly-repeating AlarmKit alarm per selected weekday. Each one carries the
/// sound of its next occurrence, so every day sounds different.
struct MainAlarmRecord: Codable, Equatable {
    var id: UUID
    var weekday: Int
    var hour: Int
    var minute: Int
    var sound: String?
    var nextFire: Date
}

/// A one-shot alarm that rings again if the challenge has not been completed.
struct RetryRecord: Codable, Equatable {
    var id: UUID
    var occurrence: Date
    var fireDate: Date
}

struct TestRecord: Codable, Equatable {
    var id: UUID
    var occurrence: Date
}

struct WakeRecord: Codable, Equatable, Identifiable {
    var occurrence: Date
    var completedAt: Date
    var solved: Int
    var mistakes: Int
    var isTest: Bool

    var id: Date { completedAt }
}

struct ActiveSession: Equatable {
    var occurrence: Date
    var isTest: Bool
}

struct VigiliaState: Equatable {
    var settings = AlarmSettings()
    /// Occurrences before this moment never start a session (e.g. the alarm was just set).
    var armedSince = Date.distantPast
    var mains: [MainAlarmRecord] = []
    var retries: [RetryRecord] = []
    var test: TestRecord?
    var completedOccurrences: [Date] = []
    var history: [WakeRecord] = []
    var settingsUnlockedUntil: Date?

    func isCompleted(_ occurrence: Date) -> Bool {
        completedOccurrences.contains { $0.isSameInstant(as: occurrence) }
    }

    mutating func markCompleted(_ occurrence: Date) {
        guard !isCompleted(occurrence) else { return }
        completedOccurrences.append(occurrence)
        if completedOccurrences.count > 60 {
            completedOccurrences.removeFirst(completedOccurrences.count - 60)
        }
    }

    func hasPendingRetry(for occurrence: Date, after now: Date) -> Bool {
        retries.contains { $0.occurrence.isSameInstant(as: occurrence) && $0.fireDate > now }
    }

    /// The alarm that is ringing (or re-ringing) right now and still needs the challenge.
    func activeSession(at now: Date, calendar: Calendar) -> ActiveSession? {
        var candidates: [ActiveSession] = []
        if let test {
            candidates.append(ActiveSession(occurrence: test.occurrence, isTest: true))
        }
        if settings.isEnabled,
           let latest = AlarmMath.latestOccurrence(
               weekdays: settings.weekdays, hour: settings.hour, minute: settings.minute,
               notAfter: now.addingTimeInterval(AlarmRules.earlyTolerance), calendar: calendar),
           latest >= armedSince {
            candidates.append(ActiveSession(occurrence: latest, isTest: false))
        }
        for retry in retries where retry.fireDate > now
            && !candidates.contains(where: { $0.occurrence.isSameInstant(as: retry.occurrence) }) {
            candidates.append(ActiveSession(occurrence: retry.occurrence, isTest: false))
        }

        return candidates
            .filter { session in
                guard session.occurrence <= now.addingTimeInterval(AlarmRules.earlyTolerance),
                      !isCompleted(session.occurrence) else { return false }
                let window = session.isTest ? AlarmRules.testSessionWindow : AlarmRules.sessionWindow
                return now.timeIntervalSince(session.occurrence) <= window
                    || hasPendingRetry(for: session.occurrence, after: now)
            }
            .max { $0.occurrence < $1.occurrence }
    }
}

extension VigiliaState: Codable {
    private enum CodingKeys: String, CodingKey {
        case settings, armedSince, mains, retries, test, completedOccurrences, history, settingsUnlockedUntil
    }

    // Every key is optional so that older saved data keeps loading after updates.
    init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        self.init()
        settings = try container.decodeIfPresent(AlarmSettings.self, forKey: .settings) ?? settings
        armedSince = try container.decodeIfPresent(Date.self, forKey: .armedSince) ?? armedSince
        mains = try container.decodeIfPresent([MainAlarmRecord].self, forKey: .mains) ?? []
        retries = try container.decodeIfPresent([RetryRecord].self, forKey: .retries) ?? []
        test = try container.decodeIfPresent(TestRecord.self, forKey: .test)
        completedOccurrences = try container.decodeIfPresent([Date].self, forKey: .completedOccurrences) ?? []
        history = try container.decodeIfPresent([WakeRecord].self, forKey: .history) ?? []
        settingsUnlockedUntil = try container.decodeIfPresent(Date.self, forKey: .settingsUnlockedUntil)
    }
}
