#!/usr/bin/env bash
# nanoMuse Cloud — your own relay in one command.
#
#   bash scripts/self-host.sh           # a server with a domain: Caddy fetches the certificate
#   bash scripts/self-host.sh --local   # this machine only: http://127.0.0.1:8787, codes in the log
#
# Asks five things (domain, an e-mail for Let's Encrypt, how sign-in codes go out, the
# model provider, the admin password), writes cloud/.env with fresh random secrets, starts
# docker compose, waits for /healthz and prints where to go next. Running it again keeps
# the secrets and the accounts; it only re-asks, with the current values as defaults.
#
#   --local            no domain, no TLS; the relay listens on 127.0.0.1:8787
#   --bind ADDR        with --local: listen on another address (0.0.0.0 for the whole LAN)
#   --port N           with --local: another port (default 8787)
#   --no-start         write cloud/.env only
#
# Needs: docker with the compose plugin (or docker-compose), curl. docs/self-hosting.md
# explains the three ways to run nanoMuse yourself; this script is the second.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CLOUD="$ROOT/cloud"
ENV_FILE="$CLOUD/.env"

LOCAL=0; BIND=127.0.0.1; PORT=8787; START=1
while [ $# -gt 0 ]; do
  case "$1" in
    --local) LOCAL=1 ;;
    --bind) BIND="$2"; shift ;;
    --port) PORT="$2"; shift ;;
    --no-start) START=0 ;;
    -h|--help) sed -n '2,19p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "unknown option: $1 (try --help)" >&2; exit 2 ;;
  esac
  shift
done

say() { printf '%s\n' "$*"; }
die() { printf 'self-host: %s\n' "$*" >&2; exit 1; }

# --- tools --------------------------------------------------------------------------------
if docker compose version >/dev/null 2>&1; then COMPOSE=(docker compose)
elif command -v docker-compose >/dev/null 2>&1; then COMPOSE=(docker-compose)
else die "docker compose is not installed: https://docs.docker.com/compose/install/"; fi
command -v curl >/dev/null 2>&1 || die "curl is not installed"
docker info >/dev/null 2>&1 || die "docker is installed but not running, or you are not allowed to use it (try: sudo usermod -aG docker \$USER, then log in again)"

random_hex() {
  if command -v openssl >/dev/null 2>&1; then openssl rand -hex 32
  else od -An -N32 -tx1 /dev/urandom | tr -d ' \n'; fi
}

# --- the current .env, if any ---------------------------------------------------------------
get() { # get KEY  → current value from .env, empty when absent
  [ -f "$ENV_FILE" ] || return 0
  sed -n "s/^$1=//p" "$ENV_FILE" | head -1
}
set_kv() { # set_kv KEY VALUE  → replace the line or append it; the value is taken verbatim
  local tmp; tmp="$(mktemp)"
  V="$2" awk -v k="$1" 'BEGIN { v = ENVIRON["V"]; done = 0 }
    index($0, k "=") == 1 { if (!done) { print k "=" v; done = 1 }; next }
    { print }
    END { if (!done) print k "=" v }' "$ENV_FILE" > "$tmp"
  mv "$tmp" "$ENV_FILE"
}
ask() { # ask VAR "question" "default"  → reads a line; Enter keeps the default
  local var="$1" q="$2" def="$3" ans
  if [ -n "$def" ]; then printf '%s [%s]: ' "$q" "$def"; else printf '%s: ' "$q"; fi
  IFS= read -r ans || ans=""
  [ -t 0 ] || printf '\n' # answers piped in do not echo their newline
  printf -v "$var" '%s' "${ans:-$def}"
}
ask_secret() { # ask_secret VAR "question" has_current  → silent; Enter keeps what .env has
  local var="$1" q="$2" has="$3" ans
  if [ "$has" = 1 ]; then printf '%s [Enter keeps the current one]: ' "$q"; else printf '%s: ' "$q"; fi
  if [ -t 0 ]; then IFS= read -rs ans || ans=""; printf '\n'; else IFS= read -r ans || ans=""; fi
  printf -v "$var" '%s' "$ans"
}

if [ ! -f "$ENV_FILE" ]; then
  cp "$CLOUD/.env.example" "$ENV_FILE"
  say "Writing a new $ENV_FILE from .env.example."
else
  say "Updating $ENV_FILE (secrets and accounts are kept)."
fi
chmod 600 "$ENV_FILE"

