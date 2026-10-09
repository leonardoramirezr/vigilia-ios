import ActivityKit
import AlarmKit
import Foundation
import SwiftUI
import UIKit

struct VigiliaAlarmMetadata: AlarmMetadata {
    var kind: String
}

struct ChallengeRequest: Identifiable, Equatable {
    enum Purpose: Equatable {
        case wake(occurrence: Date, isTest: Bool)
        case unlockSettings
    }

    let id = UUID()
    let purpose: Purpose
}

struct ChallengeSummary {
    var solved: Int
    var mistakes: Int
}

/// Owns every AlarmKit alarm the app creates.
///
/// - One weekly-repeating alarm per selected weekday, each with the sound of its
///   next occurrence, so the alarm sounds different every day.
/// - A chain of one-shot "re-ring" alarms after each occurrence. AlarmKit always
///   shows a Stop control and the physical buttons silence the alarm, so instead of
///   fighting that, the alarm simply comes back until the challenge is completed.
///   The chain lives in the system, so closing or killing the app does not stop it.
@MainActor
final class AlarmController: ObservableObject {
    static let shared = AlarmController()

    enum AlarmKind: String {
        case main, retry, test
    }

    @Published private(set) var state: VigiliaState
    @Published private(set) var authorization: AlarmManager.AuthorizationState
    @Published private(set) var now = Date()
    /// AlarmKit reports one of the app's alarms going off right now.
    @Published private(set) var hasAlertingAlarm = false
    @Published var challenge: ChallengeRequest?
    @Published var notice: String?

    let sounds = SoundLibrary.shared
    private let manager = AlarmManager.shared
    private static let storageKey = "vigilia.state.v1"
    private var calendar: Calendar { Calendar.autoupdatingCurrent }
    private var operations: Task<Void, Never>?
    private var pendingReconcile: Task<Void, Never>?
    private var observing = false
    private var lastWatchdog = Date.distantPast
    private var isStateLoaded = false

    private init() {
        state = VigiliaState()
        authorization = AlarmManager.shared.authorizationState
        loadState()
    }

    /// After a reboot iOS keeps app data encrypted until the first unlock, and an
    /// alarm button can launch the app before that. Unreadable data must never be
    /// mistaken for "no alarm configured", or the next save would wipe the alarms.
    private func loadState() {
        guard !isStateLoaded else { return }
        if let data = UserDefaults.standard.data(forKey: Self.storageKey),
           let saved = try? JSONDecoder().decode(VigiliaState.self, from: data) {
            state = saved
            isStateLoaded = true
        } else if UIApplication.shared.isProtectedDataAvailable {
            isStateLoaded = true
        }
    }

    // MARK: - Derived values for the UI

    var isSettingsLocked: Bool {
        state.settings.isEnabled && (state.settingsUnlockedUntil ?? .distantPast) <= now
    }

    /// An alarm is going off, or went off and its challenge is still pending.
    /// Settings changes are ignored meanwhile (see `applySettings`).
    var isAlarmRinging: Bool {
        hasAlertingAlarm || state.activeSession(at: now, calendar: calendar) != nil
    }

    var nextOccurrence: Date? {
        nextOccurrence(after: now)
    }

    func soundInfo(for date: Date) -> SoundInfo? {
        sounds.sound(for: date, timeZone: calendar.timeZone)
    }

    // MARK: - Lifecycle

    func sceneDidBecomeActive() {
        loadState()
        startObserving()
        now = Date()
        authorization = manager.authorizationState
        refreshAlerting()
        presentChallengeIfNeeded()
        reconcileSoon(after: 0)
    }

    /// Called every few seconds while the app is on screen.
    func heartbeat() {
        loadState()
        now = Date()
        refreshAlerting()
        presentChallengeIfNeeded()
    }

    private func startObserving() {
        guard !observing else { return }
        observing = true
        Task {
            for await alarms in manager.alarmUpdates {
                self.now = Date()
                self.hasAlertingAlarm = alarms.contains { $0.state == .alerting }
                if self.hasAlertingAlarm {
                    self.presentChallengeIfNeeded()
                }
            }
        }
        Task {
            for await authorization in manager.authorizationUpdates {
                self.authorization = authorization
                if authorization == .authorized {
                    self.reconcileSoon(after: 0)
                }
            }
        }
    }

