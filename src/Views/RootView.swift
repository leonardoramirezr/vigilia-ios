import SwiftUI

struct RootView: View {
    @EnvironmentObject private var controller: AlarmController
    @Environment(\.scenePhase) private var scenePhase
    private let clock = Timer.publish(every: 5, on: .main, in: .common).autoconnect()

    var body: some View {
        HomeView()
            .fullScreenCover(item: $controller.challenge) { request in
                ChallengeView(request: request)
                    .environmentObject(controller)
                    .interactiveDismissDisabled()
            }
            .onChange(of: scenePhase, initial: true) { _, phase in
                if phase == .active {
                    controller.sceneDidBecomeActive()
                }
            }
            .onReceive(clock) { _ in
                controller.heartbeat()
            }
    }
}
