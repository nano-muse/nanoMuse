# nanoMuse Cloud on nanomuse-hk

The production relay behind `https://cloud.nanomuse.cn` runs on the same Hong
Kong box as the project site, behind the showcase's Caddy
(`demo/showcase`). This directory is everything specific to that box; the
relay itself is [`cloud/`](../../README.md).

| | |
|---|---|
| host | `nanomuse-hk` (SSH alias), Ubuntu 24.04, Docker |
| relay | `/opt/nanomuse/relay/` — `docker-compose.yml`, `.env`, `src/`, `data/cloud.db` |
| container | `nanomuse-relay`, on the `showcase_edge` network, no published ports; runs as uid 10001, which owns `data/` on the host (`deploy.sh` keeps it so) |
| TLS / vhost | `demo/showcase/sites.d/cloud.nanomuse.cn.caddy` → `nanomuse-relay:8787` |
| backups | `/opt/nanomuse/backups/cloud-*.db.gz`, daily 04:10 UTC, 14 days (`KEEP_DAYS` in the service unit; the script's own default is 30), and a mirror of the record's files in `/opt/nanomuse/backups/blobs/` (`backup.sh`, systemd timer); with `cos.env` on the box, the day's copy also goes to a COS bucket encrypted ([Off the box](#off-the-box)) |
| self-check | `selfcheck.sh` every 10 min (systemd timer): the public `/healthz`, the relay's `/v1/admin/health` (aggregates only: requests under way, hub counters, the hour's upstream errors, content-check refusals and refusals, the database), free disk, and the age of the newest `cloud-*.db.gz` under `/opt/nanomuse/backups` (a problem when it is older than 48 hours, `BACKUP_MAX_H`, or there is none) — one line in the journal (`journalctl -t nanomuse-selfcheck`); with `ALERT_URL` in `.env` (a webhook taking `{"text": …}`) a problem is posted there, once an hour per problem |
| admin | `https://cloud.nanomuse.cn/app/admin/`, token in `/opt/nanomuse/relay/ADMIN_TOKEN.txt` (0600) |
| DNS | DNSPod: `cloud` A → the box's address, same as the apex |

## First time

On the box, once, as the deploying user:

```bash
sudo mkdir -p /opt/nanomuse/relay && sudo chown "$USER" /opt/nanomuse/relay
cd /opt/nanomuse/relay
umask 077
cat > .env <<EOF
PUBLIC_BASE=https://cloud.nanomuse.cn
CLOUD_SECRET=$(openssl rand -hex 32)
CLOUD_ADMIN_TOKEN=$(openssl rand -hex 32)
# anyone may sign in; the members below (comma-separated phone numbers /
# e-mail addresses) have no limit, everyone else ¥10 for good, +¥5 an
# invite (to both sides)
SIGNUP_OPEN=1
ALLOWED_IDENTIFIERS=
ALLOWANCE_CNY=10
INVITE_BONUS_CNY=5
OWN_KEY_DOCS=https://nanomuse.cn/own-key
# what "Help improve nanoMuse's AI models" starts as for new accounts (1 = on
# until turned off under Settings → Data controls); say it in PRIVACY_URL
IMPROVE_DEFAULT=1
PRIVACY_URL=https://nanomuse.cn/privacy/
DAY_OFFSET_H=8
USD_CNY=7.1
# no token ceiling; usage is metered and shown
SIGNUP_TOKENS=0
DAILY_CAP_TOKENS=0
PER_MINUTE_REQUESTS=30
# codes: log until DirectMail is set up, then smtp
CODE_SENDER=log
SMTP_HOST=smtpdm.aliyun.com
SMTP_PORT=465
SMTP_USER=no-reply@mail.nanomuse.cn
SMTP_PASSWORD=
SMTP_FROM=nanoMuse <no-reply@mail.nanomuse.cn>
# the 百炼 key the relay spends (public endpoints; never a private one)
UPSTREAM_BASE=https://dashscope.aliyuncs.com/compatible-mode/v1
DASHSCOPE_BASE=https://dashscope.aliyuncs.com/api/v1
UPSTREAM_KEY=
EOF
sed -n 's/^CLOUD_ADMIN_TOKEN=//p' .env > ADMIN_TOKEN.txt
```

Fill `ALLOWED_IDENTIFIERS` and `UPSTREAM_KEY` with an editor on the box (not
over a chat, not in a shell history: `nano .env`). Then, from a checkout on
a machine with the SSH alias:

```bash
cloud/deploy/nanomuse-hk/deploy.sh
```

