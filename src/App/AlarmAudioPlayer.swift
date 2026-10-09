import AVFoundation
import Foundation

/// In-app playback: previews, and the alarm that comes back when the challenge is
/// left idle. Uses the playback category so it ignores the silent switch.
@MainActor
final class AlarmAudioPlayer: NSObject, ObservableObject, AVAudioPlayerDelegate {
    static let shared = AlarmAudioPlayer()

    @Published private(set) var playingFile: String?
    private var player: AVAudioPlayer?

    func play(_ file: String, loop: Bool) {
        if playingFile == file, player?.isPlaying == true { return }
        stop()
        guard let url = Bundle.main.url(forResource: file, withExtension: nil) else { return }
        do {
            let session = AVAudioSession.sharedInstance()
            try session.setCategory(.playback, mode: .default)
            try session.setActive(true)
            let player = try AVAudioPlayer(contentsOf: url)
            player.numberOfLoops = loop ? -1 : 0
            player.delegate = self
            player.prepareToPlay()
            player.play()
            self.player = player
            playingFile = file
        } catch {
            playingFile = nil
        }
    }

    func stop() {
        guard let player else { return }
        player.stop()
        self.player = nil
        playingFile = nil
        try? AVAudioSession.sharedInstance().setActive(false, options: .notifyOthersOnDeactivation)
    }

    nonisolated func audioPlayerDidFinishPlaying(_ player: AVAudioPlayer, successfully flag: Bool) {
        Task { @MainActor in
            self.stop()
        }
    }
}
