import Foundation

struct MathProblem: Equatable {
    let prompt: String
    let answer: Int
}

/// How many digits the numbers in the challenge have. Answers can be longer
/// (6 × 9 = 54 is a one-digit operation).
enum ChallengeDifficulty: Int, Codable, CaseIterable, Identifiable {
    case oneDigit = 1
    case twoDigits = 2
    case threeDigits = 3

    var id: Int { rawValue }

    var title: String {
        switch self {
        case .oneDigit: return "1 dígito"
        case .twoDigits: return "2 dígitos"
        case .threeDigits: return "3 dígitos"
        }
    }

    var example: String {
        switch self {
        case .oneDigit: return "7 + 8, 6 × 9, 8 × 7 − 4 × 6"
        case .twoDigits: return "47 + 38, 6 × 23, 7 × 13 − 25"
        case .threeDigits: return "347 + 285, 6 × 135, 7 × 124 − 358"
        }
    }
}

/// How much time the challenge has to accumulate (it only runs while answering well).
enum ChallengeDuration: Int, Codable, CaseIterable, Identifiable {
    case oneMinute = 1
    case twoMinutes = 2
    case threeMinutes = 3
    case fourMinutes = 4
    case fiveMinutes = 5
    case sixMinutes = 6
    case sevenMinutes = 7
    case eightMinutes = 8
    case nineMinutes = 9
    case tenMinutes = 10

    var id: Int { rawValue }

    var seconds: TimeInterval { TimeInterval(rawValue * 60) }

    /// Short label for the picker.
    var title: String { "\(rawValue) min" }

    /// For sentences: "1 minuto", "2 minutos".
    var text: String { rawValue == 1 ? "1 minuto" : "\(rawValue) minutos" }
}

enum ProblemFactory {
    /// Levels 0…4. Higher levels mix more operations; the difficulty sets how many
    /// digits the numbers have. Every answer is a non-negative integer so a plain
    /// numeric keypad is enough.
    static func make<R: RandomNumberGenerator>(level: Int, difficulty: ChallengeDifficulty, using rng: inout R) -> MathProblem {
        let level = max(0, min(4, level))
        switch difficulty {
        case .oneDigit: return oneDigit(level: level, using: &rng)
        case .twoDigits: return twoDigits(level: level, using: &rng)
        case .threeDigits: return threeDigits(level: level, using: &rng)
        }
    }

    private static func oneDigit<R: RandomNumberGenerator>(level: Int, using rng: inout R) -> MathProblem {
        switch level {
        case 0:
            let a = Int.random(in: 2...9, using: &rng)
            let b = Int.random(in: 2...9, using: &rng)
            return MathProblem(prompt: "\(a) + \(b) = ?", answer: a + b)
        case 1:
            let a = Int.random(in: 3...9, using: &rng)
            let b = Int.random(in: 3...9, using: &rng)
            return MathProblem(prompt: "\(a) × \(b) = ?", answer: a * b)
        case 2:
            let a = Int.random(in: 2...9, using: &rng)
            let b = Int.random(in: 2...9, using: &rng)
            let c = Int.random(in: 2...9, using: &rng)
            return MathProblem(prompt: "\(a) + \(b) + \(c) = ?", answer: a + b + c)
        case 3:
            // a × b is at least 9, so subtracting c never goes below zero.
            let a = Int.random(in: 3...9, using: &rng)
            let b = Int.random(in: 3...9, using: &rng)
            let c = Int.random(in: 2...9, using: &rng)
            if Bool.random(using: &rng) {
                return MathProblem(prompt: "\(a) × \(b) + \(c) = ?", answer: a * b + c)
            }
            return MathProblem(prompt: "\(a) × \(b) − \(c) = ?", answer: a * b - c)
        default:
            var a = Int.random(in: 2...9, using: &rng)
            var b = Int.random(in: 2...9, using: &rng)
            var c = Int.random(in: 2...9, using: &rng)
            var d = Int.random(in: 2...9, using: &rng)
            if Bool.random(using: &rng) {
                return MathProblem(prompt: "\(a) × \(b) + \(c) × \(d) = ?", answer: a * b + c * d)
            }
            if a * b < c * d {
                swap(&a, &c)
                swap(&b, &d)
            }
            return MathProblem(prompt: "\(a) × \(b) − \(c) × \(d) = ?", answer: a * b - c * d)
        }
    }

