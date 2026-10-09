import AlarmKit
import SwiftUI
import UIKit

struct HomeView: View {
    @EnvironmentObject private var controller: AlarmController
    @EnvironmentObject private var player: AlarmAudioPlayer

    var body: some View {
        NavigationStack {
            Form {
                if controller.authorization != .authorized {
                    permissionSection
                }
                alarmSection
                upcomingSection
                testSection
                if let expiration = ProvisioningInfo.expirationDate {
                    signingSection(expiration)
                }
                statsSection
                if !controller.state.history.isEmpty {
                    historySection
                }
                howItWorksSection
            }
            .navigationTitle("Vigilia")
            .alert("Vigilia", isPresented: noticeIsPresented) {
                Button("OK", role: .cancel) {}
            } message: {
                Text(controller.notice ?? "")
            }
        }
        .tint(.orange)
    }

    // MARK: Sections

    private var permissionSection: some View {
        Section {
            if controller.authorization == .denied {
                Label("Vigilia no tiene permiso para programar alarmas.", systemImage: "exclamationmark.triangle.fill")
                    .foregroundStyle(.orange)
                Button("Abrir Ajustes") {
                    if let url = URL(string: UIApplication.openSettingsURLString) {
                        UIApplication.shared.open(url)
                    }
                }
            } else {
                Text("Vigilia necesita permiso para crear alarmas que suenen aunque el iPhone esté en silencio o en modo Concentración.")
                Button("Permitir alarmas") {
                    Task { _ = await controller.ensureAuthorized() }
                }
            }
        }
    }

    private var alarmSection: some View {
        Section {
            Toggle(isOn: enabledBinding) {
                Label("Alarma activada", systemImage: "alarm.fill")
            }
            .disabled(controller.isSettingsLocked)
            DatePicker("Hora", selection: timeBinding, displayedComponents: .hourAndMinute)
                .disabled(controller.isSettingsLocked)
            WeekdayPicker(selection: weekdaysBinding)
                .disabled(controller.isSettingsLocked)
            DifficultyPicker(selection: difficultyBinding)
                .disabled(controller.isSettingsLocked)
            if controller.isSettingsLocked {
                Button {
                    controller.requestUnlock()
                } label: {
                    Label("Desbloquear con el reto de 1 minuto", systemImage: "lock.fill")
                }
            } else if controller.state.settings.isEnabled, let until = controller.state.settingsUnlockedUntil, until > controller.now {
                Label("Desbloqueada hasta las \(until.formatted(date: .omitted, time: .shortened))", systemImage: "lock.open.fill")
                    .foregroundStyle(.secondary)
            }
        } header: {
            Text("Alarma")
        } footer: {
            Text(controller.state.settings.isEnabled
                 ? "Mientras esté activada, para cambiarla o apagarla tienes que completar el reto mental."
                 : "Al activarla tendrás 5 minutos para ajustarla; después queda bloqueada y cambiarla o apagarla requiere el reto mental.")
        }
    }

    private var upcomingSection: some View {
        Section {
            if let next = controller.nextOccurrence {
                LabeledContent("Suena") {
                    Text(next.formatted(.dateTime.weekday(.wide).hour().minute()))
                }
                LabeledContent("Falta") {
                    Text(next, style: .relative)
                }
                if let sound = controller.soundInfo(for: next) {
                    LabeledContent("Sonido de ese día", value: sound.title)
                    previewButton(for: sound)
                }
            } else {
                Text("No hay ninguna alarma programada.")
                    .foregroundStyle(.secondary)
            }
        } header: {
            Text("Próxima alarma")
        } footer: {
            Text("Hay \(controller.sounds.sounds.count) sonidos y cada día suena uno distinto; no se repite ninguno hasta haberlos usado todos.")
        }
    }

    private var testSection: some View {
        Section {
            Button {
                controller.scheduleTest()
            } label: {
                Label("Probar: sonará en 1 minuto", systemImage: "bell.badge.fill")
            }
            .disabled(controller.authorization == .denied)
            if let test = controller.state.test, test.occurrence > controller.now {
                LabeledContent("Prueba programada") {
                    Text(test.occurrence, style: .relative)
                }
            }
        } footer: {
            Text("La prueba funciona igual que la alarma real: no se puede posponer y vuelve a sonar hasta que completes el reto.")
        }
    }

    private func signingSection(_ expiration: Date) -> some View {
        Section {
            LabeledContent("Vence") {
                Text(expiration.formatted(date: .abbreviated, time: .shortened))
            }
            if expiration < controller.now.addingTimeInterval(2 * 24 * 3600) {
                Label("Refresca o reinstala la app antes de que venza: si vence no abrirá y no podrás completar el reto.",
                      systemImage: "exclamationmark.triangle.fill")
                    .foregroundStyle(.orange)
            }
        } header: {
            Text("Firma de la app")
        } footer: {
            Text("Con una cuenta gratuita de Apple la firma dura 7 días.")
        }
    }

    private var statsSection: some View {
        let week = WakeStatistics.samples(from: controller.state.history, period: .week, now: controller.now, calendar: .current)
        let average = WakeStatistics.summary(of: week.map(\.minuteOfDay))?.average
        return Section {
            NavigationLink {
                StatsView()
            } label: {
                LabeledContent {
                    if let average {
                        Text(Clock.text(average))
                    }
                } label: {
                    Label("Estadísticas", systemImage: "chart.xyaxis.line")
                }
            }
        } footer: {
            if average != nil {
                Text("Hora promedio a la que apagaste la alarma en los últimos 7 días.")
            }
        }
    }

