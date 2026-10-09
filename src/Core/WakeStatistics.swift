import Foundation

/// The three choices on the statistics screen. They are independent: every
/// combination is valid.
enum StatsMetric: String, CaseIterable, Identifiable {
    case average, evolution

    var id: String { rawValue }
}

enum StatsGrouping: String, CaseIterable, Identifiable {
    case byWeekday, wholeWeek

    var id: String { rawValue }
}

enum StatsPeriod: String, CaseIterable, Identifiable {
    case always, year, month, week

    var id: String { rawValue }

    /// Where the period starts, counting back from `now`; nil counts everything.
    func start(before now: Date, calendar: Calendar) -> Date? {
        switch self {
        case .always: return nil
        case .year: return calendar.date(byAdding: .year, value: -1, to: now)
        case .month: return calendar.date(byAdding: .month, value: -1, to: now)
        case .week: return calendar.date(byAdding: .day, value: -7, to: now)
        }
    }
}

/// The three things measured about each wake-up.
enum WakeMeasure: CaseIterable, Identifiable {
    /// When the alarm rang for the first time.
    case alarmTime
    /// When the challenge was completed and the alarm turned off.
    case offTime
    /// How long it took to turn it off, from the first ring.
    case timeToOff

    var id: Self { self }

    /// Times of day wrap around midnight; durations don't.
    var isTimeOfDay: Bool { self != .timeToOff }
}

/// A wake-up reduced to what the statistics need.
struct WakeSample: Equatable {
    /// Start of the day the alarm rang.
    var day: Date
    /// Calendar weekday of the alarm: 1 = Sunday … 7 = Saturday.
    var weekday: Int
    /// When the alarm rang for the first time, in minutes after midnight.
    var alarmMinute: Double
    /// When the challenge was completed (the alarm turned off), in minutes after midnight.
    var offMinute: Double
    /// Minutes from the first ring to turning it off.
    var minutesToOff: Double

    func value(_ measure: WakeMeasure) -> Double {
        switch measure {
        case .alarmTime: return alarmMinute
        case .offTime: return offMinute
        case .timeToOff: return minutesToOff
        }
    }
}

struct WakeSummary: Equatable {
    /// Minutes after midnight (0..<1440), or minutes for a duration.
    var average: Double
    /// 10th, 50th (median) and 90th percentiles, on the same scale as `average`.
    var p10: Double
    var p50: Double
    var p90: Double
    var count: Int
}

/// One point of the evolution chart: a wake-up, or the average of a week or a month.
struct WakePoint: Equatable, Identifiable {
    var date: Date
    /// Minutes after midnight on the chart's continuous scale, or minutes for a
    /// duration. Times can drop below 0 or pass 1440 so that times on both sides
    /// of midnight stay together.
    var minute: Double
    /// nil when the whole week is drawn as a single line.
    var weekday: Int?
    /// Wake-ups averaged into this point.
    var count: Int

    var id: String { "\(weekday ?? 0)-\(date.timeIntervalSinceReferenceDate)" }
}

struct WakeTrend: Equatable {
    enum Resolution: Equatable {
        case day, week, month
    }

    var resolution: Resolution
    var points: [WakePoint]
    /// Average of every wake-up, on the same scale as the points.
    var average: Double?
}

enum WakeStatistics {
    static let minutesPerDay = 1440.0

    /// Real wake-ups (tests don't count) whose alarm rang within the period, oldest first.
    static func samples(from history: [WakeRecord], period: StatsPeriod, now: Date, calendar: Calendar) -> [WakeSample] {
        let start = period.start(before: now, calendar: calendar) ?? .distantPast
        return history
            .filter { !$0.isTest && $0.occurrence >= start && $0.occurrence <= now }
            .map { record in
                WakeSample(
                    day: calendar.startOfDay(for: record.occurrence),
                    weekday: calendar.component(.weekday, from: record.occurrence),
                    alarmMinute: minuteOfDay(record.occurrence, calendar: calendar),
                    offMinute: minuteOfDay(record.completedAt, calendar: calendar),
                    minutesToOff: max(0, record.completedAt.timeIntervalSince(record.occurrence) / 60))
            }
            .sorted { $0.day < $1.day }
    }

    static func summary(of samples: [WakeSample], _ measure: WakeMeasure) -> WakeSummary? {
        let values = samples.map { $0.value(measure) }
        return measure.isTimeOfDay ? summary(ofTimes: values) : summary(ofDurations: values)
    }

    /// Times of day: they average and sort correctly across midnight.
    static func summary(ofTimes minutes: [Double]) -> WakeSummary? {
        guard var summary = summary(ofDurations: unwrapped(minutes)) else { return nil }
        summary.average = normalized(summary.average)
        summary.p10 = normalized(summary.p10)
        summary.p50 = normalized(summary.p50)
        summary.p90 = normalized(summary.p90)
        return summary
    }

    /// Plain numbers.
    static func summary(ofDurations values: [Double]) -> WakeSummary? {
        guard !values.isEmpty else { return nil }
        let sorted = values.sorted()
        return WakeSummary(
            average: values.reduce(0, +) / Double(values.count),
            p10: percentile(0.1, ofSorted: sorted),
            p50: percentile(0.5, ofSorted: sorted),
            p90: percentile(0.9, ofSorted: sorted),
            count: values.count)
    }

