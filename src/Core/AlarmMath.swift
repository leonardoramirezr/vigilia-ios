import Foundation

enum AlarmRules {
    /// Minutes after the alarm at which it rings again unless the challenge is done.
    /// Pre-scheduled in AlarmKit, so they fire even if the app is closed or killed.
    static let retryMinutes = [1, 2, 3, 4, 5, 6, 7, 8, 10, 12, 15, 20, 30, 45, 60]
    /// How long after the alarm the app still demands the challenge.
    static let sessionWindow: TimeInterval = 65 * 60
    /// Stopping the alarm from the lock screen keeps re-arming it up to this point.
    static let maxSessionLength: TimeInterval = 2 * 60 * 60
    /// While the challenge is open, the next re-ring is always at most this far away.
    static let watchdogDelay: TimeInterval = 75
    /// The alarm may fire a moment before the app's clock says it should.
    static let earlyTolerance: TimeInterval = 20
    static let settingsUnlockDuration: TimeInterval = 5 * 60
    static let testDelay: TimeInterval = 60
    static let testRetryMinutes = [1, 2, 3]
    static let testSessionWindow: TimeInterval = 10 * 60
}

enum AlarmMath {
    /// Weekdays use Calendar numbering: 1 = Sunday … 7 = Saturday.
    static func nextOccurrence(weekday: Int, hour: Int, minute: Int, after date: Date, calendar: Calendar) -> Date? {
        calendar.nextDate(
            after: date,
            matching: DateComponents(hour: hour, minute: minute, second: 0, weekday: weekday),
            matchingPolicy: .nextTime)
    }

    static func nextOccurrence(weekdays: Set<Int>, hour: Int, minute: Int, after date: Date, calendar: Calendar) -> Date? {
        weekdays
            .compactMap { nextOccurrence(weekday: $0, hour: hour, minute: minute, after: date, calendar: calendar) }
            .min()
    }

    static func latestOccurrence(weekdays: Set<Int>, hour: Int, minute: Int, notAfter date: Date, calendar: Calendar) -> Date? {
        weekdays
            .compactMap { weekday in
                calendar.nextDate(
                    after: date.addingTimeInterval(1),
                    matching: DateComponents(hour: hour, minute: minute, second: 0, weekday: weekday),
                    matchingPolicy: .nextTime,
                    direction: .backward)
            }
            .max()
    }
}

extension Date {
    func isSameInstant(as other: Date) -> Bool {
        abs(timeIntervalSince(other)) < 1
    }
}