    private func presentChallengeIfNeeded() {
        guard let session = state.activeSession(at: Date(), calendar: calendar) else { return }
        if case .wake(let occurrence, _)? = challenge?.purpose, occurrence.isSameInstant(as: session.occurrence) {
            return
        }
        challenge = ChallengeRequest(purpose: .wake(occurrence: session.occurrence, isTest: session.isTest))
    }

    // MARK: - Settings

    func setEnabled(_ enabled: Bool) {
        if enabled {
            Task {
                guard await self.ensureAuthorized() else {
                    self.notice = "Sin permiso para crear alarmas. Actívalo en Ajustes > Vigilia > Alarmas."
                    return
                }
                guard !self.state.settings.isEnabled, self.applySettings({ $0.isEnabled = true }) else { return }
                // A few minutes to fine-tune the time and days before it locks.
                self.state.settingsUnlockedUntil = Date().addingTimeInterval(AlarmRules.settingsUnlockDuration)
                self.now = Date()
                self.save()
            }
        } else if !isSettingsLocked {
            applySettings { $0.isEnabled = false }
        }
    }

    func updateSettings(_ change: (inout AlarmSettings) -> Void) {
        guard !isSettingsLocked else { return }
        applySettings(change)
    }

    func requestUnlock() {
        challenge = ChallengeRequest(purpose: .unlockSettings)
    }

    /// Ignored while an alarm rings (see `VigiliaState.changeSettings`): only the
    /// challenge may silence it. Returns false when the change was ignored.
    @discardableResult
    private func applySettings(_ change: (inout AlarmSettings) -> Void) -> Bool {
        // Publishing `now` also puts the pickers back on the stored values when ignored.
        now = Date()
        refreshAlerting()
        guard state.changeSettings(at: now, isAlerting: hasAlertingAlarm, calendar: calendar, change) else { return false }
        save()
        reconcileSoon(after: 0.8)
        return true
    }

    private func refreshAlerting() {
        if let alarms = try? manager.alarms {
            hasAlertingAlarm = alarms.contains { $0.state == .alerting }
        }
    }

    func ensureAuthorized() async -> Bool {
        switch manager.authorizationState {
        case .authorized:
            authorization = .authorized
            return true
        case .denied:
            authorization = .denied
            return false
        case .notDetermined:
            let result = (try? await manager.requestAuthorization()) ?? .denied
            authorization = result
            return result == .authorized
        @unknown default:
            return false
        }
    }

    // MARK: - Test alarm

    func scheduleTest() {
        enqueue {
            guard await self.ensureAuthorized() else {
                self.notice = "Sin permiso para crear alarmas. Actívalo en Ajustes > Vigilia > Alarmas."
                return
            }
            self.cancelTest()
            let occurrence = Date(timeIntervalSinceReferenceDate: Date().timeIntervalSinceReferenceDate.rounded(.up) + AlarmRules.testDelay)
            let sound = self.soundInfo(for: self.nextOccurrence ?? Date())?.file
            let id = UUID()
            do {
                try await self.scheduleAlarm(id: id, kind: .test, schedule: .fixed(occurrence), sound: sound)
                self.state.test = TestRecord(id: id, occurrence: occurrence)
                await self.scheduleRetries(
                    for: occurrence,
                    at: AlarmRules.testRetryMinutes.map { occurrence.addingTimeInterval(TimeInterval($0 * 60)) },
                    sound: sound)
                self.notice = "La prueba sonará en 1 minuto. Bloquea el iPhone para verla como una alarma de verdad."
            } catch {
                self.report(error)
            }
            self.save()
        }
    }

    private func cancelTest() {
        guard let test = state.test else { return }
        try? manager.cancel(id: test.id)
        cancelRetries { $0.occurrence.isSameInstant(as: test.occurrence) }
        state.test = nil
    }

    // MARK: - Challenge