which syncs `cloud/`, installs the compose file, the backup and self-check
scripts with their timers (the units run `/opt/nanomuse/relay/*.sh`, the copies
`deploy.sh` puts there, not the checkout) and the Caddy site, builds and starts the container, and checks `/healthz` inside
the container and through the public name. The public check fails until the
`cloud` A record has spread and Caddy has fetched the certificate (a minute
after the record resolves).

## Every later deploy

```bash
cloud/deploy/nanomuse-hk/deploy.sh
```

The database and `.env` are never touched. A change to `.env` needs
`docker compose up -d` (or `deploy.sh`) to take effect.

## Day to day

```bash
ssh nanomuse-hk docker logs -f --since 10m nanomuse-relay      # codes when CODE_SENDER=log, errors
ssh nanomuse-hk 'cd /opt/nanomuse/relay && docker compose ps'
ssh nanomuse-hk /opt/nanomuse/relay/backup.sh                     # a backup right now
scp nanomuse-hk:/opt/nanomuse/backups/cloud-*.db.gz ~/backups/   # a copy off the box by hand (the bucket gets one daily, below)
```

Sign-up is open; everyone gets ¥10 for the account's lifetime and +¥5 per
person they invite (the person invited gets +¥5 too). Giving
someone more: *加额度* on the admin page (into their pool), or press *设为成员*
next to their account on the admin page (no restart), or add the number or
address to `ALLOWED_IDENTIFIERS` in `.env` and `docker compose up -d`.
Removing someone: disable or delete the account on the admin page. Closing
the door again: the *Sign-ups* switch under *Controls* on the admin page
(relay 0.22; no restart, a note for the audit log, members still sign in) —
or `SIGNUP_OPEN=0` in `.env` and `docker compose up -d` to make it the
default a restart comes back to.

Pausing — the switches under *Controls* on the admin page, or
`python -m nanomuse_cloud admin controls set <switch> off --note "…"` from the
relay's shell ([docs/cloud.md › Controls](../../../docs/cloud.md#controls)):
*Free allowance* stops the spending while sign-in, the hub and sync keep
working (the apps say so and offer the other ways on); *Cloud service*
answers every API call with 503 `service_paused` while the console, the health
check and `/v1/config` keep answering; *Conversation sync* and *Device hub*
pause one thing each. All of it comes back with the switch, nothing restarts.
A threshold rule (*at N accounts → notify / close sign-ups / pause the
allowance*) does the same by itself; `ADMIN_EMAIL` in `.env` is where
*notify* goes, and `ALERT_URL` is where the self-check posts a problem; with
either empty the line lands only in the audit log or the journal.

Kill switch — the process stops, nothing else on the box changes:

```bash
ssh nanomuse-hk 'cd /opt/nanomuse/relay && docker compose stop'
```

and `docker compose start` brings it back. Blanking `UPSTREAM_KEY` and `up -d`
also cuts the spending (the models answer 503 `upstream_unconfigured`), but
the *Free allowance* switch says it better to the apps.

## Restoring

The scheduled backup requires Python 3 and `flock` on the host. It takes an
exclusive lock and checks free space before starting SQLite's copy. Both the
database and backup filesystems must have ordinary-user available space of at
least twice the combined database and WAL size, plus 5 GiB for the running
service. Root-reserved blocks do not count. Insufficient space or an unreadable
capacity check fails the service before copying or deleting expired backups;
`journalctl -u nanomuse-relay-backup.service` shows the byte counts. Add capacity
or review recovery points before retrying. This check cannot reserve space
against other writers and does not automatically remove backups to make room.

```bash
ssh nanomuse-hk 'cd /opt/nanomuse/relay && docker compose stop \
  && gunzip -c /opt/nanomuse/backups/cloud-YYYYMMDD-HHMMSS.db.gz \
     | docker compose run --rm --no-deps -T relay sh -c "cat > data/cloud.db && rm -f data/cloud.db-wal data/cloud.db-shm" \
  && docker compose start'
```

