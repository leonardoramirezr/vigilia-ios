import Foundation

struct AlarmTime: Codable, Hashable {
    var hour: Int
    var minute: Int
}

struct AlarmSettings: Equatable {
    var isEnabled = false
    var hour = 7
    var minute = 0
    /// Calendar weekdays: 1 = Sunday … 7 = Saturday.
    var weekdays: Set<Int> = Set(1...7)
    /// When false, each weekday rings at its own time from `dayTimes`.
    var sameTimeEveryDay = true
    /// Per-weekday times, used only when `sameTimeEveryDay` is false. Days missing
    /// here ring at `hour:minute`. Kept while the same time is used, so switching
    /// back to per-day times restores them.
    var dayTimes: [Int: AlarmTime] = [:]

    var defaultTime: AlarmTime {
        AlarmTime(hour: hour, minute: minute)
    }

    func time(on weekday: Int) -> AlarmTime {
        sameTimeEveryDay ? defaultTime : dayTimes[weekday] ?? defaultTime
    }

    /// Every selected weekday with the time it rings.
    var schedule: [Int: AlarmTime] {
        Dictionary(uniqueKeysWithValues: weekdays.map { ($0, time(on: $0)) })
    }
    var difficulty = ChallengeDifficulty.twoDigits
}

extension AlarmSettings: Codable {
    private enum CodingKeys: String, CodingKey {
        case isEnabled, hour, minute, weekdays, sameTimeEveryDay, dayTimes, difficulty
    }

    // Every key is optional so that settings saved by older versions keep loading.
    init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        self.init()
        isEnabled = try container.decodeIfPresent(Bool.self, forKey: .isEnabled) ?? isEnabled
        hour = try container.decodeIfPresent(Int.self, forKey: .hour) ?? hour
        minute = try container.decodeIfPresent(Int.self, forKey: .minute) ?? minute
        weekdays = try container.decodeIfPresent(Set<Int>.self, forKey: .weekdays) ?? weekdays
        sameTimeEveryDay = try container.decodeIfPresent(Bool.self, forKey: .sameTimeEveryDay) ?? sameTimeEveryDay
        dayTimes = try container.decodeIfPresent([Int: AlarmTime].self, forKey: .dayTimes) ?? dayTimes
        // An unknown level (saved by a newer version) must not lose the alarm.
        difficulty = (try? container.decodeIfPresent(ChallengeDifficulty.self, forKey: .difficulty)) ?? difficulty
    }
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
    /// A one-shot alarm at `nextFire` instead of the weekly one, because the
    /// occurrence before it was turned off in advance (see `MainAlarmPlan`).
    var isOneShot: Bool?
}

/// What the alarm of one weekday must look like in AlarmKit.
struct MainAlarmPlan: Equatable {
    var weekday: Int
    var time: AlarmTime
    /// The next time it rings.
    var fireDate: Date
    /// The occurrence turned off in advance, if any. A weekly alarm can't skip one
    /// week, so until it passes a one-shot alarm at `fireDate` stands in for it.
    var skipped: Date?

    var isOneShot: Bool { skipped != nil }
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

    /// Newest first. Real wake-ups are kept for the statistics; tests only show up
    /// in the list on the home screen.
    mutating func recordWake(_ record: WakeRecord) {
        var kept: [WakeRecord] = []
        var wakes = 0
        var tests = 0
        for entry in [record] + history {
            if entry.isTest {
                tests += 1
                if tests > AlarmRules.testHistoryLimit { continue }
            } else {
                wakes += 1
                if wakes > AlarmRules.historyLimit { continue }
            }
            kept.append(entry)
        }
        history = kept
    }

    /// Applies a settings change unless an alarm is going off (`isAlerting`) or its
    /// challenge is still pending. Every change restarts `armedSince`, which drops the
    /// ringing occurrence from `activeSession`: with no re-ring pending, the session
    /// would end and the alarm would stop coming back without the challenge.
    /// Returns false when the change was ignored or changed nothing.
    mutating func changeSettings(
        at now: Date, isAlerting: Bool, calendar: Calendar, _ change: (inout AlarmSettings) -> Void
    ) -> Bool {
        guard !isAlerting, activeSession(at: now, calendar: calendar) == nil else { return false }
        var updated = settings
        change(&updated)
        if updated.weekdays.isEmpty {
            updated.weekdays = settings.weekdays
        }
        guard updated != settings else { return false }
        settings = updated
        armedSince = now
        return true
    }

    /// The next ring of every selected weekday. An occurrence that was turned off in
    /// advance (completed before it rang) is skipped: that weekday rings a week later.
    func mainAlarmPlans(after now: Date, calendar: Calendar) -> [Int: MainAlarmPlan] {
        guard settings.isEnabled else { return [:] }
        var plans: [Int: MainAlarmPlan] = [:]
        for (weekday, time) in settings.schedule {
            guard let next = AlarmMath.nextOccurrence(
                weekday: weekday, hour: time.hour, minute: time.minute, after: now, calendar: calendar) else { continue }
            if isCompleted(next) {
                guard let following = AlarmMath.nextOccurrence(
                    weekday: weekday, hour: time.hour, minute: time.minute, after: next, calendar: calendar) else { continue }
                plans[weekday] = MainAlarmPlan(weekday: weekday, time: time, fireDate: following, skipped: next)
            } else {
                plans[weekday] = MainAlarmPlan(weekday: weekday, time: time, fireDate: next)
            }
        }
        return plans
    }

    /// The next time the alarm will actually ring.
    func nextOccurrence(after now: Date, calendar: Calendar) -> Date? {
        mainAlarmPlans(after: now, calendar: calendar).values.map(\.fireDate).min()
    }

    /// The next upcoming occurrence that was turned off in advance.
    func dismissedOccurrence(after now: Date, calendar: Calendar) -> Date? {
        mainAlarmPlans(after: now, calendar: calendar).values.compactMap(\.skipped).min()
    }

    /// The next alarm, when it is close enough to turn it off in advance by doing its
    /// challenge now. Never while an alarm (or the test) still waits for its challenge.
    func earlyDismissibleOccurrence(at now: Date, calendar: Calendar) -> Date? {
        guard activeSession(at: now, calendar: calendar) == nil,
              let next = nextOccurrence(after: now, calendar: calendar) else { return nil }
        let remaining = next.timeIntervalSince(now)
        guard remaining > AlarmRules.earlyTolerance, remaining <= AlarmRules.earlyDismissWindow else { return nil }
        return next
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
               schedule: settings.schedule, notAfter: now.addingTimeInterval(AlarmRules.earlyTolerance), calendar: calendar),
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