# --- 1. domain -----------------------------------------------------------------------------
cur_domain="$(get CLOUD_DOMAIN)"
[ "$cur_domain" = "cloud.example.com" ] && cur_domain=""
if [ "$LOCAL" = 1 ]; then
  DOMAIN=local
  say
  say "1/5  (local: this machine only, no domain)"
else
  say
  say "1/5  The relay's public domain, pointing at this machine (an A record), with ports 80 and"
  say "     443 open; Caddy fetches the certificate. Type \"local\" for this machine only, no TLS."
  ask DOMAIN "     Domain" "${cur_domain:-local}"
fi
if [ "$DOMAIN" = local ] || [ "$DOMAIN" = localhost ]; then
  LOCAL=1
  BASE="http://$([ "$BIND" = 0.0.0.0 ] && echo 127.0.0.1 || echo "$BIND"):$PORT"
  set_kv CLOUD_DOMAIN localhost
  set_kv PUBLIC_BASE "$BASE"
else
  BASE="https://$DOMAIN"
  set_kv CLOUD_DOMAIN "$DOMAIN"
  set_kv PUBLIC_BASE "$BASE"
fi

# --- 2. e-mail for Let's Encrypt -----------------------------------------------------------
if [ "$LOCAL" = 0 ]; then
  say
  say "2/5  An e-mail address for Let's Encrypt. It is only written to when a certificate is"
  say "     about to expire and could not be renewed. Enter to leave it out."
  ask ACME "     E-mail" "$(get ACME_EMAIL)"
  set_kv ACME_EMAIL "$ACME"
else
  say
  say "2/5  (local: no certificate, no e-mail needed)"
fi

# --- 3. how codes go out -------------------------------------------------------------------
say
if [ "$LOCAL" = 1 ]; then
  say "3/5  Sign-in codes are printed to the relay's log:  docker compose logs relay"
  SENDER=log
else
  say "3/5  How sign-in codes reach people:"
  say "       log     printed to the relay's log only (you read them out; fine for a family)"
  say "       smtp    e-mail, through a mailbox you own"
  say "       aliyun  SMS to mainland China numbers through Alibaba Cloud (号码认证服务 by default); e-mail is not sent"
  say "       both    smtp for e-mail addresses, aliyun for phone numbers"
  cur_sender="$(get CODE_SENDER)"
  while :; do
    ask SENDER "     Codes" "${cur_sender:-log}"
    case "$SENDER" in log|smtp|aliyun|both) break ;; *) say "     one of: log smtp aliyun both" ;; esac
  done
fi
set_kv CODE_SENDER "$SENDER"
if [ "$SENDER" = smtp ] || [ "$SENDER" = both ]; then
  ask V "     SMTP host" "$(get SMTP_HOST)"; set_kv SMTP_HOST "$V"
  ask V "     SMTP port" "$(get SMTP_PORT)"; set_kv SMTP_PORT "${V:-465}"
  ask V "     SMTP user" "$(get SMTP_USER)"; set_kv SMTP_USER "$V"
  ask_secret V "     SMTP password" "$([ -n "$(get SMTP_PASSWORD)" ] && echo 1 || echo 0)"
  [ -n "$V" ] && set_kv SMTP_PASSWORD "$V"
  ask V "     From (e.g. nanoMuse <no-reply@$DOMAIN>)" "$(get SMTP_FROM)"; set_kv SMTP_FROM "$V"
fi
if [ "$SENDER" = aliyun ] || [ "$SENDER" = both ]; then
  ask V "     Aliyun AccessKey id" "$(get ALIYUN_ACCESS_KEY_ID)"; set_kv ALIYUN_ACCESS_KEY_ID "$V"
  ask_secret V "     Aliyun AccessKey secret" "$([ -n "$(get ALIYUN_ACCESS_KEY_SECRET)" ] && echo 1 || echo 0)"
  [ -n "$V" ] && set_kv ALIYUN_ACCESS_KEY_SECRET "$V"
  ask V "     SMS signature" "$(get ALIYUN_SMS_SIGN)"; set_kv ALIYUN_SMS_SIGN "$V"
  ask V "     SMS template code" "$(get ALIYUN_SMS_TEMPLATE)"; set_kv ALIYUN_SMS_TEMPLATE "$V"
fi

