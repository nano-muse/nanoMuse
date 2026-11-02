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
#   --bind ADDR        with --local: listen on another address; 0.0.0.0 for the whole LAN, and
#                      the URLs then carry this machine's LAN address so phones can use them
#   --port N           with --local: another port (default 8787)
#   --with-runtime     also start the web app's runtime (the root docker-compose.yml) and join it
#                      to the relay's docker network, so the two find each other at relay:8787
#   --runtime-port N   with --with-runtime: the runtime's host port (default 8788)
#   --no-start         write cloud/.env only
#
# Needs: docker with the compose plugin (or docker-compose), curl. docs/self-hosting.md
# explains the three ways to run nanoMuse yourself; this script is the second.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CLOUD="$ROOT/cloud"
ENV_FILE="$CLOUD/.env"

LOCAL=0; BIND=127.0.0.1; PORT=8787; START=1; RUNTIME=0; RUNTIME_PORT=8788
# The leading comment block is the help text: everything from the shebang down to the line
# below. A range of line numbers used to say where it ended, and adding a sentence to it cut
# the help short; the line that starts the script is the one thing that cannot move.
usage() { sed -n '2,/^set -euo pipefail$/p' "$0" | sed '$d' | sed 's/^# \{0,1\}//'; }
while [ $# -gt 0 ]; do
  case "$1" in
    --local) LOCAL=1 ;;
    --bind) [ $# -ge 2 ] || { echo "--bind needs an address (try --help)" >&2; exit 2; }; BIND="$2"; shift ;;
    --port)
      [ $# -ge 2 ] && [[ "$2" =~ ^[0-9]+$ ]] || { echo "--port needs a number (try --help)" >&2; exit 2; }
      PORT="$2"; shift ;;
    --with-runtime) RUNTIME=1 ;;
    --runtime-port)
      [ $# -ge 2 ] && [[ "$2" =~ ^[0-9]+$ ]] || { echo "--runtime-port needs a number (try --help)" >&2; exit 2; }
      RUNTIME=1; RUNTIME_PORT="$2"; shift ;;
    --no-start) START=0 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "unknown option: $1 (try --help)" >&2; exit 2 ;;
  esac
  shift
done

say() { printf '%s\n' "$*"; }
die() { printf 'self-host: %s\n' "$*" >&2; exit 1; }

