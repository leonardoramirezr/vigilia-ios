import SwiftUI
import UIKit

/// One minute of mental arithmetic. It is the only way to turn the alarm off (or
/// to unlock the settings while the alarm is enabled).
struct ChallengeView: View {
    let request: ChallengeRequest

    @EnvironmentObject private var controller: AlarmController
    @Environment(\.scenePhase) private var scenePhase
    @State private var challenge = ChallengeState(now: Date(), seed: UInt64.random(in: .min ... .max))
    @State private var input = ""
    @State private var now = Date()
    @State private var started = false
    @State private var finished = false
    @State private var flash: Flash?
    @State private var shakes = 0
    @State private var notice: String?
    private let timer = Timer.publish(every: 0.2, on: .main, in: .common).autoconnect()

    private enum Flash {
        case correct, wrong
    }

    private var occurrence: Date? {
        if case .wake(let occurrence, _) = request.purpose { return occurrence }
        return nil
    }

    var body: some View {
        ZStack {
            LinearGradient(
                colors: [Color(red: 0.04, green: 0.05, blue: 0.16), Color(red: 0.2, green: 0.1, blue: 0.36)],
                startPoint: .top, endPoint: .bottom)
                .ignoresSafeArea()
            if finished {
                successView
            } else {
                challengeView
            }
        }
        .preferredColorScheme(.dark)
        .onAppear(perform: begin)
        .onDisappear {
            UIApplication.shared.isIdleTimerDisabled = false
            AlarmAudioPlayer.shared.stop()
        }
        .onReceive(timer) { tick(at: $0) }
        .onChange(of: scenePhase) { _, phase in
            if phase == .background, !finished {
                restart(because: "Saliste de la app: el reto empezó de nuevo.")
            }
        }
        .sensoryFeedback(.success, trigger: challenge.solved)
        .sensoryFeedback(.error, trigger: challenge.mistakes)
    }

    // MARK: Views

    private var challengeView: some View {
        VStack(spacing: 16) {
            header
            ProgressRing(fraction: challenge.fraction, remaining: challenge.remaining, running: challenge.isRunning(at: now))
            status
            Text(challenge.problem.prompt)
                .font(.system(size: 36, weight: .bold, design: .rounded))
                .monospacedDigit()
                .lineLimit(1)
                .minimumScaleFactor(0.5)
            Text(input.isEmpty ? " " : input)
                .font(.system(size: 34, weight: .semibold, design: .monospaced))
                .frame(maxWidth: .infinity, minHeight: 56)
                .background(RoundedRectangle(cornerRadius: 14).fill(answerBackground))
                .modifier(Shake(animatableData: CGFloat(shakes)))
            keypad
            HStack {
                Text("Aciertos \(challenge.solved) · Errores \(challenge.mistakes)")
                    .font(.footnote)
                    .foregroundStyle(.secondary)
                Spacer()
                Button("Saltar (−5 s)") {
                    challenge.skip(now: Date())
                    input = ""
                }
                .font(.footnote)
            }
        }
        .padding(.horizontal, 20)
        .padding(.vertical, 12)
        .foregroundStyle(.white)
    }