# --- 4. the model provider -----------------------------------------------------------------
say
say "4/5  The OpenAI-compatible endpoint the relay spends your money on, and its key. The"
say "     default is Alibaba Model Studio (百炼); OpenRouter is https://openrouter.ai/api/v1."
say "     With no key, sign-in and the devices' hub work; chat does not."
ask UP_BASE "     Base URL" "$(get UPSTREAM_BASE)"
set_kv UPSTREAM_BASE "${UP_BASE:-https://dashscope.aliyuncs.com/compatible-mode/v1}"
has_key=0; [ -n "$(get UPSTREAM_KEY)" ] && has_key=1
ask_secret UP_KEY "     API key" "$has_key"
[ -n "$UP_KEY" ] && set_kv UPSTREAM_KEY "$UP_KEY"
[ -z "$(get UPSTREAM_KEY)" ] && say "     (no key; add UPSTREAM_KEY to cloud/.env later and run this again)"

# --- 5. the admin password -----------------------------------------------------------------
say
say "5/5  The password for the admin page ($BASE/app/admin/). Enter to have one generated."
has_admin=0; [ -n "$(get CLOUD_ADMIN_TOKEN)" ] && has_admin=1
ask_secret ADMIN "     Admin password" "$has_admin"
GENERATED_ADMIN=""
if [ -n "$ADMIN" ]; then
  set_kv CLOUD_ADMIN_TOKEN "$ADMIN"
elif [ "$has_admin" = 0 ]; then
  GENERATED_ADMIN="$(random_hex)"
  set_kv CLOUD_ADMIN_TOKEN "$GENERATED_ADMIN"
fi

# CLOUD_SECRET keys the hashes every account is stored under; it is generated once and never
# rotated by this script (rotating it would orphan every account).
[ -z "$(get CLOUD_SECRET)" ] && set_kv CLOUD_SECRET "$(random_hex)"
# A private relay for a few people: say so in INVITE_URL so invitations point here.
[ "$(get INVITE_URL)" = "https://nanomuse.cn/web/?invite=" ] && set_kv INVITE_URL "$BASE/app/?invite="

say
say "Wrote $ENV_FILE (mode 600). Back it up together with cloud/data/; see docs/self-hosting.md."
[ "$START" = 1 ] || exit 0

# --- start ------------------------------------------------------------------------------------
cd "$CLOUD"
FILES=(-f docker-compose.yml)
if [ "$LOCAL" = 1 ]; then
  FILES+=(-f docker-compose.local.yml)
  export RELAY_BIND="$BIND" RELAY_PORT="$PORT" PUBLIC_BASE="$BASE" CODE_SENDER="$SENDER"
fi
say
say "Starting the relay$([ "$LOCAL" = 0 ] && echo " and Caddy")…"
"${COMPOSE[@]}" "${FILES[@]}" up -d --build

health="$BASE/healthz"
[ "$LOCAL" = 1 ] && health="http://127.0.0.1:$PORT/healthz"
printf 'Waiting for %s ' "$health"
ok=0
for _ in $(seq 1 90); do
  if curl -fsS --max-time 3 "$health" >/dev/null 2>&1; then ok=1; break; fi
  printf '.'; sleep 2
done
say
if [ "$ok" = 0 ]; then
  say "The relay did not answer within three minutes. Look at:"
  say "  cd cloud && ${COMPOSE[*]} ${FILES[*]} logs --tail=50"
  [ "$LOCAL" = 0 ] && say "A certificate can take a minute; check that $DOMAIN points here and ports 80/443 are open."
  exit 1
fi

say
say "nanoMuse Cloud is up."
say
say "  Console   $BASE/app/           sign in here; the web console lives on the relay"
say "  Admin     $BASE/app/admin/     accounts, allowance, usage"
if [ -n "$GENERATED_ADMIN" ]; then
  say "            password (generated, shown once): $GENERATED_ADMIN"
else
  say "            password: the CLOUD_ADMIN_TOKEN line in cloud/.env"
fi
[ "$SENDER" = log ] && say "  Codes     ${COMPOSE[*]} ${FILES[*]} logs relay    (sign-in codes are printed there)"
say
say "Point each app at $BASE: on Android and iPhone, tap \"Use a different server\" on the"
say "sign-in screen; on the desktop, set the plugin's baseURL in cordis.patch.yml; for the"
say "terminal runtime, export NANOMUSE_CLOUD_BASE_URL=$BASE. The exact steps: docs/self-hosting.md."
if [ "$LOCAL" = 1 ]; then
  say "A phone on the same network needs --bind 0.0.0.0 and this machine's LAN address instead of 127.0.0.1."
fi
