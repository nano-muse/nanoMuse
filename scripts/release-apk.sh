#!/usr/bin/env bash
# Build, sign, name and (optionally) publish a nanoMuse release APK.
#
#   scripts/release-apk.sh <version> [--publish] [--publish-only] [--target COMMIT]
#                          [--notes FILE] [--allow-debug-key] [--prerelease]
#
# 1. checks that android/src/android/app/build.gradle.kts carries versionName <version>
#    (scripts/rebrand.py sets it),
# 2. makes sure the native artifacts and rclone.aar exist (scripts/android/build-natives.sh),
# 3. ./gradlew :app:assembleRelease — signed with android/keystore.properties when present,
# 4. verifies the arm64 sandbox and signature, refusing the debug key unless --allow-debug-key,
# 5. writes dist/nanoMuse-<version>-arm64.apk and .sha256,
# 6. with --publish: tags v<version> (annotated, at --target or HEAD, unless the tag already
#    exists), pushes the tag, then gh release create v<version> --latest with the APK, the
#    checksum and the notes (default docs/releases/v<version>.md, with What's Changed / New
#    Contributors / Contributors / Full Changelog filled in from the merged pull requests by
#    scripts/release_notes.py); --prerelease marks it as one instead and leaves Latest alone.
#
# --publish-only skips 1-5 and publishes the dist/ APK that is already there, for a version
# whose sources are an older commit (pass --target <commit> so the tag lands on it). The APK
# must pass the sandbox, version, checksum and signing checks before publication.
#
# Publishing refuses a commit that is not on origin/main (a release is cut from main, after
# the release pull request merged) and a working tree with uncommitted changes to tracked
# files (the APK would not match the tag).
set -euo pipefail
usage() { sed -n '2,26p' "$0" | sed 's/^# \{0,1\}//'; }
case "${1:-}" in -h|--help) usage; exit 0 ;; esac
source "$(dirname "${BASH_SOURCE[0]}")/android/env.sh"

version="${1:-}"
[[ "$version" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] || {
  echo "usage: $0 <version> [--publish] [--publish-only] [--target COMMIT] [--notes FILE] [--allow-debug-key] [--prerelease]" >&2
  echo "the version is x.y.z (got '${version:-nothing}'); --help explains" >&2
  exit 2
}
shift
publish=0 publish_only=0 allow_debug=0 prerelease=0 notes="" target=""
while [ $# -gt 0 ]; do
  case "$1" in
    --publish) publish=1 ;;
    --publish-only) publish=1; publish_only=1 ;;
    --target) [ $# -ge 2 ] || { echo "--target needs a commit" >&2; exit 2; }; target="$2"; shift ;;
    --allow-debug-key) allow_debug=1 ;;
    --prerelease) prerelease=1 ;;
    --notes) [ $# -ge 2 ] || { echo "--notes needs a file" >&2; exit 2; }; notes="$2"; shift ;;
    *) echo "unknown option $1 (try --help)" >&2; exit 2 ;;
  esac
  shift
done

build_tools="$(ls -d "$ANDROID_HOME"/build-tools/* | sort -V | tail -1)"
# macOS has no sha256sum; shasum writes and checks the same lines
command -v sha256sum >/dev/null 2>&1 || sha256sum() { shasum -a 256 "$@"; }
out="$NM_ROOT/dist/nanoMuse-$version-arm64.apk"

# Every part of the release carries the same version: the runtime, the desktop app, the web
# app, the iPhone app's MARKETING_VERSION (the APK is checked by badging below). Packages are
# named after these, so one left behind shows up as a wrong file name on the release.
echo "== versions"
versions_ok=1
check_version() { # file, what grep should find in it
  if grep -qE "$2" "$NM_ROOT/$1"; then echo "$1: $version"; else echo "$1: not $version" >&2; versions_ok=0; fi
}
check_version nanomuse/__init__.py "^__version__ = \"$version\""
check_version pyproject.toml "^version = \"$version\""
check_version web/package.json "\"version\": \"$version\""
check_version CITATION.cff "^version: $version$"
check_version harness/dsh-nanomuse/package.json "\"version\": \"$version\""
check_version harness/desktop/package.json "\"version\": \"$version\""
check_version android/src/ios/Minis.xcodeproj/project.pbxproj "MARKETING_VERSION = $version;"
[ $versions_ok = 1 ] || { echo "the versions above disagree — bump them first" >&2; exit 1; }

# Signature + badging of one APK; exits on the debug key unless allowed.
inspect_apk() {
  local apk="$1"
  python3 "$NM_ROOT/scripts/android/verify-sandbox-apk.py" "$apk"
  echo "== signature"
  local certs
  certs="$("$build_tools/apksigner" verify --print-certs "$apk")"
  echo "$certs" | grep -E "Signer #1 certificate (DN|SHA-256)"
  if echo "$certs" | grep -q "CN=Android Debug" && [ $allow_debug = 0 ]; then
    echo "signed with the debug key — android/keystore.properties is missing (or pass --allow-debug-key for a local test build)" >&2
    exit 1
  fi
  "$build_tools/aapt" dump badging "$apk" | grep -E "^package:|application-label:" | head -2
}