    private var header: some View {
        HStack(alignment: .top) {
            VStack(alignment: .leading, spacing: 4) {
                Text(occurrence == nil ? "Reto para desbloquear" : "Reto para apagar la alarma")
                    .font(.headline)
                Text("1 minuto de cálculo mental. El tiempo solo corre mientras respondes bien.")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
            Spacer()
            if occurrence == nil {
                Button("Cancelar") { controller.dismissChallenge() }
            }
        }
    }

    private var status: some View {
        Group {
            if let notice {
                Text(notice).foregroundStyle(.orange)
            } else if challenge.isRunning(at: now) {
                Text("¡Sigue así!")
            } else if challenge.lastCorrectAt == nil {
                Text("Responde la primera operación para empezar.")
            } else {
                Text("En pausa: responde para que el tiempo siga corriendo.").foregroundStyle(.orange)
            }
        }
        .font(.subheadline)
        .multilineTextAlignment(.center)
        .frame(minHeight: 40)
    }

    private var keypad: some View {
        let rows = [["1", "2", "3"], ["4", "5", "6"], ["7", "8", "9"], ["⌫", "0", "OK"]]
        return VStack(spacing: 10) {
            ForEach(rows, id: \.self) { row in
                HStack(spacing: 10) {
                    ForEach(row, id: \.self) { key in
                        Button {
                            press(key)
                        } label: {
                            Group {
                                if key == "⌫" {
                                    Image(systemName: "delete.left")
                                } else {
                                    Text(key)
                                }
                            }
                            .font(.title2.weight(.semibold))
                            .frame(maxWidth: .infinity, minHeight: 56)
                            .background(RoundedRectangle(cornerRadius: 14).fill(key == "OK" ? Color.orange : Color.white.opacity(0.12)))
                            .contentShape(Rectangle())
                        }
                        .buttonStyle(.plain)
                    }
                }
            }
        }
    }

    private var successView: some View {
        VStack(spacing: 20) {
            Image(systemName: occurrence == nil ? "lock.open.fill" : "sun.max.fill")
                .font(.system(size: 72))
                .foregroundStyle(.yellow)
            Text(occurrence == nil ? "Ajustes desbloqueados" : "¡Buenos días!")
                .font(.largeTitle.bold())
            Text(occurrence == nil
                 ? "Tienes 5 minutos para cambiar o desactivar la alarma."
                 : "Alarma apagada. Resolviste \(challenge.solved) operaciones con \(challenge.mistakes) errores.")
                .multilineTextAlignment(.center)
                .foregroundStyle(.secondary)
            Button {
                controller.dismissChallenge()
            } label: {
                Text("Listo")
                    .font(.headline)
                    .frame(maxWidth: .infinity, minHeight: 54)
                    .background(RoundedRectangle(cornerRadius: 16).fill(Color.orange))
            }
            .buttonStyle(.plain)
        }
        .padding(32)
        .foregroundStyle(.white)
    }

    private var answerBackground: Color {
        switch flash {
        case .correct: return Color.green.opacity(0.35)
        case .wrong: return Color.red.opacity(0.4)
        case nil: return Color.white.opacity(0.08)
        }
    }

    // MARK: Logic

    private func begin() {
        guard !started else { return }
        started = true
        UIApplication.shared.isIdleTimerDisabled = true
        challenge = ChallengeState(now: Date(), seed: UInt64.random(in: .min ... .max))
        controller.challengeDidStart(request)
    }

    private func tick(at date: Date) {
        now = date
        guard !finished else { return }
        challenge.tick(now: date)
        if challenge.isComplete {
            finish()
            return
        }
        // Left idle during a wake-up challenge: the alarm comes back inside the app.
        if let occurrence, challenge.idleTime(at: date) >= challenge.rules.graceSeconds,
           let sound = controller.soundInfo(for: occurrence) {
            AlarmAudioPlayer.shared.play(sound.file, loop: true)
        }
    }

    private func press(_ key: String) {
        guard !finished else { return }
        switch key {
        case "⌫":
            if !input.isEmpty { input.removeLast() }
        case "OK":
            submit()
        default:
            if input.count < 5 { input.append(key) }
        }
    }

    private func submit() {
        guard !input.isEmpty else { return }
        let outcome = challenge.submit(input, now: Date())
        input = ""
        notice = nil
        switch outcome {
        case .correct:
            flash = .correct
            AlarmAudioPlayer.shared.stop()
            controller.challengeMadeProgress(request)
        case .wrong:
            flash = .wrong
            withAnimation(.default) { shakes += 1 }
        case .invalid, .finished:
            break
        }
        if challenge.isComplete {
            finish()
        }
        Task {
            try? await Task.sleep(for: .milliseconds(350))
            flash = nil
        }
    }

    private func restart(because reason: String) {
        challenge.restart(now: Date())
        input = ""
        notice = reason
        AlarmAudioPlayer.shared.stop()
    }

    private func finish() {
        guard !finished else { return }
        finished = true
        AlarmAudioPlayer.shared.stop()
        controller.completeChallenge(request, summary: ChallengeSummary(solved: challenge.solved, mistakes: challenge.mistakes))
    }
}

struct ProgressRing: View {
    var fraction: Double
    var remaining: TimeInterval
    var running: Bool

    var body: some View {
        ZStack {
            Circle()
                .stroke(Color.white.opacity(0.12), lineWidth: 14)
            Circle()
                .trim(from: 0, to: fraction)
                .stroke(
                    AngularGradient(colors: [.orange, .yellow, .orange], center: .center),
                    style: StrokeStyle(lineWidth: 14, lineCap: .round))
                .rotationEffect(.degrees(-90))
                .animation(.linear(duration: 0.2), value: fraction)
            VStack(spacing: 2) {
                Text("\(Int(remaining.rounded(.up)))")
                    .font(.system(size: 44, weight: .bold, design: .rounded))
                    .monospacedDigit()
                Text(running ? "segundos" : "en pausa")
                    .font(.caption)
                    .foregroundStyle(running ? Color.secondary : Color.orange)
            }
        }
        .frame(width: 150, height: 150)
    }
}

struct Shake: GeometryEffect {
    var animatableData: CGFloat

    func effectValue(size: CGSize) -> ProjectionTransform {
        ProjectionTransform(CGAffineTransform(translationX: 10 * sin(animatableData * .pi * 4), y: 0))
    }
}
