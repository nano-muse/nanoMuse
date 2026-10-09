#!/usr/bin/env bash
# Move every version file of nanoMuse to the next version, for the release commit.
#
#   scripts/release-bump.sh <old> <new> <old-code> <new-code> [<relay-old> <relay-new>]
#   scripts/release-bump.sh 0.1.40 0.1.41 41 42            # the apps and the runtime
#   scripts/release-bump.sh 0.1.40 0.1.41 41 42 0.22.0 0.23.0   # and the relay, when it changed
#
# Edits, in place: scripts/rebrand.py (VERSION_NAME / VERSION_CODE — run it afterwards, it writes
# the Android versionName/versionCode and the iOS MARKETING_VERSION), nanomuse/__init__.py,
# pyproject.toml, CITATION.cff (version and today's date-released), the relay console's
# VERSION, web/ and the two harness/* package.json files with their lock files, and, with the
# last two arguments, cloud/nanomuse_cloud/__init__.py and cloud/pyproject.toml. Run from the
# repository root; the release recipe is in CONTRIBUTING.md.
set -euo pipefail
[ $# -eq 4 ] || [ $# -eq 6 ] || {
  echo "usage: $0 <old> <new> <old-code> <new-code> [<relay-old> <relay-new>]" >&2; exit 2; }
old="$1"; new="$2"; oc="$3"; nc="$4"; rold="${5:-}"; rnew="${6:-}"
[ -f pyproject.toml ] && [ -f scripts/rebrand.py ] || { echo "run from the repository root" >&2; exit 2; }

# in-place sed on GNU (Linux) and BSD (macOS) alike: BSD's -i wants a suffix argument
if sed --version >/dev/null 2>&1; then sedi() { sed -i "$@"; }; else sedi() { sed -i '' "$@"; }; fi

sedi "s/^VERSION_NAME = \"$old\"/VERSION_NAME = \"$new\"/; s/^VERSION_CODE = $oc\$/VERSION_CODE = $nc/" scripts/rebrand.py
sedi "s/^__version__ = \"$old\"/__version__ = \"$new\"/" nanomuse/__init__.py
sedi "s/^version = \"$old\"/version = \"$new\"/" pyproject.toml
sedi "s/^version: $old\$/version: $new/" CITATION.cff
sedi "s/^date-released: .*$/date-released: $(date +%F)/" CITATION.cff
sedi "s/const VERSION = \"$old\"/const VERSION = \"$new\"/" cloud/nanomuse_cloud/console/app.js
sedi "s/\"version\": \"$old\"/\"version\": \"$new\"/" \
  web/package.json harness/dsh-nanomuse/package.json harness/desktop/package.json
# A lock file names its own package twice (the root entry and packages[""]) and may list
# dependencies that happen to carry the same version string, so only those two lines move.
for lock in web/package-lock.json harness/desktop/package-lock.json; do
  python3 - "$lock" "$old" "$new" <<'EOF'
import sys

path, old, new = sys.argv[1:4]
lines = open(path, encoding="utf-8").read().split("\n")
moved = 0
for i, line in enumerate(lines):
    own = i < 5 or '"": {' in "\n".join(lines[max(0, i - 3):i])
    if own and line.strip() == f'"version": "{old}",':
        lines[i] = line.replace(old, new)
        moved += 1
if moved != 2:
    sys.exit(f'{path}: {moved} own version lines found, expected 2 (the root entry and packages[""])')
open(path, "w", encoding="utf-8").write("\n".join(lines))
EOF
done
if [ -n "$rold" ]; then
  sedi "s/^__version__ = \"$rold\"/__version__ = \"$rnew\"/" cloud/nanomuse_cloud/__init__.py
  sedi "s/^version = \"$rold\"/version = \"$rnew\"/" cloud/pyproject.toml
fi

echo "lock files: $(git diff --numstat -- web/package-lock.json harness/desktop/package-lock.json | awk '{print $1" lines in "$3}' | paste -sd ',' -) (expect 2 each)"
grep -n "^VERSION_NAME\|^VERSION_CODE" scripts/rebrand.py
echo "next: python scripts/rebrand.py  (must print 'clean' on a second run), then scripts/release-docs.py"
