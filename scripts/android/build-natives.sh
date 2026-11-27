#!/usr/bin/env bash
# Build everything the Gradle build needs but does not build itself:
#   proot (our fork, submodule android/deps/proot)  -> assets/proot-aarch64 + jniLibs
#   the Alpine root file system                      -> assets/alpine-minirootfs.tar.gz
#   rclone.aar (gomobile, deps/rclone-mobile)        -> app/libs/rclone.aar
# All three are git-ignored build artifacts. Each step is skipped when its
# output exists; pass --force to rebuild.
#
#   bash scripts/android/build-natives.sh [--force]
set -euo pipefail

force=0
for arg in "$@"; do
  case "$arg" in
    --force) force=1 ;;
    -h|--help) sed -n '2,9p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "unknown option $arg (try --help)" >&2; exit 2 ;;
  esac
done
source "$(dirname "${BASH_SOURCE[0]}")/env.sh"
ASSETS="$NM_APP_MAIN/assets"
JNI="$NM_APP_MAIN/jniLibs/arm64-v8a"
LIBS="$NM_GRADLE_DIR/app/libs"

# The fork builds both copies of PRoot. Its loaders are vendored files
# which deps/build_proot.sh verifies but cannot generate.
for loader in libproot-loader.so libproot-loader32.so; do
  if [ ! -e "$JNI/$loader" ]; then
    git -C "$NM_ROOT" checkout-index -- "${JNI#"$NM_ROOT"/}/$loader"
  fi
done

if [ $force = 1 ] || [ ! -s "$ASSETS/proot-aarch64" ] \
  || ! cmp -s "$ASSETS/proot-aarch64" "$JNI/libproot.so"; then
  if [ ! -f "$NM_ANDROID/deps/proot/src/GNUmakefile" ]; then
    echo "== proot submodule"
    (cd "$NM_ROOT" && git submodule update --init android/deps/proot)
  fi
  echo "== proot (NDK: ${ANDROID_NDK_HOME:-unset})"
  (cd "$NM_ANDROID" && bash deps/build_proot.sh)
else
  echo "== proot: present"
fi

if [ $force = 1 ] || [ ! -f "$ASSETS/alpine-minirootfs.tar.gz" ]; then
  echo "== alpine root file system"
  # proot-aarch64 already exists, so the script only downloads the rootfs.
  (cd "$NM_ANDROID" && bash scripts/prepare_android_sandbox.sh)
else
  echo "== rootfs: present"
fi

if [ $force = 1 ] || [ ! -f "$LIBS/rclone.aar" ] || [ -n "$(find "$NM_ANDROID/deps/rclone-mobile" \
  -type f \( -name '*.go' -o -name go.mod -o -name go.sum \) ! -name '*_test.go' -newer "$LIBS/rclone.aar" -print -quit)" ]; then
  echo "== rclone.aar (gomobile)"
  command -v gomobile >/dev/null || go install golang.org/x/mobile/cmd/gomobile@latest
  command -v gobind >/dev/null || go install golang.org/x/mobile/cmd/gobind@latest
  gomobile init
  (cd "$NM_ANDROID" && bash deps/build_rclone_android.sh)
  mkdir -p "$LIBS"
  cp "$NM_ANDROID/deps/build/rclone/rclone.aar" "$LIBS/rclone.aar"
else
  echo "== rclone.aar: present"
fi

ls -la "$ASSETS/proot-aarch64" "$ASSETS/alpine-minirootfs.tar.gz" "$JNI"/*.so "$LIBS/rclone.aar"