    /// The alarm was stopped from the system UI (Stop slider, buttons). Unless the
    /// challenge is done, make sure it rings again within a minute.
    func alarmStoppedFromSystemUI() async {
        await enqueue {
            self.loadState()
            let now = Date()
            guard self.isStateLoaded, let session = self.state.activeSession(at: now, calendar: self.calendar) else { return }
            let limit = session.isTest ? AlarmRules.testSessionWindow : AlarmRules.maxSessionLength
            guard now.timeIntervalSince(session.occurrence) < limit else { return }
            let ringsSoon = self.state.retries.contains {
                $0.occurrence.isSameInstant(as: session.occurrence)
                    && $0.fireDate > now.addingTimeInterval(15)
                    && $0.fireDate <= now.addingTimeInterval(90)
            }
            if !ringsSoon {
                await self.scheduleRetries(
                    for: session.occurrence,
                    at: [now.addingTimeInterval(60)],
                    sound: self.soundInfo(for: session.occurrence)?.file)
            }
        }.value
    }

    func openChallengeFromAlarm() {
        loadState()
        now = Date()
        presentChallengeIfNeeded()
    }

    func challengeDidStart(_ request: ChallengeRequest) {
        guard case .wake(let occurrence, _) = request.purpose else { return }
        lastWatchdog = Date()
        enqueue { await self.armWatchdog(for: occurrence) }
    }

    /// Called on every correct answer: keeps the next re-ring a little ahead, so it
    /// only fires if the person walks away from the challenge.
    func challengeMadeProgress(_ request: ChallengeRequest) {
        guard case .wake(let occurrence, _) = request.purpose else { return }
        let now = Date()
        let nextRing = state.retries
            .filter { $0.occurrence.isSameInstant(as: occurrence) && $0.fireDate > now }
            .map(\.fireDate)
            .min()
        let closeToRinging = nextRing.map { $0.timeIntervalSince(now) < 45 } ?? true
        if closeToRinging, now.timeIntervalSince(lastWatchdog) > 10 {
            lastWatchdog = now
            enqueue { await self.armWatchdog(for: occurrence) }
        } else {
            // Answering while an alarm rings (e.g. the challenge was opened early) silences it.
            enqueue { self.stopRingingAlarms() }
        }
    }

    func completeChallenge(_ request: ChallengeRequest, summary: ChallengeSummary) {
        let now = Date()
        switch request.purpose {
        case .unlockSettings:
            state.settingsUnlockedUntil = now.addingTimeInterval(AlarmRules.settingsUnlockDuration)
            self.now = now
            save()
        case .wake(let occurrence, let isTest):
            state.markCompleted(occurrence)
            state.history.insert(
                WakeRecord(occurrence: occurrence, completedAt: now, solved: summary.solved, mistakes: summary.mistakes, isTest: isTest),
                at: 0)
            state.history = Array(state.history.prefix(30))
            save()
            enqueue {
                self.stopRingingAlarms()
                self.cancelRetries { $0.occurrence.isSameInstant(as: occurrence) }
                if isTest {
                    self.cancelTest()
                }
                await self.reconcile()
            }
        }
    }

    func dismissChallenge() {
        challenge = nil
    }

    private func armWatchdog(for occurrence: Date) async {
        let now = Date()
        stopRingingAlarms()
        // Push back whatever would ring in the next couple of minutes…
        let horizon = now.addingTimeInterval(AlarmRules.watchdogDelay + 75)
        cancelRetries { $0.occurrence.isSameInstant(as: occurrence) && $0.fireDate <= horizon }
        // …and make sure something rings soon if the person leaves the challenge.
        await scheduleRetries(
            for: occurrence,
            at: [now.addingTimeInterval(AlarmRules.watchdogDelay)],
            sound: soundInfo(for: occurrence)?.file)
    }

    private func stopRingingAlarms() {
        guard let alarms = try? manager.alarms else { return }
        for alarm in alarms where alarm.state == .alerting {
            try? manager.stop(id: alarm.id)
            state.retries.removeAll { $0.id == alarm.id }
        }
        save()
    }

    // MARK: - Reconciliation

    private func reconcileSoon(after delay: TimeInterval) {
        pendingReconcile?.cancel()
        pendingReconcile = Task {
            if delay > 0 {
                try? await Task.sleep(for: .seconds(delay))
            }
            guard !Task.isCancelled else { return }
            await self.enqueue { await self.reconcile() }.value
        }
    }

