#!/bin/bash
# Builds Vigilia for iPhone without an Xcode project: plain swiftc plus the
# command-line tools that ship inside Xcode.app (Xcode is never opened).
#
# Output:
#   build/Vigilia.app   the app bundle
#   build/Vigilia.ipa   unsigned IPA, ready for Sideloadly / AltStore / SideStore
#
# Environment overrides: BUNDLE_ID, VERSION, BUILD_NUMBER.
set -euo pipefail

APP_NAME="Vigilia"
BUNDLE_ID="${BUNDLE_ID:-com.leonardoramirezr.vigilia}"
VERSION="${VERSION:-1.0}"
BUILD_NUMBER="${BUILD_NUMBER:-1}"
MIN_IOS="26.0"
BUILD_DIR="build"
OBJ_DIR="${BUILD_DIR}/obj"
SOUND_DIR="${BUILD_DIR}/sounds"
APP_BUNDLE="${BUILD_DIR}/${APP_NAME}.app"
IPA="${BUILD_DIR}/${APP_NAME}.ipa"
TARGET="arm64-apple-ios${MIN_IOS}"

cd "$(dirname "$0")"
ROOT="$(pwd)"

if ! SDK_PATH="$(xcrun --sdk iphoneos --show-sdk-path 2>/dev/null)"; then
    echo "error: iOS SDK not found." >&2
    echo "The iOS SDK is only distributed inside Xcode.app; the Command Line Tools are not enough." >&2
    echo "Install Xcode (you never need to open it) and run: sudo xcode-select -s /Applications/Xcode.app" >&2
    exit 1
fi
SDK_VERSION="$(xcrun --sdk iphoneos --show-sdk-version)"
SDK_BUILD="$(xcrun --sdk iphoneos --show-sdk-build-version)"
TOOLCHAIN_DIR="$(xcode-select -p)/Toolchains/XcodeDefault.xctoolchain"
XCODE_VERSION="$(xcodebuild -version | awk '/^Xcode/ {print $2}')"
XCODE_BUILD="$(xcodebuild -version | awk '/^Build version/ {print $3}')"
IFS=. read -r XCODE_MAJOR XCODE_MINOR XCODE_PATCH <<< "${XCODE_VERSION}"
DT_XCODE="$(printf '%02d%d%d' "${XCODE_MAJOR}" "${XCODE_MINOR:-0}" "${XCODE_PATCH:-0}")"
echo "Xcode ${XCODE_VERSION} (${XCODE_BUILD}), iOS SDK ${SDK_VERSION}"

rm -rf "${APP_BUNDLE}" "${IPA}" "${OBJ_DIR}"
mkdir -p "${APP_BUNDLE}" "${OBJ_DIR}"

SOURCES=()
while IFS= read -r file; do
    SOURCES+=("${ROOT}/${file}")
done < <(find src -name '*.swift' | sort)
printf '%s\n' "${SOURCES[@]}" > "${OBJ_DIR}/sources.txt"

# Protocols whose conformances the compiler records for App Intents metadata
# (same list Xcode passes).
cat > "${OBJ_DIR}/const-protocols.json" <<'EOF'
["AppIntent", "EntityQuery", "AppEntity", "TransientEntity", "AppEnum", "AppShortcutProviding",
 "AppShortcutsProvider", "AnyResolverProviding", "AppIntentsPackage", "DynamicOptionsProvider",
 "_IntentValueRepresentable", "_AssistantIntentsProvider", "_GenerativeFunctionExtractable",
 "IntentValueQuery", "Resolver", "AppExtension", "ExtensionPointDefining"]
EOF

echo "Compiling..."
xcrun --sdk iphoneos swiftc \
    -target "${TARGET}" \
    -sdk "${SDK_PATH}" \
    -module-name "${APP_NAME}" \
    -parse-as-library \
    -O -wmo \
    -emit-const-values-path "${ROOT}/${OBJ_DIR}/${APP_NAME}.swiftconstvalues" \
    -Xfrontend -const-gather-protocols-file -Xfrontend "${ROOT}/${OBJ_DIR}/const-protocols.json" \
    -o "${APP_BUNDLE}/${APP_NAME}" \
    "${SOURCES[@]}"