    private static func twoDigits<R: RandomNumberGenerator>(level: Int, using rng: inout R) -> MathProblem {
        switch level {
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
            let c = Int.random(in: 10...min(99, a * b - 1), using: &rng)
            return MathProblem(prompt: "\(a) × \(b) − \(c) = ?", answer: a * b - c)
        }
    }

    private static func threeDigits<R: RandomNumberGenerator>(level: Int, using rng: inout R) -> MathProblem {
        switch level {
        case 0:
            let a = Int.random(in: 125...689, using: &rng)
            let b = Int.random(in: 114...499, using: &rng)
            return MathProblem(prompt: "\(a) + \(b) = ?", answer: a + b)
        case 1:
            let a = Int.random(in: 420...999, using: &rng)
            let b = Int.random(in: 113...(a - 110), using: &rng)
            return MathProblem(prompt: "\(a) − \(b) = ?", answer: a - b)
        case 2:
            let a = Int.random(in: 3...9, using: &rng)
            let b = Int.random(in: 112...249, using: &rng)
            return MathProblem(prompt: "\(a) × \(b) = ?", answer: a * b)
        case 3:
            if Bool.random(using: &rng) {
                let a = Int.random(in: 112...499, using: &rng)
                let b = Int.random(in: 112...399, using: &rng)
                let c = Int.random(in: 106...299, using: &rng)
                return MathProblem(prompt: "\(a) + \(b) + \(c) = ?", answer: a + b + c)
            }
            let start = Int.random(in: 102...420, using: &rng)
            let step = Int.random(in: 13...75, using: &rng)
            let terms = (0..<4).map { String(start + $0 * step) }
            return MathProblem(prompt: terms.joined(separator: ", ") + ", ?", answer: start + 4 * step)
        default:
            let a = Int.random(in: 3...9, using: &rng)
            let b = Int.random(in: 102...199, using: &rng)
            let c = Int.random(in: 100...min(999, a * b - 1), using: &rng)
            return MathProblem(prompt: "\(a) × \(b) − \(c) = ?", answer: a * b - c)
        }
    }
}

struct ChallengeRules: Equatable {
    var difficulty: ChallengeDifficulty
    var requiredSeconds: TimeInterval = 60
    /// After each correct answer the clock keeps running this long, then pauses.
    var graceSeconds: TimeInterval
    var wrongPenalty: TimeInterval = 5
    var skipPenalty: TimeInterval = 5

    init(difficulty: ChallengeDifficulty = .twoDigits, duration: ChallengeDuration = .oneMinute) {
        self.difficulty = difficulty
        requiredSeconds = duration.seconds
        // Three-digit operations take longer to work out, and the alarm comes back
        // inside the app once this much time passes without a correct answer.
        graceSeconds = difficulty == .threeDigits ? 25 : 15
    }
}

/// One to ten minutes of mental arithmetic. The clock only advances while the
/// person keeps answering correctly, so it cannot be completed by waiting. Operations
/// get harder as the clock advances, whatever the duration.
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
        problem = ProblemFactory.make(level: 0, difficulty: rules.difficulty, using: &generator)
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
        var candidate = ProblemFactory.make(level: level, difficulty: rules.difficulty, using: &rng)
        if candidate.prompt == problem.prompt {
            candidate = ProblemFactory.make(level: level, difficulty: rules.difficulty, using: &rng)
        }
        problem = candidate
    }
}
