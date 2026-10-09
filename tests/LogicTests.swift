import Foundation

/// Plain executable instead of XCTest so it runs with nothing but swiftc:
///     make test
@main
struct LogicTests {
    static var checks = 0
    static var failures = 0

    static func main() {
        testSoundRotation()
        testProblems()
        testChallengeClock()
        testOccurrences()
        testSessions()
        testHistory()
        testStatistics()
        print("\(checks) checks, \(failures) failures")
        exit(failures == 0 ? 0 : 1)
    }

    static func expect(_ condition: @autoclosure () -> Bool, _ message: @autoclosure () -> String, line: Int = #line) {
        checks += 1
        if !condition() {
            failures += 1
            print("FAIL (line \(line)): \(message())")
        }
    }

    static let mexico = TimeZone(identifier: "America/Mexico_City")!

    static var calendar: Calendar {
        var calendar = Calendar(identifier: .gregorian)
        calendar.timeZone = mexico
        return calendar
    }

    static func date(_ text: String) -> Date {
        let formatter = DateFormatter()
        formatter.locale = Locale(identifier: "en_US_POSIX")
        formatter.timeZone = mexico
        formatter.dateFormat = "yyyy-MM-dd'T'HH:mm:ss"
        return formatter.date(from: text)!
    }

    static func testSoundRotation() {
        for count in [1, 2, 3, 4, 7, 30] {
            var previous: Int?
            var cycles: [Int: Set<Int>] = [:]
            for day in -400...1200 {
                let index = SoundRotation.index(forDay: day, count: count)
                expect((0..<count).contains(index), "index \(index) out of range for \(count) sounds")
                if count > 1, let previous {
                    expect(index != previous, "same sound two days in a row (\(count) sounds, day \(day))")
                }
                previous = index
                let cycle = Int((Double(day) / Double(count)).rounded(.down))
                cycles[cycle, default: []].insert(index)
            }
            let complete = cycles.filter { cycle, _ in cycle * count >= -400 && (cycle + 1) * count - 1 <= 1200 }
            for (cycle, indices) in complete {
                expect(indices.count == count, "cycle \(cycle) does not play every one of the \(count) sounds")
            }
        }
        expect(SoundRotation.index(forDay: 321, count: 30) == SoundRotation.index(forDay: 321, count: 30), "rotation is deterministic")

        let night = date("2026-10-09T23:59:00")
        let morning = date("2026-10-10T07:00:00")
        expect(SoundRotation.dayNumber(for: morning, timeZone: mexico) - SoundRotation.dayNumber(for: night, timeZone: mexico) == 1,
               "the day changes at local midnight")
    }

    static func evaluate(_ prompt: String) -> Int? {
        if prompt.hasSuffix(", ?") {
            let terms = prompt.dropLast(3).split(separator: ",").compactMap { Int($0.trimmingCharacters(in: .whitespaces)) }
            guard terms.count >= 3 else { return nil }
            let step = terms[1] - terms[0]
            guard zip(terms, terms.dropFirst()).allSatisfy({ $1 - $0 == step }) else { return nil }
            return terms[terms.count - 1] + step
        }
        guard prompt.hasSuffix(" = ?") else { return nil }
        let tokens = prompt.dropLast(4).split(separator: " ").map(String.init)
        guard let first = Int(tokens[0]) else { return nil }
        var terms = [first]
        var operators: [String] = []
        var index = 1
        while index + 1 < tokens.count {
            guard let value = Int(tokens[index + 1]) else { return nil }
            if tokens[index] == "×" {
                terms[terms.count - 1] *= value
            } else {
                operators.append(tokens[index])
                terms.append(value)
            }
            index += 2
        }
        var result = terms[0]
        for (op, value) in zip(operators, terms.dropFirst()) {
            switch op {
            case "+": result += value
            case "−": result -= value
            default: return nil
            }
        }
        return result
    }