# The alarm buttons run App Intents; iOS finds them through this metadata.
echo "Extracting App Intents metadata..."
echo "${ROOT}/${OBJ_DIR}/${APP_NAME}.swiftconstvalues" > "${OBJ_DIR}/const-values.txt"
if ! xcrun appintentsmetadataprocessor \
    --toolchain-dir "${TOOLCHAIN_DIR}" \
    --module-name "${APP_NAME}" \
    --sdk-root "${SDK_PATH}" \
    --xcode-version "${XCODE_BUILD}" \
    --platform-family iOS \
    --deployment-target "${MIN_IOS}" \
    --target-triple "${TARGET}" \
    --binary-file "${ROOT}/${APP_BUNDLE}/${APP_NAME}" \
    --output "${ROOT}/${APP_BUNDLE}" \
    --source-file-list "${ROOT}/${OBJ_DIR}/sources.txt" \
    --swift-const-vals-list "${ROOT}/${OBJ_DIR}/const-values.txt" \
    --compile-time-extraction; then
    echo "error: appintentsmetadataprocessor failed. Options supported by this Xcode:" >&2
    xcrun appintentsmetadataprocessor --help >&2 || true
    exit 1
fi
for intent in StopAlarmIntent OpenChallengeIntent; do
    if ! grep -q "${intent}" "${APP_BUNDLE}/Metadata.appintents/extract.actionsdata" 2>/dev/null; then
        echo "error: ${intent} is missing from the App Intents metadata" >&2
        exit 1
    fi
done

echo "Writing Info.plist..."
INFO="${APP_BUNDLE}/Info.plist"
cp Info.plist "${INFO}"
plutil -replace CFBundleIdentifier -string "${BUNDLE_ID}" "${INFO}"
plutil -replace CFBundleShortVersionString -string "${VERSION}" "${INFO}"
plutil -replace CFBundleVersion -string "${BUILD_NUMBER}" "${INFO}"
plutil -replace MinimumOSVersion -string "${MIN_IOS}" "${INFO}"
plutil -replace CFBundleSupportedPlatforms -json '["iPhoneOS"]' "${INFO}"
plutil -replace DTPlatformName -string iphoneos "${INFO}"
plutil -replace DTPlatformVersion -string "${SDK_VERSION}" "${INFO}"
plutil -replace DTPlatformBuild -string "${SDK_BUILD}" "${INFO}"
plutil -replace DTSDKName -string "iphoneos${SDK_VERSION}" "${INFO}"
plutil -replace DTSDKBuild -string "${SDK_BUILD}" "${INFO}"
plutil -replace DTXcode -string "${DT_XCODE}" "${INFO}"
plutil -replace DTXcodeBuild -string "${XCODE_BUILD}" "${INFO}"
plutil -replace DTCompiler -string com.apple.compilers.llvm.clang.1_0 "${INFO}"
plutil -replace BuildMachineOSBuild -string "$(sw_vers -buildVersion)" "${INFO}"

echo "Compiling app icon..."
if xcrun actool Resources/Assets.xcassets \
    --compile "${APP_BUNDLE}" \
    --platform iphoneos \
    --minimum-deployment-target "${MIN_IOS}" \
    --app-icon AppIcon \
    --target-device iphone \
    --output-partial-info-plist "${OBJ_DIR}/assets-Info.plist" \
    --output-format human-readable-text --errors --warnings --notices; then
    /usr/libexec/PlistBuddy -c "Merge ${OBJ_DIR}/assets-Info.plist" "${INFO}"
else
    echo "warning: actool failed; building without an app icon" >&2
fi

# Sounds are synthesized from scratch (license-free) and cached between builds.
if [ ! -f "${SOUND_DIR}/.stamp" ] || [ scripts/generate_sounds.py -nt "${SOUND_DIR}/.stamp" ]; then
    echo "Generating sounds..."
    rm -rf "${SOUND_DIR}"
    python3 scripts/generate_sounds.py --out "${SOUND_DIR}"
    touch "${SOUND_DIR}/.stamp"
fi
echo "Converting sounds..."
for wav in "${SOUND_DIR}"/*.wav; do
    afconvert -f caff -d ima4 "${wav}" "${APP_BUNDLE}/$(basename "${wav}" .wav).caf"
done
cp "${SOUND_DIR}/Sounds.json" "${APP_BUNDLE}/Sounds.json"

printf 'APPL????' > "${APP_BUNDLE}/PkgInfo"
plutil -lint "${INFO}" > /dev/null

echo "Packaging IPA..."
mkdir -p "${OBJ_DIR}/Payload"
cp -R "${APP_BUNDLE}" "${OBJ_DIR}/Payload/"
(cd "${OBJ_DIR}" && zip -qry "${ROOT}/${IPA}" Payload)

echo "Done: ${APP_BUNDLE}"
echo "      ${IPA} (unsigned: sign it while installing with Sideloadly, AltStore or SideStore)"
