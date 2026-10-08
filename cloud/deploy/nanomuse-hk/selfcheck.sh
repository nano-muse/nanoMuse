#!/bin/sh
# The relay's self-check, every ten minutes (nanomuse-relay-selfcheck.timer; harmless by
# hand). Reads a few things and writes one line to the journal:
#
#   GET https://cloud.nanomuse.cn/healthz              the public door answers
#   GET http://nanomuse-relay:8787/v1/admin/health     aggregates only (api.py admin_health):
#                                                      requests under way, the hub's counters,
#                                                      the last hour's refusals and upstream
#                                                      errors, the database; never an account
#   df on the relay's volume                           free disk
#   the newest cloud-*.db.gz under BACKUP_DIR          backup.sh ran lately
#
# When the public door is down, the relay says `ok: false`, the box is short of disk, or the
# latest backup is older than BACKUP_MAX_H hours (or there is none), the line is a warning
# and, with ALERT_URL in .env (any webhook that takes a JSON {"text": …}, a Feishu/Slack-style
# incoming hook), the same line is posted there, at most once an hour for the same problem
# (state in STATE_DIR).
#
#   RELAY_DIR     where .env lives (default /opt/nanomuse/relay)
#   PUBLIC_BASE   the public name (default https://cloud.nanomuse.cn)
#   DISK_MIN_MB   warn below this much free on the relay's volume (default 2048)
#   BACKUP_DIR    where backup.sh writes (default /opt/nanomuse/backups, as in backup.sh)
#   BACKUP_MAX_H  warn when the newest backup is older than this many hours (default 48)
#   STATE_DIR     where the once-an-hour state lives (default /run/nanomuse-selfcheck)
set -eu

relay=${RELAY_DIR:-/opt/nanomuse/relay}
public=${PUBLIC_BASE:-https://cloud.nanomuse.cn}
disk_min=${DISK_MIN_MB:-2048}
backups=${BACKUP_DIR:-/opt/nanomuse/backups}
backup_max_h=${BACKUP_MAX_H:-48}
state=${STATE_DIR:-/run/nanomuse-selfcheck}
mkdir -p "$state"

tok=$(grep '^CLOUD_ADMIN_TOKEN=' "$relay/.env" 2>/dev/null | cut -d= -f2- || true)
alert=$(grep '^ALERT_URL=' "$relay/.env" 2>/dev/null | cut -d= -f2- || true)

problems=""
add() { problems="${problems}${problems:+; }$1"; }

# 1. the public door
if ! curl -fsS -m 15 "$public/healthz" >/dev/null 2>&1; then
	add "public $public/healthz not answering"
fi

# 2. the relay's own view, over the edge network (no published ports)
health=$(docker exec nanomuse-relay python -c "
import json, sys, urllib.request
req = urllib.request.Request('http://127.0.0.1:8787/v1/admin/health', headers={'X-Admin-Token': sys.argv[1]})
print(urllib.request.urlopen(req, timeout=10).read().decode())" "$tok" 2>/dev/null || true)
if [ -z "$health" ]; then
	add "relay /v1/admin/health not answering"
	summary="(no relay data)"
else
	summary=$(printf '%s' "$health" | python3 -c "
import json, sys
h = json.load(sys.stdin)
hub = h.get('hub') or {}
lh = h.get('last_hour') or {}
inf = h.get('in_flight') or {}
print('v%s hub=%s online/%s accounts, pending=%s, dropped=%s, flood_closes=%s; last hour: %s requests, %s upstream errors, %s refused, %s sign-ins (%s failed); in flight %s/%s accounts; db %.1f MB%s' % (
    h.get('version'), hub.get('online'), hub.get('accounts_online'), hub.get('pending_calls'), hub.get('dropped_frames'), hub.get('flood_closes'),
    lh.get('requests'), lh.get('upstream_errors'), lh.get('budget_refused'), lh.get('sign_ins'), lh.get('sign_in_failures'),
    inf.get('requests'), inf.get('accounts'), (h.get('db') or {}).get('size_bytes', 0) / 1048576, '' if (h.get('db') or {}).get('writable') else ' NOT WRITABLE'))
for p in h.get('problems') or []:
    print('PROBLEM ' + p)
")
	for p in $(printf '%s\n' "$summary" | sed -n 's/^PROBLEM //p' | tr ' ' '_'); do
		add "$(printf '%s' "$p" | tr '_' ' ')"
	done
	summary=$(printf '%s\n' "$summary" | sed '/^PROBLEM /d')
fi

# 3. the disk the data lives on
free_mb=$(df -Pm "$relay" | awk 'NR==2 {print $4}')
if [ "${free_mb:-0}" -lt "$disk_min" ]; then
	add "only ${free_mb} MB free under $relay"
fi

# 4. the backups: backup.sh writes cloud-YYYYMMDD-HHMMSS.db.gz once a day; the newest one
# must be younger than BACKUP_MAX_H hours (two missed nights), and there must be one at all
newest=$(ls -t "$backups"/cloud-*.db.gz 2>/dev/null | head -n 1 || true)
if [ -z "$newest" ]; then
	add "no backup yet under $backups"
elif [ -n "$(find "$newest" -mmin +$((backup_max_h * 60)) 2>/dev/null)" ]; then
	add "latest backup $(basename "$newest") is older than ${backup_max_h} hours"
fi

if [ -z "$problems" ]; then
	logger -t nanomuse-selfcheck -p user.info "ok: $summary"
	rm -f "$state/last-problem"
	exit 0
fi

line="nanoMuse Cloud self-check: $problems. $summary"
logger -t nanomuse-selfcheck -p user.warning "$line"
if [ -n "$alert" ]; then
	# the same problem is posted at most once an hour
	key=$(printf '%s' "$problems" | md5sum | cut -c1-16)
	if [ ! -f "$state/last-problem" ] || [ "$(cat "$state/last-problem" 2>/dev/null)" != "$key" ] \
		|| [ -n "$(find "$state/last-problem" -mmin +60 2>/dev/null)" ]; then
		printf '%s' "$key" >"$state/last-problem"
		python3 - "$alert" "$line" <<'EOF' || true
import json, sys, urllib.request
url, text = sys.argv[1], sys.argv[2]
body = json.dumps({"text": text, "msg_type": "text", "content": {"text": text}}).encode()
req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
urllib.request.urlopen(req, timeout=10).read()
EOF
	fi
fi
exit 1