    /// Every number shown in the prompt (not the answer).
    static func operands(_ prompt: String) -> [Int] {
        prompt.split(whereSeparator: { !$0.isNumber }).compactMap { Int($0) }
    }

    static func testProblems() {
        var rng = SeededRandom(seed: 42)
        for difficulty in ChallengeDifficulty.allCases {
            let digits = difficulty.rawValue
            for level in 0...4 {
                for _ in 0..<3000 {
                    let problem = ProblemFactory.make(level: level, difficulty: difficulty, using: &rng)
                    let numbers = operands(problem.prompt)
                    expect(evaluate(problem.prompt) == problem.answer, "wrong answer for \"\(problem.prompt)\": \(problem.answer)")
                    expect(problem.answer >= 0 && problem.answer <= 9999, "answer does not fit the keypad: \(problem.prompt)")
                    expect(numbers.allSatisfy { $0 > 0 && String($0).count <= digits }, "\(difficulty) has a longer number: \(problem.prompt)")
                    expect(numbers.contains { String($0).count == digits }, "\(difficulty) has no \(digits)-digit number: \(problem.prompt)")
                }
            }
        }
    }

    static func testChallengeClock() {
        let start = Date(timeIntervalSinceReferenceDate: 800_000_000)
        var state = ChallengeState(now: start, seed: 7)
        state.tick(now: start.addingTimeInterval(20))
        expect(state.progress == 0, "the clock waits for the first correct answer")
        expect(state.idleTime(at: start.addingTimeInterval(20)) == 20, "idle time counts from the start")

        var now = start.addingTimeInterval(20)
        expect(state.submit(String(state.problem.answer), now: now) == .correct, "correct answer accepted")
        state.tick(now: now.addingTimeInterval(10))
        expect(abs(state.progress - 10) < 0.001, "the clock runs after a correct answer")
        expect(state.isRunning(at: now.addingTimeInterval(10)), "running inside the grace period")
        state.tick(now: now.addingTimeInterval(40))
        expect(abs(state.progress - 15) < 0.001, "the clock pauses after the grace period")
        expect(!state.isRunning(at: now.addingTimeInterval(40)), "paused after the grace period")

        now = now.addingTimeInterval(40)
        expect(state.submit(String(state.problem.answer + 1), now: now) == .wrong, "wrong answer rejected")
        expect(abs(state.progress - 10) < 0.001, "a mistake costs 5 seconds")
        expect(state.submit("", now: now) == .invalid, "empty input ignored")
        state.skip(now: now)
        expect(abs(state.progress - 5) < 0.001, "skipping costs 5 seconds")

        var answers = 0
        while !state.isComplete && answers < 100 {
            _ = state.submit(String(state.problem.answer), now: now)
            now = now.addingTimeInterval(5)
            state.tick(now: now)
            answers += 1
        }
        expect(state.isComplete, "the challenge can be completed")
        expect(answers == 11, "answering every 5 s takes the expected time (took \(answers) answers)")
        expect(state.progress == state.rules.requiredSeconds, "progress is capped")
        expect(state.submit("1", now: now) == .finished, "no answers after finishing")

        state.restart(now: now)
        expect(state.progress == 0 && !state.isComplete && state.lastCorrectAt == nil, "restart starts over")

        for difficulty in ChallengeDifficulty.allCases {
            var hard = ChallengeState(rules: ChallengeRules(difficulty: difficulty), now: start, seed: 9)
            var problems = Set<String>()
            for step in 0..<40 {
                problems.insert(hard.problem.prompt)
                expect(operands(hard.problem.prompt).allSatisfy { String($0).count <= difficulty.rawValue },
                       "the challenge uses the chosen difficulty: \(hard.problem.prompt)")
                _ = hard.submit(String(hard.problem.answer), now: start.addingTimeInterval(Double(step)))
            }
            expect(problems.count > 20, "\(difficulty) problems vary")
        }
        expect(ChallengeRules(difficulty: .threeDigits).graceSeconds > ChallengeRules().graceSeconds,
               "three-digit operations get more time per answer")
    }

