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
        testEarlyDismissal()
        testStoredData()
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
        for count in [1, 2, 3, 4, 7, 30, 90] {
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

    /// 2026-10-09 is a Friday (weekday 6).
    static func testEarlyDismissal() {
        let alarm = date("2026-10-09T07:00:00")
        let monday = date("2026-10-12T07:00:00")
        let nextFriday = date("2026-10-16T07:00:00")
        var state = VigiliaState()
        state.settings = AlarmSettings(isEnabled: true, hour: 7, minute: 0, weekdays: [2, 3, 4, 5, 6])
        state.armedSince = date("2026-10-08T22:00:00")

        expect(state.earlyDismissibleOccurrence(at: date("2026-10-09T03:59:00"), calendar: calendar) == nil,
               "more than 3 hours before it can't be turned off")
        expect(state.earlyDismissibleOccurrence(at: date("2026-10-09T04:00:00"), calendar: calendar) == alarm,
               "exactly 3 hours before it can")
        expect(state.earlyDismissibleOccurrence(at: date("2026-10-09T06:59:00"), calendar: calendar) == alarm,
               "a minute before it can")
        expect(state.earlyDismissibleOccurrence(at: date("2026-10-09T06:59:50"), calendar: calendar) == nil,
               "not when it is about to ring")
        expect(state.earlyDismissibleOccurrence(at: date("2026-10-09T07:30:00"), calendar: calendar) == nil,
               "not while its challenge is pending")
        expect(state.mainAlarmPlans(after: date("2026-10-09T06:00:00"), calendar: calendar)[6]
               == MainAlarmPlan(weekday: 6, time: AlarmTime(hour: 7, minute: 0), fireDate: alarm),
               "a weekly alarm before turning it off")

        var disabled = state
        disabled.settings.isEnabled = false
        expect(disabled.earlyDismissibleOccurrence(at: date("2026-10-09T06:00:00"), calendar: calendar) == nil,
               "nothing to turn off when the alarm is off")
        expect(disabled.mainAlarmPlans(after: date("2026-10-09T06:00:00"), calendar: calendar).isEmpty, "no alarms when it is off")

        var pendingTest = state
        pendingTest.test = TestRecord(id: UUID(), occurrence: date("2026-10-09T05:58:00"))
        expect(pendingTest.earlyDismissibleOccurrence(at: date("2026-10-09T06:00:00"), calendar: calendar) == nil,
               "not while the test alarm waits for its challenge")

        // Challenge done at 6:00 for the 7:00 alarm.
        let before = date("2026-10-09T06:00:00")
        state.markCompleted(alarm)
        expect(state.nextOccurrence(after: before, calendar: calendar) == monday, "the next alarm is now Monday's")
        expect(state.dismissedOccurrence(after: before, calendar: calendar) == alarm, "today's alarm shows as turned off")
        expect(state.earlyDismissibleOccurrence(at: before, calendar: calendar) == nil, "Monday is too far away to turn off")
        let plans = state.mainAlarmPlans(after: before, calendar: calendar)
        expect(plans[6] == MainAlarmPlan(weekday: 6, time: AlarmTime(hour: 7, minute: 0), fireDate: nextFriday, skipped: alarm),
               "Fridays become a one-shot alarm next Friday")
        expect(plans[2]?.fireDate == monday && plans[2]?.isOneShot == false, "the other days stay weekly")
        expect(state.activeSession(at: alarm.addingTimeInterval(30), calendar: calendar) == nil, "it doesn't start a session")
        expect(state.activeSession(at: alarm.addingTimeInterval(30 * 60), calendar: calendar) == nil, "nor later")

        let after = date("2026-10-09T07:30:00")
        expect(state.mainAlarmPlans(after: after, calendar: calendar)[6]
               == MainAlarmPlan(weekday: 6, time: AlarmTime(hour: 7, minute: 0), fireDate: nextFriday),
               "once it has passed, Fridays are weekly again")
        expect(state.dismissedOccurrence(after: after, calendar: calendar) == nil, "nothing turned off ahead anymore")
        expect(state.activeSession(at: nextFriday.addingTimeInterval(30), calendar: calendar)?.occurrence == nextFriday,
               "next Friday rings as usual")
        expect(state.activeSession(at: monday.addingTimeInterval(30), calendar: calendar)?.occurrence == monday,
               "Monday rings as usual")

        var changed = state
        expect(changed.changeSettings(at: before, isAlerting: false, calendar: calendar) { $0.minute = 5 },
               "the time can still change after turning it off")
        expect(changed.nextOccurrence(after: before, calendar: calendar) == date("2026-10-09T07:05:00"),
               "a new time rings: only the 7:00 alarm was turned off")

        var perDay = VigiliaState()
        perDay.settings = AlarmSettings(isEnabled: true, hour: 7, minute: 0, weekdays: [6, 7], sameTimeEveryDay: false,
                                        dayTimes: [6: AlarmTime(hour: 23, minute: 30), 7: AlarmTime(hour: 0, minute: 30)])
        perDay.markCompleted(date("2026-10-09T23:30:00"))
        expect(perDay.earlyDismissibleOccurrence(at: date("2026-10-09T23:00:00"), calendar: calendar) == date("2026-10-10T00:30:00"),
               "the alarm after the one turned off can be turned off too when it is close")

        let old = Data(#"{"mains":[{"id":"6F9619FF-8B86-D011-B42D-00C04FC964FF","weekday":2,"hour":7,"minute":0,"nextFire":0}]}"#.utf8)
        let decoded = try? JSONDecoder().decode(VigiliaState.self, from: old)
        expect(decoded?.mains.first?.isOneShot == nil && decoded?.mains.count == 1, "alarms saved before one-shots keep loading")
        state.mains = [MainAlarmRecord(id: UUID(), weekday: 6, hour: 7, minute: 0, sound: nil, nextFire: nextFriday, isOneShot: true)]
        expect(try! JSONDecoder().decode(VigiliaState.self, from: JSONEncoder().encode(state)) == state, "one-shot alarms survive a round trip")
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

        expect(close(WakeStatistics.summary(ofTimes: [360, 360, 540])?.average, 420), "close times average as plain numbers")
        let midnight = WakeStatistics.summary(ofTimes: [1430, 10])?.average
        expect(close(midnight, 0) || close(midnight, 1440), "23:50 and 0:10 average to midnight, not noon")
        let late = WakeStatistics.summary(ofTimes: [1430, 10, 20])
        expect(close(late?.average, 20.0 / 3), "the average works across midnight")
        // In order: 23:50, 0:10, 0:20.
        expect(close(late?.p10, 1434) && close(late?.p50, 10) && close(late?.p90, 18),
               "percentiles work across midnight (got \(String(describing: late)))")
        expect(WakeStatistics.summary(ofTimes: []) == nil && WakeStatistics.summary(ofDurations: []) == nil, "no wake-ups, no average")

        let durations = WakeStatistics.summary(ofDurations: [7, 3, 10, 1, 5, 9, 2, 8, 4, 6])
        expect(close(durations?.average, 5.5) && durations?.count == 10, "durations average as plain numbers")
        expect(close(durations?.p10, 1.9) && close(durations?.p50, 5.5) && close(durations?.p90, 9.1),
               "percentiles interpolate between the nearest values (got \(String(describing: durations)))")
        let lone = WakeStatistics.summary(ofDurations: [3])
        expect(lone == WakeSummary(average: 3, p10: 3, p50: 3, p90: 3, count: 1), "a single value is every percentile")
        expect(close(WakeStatistics.summary(ofDurations: [10, 800])?.average, 405), "durations never wrap around midnight")

        // 100 days ending on Friday 2026-10-09: on weekdays the alarm rings at 7:00 and
        // is turned off at 7:05; on weekends it rings at 8:00 and is turned off at 8:30.
        // Plus a test, which never counts.
        let now = date("2026-10-09T12:00:00")
        var history: [WakeRecord] = []
        for back in 0..<100 {
            let day = calendar.date(byAdding: .day, value: -back, to: date("2026-10-09T07:00:00"))!
            let weekend = [1, 7].contains(calendar.component(.weekday, from: day))
            let occurrence = weekend ? day.addingTimeInterval(3600) : day
            history.append(WakeRecord(occurrence: occurrence, completedAt: occurrence.addingTimeInterval(weekend ? 30 * 60 : 5 * 60),
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
        expect(samples(.always).allSatisfy { sample in
            [1, 7].contains(sample.weekday)
                ? sample.alarmMinute == 480 && sample.offMinute == 510 && close(sample.minutesToOff, 30)
                : sample.alarmMinute == 420 && sample.offMinute == 425 && close(sample.minutesToOff, 5)
        }, "each wake-up keeps when the alarm rang, when it was turned off and how long that took")

        let week = samples(.week)
        let alarmWeek = WakeStatistics.summary(of: week, .alarmTime)
        expect(close(alarmWeek?.average, (5 * 420 + 2 * 480) / 7.0) && alarmWeek?.count == 7, "whole-week alarm time")
        let offWeek = WakeStatistics.summary(of: week, .offTime)
        expect(close(offWeek?.average, (5 * 425 + 2 * 510) / 7.0), "whole-week time turned off")
        expect(close(offWeek?.p10, 425) && close(offWeek?.p50, 425) && close(offWeek?.p90, 510), "whole-week percentiles")
        let delayWeek = WakeStatistics.summary(of: week, .timeToOff)
        expect(close(delayWeek?.average, (5 * 5 + 2 * 30) / 7.0) && close(delayWeek?.p50, 5) && close(delayWeek?.p90, 30),
               "whole-week time to turn it off")

        let byDay = WakeStatistics.summaryByWeekday(samples(.always), .offTime)
        expect(byDay.count == 7, "every weekday has an average")
        expect((2...6).allSatisfy { close(byDay[$0]?.average, 425) }, "weekday average")
        expect(close(byDay[1]?.average, 510) && close(byDay[7]?.average, 510), "weekend average")
        expect(byDay.values.reduce(0) { $0 + $1.count } == 100, "every wake-up belongs to one weekday")
        let delayByDay = WakeStatistics.summaryByWeekday(samples(.always), .timeToOff)
        expect((2...6).allSatisfy { close(delayByDay[$0]?.p90, 5) } && close(delayByDay[1]?.p10, 30), "weekday percentiles")
        let alarmByDay = WakeStatistics.summaryByWeekday(samples(.always), .alarmTime)
        expect(close(alarmByDay[2]?.average, 420) && close(alarmByDay[7]?.average, 480), "weekday alarm times")

        // Past midnight: the alarm rang at 23:55 and was turned off at 0:05.
        let lateNight = WakeStatistics.samples(
            from: [WakeRecord(occurrence: date("2026-10-08T23:55:00"), completedAt: date("2026-10-09T00:05:00"),
                              solved: 10, mistakes: 0, isTest: false),
                   // Turned off a few seconds before the scheduled time.
                   WakeRecord(occurrence: date("2026-10-07T07:00:00"), completedAt: date("2026-10-07T06:59:50"),
                              solved: 10, mistakes: 0, isTest: false)],
            period: .always, now: now, calendar: calendar)
        expect(lateNight.count == 2 && lateNight[1].alarmMinute == 1435 && lateNight[1].offMinute == 5
               && close(lateNight[1].minutesToOff, 10), "a wake-up past midnight")
        expect(lateNight.first?.minutesToOff == 0, "the time to turn it off is never negative")

        for measure in WakeMeasure.allCases {
            let daily = WakeStatistics.trend(of: samples(.month), measure, grouping: .wholeWeek, calendar: calendar)
            expect(daily.resolution == .day && daily.points.count == 30, "a month shows every wake-up (\(measure))")
            expect(zip(daily.points, daily.points.dropFirst()).allSatisfy { $0.date < $1.date }, "points are in order (\(measure))")
        }
        let alarmPoints = WakeStatistics.trend(of: samples(.always), .alarmTime, grouping: .byWeekday, calendar: calendar).points
        let delayPoints = WakeStatistics.trend(of: samples(.always), .timeToOff, grouping: .byWeekday, calendar: calendar).points
        expect(alarmPoints.map(\.id) == delayPoints.map(\.id), "every chart has the same points")
        expect(delayPoints.allSatisfy { close($0.minute, [1, 7].contains($0.weekday!) ? 30 : 5) }, "the time to turn it off on the chart")

        let weekly = WakeStatistics.trend(of: samples(.always), .offTime, grouping: .wholeWeek, calendar: calendar)
        expect(weekly.resolution == .week, "longer periods show weekly averages")
        expect(weekly.points.count >= 14 && weekly.points.count <= 16, "about one point per week (got \(weekly.points.count))")
        expect(weekly.points.reduce(0) { $0 + $1.count } == 100, "weekly points cover every wake-up")
        expect(weekly.points.allSatisfy { $0.weekday == nil && $0.minute >= 425 && $0.minute <= 510 }, "weekly averages")

        let perDay = WakeStatistics.trend(of: samples(.always), .offTime, grouping: .byWeekday, calendar: calendar)
        expect(Set(perDay.points.compactMap(\.weekday)) == Set(1...7), "one line per weekday")
        expect(perDay.points.allSatisfy { point in
            close(point.minute, [1, 7].contains(point.weekday!) ? 510 : 425)
        }, "each weekday line keeps its own times")

        func sample(_ day: Date, weekday: Int, off: Double, delay: Double = 5) -> WakeSample {
            WakeSample(day: day, weekday: weekday, alarmMinute: WakeStatistics.normalized(off - delay), offMinute: off, minutesToOff: delay)
        }
        let years = (0..<500).map { back in
            sample(calendar.date(byAdding: .day, value: -back, to: date("2026-10-09T00:00:00"))!, weekday: 1, off: 420)
        }
        let monthly = WakeStatistics.trend(of: years.reversed(), .offTime, grouping: .wholeWeek, calendar: calendar)
        expect(monthly.resolution == .month && monthly.points.count == 18, "years show monthly averages (got \(monthly.points.count))")

        let night = [
            sample(date("2026-10-01T00:00:00"), weekday: 5, off: 1430, delay: 10),
            sample(date("2026-10-02T00:00:00"), weekday: 6, off: 10, delay: 800),
        ]
        let nightTrend = WakeStatistics.trend(of: night, .offTime, grouping: .wholeWeek, calendar: calendar).points
        expect(nightTrend.count == 2 && abs(nightTrend[0].minute - nightTrend[1].minute) == 20, "the chart does not jump at midnight")
        let nightAverage = WakeStatistics.trend(of: night, .offTime, grouping: .wholeWeek, calendar: calendar).average
        expect(close(nightAverage, 0) || close(nightAverage, 1440), "the chart's average sits between the points")
        let nightDelay = WakeStatistics.trend(of: night, .timeToOff, grouping: .wholeWeek, calendar: calendar)
        expect(nightDelay.points.map(\.minute) == [10, 800] && close(nightDelay.average, 405), "durations on the chart are plain numbers")
        expect(close(weekly.average, (byDay[1]!.average * 28 + 425 * 72) / 100), "the chart's average covers every wake-up")

        let axis = WakeStatistics.axis(for: [401, 472], .offTime)
        expect(axis == (390, 510, 30), "axis in half hours around the data (got \(axis))")
        let single = WakeStatistics.axis(for: [420], .alarmTime)
        expect(single == (405, 435, 15), "a single point still gets an axis (got \(single))")
        let quick = WakeStatistics.axis(for: [2.5, 9], .timeToOff)
        expect(quick == (0, 10, 2), "durations get minute steps (got \(quick))")
        let instant = WakeStatistics.axis(for: [0.2], .timeToOff)
        expect(instant == (0, 1, 1), "durations never go below zero (got \(instant))")
    }
}
