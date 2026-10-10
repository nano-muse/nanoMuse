#!/usr/bin/env sh
# Build the site for local development of the showcase: MobileGym with the nanoMuse app
# installed and pointed at the gateway, as /phone.html, and the page around it (page/) at /.
# Production builds the same thing inside caddy/Dockerfile; this is for running the gateway on
# your machine with SITE_DIR.
#
#   demo/showcase/site/build.sh [/path/to/mobilegym]     # default: ./site/mobilegym (cloned)
#   SITE_DIR=$PWD/demo/showcase/site/dist python -m showcase_gateway
set -eu

here=$(cd "$(dirname "$0")" && pwd)
root=$(cd "$here/../../.." && pwd)
checkout=${1:-$here/mobilegym}
gateway=${NANOMUSE_DEMO:-/api/demo}
# the phone's media (app images, launcher widgets, icon themes) is MobileGym's companion
# dataset: /cdn on our own origin (the gateway's CDN_DIR, the compose file's ./data), or
# MobileGym's CDN — MOBILEGYM_CDN_BASE=https://cdn.mobilegym.dev — when it is not downloaded
cdn=${MOBILEGYM_CDN_BASE:-/cdn}

if [ ! -d "$checkout" ]; then
  git clone --depth 1 "${MOBILEGYM_REPO:-https://github.com/Purewhiter/mobilegym.git}" "$checkout"
fi
cd "$checkout"
[ -d node_modules ] || npm ci --no-audit --no-fund
"$root/demo/mobilegym/install.sh" "$checkout"
# the showcase's one change to the seed data (张伟 invites to a hike); fails if upstream moved it
sh "$root/demo/mobilegym/patch-seed.sh" "$checkout"
VITE_NANOMUSE_DEMO="$gateway" VITE_CDN_BASE="$cdn" npm run build
rm -rf "$here/dist"
cp -R dist "$here/dist"
# the phone moves to /phone.html (its assets keep their absolute paths); the page takes /, with
# MobileGym's own chrome (gesture keys, State Builder, power) composed in from the checkout
mv "$here/dist/index.html" "$here/dist/phone.html"
node "$here/compose.mjs" "$checkout" "$here/page" "$here/dist"
echo "site built: $here/dist (gateway at $gateway)"