    static func testOccurrences() {
        let weekdaysOnly: Set<Int> = [2, 3, 4, 5, 6]
        expect(AlarmMath.nextOccurrence(weekdays: Set(1...7), hour: 7, minute: 0, after: date("2026-10-09T06:00:00"), calendar: calendar)
               == date("2026-10-09T07:00:00"), "same-day occurrence")
        expect(AlarmMath.nextOccurrence(weekdays: weekdaysOnly, hour: 7, minute: 0, after: date("2026-10-09T07:30:00"), calendar: calendar)
               == date("2026-10-12T07:00:00"), "skips the weekend")
        expect(AlarmMath.latestOccurrence(weekdays: weekdaysOnly, hour: 7, minute: 0, notAfter: date("2026-10-09T07:30:00"), calendar: calendar)
               == date("2026-10-09T07:00:00"), "latest occurrence is today")
        expect(AlarmMath.latestOccurrence(weekdays: [2], hour: 7, minute: 0, notAfter: date("2026-10-09T07:30:00"), calendar: calendar)
               == date("2026-10-05T07:00:00"), "latest Monday")
        expect(AlarmMath.latestOccurrence(weekdays: weekdaysOnly, hour: 7, minute: 0, notAfter: date("2026-10-09T07:00:00"), calendar: calendar)
               == date("2026-10-09T07:00:00"), "an occurrence at the exact time counts")
    }

