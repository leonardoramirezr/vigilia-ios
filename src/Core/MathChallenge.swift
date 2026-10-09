import Foundation

struct MathProblem: Equatable {
    let prompt: String
    let answer: Int
}

enum ProblemFactory {
    /// Levels 0…4. Higher levels mix more operations and bigger numbers.
    /// Every answer is a non-negative integer so a plain numeric keypad is enough.
    static func make<R: RandomNumberGenerator>(level: Int, using rng: inout R) -> MathProblem {
        switch max(0, min(4, level)) {
        case 0:
            let a = Int.random(in: 13...68, using: &rng)
            let b = Int.random(in: 14...49, using: &rng)
            return MathProblem(prompt: "\(a) + \(b) = ?", answer: a + b)
        case 1:
            let a = Int.random(in: 42...99, using: &rng)
            let b = Int.random(in: 13...(a - 11), using: &rng)
            return MathProblem(prompt: "\(a) − \(b) = ?", answer: a - b)
        case 2:
            let a = Int.random(in: 3...9, using: &rng)
            let b = Int.random(in: 12...29, using: &rng)
            return MathProblem(prompt: "\(a) × \(b) = ?", answer: a * b)
        case 3:
            if Bool.random(using: &rng) {
                let a = Int.random(in: 12...59, using: &rng)
                let b = Int.random(in: 12...49, using: &rng)
                let c = Int.random(in: 6...39, using: &rng)
                return MathProblem(prompt: "\(a) + \(b) + \(c) = ?", answer: a + b + c)
            }
            let start = Int.random(in: 2...40, using: &rng)
            let step = Int.random(in: 3...14, using: &rng)
            let terms = (0..<4).map { String(start + $0 * step) }
            return MathProblem(prompt: terms.joined(separator: ", ") + ", ?", answer: start + 4 * step)
        default:
            let a = Int.random(in: 3...9, using: &rng)
            let b = Int.random(in: 6...14, using: &rng)
            let c = Int.random(in: 5...(a * b - 1), using: &rng)
            return MathProblem(prompt: "\(a) × \(b) − \(c) = ?", answer: a * b - c)
        }
    }
}

struct ChallengeRules: Equatable {
    var requiredSeconds: TimeInterval = 60
    /// After each correct answer the clock keeps running this long, then pauses.
    var graceSeconds: TimeInterval = 15
    var wrongPenalty: TimeInterval = 5
    var skipPenalty: TimeInterval = 5
}

/// One minute of mental arithmetic. The clock only advances while the person keeps
/// answering correctly, so it cannot be completed by waiting.
struct ChallengeState {
    enum Outcome: Equatable {
        case correct, wrong, invalid, finished
    }

    let rules: ChallengeRules
    private(set) var progress: TimeInterval = 0
    private(set) var problem: MathProblem
    private(set) var solved = 0
    private(set) var mistakes = 0
    private(set) var skipped = 0
    private(set) var startedAt: Date
    private(set) var lastCorrectAt: Date?
    private var lastTick: Date
    private var rng: SeededRandom

    init(rules: ChallengeRules = ChallengeRules(), now: Date, seed: UInt64) {
        var generator = SeededRandom(seed: seed)
        self.rules = rules
        startedAt = now
        lastTick = now
        problem = ProblemFactory.make(level: 0, using: &generator)
        rng = generator
    }

    var isComplete: Bool { progress >= rules.requiredSeconds }
    var remaining: TimeInterval { max(0, rules.requiredSeconds - progress) }
    var fraction: Double { min(1, progress / rules.requiredSeconds) }

    func isRunning(at now: Date) -> Bool {
        guard !isComplete, let lastCorrectAt else { return false }
        return now.timeIntervalSince(lastCorrectAt) < rules.graceSeconds
    }

    /// Seconds since the last correct answer, or since the start.
    func idleTime(at now: Date) -> TimeInterval {
        now.timeIntervalSince(lastCorrectAt ?? startedAt)
    }

    mutating func tick(now: Date) {
        defer { lastTick = max(lastTick, now) }
        guard !isComplete, let lastCorrectAt else { return }
        let end = min(now, lastCorrectAt.addingTimeInterval(rules.graceSeconds))
        if end > lastTick {
            progress = min(rules.requiredSeconds, progress + end.timeIntervalSince(lastTick))
        }
    }

    mutating func submit(_ text: String, now: Date) -> Outcome {
        tick(now: now)
        guard !isComplete else { return .finished }
        guard let value = Int(text) else { return .invalid }
        if value == problem.answer {
            solved += 1
            lastCorrectAt = now
            nextProblem()
            return .correct
        }
        mistakes += 1
        progress = max(0, progress - rules.wrongPenalty)
        return .wrong
    }

    mutating func skip(now: Date) {
        tick(now: now)
        guard !isComplete else { return }
        skipped += 1
        progress = max(0, progress - rules.skipPenalty)
        nextProblem()
    }

    mutating func restart(now: Date) {
        progress = 0
        lastCorrectAt = nil
        startedAt = now
        lastTick = now
        nextProblem()
    }

    private mutating func nextProblem() {
        let level = max(0, Int(fraction * 5) - Int.random(in: 0...1, using: &rng))
        var candidate = ProblemFactory.make(level: level, using: &rng)
        if candidate.prompt == problem.prompt {
            candidate = ProblemFactory.make(level: level, using: &rng)
        }
        problem = candidate
    }
}
