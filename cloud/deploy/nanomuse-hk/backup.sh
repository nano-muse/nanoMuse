#!/bin/sh
# Daily copy of the relay's SQLite database, taken with SQLite's own backup
# (consistent under WAL, no need to stop the container), gzipped, kept for 30
# days, and, when cos.env says where, sent off the box encrypted. Run by
# nanomuse-relay-backup.timer; harmless to run by hand.
#
#   RELAY_DIR     where docker-compose.yml lives (default /opt/nanomuse/relay)
#   BACKUP_DIR    where copies go (default /opt/nanomuse/backups)
#   KEEP_DAYS     how many days of copies to keep (default 30)
#   BACKUP_OWNER  who owns the copies, as user:group (default: the owner of RELAY_DIR,
#                 the deploying user that deploy.sh gave the directory to)
#
# The copies are only useful together with CLOUD_SECRET from .env (the
# hashes and the encrypted identifiers are keyed by it), so .env is copied
# alongside, once, and again whenever it changes, with the same 0600 mode.
#
# Off the box, when RELAY_DIR/cos.env exists (README › Off the box): the day's copy,
# encrypted to an age public key whose private half the maintainer keeps away from the
# box, goes to a COS bucket under relay/ through rclone's S3 interface, with a key that
# may put objects into that bucket and nothing else; the bucket's own lifecycle rule
# expires the copies. .env and the record's files never leave the box. A failed upload
# is a line in the journal, not a failed backup: the local copy exists.
#
#   cos.env: COS_BUCKET, COS_REGION, COS_SECRET_ID, COS_SECRET_KEY, BACKUP_AGE_RECIPIENT
#
# The timer runs this as root, and the database copy comes out of the container
# owned by uid 10001, so without the chown below every file under BACKUP_DIR
# was readable by root alone and `scp nanomuse-hk:/opt/nanomuse/backups/...`
# as the deploying user failed. The copies are handed to BACKUP_OWNER, mode
# 0600, so that user can read, copy off and restore them without sudo.
set -eu

relay=${RELAY_DIR:-/opt/nanomuse/relay}
out=${BACKUP_DIR:-/opt/nanomuse/backups}
keep=${KEEP_DAYS:-30}
owner=${BACKUP_OWNER:-$(stat -c '%u:%g' "$relay")}
here=$(cd "$(dirname "$0")" && pwd)

umask 077
# A manual run and the timer must not both pass the same free-space check.
exec 9>>"$relay/.backup.lock"
if ! flock -n 9; then
	echo "backup: another backup is running" >&2
	exit 1
fi
mkdir -p "$out"
python3 "$here/backup_preflight.py" "$relay/data/cloud.db" "$out"
chown "$owner" "$out"
stamp=$(date -u +%Y%m%d-%H%M%S)

# sqlite3 inside the relay image (python:3.12-slim has the module, not the CLI):
# python's sqlite3 backup API writes a consistent snapshot to a new file.
docker exec -i nanomuse-relay python - "$stamp" <<'EOF'
import sqlite3, sys
src = sqlite3.connect("/srv/nanomuse-cloud/data/cloud.db")
dst = sqlite3.connect(f"/srv/nanomuse-cloud/data/.backup-{sys.argv[1]}.db")
with dst:
    src.backup(dst)
dst.close(); src.close()
EOF
mv "$relay/data/.backup-$stamp.db" "$out/cloud-$stamp.db"
gzip -f "$out/cloud-$stamp.db"
chown "$owner" "$out/cloud-$stamp.db.gz"
chmod 600 "$out/cloud-$stamp.db.gz"

# 0.29 keeps the record's files (pictures, clips) under data/blobs, one file per hash;
# the rows in the database point at them. A mirror of the directory sits beside the
# copies: files are never rewritten, so the mirror only gains what the relay added and
# loses what it removed (a deleted account, the store's cap).
if [ -d "$relay/data/blobs" ]; then
	mkdir -p "$out/blobs"
	rsync -a --delete "$relay/data/blobs/" "$out/blobs/"
	chown -R "$owner" "$out/blobs"
	chmod -R u+rwX,go-rwx "$out/blobs"
fi

if [ -f "$relay/.env" ] && ! cmp -s "$relay/.env" "$out/env.latest" 2>/dev/null; then
	cp "$relay/.env" "$out/env-$stamp"
	cp "$relay/.env" "$out/env.latest"
	chown "$owner" "$out/env-$stamp" "$out/env.latest"
	chmod 600 "$out/env-$stamp" "$out/env.latest"
fi

find "$out" -name 'cloud-*.db.gz' -mtime +"$keep" -delete
echo "backup: $out/cloud-$stamp.db.gz ($(du -h "$out/cloud-$stamp.db.gz" | cut -f1))"

if [ -f "$relay/cos.env" ]; then
	if ! command -v age >/dev/null || ! command -v rclone >/dev/null; then
		echo "backup: cos.env is there but age or rclone is not installed; nothing went off the box" >&2
		exit 0
	fi
	(
		set -a
		# shellcheck disable=SC1091
		. "$relay/cos.env"
		set +a
		enc="$out/.cloud-$stamp.db.gz.age"
		trap 'rm -f "$enc"' EXIT
		age -r "$BACKUP_AGE_RECIPIENT" -o "$enc" "$out/cloud-$stamp.db.gz"
		export RCLONE_CONFIG_COS_TYPE=s3 RCLONE_CONFIG_COS_PROVIDER=TencentCOS RCLONE_CONFIG_COS_ACL=private
		export RCLONE_CONFIG_COS_ACCESS_KEY_ID="$COS_SECRET_ID" RCLONE_CONFIG_COS_SECRET_ACCESS_KEY="$COS_SECRET_KEY"
		export RCLONE_CONFIG_COS_ENDPOINT="cos.$COS_REGION.myqcloud.com"
		if rclone copyto --s3-no-check-bucket --s3-chunk-size 64M -q "$enc" "cos:$COS_BUCKET/relay/cloud-$stamp.db.gz.age"; then
			echo "backup: off the box as relay/cloud-$stamp.db.gz.age in $COS_BUCKET"
		else
			echo "backup: the upload to $COS_BUCKET failed; the local copy stands" >&2
		fi
	)
fi
