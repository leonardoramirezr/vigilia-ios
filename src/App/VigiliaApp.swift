import SwiftUI

@main
struct VigiliaApp: App {
    var body: some Scene {
        WindowGroup {
            RootView()
                .environmentObject(AlarmController.shared)
                .environmentObject(AlarmAudioPlayer.shared)
        }
    }
}