if [ $publish_only = 0 ]; then
  gradle_file="$NM_GRADLE_DIR/app/build.gradle.kts"
  grep -q "versionName = \"$version\"" "$gradle_file" || {
    echo "build.gradle.kts does not carry versionName \"$version\" — set VERSION_NAME in scripts/rebrand.py and run it" >&2
    exit 1
  }

  bash "$NM_ROOT/scripts/android/build-natives.sh"

  echo "== assembleRelease"
  ( cd "$NM_GRADLE_DIR" && ./gradlew :app:assembleRelease --console=plain -q )
  apk="$NM_GRADLE_DIR/app/build/outputs/apk/release/app-release.apk"
  [ -f "$apk" ] || { echo "no APK at $apk" >&2; exit 1; }
  inspect_apk "$apk"

  mkdir -p "$NM_ROOT/dist"
  cp "$apk" "$out"
  ( cd "$NM_ROOT/dist" && sha256sum "$(basename "$out")" > "$(basename "$out").sha256" && cat "$(basename "$out").sha256" )
  ls -la "$out"
else
  [ -f "$out" ] && [ -f "$out.sha256" ] || { echo "publish-only needs $out and its .sha256 — build first" >&2; exit 1; }
  echo "== dist/$(basename "$out")"
  ( cd "$NM_ROOT/dist" && sha256sum -c "$(basename "$out").sha256" )
  badging="$("$build_tools/aapt" dump badging "$out")"   # a variable, not a pipe: grep -q + pipefail would SIGPIPE aapt
  echo "$badging" | grep -q "versionName='$version'" || {
    echo "$out is not versionName $version:" >&2
    echo "$badging" | grep -E "^package:" >&2
    exit 1
  }
  inspect_apk "$out"
  ls -la "$out"
fi

if [ $publish = 1 ]; then
  notes="${notes:-$NM_ROOT/docs/releases/v$version.md}"
  [ -f "$notes" ] || { echo "release notes not found: $notes (see docs/release-notes-template.md)" >&2; exit 1; }
  title="$(head -1 "$notes" | sed 's/^# *//')"
  tag="v$version"

  cd "$NM_ROOT"
  # Nothing half done goes out: the tree is committed, and the commit the tag lands on is
  # on origin/main (a release is cut from main once its pull request merged).
  if [ -n "$(git status --porcelain --untracked-files=no --ignore-submodules=untracked)" ]; then
    echo "the working tree has uncommitted changes; commit or stash them before publishing" >&2
    git status --short --untracked-files=no --ignore-submodules=untracked >&2
    exit 1
  fi
  if git rev-parse -q --verify "refs/tags/$tag" >/dev/null; then
    echo "== tag $tag exists at $(git rev-parse --short "$tag^{commit}")"
    [ -z "$target" ] || [ "$(git rev-parse "$tag^{commit}")" = "$(git rev-parse "$target^{commit}")" ] || {
      echo "tag $tag already points elsewhere than --target $target" >&2; exit 1; }
    commit="$(git rev-parse "$tag^{commit}")"
  else
    commit="$(git rev-parse "${target:-HEAD}^{commit}")"
  fi
  git fetch -q origin main
  git merge-base --is-ancestor "$commit" origin/main || {
    echo "$(git rev-parse --short "$commit") is not on origin/main; merge the release pull request first" >&2
    exit 1
  }
  if ! git rev-parse -q --verify "refs/tags/$tag" >/dev/null; then
    echo "== tag $tag -> $(git rev-parse --short "$commit")"
    git tag -a "$tag" "$commit" -m "nanoMuse $version"
  fi
  git push origin "refs/tags/$tag"

  if gh release view "$tag" >/dev/null 2>&1; then
    echo "release $tag already exists on GitHub — nothing published" >&2
    exit 1
  fi
  if [ "$prerelease" = 1 ]; then kind="--prerelease"; else kind="--latest"; fi
  # What's Changed / New Contributors / Contributors / Full Changelog come from the pull
  # requests merged since the previous tag (scripts/release_notes.py). When that fails nothing
  # is published: a release page without them cannot be regenerated by this script once it
  # exists, and the tag is already pushed, so fixing the cause and running again with
  # --publish-only --target picks up right here.
  body="$(mktemp)"
  if ! python3 "$NM_ROOT/scripts/release_notes.py" "$version" --notes "$notes" --target "$tag" -o "$body"; then
    rm -f "$body"
    echo "release_notes.py failed; nothing published. Fix the cause (scripts/release_notes.py $version shows the body), then: $0 $version --publish-only --target $commit" >&2
    exit 1
  fi
  echo "== gh release create $tag $kind"
  gh release create "$tag" "$out" "$out.sha256" --verify-tag $kind --title "$title" --notes-file "$body"
  rm -f "$body"
fi