    /// Brings the alarms registered in AlarmKit in line with the settings.
    private func reconcile() async {
        loadState()
        self.now = Date()
        authorization = manager.authorizationState
        guard isStateLoaded, authorization == .authorized else { return }

        var live: [UUID: Alarm] = [:]
        do {
            for alarm in try manager.alarms {
                live[alarm.id] = alarm
            }
        } catch {
            notice = "No se pudieron leer las alarmas: \(error.localizedDescription)"
            return
        }
        hasAlertingAlarm = live.values.contains { $0.state == .alerting }

        let now = Date()
        let session = state.activeSession(at: now, calendar: calendar)
        let next = nextOccurrence(after: now)

        // AlarmKit deletes one-shot alarms once they fire and are stopped.
        state.retries.removeAll { live[$0.id] == nil }
        if let test = state.test, session?.isTest != true, test.occurrence < now {
            cancelTest()
        }

        // Re-rings are only kept for the ringing session, the next alarm and a pending test.
        var wanted: [Date] = []
        if let session { wanted.append(session.occurrence) }
        if let next { wanted.append(next) }
        if let test = state.test { wanted.append(test.occurrence) }
        cancelRetries { retry in
            live[retry.id]?.state != .alerting
                && (!wanted.contains { $0.isSameInstant(as: retry.occurrence) } || retry.fireDate < now.addingTimeInterval(-120))
        }

        await reconcileMainAlarms(live: live, now: now)

        if let next, !state.retries.contains(where: { $0.occurrence.isSameInstant(as: next) }) {
            await scheduleRetries(
                for: next,
                at: AlarmRules.retryMinutes.map { next.addingTimeInterval(TimeInterval($0 * 60)) },
                sound: soundInfo(for: next)?.file)
        }

        // Anything else that belongs to the app but is not tracked is stale.
        var tracked = Set(state.mains.map(\.id) + state.retries.map(\.id))
        if let test = state.test { tracked.insert(test.id) }
        for (id, alarm) in live where !tracked.contains(id) && alarm.state != .alerting {
            try? manager.cancel(id: id)
        }
        save()
    }

    private func reconcileMainAlarms(live: [UUID: Alarm], now: Date) async {
        let times = state.settings.isEnabled ? state.settings.schedule : [:]
        var kept: [MainAlarmRecord] = []
        var covered = Set<Int>()

        for record in state.mains {
            guard let alarm = live[record.id] else { continue }
            let matches = times[record.weekday] == AlarmTime(hour: record.hour, minute: record.minute)
                && !covered.contains(record.weekday)
            if alarm.state == .alerting {
                // Never interrupt an alarm that is ringing; it is revisited next time.
                kept.append(record)
                if matches { covered.insert(record.weekday) }
                continue
            }
            if matches, let next = AlarmMath.nextOccurrence(
                weekday: record.weekday, hour: record.hour, minute: record.minute, after: now, calendar: calendar) {
                // Swapping the alarm right before it fires could lose it, so keep it then.
                if soundInfo(for: next)?.file == record.sound || next.timeIntervalSince(now) < 120 {
                    var updated = record
                    updated.nextFire = next
                    kept.append(updated)
                    covered.insert(record.weekday)
                    continue
                }
            }
            try? manager.cancel(id: record.id)
        }

        for (weekday, time) in times.sorted(by: { $0.key < $1.key }) where !covered.contains(weekday) {
            guard let next = AlarmMath.nextOccurrence(
                weekday: weekday, hour: time.hour, minute: time.minute, after: now, calendar: calendar) else { continue }
            let sound = soundInfo(for: next)?.file
            let schedule = Alarm.Schedule.relative(.init(
                time: .init(hour: time.hour, minute: time.minute),
                repeats: .weekly([Self.localeWeekday(weekday)])))
            let id = UUID()
            do {
                try await scheduleAlarm(id: id, kind: .main, schedule: schedule, sound: sound)
                kept.append(MainAlarmRecord(id: id, weekday: weekday, hour: time.hour, minute: time.minute, sound: sound, nextFire: next))
            } catch {
                report(error)
            }
        }
        state.mains = kept
    }

    // MARK: - AlarmKit

