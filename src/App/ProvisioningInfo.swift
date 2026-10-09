import Foundation

enum ProvisioningInfo {
    /// When the signature of a sideloaded build stops working (7 days with a free
    /// Apple ID). Nil for unsigned builds.
    static let expirationDate: Date? = {
        guard let url = Bundle.main.url(forResource: "embedded", withExtension: "mobileprovision"),
              let data = try? Data(contentsOf: url),
              let start = data.range(of: Data("<?xml".utf8)),
              let end = data.range(of: Data("</plist>".utf8), in: start.upperBound..<data.endIndex)
        else { return nil }
        let plist = try? PropertyListSerialization.propertyList(
            from: data.subdata(in: start.lowerBound..<end.upperBound), format: nil)
        return (plist as? [String: Any])?["ExpirationDate"] as? Date
    }()
}