The record's files go back with `sudo rsync -a /opt/nanomuse/backups/blobs/
/opt/nanomuse/relay/data/blobs/` (then `sudo chown -R 10001:10001` on it); a
turn whose file is missing is still read back, with the reference and no picture.

No `sudo`: the copies under `/opt/nanomuse/backups` belong to the deploying
user (`backup.sh` hands each one over, mode 0600; `BACKUP_OWNER` in the
timer's environment names another owner), and the restored file is written
by a one-off container of the relay's own image, which runs as uid 10001
and so leaves `data/cloud.db` owned by the user the relay runs as. A
`cloud.db` written on the host by the deploying user would stop the relay at
start with the sentence about the directory not being writable. Copies taken
before the hand-over was in `backup.sh` are root's; one `sudo chown -R
"$USER" /opt/nanomuse/backups` on the box (or the next `deploy.sh`, which
does the same) makes them readable too.

A backup is only readable with the `CLOUD_SECRET` it was written under;
`backup.sh` keeps a copy of `.env` next to the database copies for that
reason (`env.latest`, 0600).

## Off the box

A copy that lives only on the box goes with the box. With `/opt/nanomuse/relay/cos.env`
in place, `backup.sh` also sends each day's copy to a COS bucket, encrypted on the box
to an [age](https://age-encryption.org) public key whose private half the maintainer keeps
elsewhere (a password manager), so the bucket holds nothing anyone can read, Tencent
included. `.env` (with `CLOUD_SECRET`) and the record's files (the pictures) never leave
the box: a database copy without the secret is unreadable, and the pictures would be an
unencrypted mirror of people's screens. The bucket's lifecycle rule, not the script,
expires the copies.

Once, in the Tencent Cloud console (the box is in `ap-hongkong`; keep the bucket there,
so the daily 6 GB travel over the private network and cost no traffic):

1. **COS › 存储桶列表 › 创建存储桶**: region 中国香港, a name like `nanomuse-backups`
   (COS appends the APPID), 私有读写, default encryption on, versioning off.
2. **The bucket › 基础配置 › 生命周期 › 添加规则**: the whole bucket, 当前版本 删除
   after 30 days (the box itself keeps 14), nothing else.
3. **访问管理 (CAM) › 用户 › 新建用户 › 自定义创建 › 可访问资源并接收消息**,
   programmatic access only (no console), no group; then **策略 › 新建自定义策略 ›
   按策略语法** with this document (the APPID and bucket name as the console shows
   them), and attach it to the user:

   ```json
   {"version": "2.0", "statement": [{"effect": "allow",
     "action": ["cos:PutObject", "cos:HeadObject", "cos:InitiateMultipartUpload",
                "cos:UploadPart", "cos:CompleteMultipartUpload",
                "cos:AbortMultipartUpload", "cos:ListParts"],
     "resource": ["qcs::cos:ap-hongkong:uid/APPID:nanomuse-backups-APPID/relay/*"]}]}
   ```

   The key can put copies under `relay/` and nothing else: not list them, not read them,
   not delete them. The SecretId and SecretKey are shown once; they go into `cos.env`
   below and nowhere else.
4. The age key pair, on the box, in a root-only file the private half never leaves except
   into the maintainer's password manager:

   ```bash
   ssh nanomuse-hk 'sudo apt-get install -y age rclone && umask 077 && age-keygen -o /tmp/backup-age.key 2>/dev/null \
     && sudo install -m 600 /tmp/backup-age.key /root/backup-age.key && shred -u /tmp/backup-age.key \
     && sudo grep -o "age1[a-z0-9]*" /root/backup-age.key'
   ```

   prints the public key (`age1…`). Copy the private half out (`ssh nanomuse-hk sudo cat
   /root/backup-age.key`, into the password manager), then `ssh nanomuse-hk sudo shred -u
   /root/backup-age.key` so the box holds the public half only. Without the private half
   the copies in the bucket are gone for good; with the private half and nothing else they
   open anywhere.
5. `cos.env` on the box, with an editor, mode 0600, owned by root (the timer runs as root):

   ```
   COS_BUCKET=nanomuse-backups-APPID
   COS_REGION=ap-hongkong
   COS_SECRET_ID=…
   COS_SECRET_KEY=…
   BACKUP_AGE_RECIPIENT=age1…
   ```

`ssh nanomuse-hk sudo /opt/nanomuse/relay/backup.sh` then ends with `backup: off the box
as relay/cloud-….db.gz.age in …`; the journal of `nanomuse-relay-backup.service` has the
line each night, and a failed upload is a warning there (the local copy stands). About
¥25 a month at 30 copies of 6 GB in standard storage; 低频存储 halves it.

Restoring from the bucket needs a key that may read it (the account's own, in the console,
not the write-only one), rclone with that key, and the private half of the age key:

```bash
rclone copyto cos:nanomuse-backups-APPID/relay/cloud-YYYYMMDD-HHMMSS.db.gz.age ./cloud.db.gz.age
age -d -i backup-age.key -o cloud.db.gz cloud.db.gz.age     # then as in Restoring, with CLOUD_SECRET from the box's .env
```