    private func scheduleAlarm(id: UUID, kind: AlarmKind, schedule: Alarm.Schedule, sound: String?) async throws {
        let attributes = AlarmAttributes<VigiliaAlarmMetadata>(
            presentation: AlarmPresentation(alert: Self.alert(for: kind)),
            metadata: VigiliaAlarmMetadata(kind: kind.rawValue),
            tintColor: Color(red: 0.95, green: 0.45, blue: 0.2))
        let alertSound: AlertConfiguration.AlertSound
        if let sound {
            alertSound = .named(sound)
        } else {
            alertSound = .default
        }
        let configuration = AlarmManager.AlarmConfiguration<VigiliaAlarmMetadata>.alarm(
            schedule: schedule,
            attributes: attributes,
            stopIntent: StopAlarmIntent(alarmID: id.uuidString),
            secondaryIntent: OpenChallengeIntent(alarmID: id.uuidString),
            sound: alertSound)
        _ = try await manager.schedule(id: id, configuration: configuration)
    }

    /// No snooze button: the only extra action opens the challenge.
    private static func alert(for kind: AlarmKind) -> AlarmPresentation.Alert {
        let title: LocalizedStringResource
        switch kind {
        case .main: title = "¡Despierta! Haz el reto"
        case .retry: title = "Sigue sonando: haz el reto"
        case .test: title = "Prueba de Vigilia"
        }
        let challengeButton = AlarmButton(text: "Resolver reto", textColor: .white, systemImageName: "brain.head.profile")
        if #available(iOS 26.1, *) {
            return AlarmPresentation.Alert(title: title, secondaryButton: challengeButton, secondaryButtonBehavior: .custom)
        } else {
            return AlarmPresentation.Alert(
                title: title,
                stopButton: AlarmButton(text: "Detener", textColor: .white, systemImageName: "stop.fill"),
                secondaryButton: challengeButton,
                secondaryButtonBehavior: .custom)
        }
    }

    private func scheduleRetries(for occurrence: Date, at dates: [Date], sound: String?) async {
        let earliest = Date().addingTimeInterval(5)
        for date in dates where date > earliest {
            let id = UUID()
            do {
                try await scheduleAlarm(id: id, kind: .retry, schedule: .fixed(date), sound: sound)
                state.retries.append(RetryRecord(id: id, occurrence: occurrence, fireDate: date))
            } catch {
                report(error)
                break
            }
        }
        save()
    }

    private func cancelRetries(where shouldCancel: (RetryRecord) -> Bool) {
        let doomed = state.retries.filter(shouldCancel)
        guard !doomed.isEmpty else { return }
        for retry in doomed {
            try? manager.cancel(id: retry.id)
        }
        let ids = Set(doomed.map(\.id))
        state.retries.removeAll { ids.contains($0.id) }
    }

    // MARK: - Helpers

    /// Runs alarm operations one after another so they never interleave.
    @discardableResult
    private func enqueue(_ operation: @escaping @MainActor () async -> Void) -> Task<Void, Never> {
        let previous = operations
        let task = Task {
            await previous?.value
            await operation()
        }
        operations = task
        return task
    }

    private func nextOccurrence(after date: Date) -> Date? {
        let settings = state.settings
        guard settings.isEnabled else { return nil }
        return AlarmMath.nextOccurrence(schedule: settings.schedule, after: date, calendar: calendar)
    }

    private func save() {
        guard isStateLoaded else { return }
        if let data = try? JSONEncoder().encode(state) {
            UserDefaults.standard.set(data, forKey: Self.storageKey)
        }
    }

    private func report(_ error: Error) {
        if let alarmError = error as? AlarmManager.AlarmError, alarmError == .maximumLimitReached {
            notice = "iOS no permite programar más alarmas por ahora."
        } else {
            notice = "No se pudo programar la alarma: \(error.localizedDescription)"
        }
    }

    private static func localeWeekday(_ weekday: Int) -> Locale.Weekday {
        switch weekday {
        case 1: return .sunday
        case 2: return .monday
        case 3: return .tuesday
        case 4: return .wednesday
        case 5: return .thursday
        case 6: return .friday
        default: return .saturday
        }
    }
}
