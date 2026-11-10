#!/bin/bash
set -euo pipefail

test "${PRODUCT_NAME:?}" = UDP
test "${BASE_DIR:?}" = test
test "${MACOS_DEPLOYMENT_TARGET:?}" = 11.0
case "${1:?native phase required}" in
  import-certificate)
    KEYCHAIN_PATH="$RUNNER_TEMP/build.keychain-db"
    CERT_PATH="$RUNNER_TEMP/certificate.p12"
    printf '%s' "$CERT_BASE64" | base64 --decode -o "$CERT_PATH"
    security create-keychain -p "$KEYCHAIN_PASSWORD" "$KEYCHAIN_PATH"
    security set-keychain-settings -lut 21600 "$KEYCHAIN_PATH"
    security unlock-keychain -p "$KEYCHAIN_PASSWORD" "$KEYCHAIN_PATH"
    security import "$CERT_PATH" -P "$CERT_PASSWORD" -A -t cert -f pkcs12 -k "$KEYCHAIN_PATH"
    security list-keychain -d user -s "$KEYCHAIN_PATH" login.keychain
    security set-key-partition-list -S apple-tool:,apple:,codesign: -s -k "$KEYCHAIN_PASSWORD" "$KEYCHAIN_PATH"
    echo "KEYCHAIN_PATH=$KEYCHAIN_PATH" >> "$GITHUB_ENV"
    ;;
  store-credentials)
    xcrun notarytool store-credentials "notarytool-profile" \
      --apple-id "$APPLE_ID" --team-id "$TEAM_ID" --password "$APP_PASSWORD" \
      --keychain "$KEYCHAIN_PATH"
    ;;
  build)
    python3 .github/scripts/native.py clean-macos
    xcodebuild -project "$PRODUCT_NAME.xcodeproj" \
      -target "$PRODUCT_NAME" -configuration Default \
      ARCHS="arm64 x86_64" ONLY_ACTIVE_ARCH=NO \
      MACOSX_DEPLOYMENT_TARGET="$MACOS_DEPLOYMENT_TARGET" \
      CODE_SIGNING_ALLOWED=NO \
      CONFIGURATION_BUILD_DIR="$PWD/$BASE_DIR/Plugins" build
    ;;
  verify)
    python3 .github/scripts/native.py verify-unsigned
    architectures=$(lipo -archs "$BASE_DIR/Plugins/$PRODUCT_NAME.bundle/Contents/MacOS/$PRODUCT_NAME")
    case " $architectures " in *" arm64 "*) ;; *) exit 1 ;; esac
    case " $architectures " in *" x86_64 "*) ;; *) exit 1 ;; esac
    echo "BUNDLE_PATH=$BASE_DIR/Plugins/$PRODUCT_NAME.bundle" >> "$GITHUB_ENV"
    ;;
  merge-windows)
    python3 .github/scripts/native.py merge-windows
    ;;
  sign)
    python3 .github/scripts/native.py verify-unsigned
    IDENTITY=$(security find-identity -v -p codesigning "$KEYCHAIN_PATH" \
      | grep "Developer ID Application" | head -1 | sed -E 's/.*"(.*)".*/\1/')
    test -n "$IDENTITY"
    codesign --verbose --deep --timestamp --force --options=runtime \
      --sign "$IDENTITY" "$BUNDLE_PATH"
    codesign --verify --deep --strict --verbose=2 "$BUNDLE_PATH"
    ;;
  package)
    python3 .github/scripts/native.py verify-resources
    ZIP_PATH="${PRODUCT_NAME}-${VERSION}.zip"
    DMG_PATH="${PRODUCT_NAME}-${VERSION}.dmg"
    test ! -e "$ZIP_PATH"
    test ! -L "$ZIP_PATH"
    test ! -e "$DMG_PATH"
    test ! -L "$DMG_PATH"
    ditto -c -k --keepParent "$BUNDLE_PATH" "$ZIP_PATH"
    hdiutil create -format UDBZ -volname "$PRODUCT_NAME" -srcfolder "$BUNDLE_PATH" "$DMG_PATH"
    for artifact in "$ZIP_PATH" "$DMG_PATH"; do
      response=$(xcrun notarytool submit "$artifact" \
        --keychain-profile "notarytool-profile" --keychain "$KEYCHAIN_PATH" \
        --wait --output-format json)
      printf '%s' "$response" | python3 .github/scripts/native.py accepted
    done
    xcrun stapler staple "$DMG_PATH"
    codesign --verify --deep --strict --verbose=2 "$BUNDLE_PATH"
    python3 .github/scripts/native.py verify-resources
    echo "ZIP_PATH=$ZIP_PATH" >> "$GITHUB_ENV"
    echo "DMG_PATH=$DMG_PATH" >> "$GITHUB_ENV"
    ;;
  *)
    echo "Unknown native phase: $1" >&2
    exit 1
    ;;
esac
