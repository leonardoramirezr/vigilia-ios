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
        testDaySchedules()
        testSessions()
        testSettingsWhileRinging()
        testStoredData()
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

    static func testProblems() {
        var rng = SeededRandom(seed: 42)
        for level in 0...4 {
            for _ in 0..<3000 {
                let problem = ProblemFactory.make(level: level, using: &rng)
                expect(evaluate(problem.prompt) == problem.answer, "wrong answer for \"\(problem.prompt)\": \(problem.answer)")
                expect(problem.answer >= 0 && problem.answer < 1000, "answer out of range: \(problem.prompt)")
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
    }

    static func schedule(_ weekdays: Set<Int>, _ hour: Int, _ minute: Int) -> [Int: AlarmTime] {
        Dictionary(uniqueKeysWithValues: weekdays.map { ($0, AlarmTime(hour: hour, minute: minute)) })
    }

    static func testOccurrences() {
        let weekdaysOnly: Set<Int> = [2, 3, 4, 5, 6]
        expect(AlarmMath.nextOccurrence(schedule: schedule(Set(1...7), 7, 0), after: date("2026-10-09T06:00:00"), calendar: calendar)
               == date("2026-10-09T07:00:00"), "same-day occurrence")
        expect(AlarmMath.nextOccurrence(schedule: schedule(weekdaysOnly, 7, 0), after: date("2026-10-09T07:30:00"), calendar: calendar)
               == date("2026-10-12T07:00:00"), "skips the weekend")
        expect(AlarmMath.latestOccurrence(schedule: schedule(weekdaysOnly, 7, 0), notAfter: date("2026-10-09T07:30:00"), calendar: calendar)
               == date("2026-10-09T07:00:00"), "latest occurrence is today")
        expect(AlarmMath.latestOccurrence(schedule: schedule([2], 7, 0), notAfter: date("2026-10-09T07:30:00"), calendar: calendar)
               == date("2026-10-05T07:00:00"), "latest Monday")
        expect(AlarmMath.latestOccurrence(schedule: schedule(weekdaysOnly, 7, 0), notAfter: date("2026-10-09T07:00:00"), calendar: calendar)
               == date("2026-10-09T07:00:00"), "an occurrence at the exact time counts")
        expect(AlarmMath.nextOccurrence(schedule: [:], after: date("2026-10-09T06:00:00"), calendar: calendar) == nil,
               "no days, no occurrence")
    }

    /// 2026-10-09 is a Friday (weekday 6).
    static func testDaySchedules() {
        var settings = AlarmSettings(isEnabled: true, hour: 7, minute: 0, weekdays: Set(1...7))
        settings.dayTimes = [6: AlarmTime(hour: 5, minute: 45), 7: AlarmTime(hour: 9, minute: 30)]
        expect(settings.schedule == schedule(Set(1...7), 7, 0), "the same time every day ignores the per-day times")

        settings.sameTimeEveryDay = false
        expect(settings.time(on: 6) == AlarmTime(hour: 5, minute: 45), "Friday uses its own time")
        expect(settings.time(on: 7) == AlarmTime(hour: 9, minute: 30), "Saturday uses its own time")
        expect(settings.time(on: 2) == AlarmTime(hour: 7, minute: 0), "a day without its own time uses the shared one")
        settings.weekdays = [2, 6, 7]
        expect(Set(settings.schedule.keys) == [2, 6, 7], "only the selected days ring")

        let times = settings.schedule
        expect(AlarmMath.nextOccurrence(schedule: times, after: date("2026-10-09T05:00:00"), calendar: calendar)
               == date("2026-10-09T05:45:00"), "Friday rings at its own time")
        expect(AlarmMath.nextOccurrence(schedule: times, after: date("2026-10-09T06:00:00"), calendar: calendar)
               == date("2026-10-10T09:30:00"), "then Saturday at its own time")
        expect(AlarmMath.nextOccurrence(schedule: times, after: date("2026-10-10T10:00:00"), calendar: calendar)
               == date("2026-10-12T07:00:00"), "then Monday at the shared time")
        expect(AlarmMath.latestOccurrence(schedule: times, notAfter: date("2026-10-10T08:00:00"), calendar: calendar)
               == date("2026-10-09T05:45:00"), "before Saturday's alarm the latest one is Friday's")

        var state = VigiliaState()
        state.settings = settings
        state.armedSince = date("2026-10-08T22:00:00")
        expect(state.activeSession(at: date("2026-10-09T05:46:00"), calendar: calendar)?.occurrence == date("2026-10-09T05:45:00"),
               "a per-day time starts a session")
        expect(state.activeSession(at: date("2026-10-09T07:01:00"), calendar: calendar) == nil,
               "the shared time does not ring on a day with its own time")
        expect(state.activeSession(at: date("2026-10-10T07:01:00"), calendar: calendar) == nil,
               "nothing rings on Saturday before its own time")
    }

    static func testSettingsWhileRinging() {
        let alarm = date("2026-10-09T07:00:00")
        var state = VigiliaState()
        state.settings = AlarmSettings(isEnabled: true, hour: 7, minute: 0, weekdays: Set(1...7))
        state.armedSince = date("2026-10-08T22:00:00")
        let ringing = alarm.addingTimeInterval(30 * 60)

        // Why changes are ignored: applied blindly, a new time restarts `armedSince` and,
        // with no re-ring pending, the session (and the alarm) ends without the challenge.
        var blind = state
        blind.settings.hour = 8
        blind.armedSince = ringing
        expect(blind.activeSession(at: ringing, calendar: calendar) == nil, "a blind change would end the session")

        var guarded = state
        expect(!guarded.changeSettings(at: ringing, isAlerting: false, calendar: calendar) { $0.hour = 8 },
               "a new time is ignored while the challenge is pending")
        expect(!guarded.changeSettings(at: ringing, isAlerting: false, calendar: calendar) { $0.isEnabled = false },
               "the alarm cannot be turned off while it rings")
        expect(!guarded.changeSettings(at: ringing, isAlerting: false, calendar: calendar) { $0.weekdays = [1] },
               "days cannot change while it rings")
        expect(!guarded.changeSettings(at: ringing, isAlerting: false, calendar: calendar) {
                   $0.sameTimeEveryDay = false
                   $0.dayTimes[6] = AlarmTime(hour: 9, minute: 0)
               }, "per-day times cannot change while it rings")
        expect(guarded == state, "ignored changes leave the state untouched")
        expect(guarded.activeSession(at: ringing, calendar: calendar)?.occurrence == alarm, "the session goes on")
        expect(!guarded.changeSettings(at: alarm.addingTimeInterval(-10), isAlerting: false, calendar: calendar) { $0.hour = 8 },
               "ignored a few seconds before it rings, too")
        expect(!guarded.changeSettings(at: alarm.addingTimeInterval(-3600), isAlerting: true, calendar: calendar) { $0.hour = 8 },
               "ignored while AlarmKit reports an alarm going off")

        guarded.markCompleted(alarm)
        expect(guarded.changeSettings(at: ringing, isAlerting: false, calendar: calendar) { $0.hour = 8 },
               "allowed once the challenge is done")
        expect(guarded.settings.hour == 8 && guarded.armedSince == ringing, "the change is applied and re-arms")
        expect(!guarded.changeSettings(at: ringing, isAlerting: false, calendar: calendar) { $0.hour = 8 }, "no-op changes report false")
        expect(!guarded.changeSettings(at: ringing, isAlerting: false, calendar: calendar) { $0.weekdays = [] }, "at least one day stays selected")

        var test = VigiliaState()
        test.test = TestRecord(id: UUID(), occurrence: alarm)
        expect(!test.changeSettings(at: alarm.addingTimeInterval(60), isAlerting: false, calendar: calendar) { $0.isEnabled = true },
               "settings wait for the test alarm's challenge too")
        expect(test.changeSettings(at: alarm.addingTimeInterval(-120), isAlerting: false, calendar: calendar) { $0.isEnabled = true },
               "allowed before the test rings")
    }

    static func testStoredData() {
        // Saved by the version that only had one time for every day.
        let legacy = Data(#"{"settings":{"isEnabled":true,"hour":6,"minute":15,"weekdays":[2,3,4,5,6]},"armedSince":700000000}"#.utf8)
        let decoded = try? JSONDecoder().decode(VigiliaState.self, from: legacy)
        expect(decoded != nil, "data from the previous version still loads")
        if let settings = decoded?.settings {
            expect(settings.isEnabled && settings.hour == 6 && settings.minute == 15 && settings.weekdays == [2, 3, 4, 5, 6],
                   "previous settings are kept")
            expect(settings.sameTimeEveryDay && settings.dayTimes.isEmpty, "previous settings keep one time for every day")
        }

        var state = VigiliaState()
        state.settings.sameTimeEveryDay = false
        state.settings.dayTimes = [1: AlarmTime(hour: 10, minute: 0), 6: AlarmTime(hour: 5, minute: 45)]
        let data = try! JSONEncoder().encode(state)
        expect(try! JSONDecoder().decode(VigiliaState.self, from: data) == state, "per-day times survive a round trip")
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

        let data = try! JSONEncoder().encode(state)
        expect(try! JSONDecoder().decode(VigiliaState.self, from: data) == state, "state survives a round trip")
        expect(try! JSONDecoder().decode(VigiliaState.self, from: Data("{}".utf8)) == VigiliaState(), "missing keys use defaults")
    }
}