if [ "$RUNTIME" = 1 ]; then
  [[ "$PORT" =~ ^[0-9]{1,5}$ ]] || die "--port must be between 1 and 65535"
  PORT=$((10#$PORT))
  [ "$PORT" -ge 1 ] && [ "$PORT" -le 65535 ] || die "--port must be between 1 and 65535"
  [[ "$RUNTIME_PORT" =~ ^[0-9]{1,5}$ ]] || die "--runtime-port must be between 1 and 65535"
  RUNTIME_PORT=$((10#$RUNTIME_PORT))
  [ "$RUNTIME_PORT" -ge 1 ] && [ "$RUNTIME_PORT" -le 65535 ] || die "--runtime-port must be between 1 and 65535"
fi

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
lan_address() { # the IPv4 address other machines on the network reach this one at; empty when unknown
  local a="" ifc=""
  if command -v ip >/dev/null 2>&1; then # Linux
    a="$(ip -4 route get 1.1.1.1 2>/dev/null | awk '{ for (i = 1; i <= NF; i++) if ($i == "src") { print $(i + 1); exit } }' || true)"
  fi
  if [ -z "$a" ] && command -v ipconfig >/dev/null 2>&1 && command -v route >/dev/null 2>&1; then # macOS
    ifc="$(route -n get 1.1.1.1 2>/dev/null | awk '/interface:/ { print $2; exit }' || true)"
    [ -n "$ifc" ] && a="$(ipconfig getifaddr "$ifc" 2>/dev/null || true)"
  fi
  if [ -z "$a" ]; then a="$(hostname -I 2>/dev/null | awk '{ print $1 }' || true)"; fi
  printf '%s' "$a"
}

# --- the current .env, if any ---------------------------------------------------------------
get() { # get KEY [FILE]  → current value from .env, empty when absent
  local f="${2:-$ENV_FILE}"
  [ -f "$f" ] || return 0
  sed -n "s/^$1=//p" "$f" | head -1
}
set_kv() { # set_kv KEY VALUE [FILE]  → replace the line or append it; the value is taken verbatim
  local f tmp; f="${3:-$ENV_FILE}"; tmp="$(mktemp)"
  V="$2" awk -v k="$1" 'BEGIN { v = ENVIRON["V"]; done = 0 }
    index($0, k "=") == 1 { if (!done) { print k "=" v; done = 1 }; next }
    { print }
    END { if (!done) print k "=" v }' "$f" > "$tmp"
  mv "$tmp" "$f"
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
prev_base="$(get PUBLIC_BASE)"
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
  # PUBLIC_BASE is what the invitation links and the printed URLs carry. Listening on every
  # interface is for the phones on the network, and they reach this machine at its LAN
  # address, not at 127.0.0.1; a specific --bind address is used as given.
  HOST="$BIND"
  if [ "$BIND" = 0.0.0.0 ]; then
    HOST="$(lan_address)"
    if [ -z "$HOST" ]; then
      HOST=127.0.0.1
      say "     No network address found; the URLs say 127.0.0.1. A phone needs this machine's LAN address instead."
    fi
  fi
  BASE="http://$HOST:$PORT"
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
# A private relay for a few people: say so in INVITE_URL so invitations point here, and
# follow the address when a second run changes it (--local first, --bind 0.0.0.0 later).
case "$(get INVITE_URL)" in
  "https://nanomuse.cn/web/?invite="|"$prev_base/app/?invite=") set_kv INVITE_URL "$BASE/app/?invite=" ;;
esac

say
say "Wrote $ENV_FILE (mode 600). Back it up together with cloud/data/; see docs/self-hosting.md."
[ "$START" = 1 ] || exit 0

# --- the runtime, for --with-runtime ----------------------------------------------------------
RUNTIME_ENV="$ROOT/.env"

ensure_runtime_config() {
  # config/config.toml is bind-mounted read-only, and docker answers a missing host file by
  # creating a directory in its place: the container then cannot start at all ("not a
  # directory: Are you trying to mount a directory onto a file"), and the directory it left
  # behind belongs to root. Writing the file before the first `up` is what prevents that.
  local cfg="$ROOT/config/config.toml"
  if [ -d "$cfg" ]; then
    die "$cfg is a directory. Check its contents; if it is empty, remove it with: sudo rmdir -- '$cfg'"
  fi
  if [ -f "$cfg" ]; then return 0; fi
  cp "$ROOT/config/config.example.toml" "$cfg"
  say "Wrote config/config.toml from the example; the runtime's own settings are in it."
}

write_runtime_env() {
  if [ ! -f "$RUNTIME_ENV" ]; then
    cp "$ROOT/.env.example" "$RUNTIME_ENV"
    say "Writing a new $RUNTIME_ENV from .env.example (the runtime's settings)."
  fi
  # A fixed token keeps the web app's URL the same across restarts. It is generated once and
  # never rotated, and it is the one the URL printed at the end carries.
  if [ -z "$(get NANOMUSE_SERVER_TOKEN "$RUNTIME_ENV")" ]; then
    set_kv NANOMUSE_SERVER_TOKEN "$(random_hex)" "$RUNTIME_ENV"
  fi
  # The relay is one more OpenAI-compatible provider to the runtime: signing in on the
  # runtime's page is what gives it the account's key, so no model key belongs here. The
  # address is the relay's name on the network the two stacks share, not 127.0.0.1 — inside
  # its container the runtime is 127.0.0.1, and under TLS the relay publishes no port at all.
  if [ -z "$(get NANOMUSE_CLOUD_BASE_URL "$RUNTIME_ENV")" ]; then
    set_kv NANOMUSE_CLOUD_BASE_URL "http://relay:8787" "$RUNTIME_ENV"
  fi
  chmod 600 "$RUNTIME_ENV"
}

relay_network() { # the docker network the relay was started on; empty when it cannot be read
  local id
  # `|| true` everywhere a docker command feeds a pipe: set -o pipefail turns a failed `ps` or
  # an early-closing `head` into a non-zero pipeline, and that would stop the script over a
  # name it only wanted to read.
  id="$("${COMPOSE[@]}" "${FILES[@]}" ps -q relay 2>/dev/null | awk 'NR==1' || true)"
  if [ -z "$id" ]; then return 0; fi
  docker inspect -f '{{range $k, $v := .NetworkSettings.Networks}}{{$k}}{{"\n"}}{{end}}' "$id" 2>/dev/null | awk 'NR==1' || true
}

up_runtime() {
  local net id ok=0 tries probe_host
  # read before the working directory changes: the relay's compose files are relative to cloud/
  net="$(relay_network)"
  if [ -z "$net" ]; then
    say "Could not read the relay's Docker network. The relay is up; the runtime was not started."
    return 1
  fi
  say
  say "Starting the runtime on port $RUNTIME_PORT (the first build takes a few minutes)…"
  cd "$ROOT" || return 1
  # Created first, started afterwards, so it joins the relay's network before its first
  # request; on a second run it is already joined and the connect is a no-op.
  NANOMUSE_RUNTIME_BIND="$RUNTIME_BIND" NANOMUSE_RUNTIME_PORT="$RUNTIME_PORT" \
    "${COMPOSE[@]}" -f docker-compose.yml up -d --build --no-start app || return 1
  id="$("${COMPOSE[@]}" -f docker-compose.yml ps -a -q app 2>/dev/null | awk 'NR==1' || true)"
  RUNTIME_JOINED=0
  if [ -n "$net" ] && [ -n "$id" ]; then
    if docker network connect "$net" "$id" 2>/dev/null; then
      RUNTIME_JOINED=1
    elif docker inspect -f '{{range $k, $v := .NetworkSettings.Networks}}{{$k}}{{"\n"}}{{end}}' "$id" 2>/dev/null | grep -Fxq -- "$net"; then
      RUNTIME_JOINED=1 # already joined by an earlier run
    fi
  fi
  if [ "$RUNTIME_JOINED" = 0 ]; then
    say "Could not join the relay's Docker network. The relay is up; the runtime was not started."
    return 1
  fi
  "${COMPOSE[@]}" -f docker-compose.yml start app || return 1
  probe_host="$RUNTIME_BIND"
  [ "$probe_host" != 0.0.0.0 ] || probe_host=127.0.0.1
  health="http://$probe_host:$RUNTIME_PORT/api/health"
  printf 'Waiting for %s ' "$health"
  tries=0
  while [ "$tries" -lt 90 ]; do
    if curl -fsS --max-time 3 "$health" >/dev/null 2>&1; then ok=1; break; fi
    printf '.'; tries=$((tries + 1)); sleep 2
  done
  say
  if [ "$ok" = 0 ]; then
    say "The runtime did not answer within three minutes. The relay is up without it; look at:"
    say "  ${COMPOSE[*]} -f docker-compose.yml logs --tail=50 app    (from the repository root)"
    return 1
  fi
  return 0
}

# --- start ------------------------------------------------------------------------------------
# Everything the runtime needs that is cheap to get wrong: checked before the relay's three
# minutes of building, not after them.
if [ "$RUNTIME" = 1 ]; then
  # Both stacks publish a host port, and --local puts the relay on 8787.
  if [ "$LOCAL" = 1 ] && [ "$RUNTIME_PORT" = "$PORT" ]; then
    die "the runtime would take the relay's port $PORT; pick another with --runtime-port N"
  fi
  if [ "$LOCAL" = 0 ] && { [ "$RUNTIME_PORT" = 80 ] || [ "$RUNTIME_PORT" = 443 ]; }; then
    die "the runtime would take Caddy's port $RUNTIME_PORT; pick another with --runtime-port N"
  fi
  ensure_runtime_config
  write_runtime_env
  # A domain secures the relay through Caddy, not the runtime's HTTP port.
  # Keep that port local unless --local --bind explicitly selected another address.
  if [ "$LOCAL" = 1 ]; then RUNTIME_BIND="$BIND"; else RUNTIME_BIND=127.0.0.1; fi
  RUNTIME_SHOWN="$RUNTIME_BIND"
  if [ "$RUNTIME_SHOWN" = 0.0.0.0 ]; then
    RUNTIME_SHOWN="$(lan_address)"
    [ -n "$RUNTIME_SHOWN" ] || RUNTIME_SHOWN=127.0.0.1
  fi
fi
cd "$CLOUD"
FILES=(-f docker-compose.yml)
if [ "$LOCAL" = 1 ]; then
  FILES+=(-f docker-compose.local.yml)
  export RELAY_BIND="$BIND" RELAY_PORT="$PORT" PUBLIC_BASE="$BASE" CODE_SENDER="$SENDER"
fi
say
say "Starting the relay$([ "$LOCAL" = 0 ] && echo " and Caddy")…"
# The relay runs as uid 10001 in its container; the bind-mounted data directory must be its.
# Docker creates a missing ./data as root, so the chown runs inside the image, as root, and
# needs no sudo on the host. Idempotent.
"${COMPOSE[@]}" "${FILES[@]}" build relay
"${COMPOSE[@]}" "${FILES[@]}" run --rm --no-deps --user 0 relay chown -R 10001:10001 /srv/nanomuse-cloud/data
"${COMPOSE[@]}" "${FILES[@]}" up -d --build

health="$BASE/healthz"
# --local publishes the port on the bind address only: 0.0.0.0 answers on loopback, a
# specific address does not, so that one is asked at the address itself.
[ "$LOCAL" = 1 ] && health="http://$([ "$BIND" = 0.0.0.0 ] && echo 127.0.0.1 || echo "$BIND"):$PORT/healthz"
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

# --- the runtime, when asked for ---------------------------------------------------------------
if [ "$RUNTIME" = 1 ]; then
  if ! up_runtime; then exit 1; fi
  RUNTIME_URL="http://$RUNTIME_SHOWN:$RUNTIME_PORT/"
  RUNTIME_TOKEN="$(get NANOMUSE_SERVER_TOKEN "$RUNTIME_ENV")"
  if [ -n "$RUNTIME_TOKEN" ]; then
    RUNTIME_URL="${RUNTIME_URL}#token=$RUNTIME_TOKEN"
  fi
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
[ "$SENDER" = log ] && say "  Codes     cd cloud && ${COMPOSE[*]} ${FILES[*]} logs relay    (sign-in codes are printed there)"
if [ "$RUNTIME" = 1 ]; then
  say
  say "  Runtime   $RUNTIME_URL"
  say "            the agent and the web app on this machine; the token is the"
  say "            NANOMUSE_SERVER_TOKEN line in .env, so the link survives a restart"
  say "  Logs      ${COMPOSE[*]} -f docker-compose.yml logs app    (from the repository root)"
fi
say
say "Point each app at $BASE: on Android and iPhone, tap \"Use a different server\" on the"
say "sign-in screen; on the desktop, set the plugin's baseURL in cordis.patch.yml; for the"
say "terminal runtime, export NANOMUSE_CLOUD_BASE_URL=$BASE. The exact steps: docs/self-hosting.md."
if [ "$RUNTIME" = 1 ] && [ "$(get NANOMUSE_CLOUD_BASE_URL "$RUNTIME_ENV")" = http://relay:8787 ]; then
  say "The runtime started here already points at this relay (http://relay:8787, the relay's name"
  say "on the network the two containers share): sign in on its page and chat goes through the"
  say "relay's provider, within the account's allowance."
fi
if [ "$RUNTIME" = 1 ] && [ "$LOCAL" = 0 ]; then
  say "The runtime's HTTP port is local to this server. Use an SSH tunnel or a TLS reverse proxy to reach it remotely."
fi
if [ "$LOCAL" = 1 ] && [ "$BIND" = 127.0.0.1 ]; then
  say "Only this machine can reach the relay. For the phones on the same network, run it again with --bind 0.0.0.0: the URLs then carry this machine's LAN address."
fi