    static func summaryByWeekday(_ samples: [WakeSample], _ measure: WakeMeasure) -> [Int: WakeSummary] {
        Dictionary(grouping: samples, by: \.weekday).compactMapValues { summary(of: $0, measure) }
    }

    /// The value below which a `fraction` of the values fall, interpolating between
    /// the two nearest values (the usual definition, as in spreadsheets).
    static func percentile(_ fraction: Double, ofSorted values: [Double]) -> Double {
        guard !values.isEmpty else { return 0 }
        let position = fraction * Double(values.count - 1)
        let lower = Int(position.rounded(.down))
        let upper = min(lower + 1, values.count - 1)
        return values[lower] + (values[upper] - values[lower]) * (position - Double(lower))
    }

    /// The evolution of one measure. Each line gets at most about 60 points: short
    /// periods show every wake-up, longer ones weekly or monthly averages.
    static func trend(of samples: [WakeSample], _ measure: WakeMeasure, grouping: StatsGrouping, calendar: Calendar) -> WakeTrend {
        guard let first = samples.map(\.day).min(), let last = samples.map(\.day).max() else {
            return WakeTrend(resolution: .day, points: [], average: nil)
        }
        let span = calendar.dateComponents([.day], from: first, to: last).day ?? 0
        let resolution: WakeTrend.Resolution = span <= 62 ? .day : span <= 62 * 7 ? .week : .month

        // One continuous scale for every point, so the lines don't jump at midnight.
        let values = samples.map { $0.value(measure) }
        let minutes = measure.isTimeOfDay ? unwrapped(values) : values
        var buckets: [BucketKey: [Double]] = [:]
        for (sample, minute) in zip(samples, minutes) {
            let key = BucketKey(
                date: bucketStart(of: sample.day, resolution: resolution, calendar: calendar),
                weekday: grouping == .byWeekday ? sample.weekday : nil)
            buckets[key, default: []].append(minute)
        }
        let points = buckets
            .map { key, minutes in
                WakePoint(date: key.date, minute: minutes.reduce(0, +) / Double(minutes.count), weekday: key.weekday, count: minutes.count)
            }
            .sorted { ($0.date, $0.weekday ?? 0) < ($1.date, $1.weekday ?? 0) }
        return WakeTrend(resolution: resolution, points: points, average: minutes.reduce(0, +) / Double(minutes.count))
    }

    /// A y-axis range in whole steps with some room above and below the values:
    /// 15, 30, 60 or 120 minutes for times of day, and from 1 minute up for
    /// durations, which never go below 0.
    static func axis(for minutes: [Double], _ measure: WakeMeasure) -> (lower: Double, upper: Double, step: Double) {
        guard let low = minutes.min(), let high = minutes.max() else { return (0, 60, 15) }
        let range = high - low
        let step: Double
        if measure.isTimeOfDay {
            step = range <= 60 ? 15 : range <= 180 ? 30 : range <= 480 ? 60 : 120
        } else {
            step = [1, 2, 5, 10, 15, 30, 60].first { range <= 4 * $0 } ?? (range / 4 / 60).rounded(.up) * 60
        }
        var lower = ((low - step / 3) / step).rounded(.down) * step
        if !measure.isTimeOfDay {
            lower = max(0, lower)
        }
        let upper = ((high + step / 3) / step).rounded(.up) * step
        return (lower, upper, step)
    }

    // MARK: - Clock arithmetic

    /// Minutes after midnight, with the seconds as a fraction.
    static func minuteOfDay(_ date: Date, calendar: Calendar) -> Double {
        let time = calendar.dateComponents([.hour, .minute, .second], from: date)
        return Double((time.hour ?? 0) * 60 + (time.minute ?? 0)) + Double(time.second ?? 0) / 60
    }

    /// Clock times can't be averaged as plain numbers: 23:50 and 0:10 must give 0:00,
    /// not noon. Every time is moved to within twelve hours of the circular mean, and
    /// for times that are close together the result is the plain average.
    static func unwrapped(_ minutes: [Double]) -> [Double] {
        guard !minutes.isEmpty else { return [] }
        var x = 0.0
        var y = 0.0
        for minute in minutes {
            let angle = minute / minutesPerDay * 2 * .pi
            x += cos(angle)
            y += sin(angle)
        }
        let center = normalized(atan2(y, x) / (2 * .pi) * minutesPerDay)
        return minutes.map { center + wrapped($0 - center) }
    }

    /// Into 0..<1440.
    static func normalized(_ minute: Double) -> Double {
        let value = minute.truncatingRemainder(dividingBy: minutesPerDay)
        return value < 0 ? value + minutesPerDay : value
    }

    /// Into -720..<720.
    private static func wrapped(_ delta: Double) -> Double {
        normalized(delta + minutesPerDay / 2) - minutesPerDay / 2
    }

    private struct BucketKey: Hashable {
        var date: Date
        var weekday: Int?
    }

    private static func bucketStart(of day: Date, resolution: WakeTrend.Resolution, calendar: Calendar) -> Date {
        switch resolution {
        case .day: return day
        case .week: return calendar.dateInterval(of: .weekOfYear, for: day)?.start ?? day
        case .month: return calendar.dateInterval(of: .month, for: day)?.start ?? day
        }
    }
}
