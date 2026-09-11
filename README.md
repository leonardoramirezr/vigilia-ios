# YOUR-APP-NAME

A minimal template for building a native macOS app with Swift and AppKit, with no Xcode project required — just Swift, a `Makefile`, and a shell script.

## Requirements

- macOS 15.0 or later
- Xcode Command Line Tools (`xcode-select --install`)

## Getting Started

1. Clone this repository.
2. Rename references to `YOUR-APP-NAME`, `your-app-name`, and `your-username` throughout the project (see [Customization](#customization) below).
3. Add your Swift source files to the `src/` directory.
4. Add your app icon and fonts (see [Resources](#resources) below).
5. Build and install the app:

```sh
make install
```

## Project Structure

```
.
├── src/                 # Swift source files
├── Resources/
│   ├── Fonts/           # .ttf font files bundled with the app
│   └── Icon/            # AppIcon.icns
├── Info.plist           # App bundle metadata
├── build.sh             # Build script
├── Makefile             # Build and install targets
└── LICENSE
```

## Building

```sh
make build
```

This compiles all Swift files in `src/` using `swiftc`, assembles a `.app` bundle under `build/`, copies in `Info.plist`, fonts, and the app icon, and ad-hoc signs the resulting bundle.

## Installing

```sh
make install
```

This builds the app and copies it into `/Applications/`.

## Customization

Search the project for the following placeholders and replace them with your own values:

| Placeholder      | Description                                  | Example         |
|-------------------|-----------------------------------------------|------------------|
| `YOUR-APP-NAME`   | Display name of the app (any case)           | `MyApp`         |
| `your-app-name`   | Lowercase app name, used in the bundle identifier | `myapp`     |
| `your-username`   | Lowercase identifier for the bundle reverse-DNS | `johndoe`     |

These appear in:

- `Makefile` — `APP_NAME`
- `build.sh` — `APP_NAME`
- `Info.plist` — `CFBundleExecutable`, `CFBundleName`, `CFBundleIdentifier`

## Resources

Place the following files before building:

- `Resources/Icon/AppIcon.icns` — the app icon
- `Resources/Fonts/*.ttf` — any custom fonts your app uses

## License

This project is licensed under the terms of the [GNU General Public License v3.0](LICENSE).
