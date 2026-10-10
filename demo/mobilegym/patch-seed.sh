#!/usr/bin/env sh
# The showcase's one change to MobileGym's seed data: 张伟's message in 微信 invites the
# visitor to a hike, not to hot pot, so that the page's two-app line (tomorrow's weather,
# then a reply to him) has a reason to look at the weather. Applied to a checkout after the
# clone, before `npm run build`: by demo/showcase/caddy/Dockerfile (the production image)
# and by demo/showcase/site/build.sh (the local preview), from this one place.
#
#   demo/mobilegym/patch-seed.sh /path/to/mobilegym
#
# Fails (exit 1) unless the original sentence is in the file exactly once, so an upstream
# change surfaces as a failed build and not as a demo quietly back on hot pot. Running it on
# a checkout that is already patched is fine. To drop the patch, delete this file and its
# two call sites; nothing else refers to it. Plain sh, grep and sed: what the image's build
# stage (node:22-bookworm-slim) has.
set -eu

target=${1:-}
if [ -z "$target" ]; then
  echo "usage: $0 /path/to/mobilegym" >&2
  exit 2
fi
file="$target/apps/Wechat/data/defaults.json"
old='"content": "明天一起去吃火锅吗？"'
new='"content": "明天一起去徒步吗？"'

if [ ! -f "$file" ]; then
  echo "patch-seed: $file is not there; is $target a MobileGym checkout?" >&2
  exit 1
fi
have_old=$(grep -c -F -- "$old" "$file" || true)
have_new=$(grep -c -F -- "$new" "$file" || true)
if [ "$have_old" -eq 0 ] && [ "$have_new" -eq 1 ]; then
  echo "patch-seed: already applied to $file (张伟 invites to a hike)"
  exit 0
fi
if [ "$have_old" -ne 1 ]; then
  echo "patch-seed: expected the sentence $old exactly once in $file, found $have_old time(s)." >&2
  echo "patch-seed: MobileGym's seed has changed upstream; update this script (or drop it) before building the showcase." >&2
  exit 1
fi
sed -i "s/$old/$new/" "$file"
if [ "$(grep -c -F -- "$new" "$file")" -ne 1 ] || [ "$(grep -c -F -- "$old" "$file" || true)" -ne 0 ]; then
  echo "patch-seed: the rewrite of $file did not come out as expected" >&2
  exit 1
fi
echo "patch-seed: 张伟's 微信 message now invites to a hike (明天一起去徒步吗？) in $file"
