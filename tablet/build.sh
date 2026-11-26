#!/bin/sh
set -eu
cd "$(dirname "$0")"
sdk="${ANDROID_SDK_ROOT:-/opt/homebrew/share/android-commandlinetools}"
java_bin="${JAVA_HOME:-/opt/homebrew/opt/openjdk@17/libexec/openjdk.jdk/Contents/Home}/bin"
export JAVA_HOME="${java_bin%/bin}"
tools="$sdk/build-tools/34.0.0"
android="$sdk/platforms/android-34/android.jar"
build="$(mktemp -d)"
trap 'rm -rf "$build"' EXIT
mkdir -p "$build/classes" "$build/dex" build
"$java_bin/javac" --release 8 -classpath "$android" -d "$build/classes" src/org/heygig/companion/MainActivity.java
"$java_bin/jar" cf "$build/classes.jar" -C "$build/classes" .
"$tools/d8" --lib "$android" --min-api 29 --output "$build/dex" "$build/classes.jar"
"$tools/aapt2" link -I "$android" --manifest AndroidManifest.xml -o "$build/base.apk"
(cd "$build/dex" && zip -q "$build/base.apk" classes.dex)
"$tools/zipalign" -f 4 "$build/base.apk" "$build/aligned.apk"
key="$HOME/.android/hey-gig-debug.keystore"
if [ ! -f "$key" ]; then
    "$java_bin/keytool" -genkeypair -keystore "$key" -storepass android -keypass android \
      -alias heygig -keyalg RSA -keysize 2048 -validity 10000 -dname 'CN=Hey GIG Development'
fi
"$tools/apksigner" sign --ks "$key" --ks-pass pass:android --out build/hey-gig.apk "$build/aligned.apk"
"$tools/apksigner" verify build/hey-gig.apk
