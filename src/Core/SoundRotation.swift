import Foundation

/// Decides which sound rings on each calendar day.
///
/// The pool is walked in a shuffled order that is reshuffled every cycle: every
/// sound plays once before any of them repeats, and the same sound never rings
/// two days in a row, not even across the boundary between two cycles.
enum SoundRotation {
    /// Days since 2025-01-01 in the given time zone. Only differences matter.
    static func dayNumber(for date: Date, timeZone: TimeZone) -> Int {
        var calendar = Calendar(identifier: .gregorian)
        calendar.timeZone = timeZone
        let reference = calendar.date(from: DateComponents(year: 2025, month: 1, day: 1))!
        return calendar.dateComponents([.day], from: reference, to: calendar.startOfDay(for: date)).day ?? 0
    }

    static func index(forDay day: Int, count: Int) -> Int {
        precondition(count > 0, "empty sound pool")
        switch count {
        case 1:
            return 0
        case 2:
            return day & 1
        default:
            let cycle = floorDivide(day, count)
            return permutation(cycle: cycle, count: count)[day - cycle * count]
        }
    }

    static func permutation(cycle: Int, count: Int) -> [Int] {
        var order = shuffledIndices(count: count, seed: cycle)
        // Swapping the first two entries never changes the last one (count >= 3),
        // so comparing against the raw previous shuffle is enough.
        if order[0] == shuffledIndices(count: count, seed: cycle - 1)[count - 1] {
            order.swapAt(0, 1)
        }
        return order
    }

    private static func shuffledIndices(count: Int, seed: Int) -> [Int] {
        var rng = SeededRandom(seed: UInt64(bitPattern: Int64(seed)) &* 0x2545_F491_4F6C_DD1D &+ 0x5EED)
        var order = Array(0..<count)
        for i in stride(from: count - 1, to: 0, by: -1) {
            order.swapAt(i, Int(rng.next() % UInt64(i + 1)))
        }
        return order
    }

    private static func floorDivide(_ a: Int, _ b: Int) -> Int {
        let quotient = a / b
        return (a % b != 0 && (a < 0) != (b < 0)) ? quotient - 1 : quotient
    }
}