    static func testSessions() {
        let alarm = date("2026-10-09T07:00:00")
        var state = VigiliaState()
        state.settings = AlarmSettings(isEnabled: true, hour: 7, minute: 0, weekdays: Set(1...7))
        state.armedSince = date("2026-10-08T22:00:00")

        expect(state.activeSession(at: alarm.addingTimeInterval(-60), calendar: calendar) == nil, "no session before the alarm")
        expect(state.activeSession(at: alarm.addingTimeInterval(30), calendar: calendar)?.occurrence == alarm, "session starts with the alarm")
        expect(state.activeSession(at: alarm.addingTimeInterval(64 * 60), calendar: calendar) != nil, "session lasts about an hour")
        expect(state.activeSession(at: alarm.addingTimeInterval(66 * 60), calendar: calendar) == nil, "session expires")

        state.retries = [RetryRecord(id: UUID(), occurrence: alarm, fireDate: alarm.addingTimeInterval(90 * 60))]
        expect(state.activeSession(at: alarm.addingTimeInterval(80 * 60), calendar: calendar)?.occurrence == alarm,
               "a pending re-ring keeps the session alive")
        state.markCompleted(alarm)
        expect(state.activeSession(at: alarm.addingTimeInterval(2 * 60), calendar: calendar) == nil, "completing the challenge ends the session")

        var fresh = VigiliaState()
        fresh.settings = state.settings
        fresh.armedSince = alarm.addingTimeInterval(10 * 60)
        expect(fresh.activeSession(at: alarm.addingTimeInterval(11 * 60), calendar: calendar) == nil,
               "setting the alarm after its time does not start a session")
        fresh.test = TestRecord(id: UUID(), occurrence: alarm.addingTimeInterval(20 * 60))
        expect(fresh.activeSession(at: alarm.addingTimeInterval(19 * 60), calendar: calendar) == nil, "test not started yet")
        expect(fresh.activeSession(at: alarm.addingTimeInterval(21 * 60), calendar: calendar)?.isTest == true, "test session")
        expect(fresh.activeSession(at: alarm.addingTimeInterval(31 * 60), calendar: calendar) == nil, "test session expires")

        state.settings.difficulty = .threeDigits
        let data = try! JSONEncoder().encode(state)
        expect(try! JSONDecoder().decode(VigiliaState.self, from: data) == state, "state survives a round trip")
        expect(try! JSONDecoder().decode(VigiliaState.self, from: Data("{}".utf8)) == VigiliaState(), "missing keys use defaults")

        let saved = Data(#"{"settings":{"isEnabled":true,"hour":6,"minute":30,"weekdays":[2,3]}}"#.utf8)
        let old = try? JSONDecoder().decode(VigiliaState.self, from: saved)
        expect(old?.settings == AlarmSettings(isEnabled: true, hour: 6, minute: 30, weekdays: [2, 3], difficulty: .twoDigits),
               "settings saved before the difficulty existed keep loading")
        let future = Data(#"{"settings":{"isEnabled":true,"hour":6,"minute":30,"weekdays":[2],"difficulty":9}}"#.utf8)
        expect((try? JSONDecoder().decode(VigiliaState.self, from: future))?.settings.isEnabled == true,
               "an unknown difficulty does not lose the alarm")
    }

    static func testHistory() {
        var state = VigiliaState()
        let start = date("2026-01-01T07:00:00")
        for day in 0..<(AlarmRules.historyLimit + 5) {
            let occurrence = start.addingTimeInterval(Double(day) * 86_400)
            state.recordWake(WakeRecord(occurrence: occurrence, completedAt: occurrence.addingTimeInterval(120),
                                        solved: 10, mistakes: 0, isTest: false))
            if day % 100 == 0 {
                state.recordWake(WakeRecord(occurrence: occurrence, completedAt: occurrence.addingTimeInterval(180),
                                            solved: 10, mistakes: 0, isTest: true))
            }
        }
        let wakes = state.history.filter { !$0.isTest }
        expect(wakes.count == AlarmRules.historyLimit, "keeps years of wake-ups for the statistics")
        expect(state.history.filter(\.isTest).count == AlarmRules.testHistoryLimit, "keeps only the latest tests")
        expect(wakes.first?.occurrence == start.addingTimeInterval(Double(AlarmRules.historyLimit + 4) * 86_400), "newest first")
        expect(zip(state.history, state.history.dropFirst()).allSatisfy { $0.completedAt >= $1.completedAt }, "history stays in order")
    }

    static func testStatistics() {
        func close(_ value: Double?, _ expected: Double) -> Bool {
            value.map { abs($0 - expected) < 0.01 } ?? false
        }

        expect(close(WakeStatistics.summary(of: [360, 360, 540])?.average, 420), "close times average as plain numbers")
        let midnight = WakeStatistics.summary(of: [1430, 10])?.average
        expect(close(midnight, 0) || close(midnight, 1440), "23:50 and 0:10 average to midnight, not noon")
        let late = WakeStatistics.summary(of: [1430, 10, 20])
        expect(close(late?.average, 20.0 / 3), "the average works across midnight")
        expect(close(late?.earliest, 1430) && close(late?.latest, 20), "earliest and latest work across midnight")
        expect(WakeStatistics.summary(of: []) == nil, "no wake-ups, no average")

        // 100 days of 7:00 alarms, ending on Friday 2026-10-09: turned off at 7:05 on
        // weekdays and at 8:30 on weekends. Plus a test, which never counts.
        let now = date("2026-10-09T12:00:00")
        var history: [WakeRecord] = []
        for back in 0..<100 {
            let occurrence = calendar.date(byAdding: .day, value: -back, to: date("2026-10-09T07:00:00"))!
            let weekend = [1, 7].contains(calendar.component(.weekday, from: occurrence))
            history.append(WakeRecord(occurrence: occurrence, completedAt: occurrence.addingTimeInterval(weekend ? 90 * 60 : 5 * 60),
                                      solved: 10, mistakes: 1, isTest: false))
        }
        history.append(WakeRecord(occurrence: date("2026-10-08T15:00:00"), completedAt: date("2026-10-08T15:02:00"),
                                  solved: 4, mistakes: 0, isTest: true))

        func samples(_ period: StatsPeriod) -> [WakeSample] {
            WakeStatistics.samples(from: history, period: period, now: now, calendar: calendar)
        }
        expect(samples(.week).count == 7, "a week counts 7 wake-ups (got \(samples(.week).count))")
        expect(samples(.month).count == 30, "a month counts 30 wake-ups (got \(samples(.month).count))")
        expect(samples(.year).count == 100 && samples(.always).count == 100, "a year and always count everything")
        expect(samples(.always).allSatisfy { $0.minuteOfDay == 425 || $0.minuteOfDay == 510 }, "the wake-up time is when the alarm was turned off")

        let week = WakeStatistics.summary(of: samples(.week).map(\.minuteOfDay))
        expect(close(week?.average, (5 * 425 + 2 * 510) / 7.0), "whole-week average")
        expect(week?.count == 7 && close(week?.earliest, 425) && close(week?.latest, 510), "whole-week spread")

        let byDay = WakeStatistics.summaryByWeekday(samples(.always))
        expect(byDay.count == 7, "every weekday has an average")
        expect((2...6).allSatisfy { close(byDay[$0]?.average, 425) }, "weekday average")
        expect(close(byDay[1]?.average, 510) && close(byDay[7]?.average, 510), "weekend average")
        expect(byDay.values.reduce(0) { $0 + $1.count } == 100, "every wake-up belongs to one weekday")

        let daily = WakeStatistics.trend(of: samples(.month), grouping: .wholeWeek, calendar: calendar)
        expect(daily.resolution == .day && daily.points.count == 30, "a month shows every wake-up")
        expect(zip(daily.points, daily.points.dropFirst()).allSatisfy { $0.date < $1.date }, "points are in order")

        let weekly = WakeStatistics.trend(of: samples(.always), grouping: .wholeWeek, calendar: calendar)
        expect(weekly.resolution == .week, "longer periods show weekly averages")
        expect(weekly.points.count >= 14 && weekly.points.count <= 16, "about one point per week (got \(weekly.points.count))")
        expect(weekly.points.reduce(0) { $0 + $1.count } == 100, "weekly points cover every wake-up")
        expect(weekly.points.allSatisfy { $0.weekday == nil && $0.minute >= 425 && $0.minute <= 510 }, "weekly averages")

        let perDay = WakeStatistics.trend(of: samples(.always), grouping: .byWeekday, calendar: calendar)
        expect(Set(perDay.points.compactMap(\.weekday)) == Set(1...7), "one line per weekday")
        expect(perDay.points.allSatisfy { point in
            close(point.minute, [1, 7].contains(point.weekday!) ? 510 : 425)
        }, "each weekday line keeps its own times")

        let years = (0..<500).map { back in
            WakeSample(day: calendar.date(byAdding: .day, value: -back, to: date("2026-10-09T00:00:00"))!, weekday: 1, minuteOfDay: 420)
        }
        let monthly = WakeStatistics.trend(of: years.reversed(), grouping: .wholeWeek, calendar: calendar)
        expect(monthly.resolution == .month && monthly.points.count == 18, "years show monthly averages (got \(monthly.points.count))")

        let night = [
            WakeSample(day: date("2026-10-01T00:00:00"), weekday: 5, minuteOfDay: 1430),
            WakeSample(day: date("2026-10-02T00:00:00"), weekday: 6, minuteOfDay: 10),
        ]
        let nightTrend = WakeStatistics.trend(of: night, grouping: .wholeWeek, calendar: calendar).points
        expect(nightTrend.count == 2 && abs(nightTrend[0].minute - nightTrend[1].minute) == 20, "the chart does not jump at midnight")
        let nightAverage = WakeStatistics.trend(of: night, grouping: .wholeWeek, calendar: calendar).average
        expect(close(nightAverage, 0) || close(nightAverage, 1440), "the chart's average sits between the points")
        expect(close(weekly.average, (byDay[1]!.average * 28 + 425 * 72) / 100), "the chart's average covers every wake-up")

        let axis = WakeStatistics.axis(for: [401, 472])
        expect(axis == (390, 510, 30), "axis in half hours around the data (got \(axis))")
        let single = WakeStatistics.axis(for: [420])
        expect(single == (405, 435, 15), "a single point still gets an axis (got \(single))")
    }
}