    private var historySection: some View {
        Section("Últimos despertares") {
            ForEach(controller.state.history.prefix(7)) { record in
                VStack(alignment: .leading, spacing: 2) {
                    Text("\(record.occurrence.formatted(.dateTime.weekday(.wide).day().month().hour().minute()))\(record.isTest ? " · prueba" : "")")
                    Text("Apagada \(minutesLate(record)) después · \(record.solved) aciertos, \(record.mistakes) errores")
                        .font(.footnote)
                        .foregroundStyle(.secondary)
                }
            }
        }
    }

    private var howItWorksSection: some View {
        Section {
            DisclosureGroup("Cómo funciona") {
                VStack(alignment: .leading, spacing: 10) {
                    Text("• Cada día suena un sonido distinto para que no te acostumbres.")
                    Text("• No existe posponer. Si la detienes desde la pantalla bloqueada o con los botones, vuelve a sonar cada minuto y luego más espaciado durante una hora.")
                    Text("• Para apagarla de verdad abre Vigilia (botón «Resolver reto») y haz 1 minuto de cálculo mental. El tiempo solo avanza mientras respondes bien y cada error resta 5 segundos.")
                    Text("• Eliges la dificultad del reto: operaciones con números de 1, 2 o 3 dígitos.")
                    Text("• Si sales de la app durante el reto, empieza de nuevo; si la cierras, la alarma vuelve a sonar en poco más de un minuto.")
                    Text("• Las alarmas viven en iOS (AlarmKit): suenan aunque cierres la app, reinicies el iPhone o esté en silencio o en Concentración.")
                }
                .font(.callout)
                .padding(.vertical, 4)
            }
        }
    }

    // MARK: Helpers

    private func previewButton(for sound: SoundInfo) -> some View {
        let playing = player.playingFile == sound.file
        return Button {
            if playing {
                player.stop()
            } else {
                player.play(sound.file, loop: false)
            }
        } label: {
            Label(playing ? "Detener" : "Escuchar", systemImage: playing ? "stop.circle.fill" : "play.circle.fill")
        }
    }

    private func minutesLate(_ record: WakeRecord) -> String {
        let minutes = max(0, Int(record.completedAt.timeIntervalSince(record.occurrence) / 60))
        return minutes == 1 ? "1 minuto" : "\(minutes) minutos"
    }

    private var noticeIsPresented: Binding<Bool> {
        Binding(
            get: { controller.notice != nil },
            set: { if !$0 { controller.notice = nil } })
    }

    private var enabledBinding: Binding<Bool> {
        Binding(
            get: { controller.state.settings.isEnabled },
            set: { controller.setEnabled($0) })
    }

    private var timeBinding: Binding<Date> {
        Binding(
            get: {
                let settings = controller.state.settings
                return Calendar.current.date(bySettingHour: settings.hour, minute: settings.minute, second: 0, of: Date()) ?? Date()
            },
            set: { date in
                let parts = Calendar.current.dateComponents([.hour, .minute], from: date)
                controller.updateSettings {
                    $0.hour = parts.hour ?? 7
                    $0.minute = parts.minute ?? 0
                }
            })
    }

    private var weekdaysBinding: Binding<Set<Int>> {
        Binding(
            get: { controller.state.settings.weekdays },
            set: { days in controller.updateSettings { $0.weekdays = days } })
    }

    private var difficultyBinding: Binding<ChallengeDifficulty> {
        Binding(
            get: { controller.state.settings.difficulty },
            set: { controller.setDifficulty($0) })
    }
}

struct DifficultyPicker: View {
    @Binding var selection: ChallengeDifficulty
    @Environment(\.isEnabled) private var isEnabled

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            Label("Dificultad del reto", systemImage: "brain.head.profile")
                .foregroundStyle(isEnabled ? Color.primary : Color.secondary)
            Picker("Dificultad del reto", selection: $selection) {
                ForEach(ChallengeDifficulty.allCases) { difficulty in
                    Text(difficulty.title).tag(difficulty)
                }
            }
            .pickerStyle(.segmented)
            .labelsHidden()
            Text("Operaciones como \(selection.example)")
                .font(.footnote)
                .foregroundStyle(.secondary)
        }
        .padding(.vertical, 4)
    }
}

struct WeekdayPicker: View {
    @Binding var selection: Set<Int>
    @Environment(\.isEnabled) private var isEnabled

    private static let letters = ["D", "L", "M", "M", "J", "V", "S"]
    static let names = ["domingo", "lunes", "martes", "miércoles", "jueves", "viernes", "sábado"]

    /// Calendar weekdays in the order of the user's region (Monday or Sunday first).
    static var orderedDays: [Int] {
        let first = Calendar.current.firstWeekday
        return (0..<7).map { (first - 1 + $0) % 7 + 1 }
    }

    var body: some View {
        HStack(spacing: 6) {
            ForEach(Self.orderedDays, id: \.self) { day in
                let isOn = selection.contains(day)
                Button {
                    var days = selection
                    if isOn {
                        if days.count > 1 { days.remove(day) }
                    } else {
                        days.insert(day)
                    }
                    selection = days
                } label: {
                    Text(Self.letters[day - 1])
                        .font(.subheadline.weight(.semibold))
                        .frame(maxWidth: .infinity, minHeight: 36)
                        .background(Circle().fill(isOn ? Color.orange : Color.secondary.opacity(0.15)))
                        .foregroundStyle(isOn ? Color.white : Color.primary)
                }
                .buttonStyle(.borderless)
                .accessibilityLabel(Self.names[day - 1])
                .accessibilityAddTraits(isOn ? .isSelected : [])
            }
        }
        .opacity(isEnabled ? 1 : 0.5)
        .padding(.vertical, 4)
    }
}
