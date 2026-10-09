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

        let data = try! JSONEncoder().encode(state)
        expect(try! JSONDecoder().decode(VigiliaState.self, from: data) == state, "state survives a round trip")
        expect(try! JSONDecoder().decode(VigiliaState.self, from: Data("{}".utf8)) == VigiliaState(), "missing keys use defaults")
    }
}
